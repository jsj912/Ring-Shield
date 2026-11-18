"""Standalone ring-level protocol scorer (RUNBOOK T-P1). Evaluation only.

    python evaluation/score_external.py --rings runs/seed1/rings.parquet runs/seed2/rings.parquet \
        --split test --window primary --out results/scored/mymethod
    python evaluation/score_external.py --compare results/scored/a results/scored/b --out results/scored/a_vs_b

Scores any file(s) of predicted rings -- one file per seed or run -- against the AMLworld
laundering-attempt ground truth under every scope convention the paper discusses, at several
Jaccard thresholds, with percentile-bootstrap intervals over truth targets (seeds averaged inside
each resample). It writes `metrics.json`, `summary.csv`, `config.json` and `evidence.json` (the
per-target matched indicators `--compare` needs).

Nothing is re-implemented: the in-scope rule and member sets come from
`ringshield.truth.load_ground_truth`, in-window pieces from `evaluation.component_scope.component_truth`,
the window restriction of predictions from `ringshield.evaluate.restrict_rings` (inside
`evaluation.ring_stats.ring_evidence`), matching from `evaluation.ring_metrics.match_rings`
(greedy one-to-one by descending Jaccard), metrics from `ring_stats.metrics_from_evidence`, and the
paired test from `ring_stats.paired_unit_bootstrap`.

Intervals (default): each resample draws |T| targets with replacement and passes the draw counts
as weights, exactly as `ring_stats.bootstrap_over_rings` (the r9 procedure) does, so a target drawn
k times counts k times. `--legacy-subsample-intervals` uses `evaluation.scope_sensitivity.boot`
instead, which passes the drawn ids without weights; `metrics_from_evidence` sums over the set of
ids, so repeats collapse and each resample is a ~63 % subsample of targets. That is the procedure
behind r14/v36; the flag exists only to reproduce those tables (T-P1). Point estimates are the same
under both.

Conventions (docs/PROTOCOL.md):
    test_visible     a ring is in scope if >= 1 of its transactions is in the window; members =
                     the accounts of those in-window transactions (the reported convention)
    full_membership  same rings; members = all of the ring's accounts (sensitivity only)
    component        each in-window connected piece of a test_visible ring is its own target
    component_ge3    the same, keeping pieces with >= 3 accounts

Input schemas:
    full     the repository's rings.parquet (any schema version; read with read_rings_any)
    minimal  parquet or JSONL with `ring_id` and `members` (list of account ids), optionally
             `member_edges` (list of edge ids). Without member_edges a ring's edges are taken to be
             every split transaction between two of its members; the window restriction then keeps
             the endpoints of those edges that fall in the window -- the same rule as for full
             rings, applied to the induced edge set.
`--min-size` is applied to the unrestricted prediction (its full member list); matching uses the
prediction restricted to the window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.component_scope import component_truth  # noqa: E402
from evaluation.ring_stats import metrics_from_evidence, paired_unit_bootstrap, ring_evidence  # noqa: E402
from evaluation.scope_sensitivity import boot  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import SPLIT_COLUMNS  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402
from contract.schema import TEST_PARQUET_RENAMES  # noqa: E402

CONVENTIONS = ("test_visible", "full_membership", "component", "component_ge3")
DEFAULT_THRESHOLDS = (0.3, 0.5, 0.7)


# ------------------------------------------------------------------------------------- inputs
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def default_eval_window() -> Path:
    """The dataset's own window file: HI-Medium runs (RINGSHIELD_PATHS=...hi_medium...) get
    configs/eval_window_hi_medium.yaml, everything else configs/eval_window.yaml."""
    ds = str(load_paths().get("dataset", "")).lower().replace("-", "_")
    p = REPO_ROOT / "configs" / f"eval_window_{ds}.yaml"
    return p if ds and p.exists() else REPO_ROOT / "configs" / "eval_window.yaml"


def load_split_edges(split: str, processed_dir: Path) -> pd.DataFrame:
    """edge_id, from_id, to_id, timestamp of one split -- all `ring_evidence` needs."""
    cols = [c for c in SPLIT_COLUMNS if c in ("EdgeID", "from_id", "to_id", "Timestamp")]
    base = pd.read_parquet(processed_dir / f"amlworld_{split}.parquet", columns=cols)
    base = base.rename(columns=TEST_PARQUET_RENAMES)
    need = {"edge_id", "from_id", "to_id", "timestamp"}
    assert need <= set(base.columns), base.columns.tolist()
    return base[sorted(need)].reset_index(drop=True)


def _read_minimal(path: Path) -> pd.DataFrame:
    if path.suffix in (".jsonl", ".json"):
        return pd.read_json(path, lines=path.suffix == ".jsonl")
    return pd.read_parquet(path)


def is_full_schema(path: Path) -> bool:
    if path.suffix != ".parquet":
        return False
    import pyarrow.parquet as pq
    names = set(pq.read_schema(path).names)
    return {"member_edges", "seed_edges", "aggregator_id"} <= names


def induced_edges(members_list: list[set], edges: pd.DataFrame) -> list[list[int]]:
    """For each member set, the edge ids of split transactions with both endpoints inside it."""
    owner: dict[int, list[int]] = {}
    for i, ms in enumerate(members_list):
        for a in ms:
            owner.setdefault(int(a), []).append(i)
    out: list[list[int]] = [[] for _ in members_list]
    f = edges["from_id"].to_numpy(np.int64)
    t = edges["to_id"].to_numpy(np.int64)
    e = edges["edge_id"].to_numpy(np.int64)
    cand = np.fromiter((a in owner for a in f), bool, len(f)) & np.fromiter((b in owner for b in t), bool, len(t))
    for fi, ti, ei in zip(f[cand], t[cand], e[cand]):
        for i in set(owner[int(fi)]) & set(owner[int(ti)]):
            out[i].append(int(ei))
    return out


def load_predictions(path: Path, edges: pd.DataFrame, min_size: int) -> tuple[list, dict]:
    """-> (ring-like records with `.member_edges` / `.seed_edges` / `.members`, info)."""
    if is_full_schema(path):
        rings = read_rings_any(path)
        schema = "full"
    else:
        df = _read_minimal(path)
        assert {"ring_id", "members"} <= set(df.columns), f"{path}: need ring_id and members, got {df.columns.tolist()}"
        members = [set(int(a) for a in m) for m in df["members"]]
        if "member_edges" in df.columns:
            medges = [[int(e) for e in m] for m in df["member_edges"]]
        else:
            medges = induced_edges(members, edges)
        rings = [SimpleNamespace(ring_id=str(r), members=sorted(m), member_edges=me, seed_edges=[])
                 for r, m, me in zip(df["ring_id"], members, medges)]
        schema = "minimal" + ("" if "member_edges" in df.columns else " (induced edges)")
    n_in = len(rings)
    rings = [r for r in rings if len(set(r.members)) >= min_size]
    return rings, {"path": str(path), "sha256": sha256(path), "schema": schema, "n_rings_in_file": n_in,
                   "n_rings_after_min_size": len(rings)}


# ------------------------------------------------------------------------------------- truth
def build_targets(gt_path: Path, W) -> dict:
    """{convention: (targets, patterns)} plus the observability block."""
    gt = pd.read_parquet(gt_path)
    tv, pat = load_ground_truth(gt_path, *W.bounds, "test_visible", verbose=False)
    fm, fpat = load_ground_truth(gt_path, *W.bounds, "full_membership", verbose=False)
    comp, cpat, _ = component_truth(tv, pat, gt, W)
    comp3, cpat3, _ = component_truth(tv, pat, gt, W, min_members=3)
    if comp:
        assert set().union(*comp.values()) == set().union(*tv.values()), "pieces must partition the visible members"
    rings_with_ge3_piece = {k[0] for k in comp3}
    obs = {"n_in_scope_rings": len(tv),
           "rings_lt3_visible_members": int(sum(1 for v in tv.values() if len(v) < 3)),
           "rings_no_in_window_piece_ge3": int(len(tv) - len(rings_with_ge3_piece)),
           "rings_split_into_ge2_pieces": int(sum(1 for r in tv if (r, 1) in comp)),
           "n_pieces": len(comp), "n_pieces_ge3": len(comp3),
           "rings_with_a_piece_ge3": len(rings_with_ge3_piece)}
    return {"test_visible": (tv, pat), "full_membership": (fm, fpat), "component": (comp, cpat),
            "component_ge3": (comp3, cpat3)}, obs


def target_key(t) -> str:
    return f"{t[0]}#{t[1]}" if isinstance(t, tuple) else str(t)


# ------------------------------------------------------------------------------------- scoring
def weighted_boot(evs, ids, metric, n, seed):
    """Percentile bootstrap over `ids` with multiplicities (the bootstrap_over_rings procedure):
    the same RNG draws as scope_sensitivity.boot, but a target drawn k times gets weight k."""
    ids = list(ids)
    if not ids:
        return float("nan"), float("nan"), float("nan")
    point = float(np.nanmean([metrics_from_evidence(e, truth_ids=ids)[metric] for e in evs]))
    rng = np.random.default_rng(seed)
    d = np.empty(n)
    for b in range(n):
        uniq, counts = np.unique(rng.integers(0, len(ids), len(ids)), return_counts=True)
        sub = [ids[i] for i in uniq]
        w = {ids[i]: int(c) for i, c in zip(uniq, counts)}
        with np.errstate(invalid="ignore"):
            d[b] = np.nanmean([metrics_from_evidence(e, truth_ids=sub, weights=w)[metric] for e in evs])
    return point, float(np.nanpercentile(d, 2.5)), float(np.nanpercentile(d, 97.5))


def score(rings_per_run: list[list], edges: pd.DataFrame, targets: dict, W, thresholds, n_boot: int,
          boot_seed: int, conventions=CONVENTIONS, legacy_intervals: bool = False,
          tie_break: str = "deterministic"):
    ci = boot if legacy_intervals else weighted_boot
    rows, evidence = [], {}
    for conv in conventions:
        truth, patterns = targets[conv]
        ids = list(truth)
        for tau in thresholds:
            evs = [ring_evidence(rings, edges, truth, W, method=f"run{i + 1}", seed=i + 1, patterns=patterns,
                                 threshold=tau, causal=True, tie_break=tie_break) for i, rings in enumerate(rings_per_run)]
            f1, f1lo, f1hi = ci(evs, ids, "ring_f1", n_boot, boot_seed)
            r, rlo, rhi = ci(evs, ids, "ring_recall", n_boot, boot_seed)
            p, plo, phi = ci(evs, ids, "ring_precision", n_boot, boot_seed)
            m = [metrics_from_evidence(e) for e in evs]
            per_pattern = {}
            for pt in sorted(set(patterns.values())):
                sub = [t for t in ids if patterns.get(t) == pt]
                per_pattern[pt] = {"n_targets": len(sub), "recall": float(np.mean(
                    [metrics_from_evidence(e, truth_ids=sub)["ring_recall"] for e in evs]))}
            rows.append({"convention": conv, "threshold": tau, "n_runs": len(evs), "n_targets": len(ids),
                         "ring_precision": float(np.mean([x["ring_precision"] for x in m])),
                         "ring_precision_lo": plo, "ring_precision_hi": phi,
                         "ring_recall": r, "ring_recall_lo": rlo, "ring_recall_hi": rhi,
                         "ring_f1": f1, "ring_f1_lo": f1lo, "ring_f1_hi": f1hi,
                         "ring_recall_ge3": float(np.nanmean([x["ring_recall_ge3"] for x in m])),
                         "member_coverage": float(np.mean([x["member_coverage"] for x in m])),
                         "matched_per_run": float(np.mean([x["n_matched"] for x in m])),
                         "predicted_per_run": float(np.mean([x["n_predicted"] for x in m])),
                         "per_pattern_recall": per_pattern})
            evidence[f"{conv}@{tau}"] = {"target_ids": [target_key(t) for t in ids],
                                        "runs": [{"matched": [int(e.matched[t]) for t in ids],
                                                  "n_predicted": int(e.n_predicted)} for e in evs]}
    return rows, evidence


def evidence_stat(ev_block: dict):
    """stat(W) for paired_unit_bootstrap: ring precision / recall / F1 with runs averaged, using the
    same precision scaling as ring_stats.metrics_from_evidence."""
    M = np.array([r["matched"] for r in ev_block["runs"]], dtype=float)       # (runs, units)
    npred = np.array([r["n_predicted"] for r in ev_block["runs"]], dtype=float)
    n = M.shape[1]

    def stat(W):
        nt = W.sum(axis=1)                                                       # (B,)
        nm = W @ M.T                                                             # (B, runs)
        rec = nm / nt[:, None]
        npe = npred[None, :] * (nt[:, None] / n)
        prec = np.minimum(np.where(npe > 0, nm / np.where(npe > 0, npe, 1), 0.0), 1.0)
        f1 = np.where(prec + rec > 0, 2 * prec * rec / np.where(prec + rec > 0, prec + rec, 1), 0.0)
        return {"ring_f1": f1.mean(axis=1), "ring_recall": rec.mean(axis=1), "ring_precision": prec.mean(axis=1)}
    return stat, n


def compare(dir_a: Path, dir_b: Path, n_boot: int, seed: int) -> list[dict]:
    ea = json.loads((dir_a / "evidence.json").read_text(encoding="utf-8"))
    eb = json.loads((dir_b / "evidence.json").read_text(encoding="utf-8"))
    rows = []
    for key in sorted(set(ea) & set(eb)):
        assert ea[key]["target_ids"] == eb[key]["target_ids"], f"{key}: the two runs were scored on different targets"
        sa, n = evidence_stat(ea[key])
        sb, _ = evidence_stat(eb[key])
        res = paired_unit_bootstrap(lambda m, W: (sa if m == "a" else sb)(W), [("a_minus_b", "a", "b")], n,
                                    n_boot=n_boot, seed=seed)
        conv, tau = key.split("@")
        for metric in ("ring_f1", "ring_recall", "ring_precision"):
            r = res[("a_minus_b", metric)]
            rows.append({"convention": conv, "threshold": float(tau), "metric": metric, "delta": r["delta"],
                         "ci_lo": r["lo"], "ci_hi": r["hi"], "p": r["p"], "n_valid_draws": r["n_valid"],
                         "n_units": n})
    return rows


# ------------------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rings", type=Path, nargs="+", help="one predicted-rings file per seed / run")
    ap.add_argument("--split", choices=["val", "test"], default="test")
    ap.add_argument("--window", choices=["primary", "tail", "whole", "val"], default="primary")
    ap.add_argument("--eval-window", type=Path, default=None, help="default: the dataset's own window file")
    ap.add_argument("--truth", type=Path, default=None, help="default: <processed_dir>/amlworld_ring_ground_truth.parquet")
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--thresholds", type=float, nargs="+", default=list(DEFAULT_THRESHOLDS))
    ap.add_argument("--conventions", nargs="+", choices=CONVENTIONS, default=list(CONVENTIONS))
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--boot-seed", type=int, default=0,
                    help="bootstrap RNG seed; 0 is the seed of the r14/v36 tables this scorer reproduces")
    ap.add_argument("--compare", type=Path, nargs=2, metavar=("DIR_A", "DIR_B"), default=None,
                    help="paired unit bootstrap of A minus B from two earlier --out directories")
    ap.add_argument("--compare-n-boot", type=int, default=10000)
    ap.add_argument("--compare-seed", type=int, default=20261114)
    ap.add_argument("--legacy-subsample-intervals", action="store_true",
                    help="reproduce the r14/v36 intervals (scope_sensitivity.boot: repeats collapse, ~63 %% "
                         "subsample per resample, too narrow); default is the weighted r9 bootstrap")
    ap.add_argument("--legacy-file-order", action="store_true",
                    help="break equal-Jaccard matcher ties by prediction file order, as the frozen tables were "
                         "scored; default is deterministic (Jaccard desc, smaller truth id, sorted member tuple)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass
    a.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if a.compare:
        rows = compare(a.compare[0], a.compare[1], a.compare_n_boot, a.compare_seed)
        pd.DataFrame(rows).to_csv(a.out / "compare.csv", index=False)
        (a.out / "compare.json").write_text(json.dumps(
            {"created_utc": stamp, "git_commit": _git_commit(), "a": str(a.compare[0]), "b": str(a.compare[1]),
             "n_boot": a.compare_n_boot, "seed": a.compare_seed,
             "test": "evaluation.ring_stats.paired_unit_bootstrap over truth targets, runs averaged",
             "rows": rows}, indent=2), encoding="utf-8")
        for r in rows:
            if r["metric"] == "ring_f1":
                print(f"{r['convention']:16s} tau={r['threshold']:.1f}  dF1 {r['delta']:+.4f} "
                      f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}]  p {r['p']:.4f}")
        print(f"-> {a.out / 'compare.csv'}")
        return rows

    if not a.rings:
        ap.error("--rings is required unless --compare is given")
    paths = load_paths()
    pdir = paths["processed_dir"]
    truth_path = a.truth or pdir / "amlworld_ring_ground_truth.parquet"
    win_path = a.eval_window or default_eval_window()
    W = load_windows(win_path)[a.window]
    if W.split != a.split:
        ap.error(f"window {a.window!r} lies in the {W.split} split, not {a.split!r}")
    edges = load_split_edges(a.split, pdir)
    targets, obs = build_targets(truth_path, W)
    runs, inputs = [], []
    for p in a.rings:
        rings, info = load_predictions(p, edges, a.min_size)
        runs.append(rings)
        inputs.append(info)
    rows, evidence = score(runs, edges, targets, W, a.thresholds, a.n_boot, a.boot_seed, a.conventions,
                           legacy_intervals=a.legacy_subsample_intervals,
                           tie_break="file_order" if a.legacy_file_order else "deterministic")
    # share of >=3-account pieces recovered, on rings that have one (component_ge3 recall at 0.5)
    ge3 = [r for r in rows if r["convention"] == "component_ge3" and abs(r["threshold"] - 0.5) < 1e-9]
    if ge3:
        obs["pieces_ge3_recovered_share_at_0.5"] = ge3[0]["ring_recall"]

    flat = pd.DataFrame([{k: v for k, v in r.items() if k != "per_pattern_recall"} for r in rows])
    flat.to_csv(a.out / "summary.csv", index=False)
    (a.out / "metrics.json").write_text(json.dumps(
        {"created_utc": stamp, "dataset": paths.get("dataset", "HI-Small"), "split": a.split,
         "window": W.as_dict() if hasattr(W, "as_dict") else a.window, "min_size": a.min_size,
         "thresholds": a.thresholds, "n_boot": a.n_boot, "boot_seed": a.boot_seed,
         "interval": ("2.5/97.5 percentile bootstrap over truth targets, runs averaged inside each resample; "
                      + ("LEGACY subsample (evaluation.scope_sensitivity.boot; repeats collapse)"
                         if a.legacy_subsample_intervals else
                         "draw counts as weights (as evaluation.ring_stats.bootstrap_over_rings)")),
         "legacy_subsample_intervals": a.legacy_subsample_intervals,
         "matcher_tie_break": "file_order" if a.legacy_file_order else "deterministic",
         "observability": obs, "rows": rows}, indent=2, default=float), encoding="utf-8")
    (a.out / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    (a.out / "config.json").write_text(json.dumps(
        {"created_utc": stamp, "git_commit": _git_commit(), "argv": sys.argv[1:] if argv is None else list(argv),
         "ringshield_paths": os.environ.get("RINGSHIELD_PATHS", "configs/paths.yaml"),
         "eval_window_file": str(win_path), "truth": {"path": str(truth_path), "sha256": sha256(truth_path)},
         "split_parquet": {"path": str(pdir / f"amlworld_{a.split}.parquet")},
         "inputs": inputs}, indent=2), encoding="utf-8")
    print(f"observability: {obs}")
    for r in rows:
        print(f"{r['convention']:16s} tau={r['threshold']:.1f} targets {r['n_targets']:5d}  "
              f"P {r['ring_precision']:.4f}  R {r['ring_recall']:.4f}  "
              f"F1 {r['ring_f1']:.4f} [{r['ring_f1_lo']:.4f}, {r['ring_f1_hi']:.4f}]")
    print(f"-> {a.out}")
    return rows


if __name__ == "__main__":
    main()
