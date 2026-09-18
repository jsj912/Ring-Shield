"""Research CLI for the platform team (Step 5): `python -m ringshield {run,train,eval,export-model}`.

    python -m ringshield run  --scores <scored_edges.parquet> [--edge-subset <parquet with edge_id>]
                              --model-dir <dir> --aggregator cc|expand|full --out <rings.parquet>
    python -m ringshield train --component expansion|affinity|typing --labels <labels.parquet>
                              --base-model-dir <dir> --out-model-dir <dir>
    python -m ringshield eval --rings <rings.parquet> --truth <gt.parquet> [--holdout <manifest.json>]
                              --scope test_visible --out <metrics.json>
    python -m ringshield export-model --run-dir <run_rings output> --out-model-dir <dir>   (research side)

docs/CLI.md is the contract for these commands. Exit code 0 on success, 2 on a usage /
validation error (message on stderr), 1 on an unexpected failure.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.schema import RINGS_ORDER, SCORED_EDGES_ORDER  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, aggregate_cc, threshold_for_pct  # noqa: E402
from ringshield.evaluate import restrict_rings, ring_metrics_full  # noqa: E402
from ringshield.model_dir import AGGREGATORS, _git_commit, from_run_dir, read_model  # noqa: E402
from ringshield.rings import Ring, read_rings_parquet, write_rings_parquet  # noqa: E402
from ringshield.truth import POLICIES, load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

VERDICTS = ("confirm", "reject", "partial")
COMPONENTS = ("expansion", "affinity", "typing")


class UsageError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- run
def _load_scored_edges(path: Path, split: str | None) -> pd.DataFrame:
    df = pd.read_parquet(path)
    cols = set(df.columns)
    if {"edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp", "score_raw"} <= cols:
        if "score_calibrated" not in cols:
            df["score_calibrated"] = df["score_raw"]
        return df
    if {"edge_id", "score_raw"} <= cols and split:
        from ringshield.scored_edges import build_scored_edges  # research-side convenience
        return build_scored_edges(path, split)
    raise UsageError(f"{path}: expected the scored_edges contract columns ({', '.join(SCORED_EDGES_ORDER[:7])}, ...); "
                     f"a bare scores file (edge_id, timestamp, score_raw) needs --split val|test")


def _aggregate(name: str, se: pd.DataFrame, params: dict, model_id: str, seed: int) -> list[Ring]:
    if name == "cc":
        rings = aggregate_cc(se, float(params["seed_frac_pct"]), int(params["min_size"]), params.get("max_gap_hours"),
                             aggregator_id="cc")
    elif name in ("expand", "full"):
        raise UsageError(f"aggregator '{name}' arrives in Steps 6-8 (expansion / partition); only 'cc' exists today. "
                         f"The command line and the output schema will not change.")
    else:
        raise UsageError(f"unknown aggregator {name!r}; choose from {', '.join(AGGREGATORS)}")
    return rings


def _tenant_of_earliest_seed(ring: Ring, se_idx: pd.DataFrame) -> int:
    """Sender bank of the ring's earliest seed edge (ties: smallest edge_id)."""
    seeds = se_idx.loc[ring.seed_edges, ["timestamp", "from_bank"]].sort_index()   # ties -> smallest edge_id
    first = seeds.sort_values("timestamp", kind="stable").index[0]
    return int(seeds.loc[first, "from_bank"])


def cmd_run(a) -> int:
    model = read_model(a.model_dir)
    aggregator = a.aggregator or model["aggregator"]
    if a.aggregator and a.aggregator != model["aggregator"]:
        print(f"[ringshield run] note: --aggregator {a.aggregator} overrides the model dir's {model['aggregator']}", file=sys.stderr)
    se = _load_scored_edges(Path(a.scores), a.split)
    n_in = len(se)
    subset_n = None
    if a.edge_subset:
        sub = pd.read_parquet(a.edge_subset)
        if "edge_id" not in sub.columns:
            raise UsageError(f"{a.edge_subset}: needs an edge_id column")
        ids = pd.Index(sub["edge_id"].astype(np.int64).unique())
        se = se[se["edge_id"].isin(ids)].reset_index(drop=True)
        subset_n = int(len(ids))
        if se.empty:
            raise UsageError("--edge-subset leaves no edges")
    params = dict(model["params"])
    for k in ("seed_frac_pct", "min_size", "max_gap_hours"):
        v = getattr(a, k.replace("-", "_"), None)
        if v is not None:
            params[k] = v
    model_id, seed = model["model_id"], int(model["seed"])
    if "model_id" in se.columns and se["model_id"].nunique() == 1 and str(se["model_id"].iloc[0]) not in ("unknown", model_id):
        print(f"[ringshield run] note: scores carry model_id {se['model_id'].iloc[0]!r}, model dir says {model_id!r}",
              file=sys.stderr)
    q = threshold_for_pct(se[SELECT_COL].to_numpy(float), float(params["seed_frac_pct"]))
    rings = _aggregate(aggregator, se, params, model_id, seed)

    # contract ids and the tenant rule (docs/CLI.md): sender bank of the earliest seed edge
    se_idx = se.set_index("edge_id").sort_index()
    out_rings = []
    for i, r in enumerate(rings):
        d = r.to_dict()
        d["ring_id"] = f"{aggregator}-{model_id}-{seed}-{i}"
        d["aggregator_id"] = aggregator
        d["tenant_id"] = _tenant_of_earliest_seed(r, se_idx)
        out_rings.append(Ring(**{c: d[c] for c in RINGS_ORDER}))
    out = Path(a.out)
    write_rings_parquet(out_rings, out)
    log = {"created_utc": _now(), "git_commit": _git_commit(), "command": "run", "scores": str(a.scores),
           "edge_subset": str(a.edge_subset) if a.edge_subset else None, "n_edges_in_file": n_in,
           "n_edge_subset_ids": subset_n, "n_edges_used": int(len(se)), "n_scored": int(se[SELECT_COL].notna().sum()),
           "model_dir": str(a.model_dir), "model": {k: model.get(k) for k in ("model_id", "seed", "aggregator", "version", "feature_set")},
           "aggregator": aggregator, "params": params, "selection_column": SELECT_COL,
           "quantile_cut": {"q": q, "rule": "strict: score_raw > q, computed within the edges given (after --edge-subset)",
                            "n_seeds": int((se[SELECT_COL] > q).sum()), "n_on_boundary": int((se[SELECT_COL] == q).sum())},
           "n_rings": len(out_rings), "n_seed_edges": int(sum(len(r.seed_edges) for r in out_rings)),
           "n_member_edges": int(sum(len(r.member_edges) for r in out_rings)),
           "ring_id_rule": "f'{aggregator}-{model_id}-{seed}-{idx}'",
           "tenant_rule": "sender bank (from_bank) of the ring's earliest seed edge; ties -> smallest edge_id",
           "out": str(out)}
    Path(str(out) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"[ringshield run] {len(out_rings)} rings from {len(se):,} edges ({log['quantile_cut']['n_seeds']:,} seeds, "
          f"q={q:.6f}, {log['quantile_cut']['n_on_boundary']} tied on the boundary) -> {out}")
    return 0


# --------------------------------------------------------------------------- train
LABELS_SCHEMA = pa.schema([("ring_id", pa.string()), ("member_accounts", pa.list_(pa.int64())),
                           ("member_edges", pa.list_(pa.int64())), ("verdict", pa.string())])


def validate_labels(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        raise UsageError(f"labels file not found: {path}")
    df = pd.read_parquet(path)
    missing = [c for c in ("ring_id", "member_accounts", "member_edges", "verdict") if c not in df.columns]
    if missing:
        raise UsageError(f"{path}: missing columns {missing}")
    bad = sorted(set(df["verdict"].astype(str)) - set(VERDICTS))
    if bad:
        raise UsageError(f"{path}: verdict values {bad} not in {VERDICTS}")
    if df["ring_id"].isna().any() or not df["ring_id"].map(lambda x: isinstance(x, str)).all():
        raise UsageError(f"{path}: ring_id must be a non-null string")
    if df["ring_id"].duplicated().any():
        raise UsageError(f"{path}: duplicate ring_id: {df['ring_id'][df['ring_id'].duplicated()].tolist()[:5]}")
    for col in ("member_accounts", "member_edges"):
        ok = df[col].map(lambda v: v is not None and hasattr(v, "__len__") and all(int(x) == x for x in list(v)))
        if not ok.all():
            raise UsageError(f"{path}: {col} must be a list of integers on every row")
    empty = df[df["verdict"].isin(["confirm", "partial"]) & (df["member_accounts"].map(len) == 0)]
    if len(empty):
        raise UsageError(f"{path}: confirm/partial rows with empty member_accounts: {empty['ring_id'].tolist()[:5]}")
    return df


def cmd_train(a) -> int:
    if a.component not in COMPONENTS:
        raise UsageError(f"--component must be one of {COMPONENTS}")
    base = Path(a.base_model_dir)
    model = read_model(base)  # validates the base dir
    labels = validate_labels(Path(a.labels))
    out = Path(a.out_model_dir)
    if out.resolve() == base.resolve():
        raise UsageError("--out-model-dir must differ from --base-model-dir")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base, out)
    counts = labels["verdict"].value_counts().to_dict()
    confirmed = labels[labels["verdict"] == "confirm"].copy()
    confirmed["added_utc"] = _now()
    confirmed["source_labels"] = str(Path(a.labels))
    confirmed["component"] = a.component
    extra_path = out / "extra_labels.parquet"
    if extra_path.exists():
        prev = pd.read_parquet(extra_path)
        confirmed = pd.concat([prev, confirmed], ignore_index=True)
    table = pa.Table.from_pandas(confirmed[["ring_id", "member_accounts", "member_edges", "verdict", "added_utc",
                                            "source_labels", "component"]], preserve_index=False)
    pq.write_table(table, extra_path)
    prev_version = json.loads((base / "version.json").read_text(encoding="utf-8")) if (base / "version.json").exists() else {}
    version = {"version": int(prev_version.get("version", model.get("version", 1))) + 1,
               "created_utc": _now(), "git_commit": _git_commit(), "component": a.component,
               "base_model_dir": str(base), "labels": str(Path(a.labels)),
               "n_labels": {v: int(counts.get(v, 0)) for v in VERDICTS},
               "n_extra_labels_total": int(len(confirmed)),
               "retrained": False,
               "note": "no learned component exists yet (Steps 6-8 add the expansion policy, affinity and typing head "
                       "behind this same command); the base model was copied unchanged and the confirmed rings appended "
                       "to extra_labels.parquet"}
    (out / "version.json").write_text(json.dumps(version, indent=2), encoding="utf-8")
    m = json.loads((out / "model.json").read_text(encoding="utf-8"))
    m["version"] = version["version"]
    (out / "model.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    print(f"[ringshield train] {a.component}: {counts} -> {out} (version {version['version']}, "
          f"{len(confirmed)} confirmed rings in extra_labels.parquet; no retraining yet)")
    return 0


# --------------------------------------------------------------------------- eval
def cmd_eval(a) -> int:
    rings = read_rings_parquet(Path(a.rings))
    if a.scope not in POLICIES:
        raise UsageError(f"--scope must be one of {POLICIES}")
    windows = load_windows()
    if a.t_min is not None and a.t_max is not None:
        t_min, t_max, window_name = int(a.t_min), int(a.t_max), "explicit"
    else:
        if a.window not in windows:
            raise UsageError(f"--window must be one of {list(windows)}")
        t_min, t_max = windows[a.window].bounds
        window_name = a.window
    truth, patterns = load_ground_truth(Path(a.truth), t_min, t_max, a.scope, verbose=False)
    holdout = None
    if a.holdout:
        man = json.loads(Path(a.holdout).read_text(encoding="utf-8"))
        ids = man.get("truth_ring_ids", man.get("ring_ids"))
        pred_ids = man.get("pred_ring_ids")
        holdout = {"manifest": str(a.holdout), "n_truth_listed": None, "n_pred_listed": None}
        if ids is not None:
            ids = {int(x) for x in ids}
            truth = {k: v for k, v in truth.items() if int(k) in ids}
            patterns = {k: v for k, v in patterns.items() if int(k) in ids}
            holdout["n_truth_listed"] = len(ids)
        if pred_ids is not None:
            keep = set(map(str, pred_ids))
            rings = [r for r in rings if r.ring_id in keep]
            holdout["n_pred_listed"] = len(keep)
    if a.scores:
        se = _load_scored_edges(Path(a.scores), None)

        class _Bounds:            # duck-typed Window: restrict_rings only calls .mask()
            def mask(self, ts):
                t = np.asarray(ts, dtype=np.int64)
                return (t >= t_min) & (t <= t_max)
        pred = restrict_rings(rings, se, _Bounds())
    else:
        pred = [r.member_set for r in rings]
    metrics = ring_metrics_full(pred, truth, patterns, float(a.match_threshold), [0.3, 0.7])
    out = {"created_utc": _now(), "git_commit": _git_commit(), "command": "eval", "rings": str(a.rings),
           "truth": str(a.truth), "scope": a.scope, "window": window_name, "t_min": t_min, "t_max": t_max,
           "match_threshold": float(a.match_threshold), "holdout": holdout, "n_rings_in_file": len(rings),
           "predicted_restricted_to_window": bool(a.scores), **metrics}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[ringshield eval] {len(pred)} rings vs {len(truth)} truth rings ({a.scope}, {window_name}): "
          f"P {metrics['ring_precision']:.4f} R {metrics['ring_recall']:.4f} F1 {metrics['ring_f1']:.4f} "
          f"R>=3 {metrics['ring_recall_ge3']} -> {a.out}")
    return 0


def cmd_export_model(a) -> int:
    p = from_run_dir(Path(a.run_dir), Path(a.out_model_dir), version=int(a.version))
    print(f"[ringshield export-model] -> {p}")
    return 0


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m ringshield", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="score edges -> rings.parquet (contract schema)")
    r.add_argument("--scores", required=True, help="scored_edges parquet (contract columns)")
    r.add_argument("--edge-subset", default=None, help="parquet with an edge_id column; restricts the input (tenant scope)")
    r.add_argument("--model-dir", required=True)
    r.add_argument("--aggregator", choices=AGGREGATORS, default=None, help="default: the model dir's aggregator")
    r.add_argument("--out", required=True, help="rings.parquet; a .log.json is written beside it")
    r.add_argument("--split", choices=["val", "test"], default=None,
                   help="research convenience: lets --scores be a bare models/score.py file for this split")
    r.add_argument("--seed-frac-pct", type=float, default=None, help="override the model dir's quantile (rarely)")
    r.add_argument("--min-size", type=int, default=None)
    r.add_argument("--max-gap-hours", type=float, default=None)
    r.set_defaults(fn=cmd_run)

    t = sub.add_parser("train", help="feed analyst verdicts back (copies the base model; no retraining yet)")
    t.add_argument("--component", required=True, choices=COMPONENTS)
    t.add_argument("--labels", required=True, help="parquet: ring_id, member_accounts, member_edges, verdict")
    t.add_argument("--base-model-dir", required=True)
    t.add_argument("--out-model-dir", required=True)
    t.set_defaults(fn=cmd_train)

    e = sub.add_parser("eval", help="rings.parquet vs ground truth -> metrics.json")
    e.add_argument("--rings", required=True)
    e.add_argument("--truth", required=True, help="ring ground-truth parquet (ring_id, from_id, to_id, timestamp_int, pattern_type)")
    e.add_argument("--holdout", default=None, help="json manifest: {'truth_ring_ids': [...]} and/or {'pred_ring_ids': [...]}")
    e.add_argument("--scope", default="test_visible", choices=POLICIES)
    e.add_argument("--window", default="primary", help="configs/eval_window.yaml window name (default primary)")
    e.add_argument("--t-min", type=int, default=None, help="explicit scope window (loader basis) instead of --window")
    e.add_argument("--t-max", type=int, default=None)
    e.add_argument("--scores", default=None, help="optional scored_edges parquet: restrict predicted rings to the window")
    e.add_argument("--match-threshold", type=float, default=0.5)
    e.add_argument("--out", required=True)
    e.set_defaults(fn=cmd_eval)

    x = sub.add_parser("export-model", help="research side: model dir from a ringshield/run_rings.py output")
    x.add_argument("--run-dir", required=True)
    x.add_argument("--out-model-dir", required=True)
    x.add_argument("--version", type=int, default=1)
    x.set_defaults(fn=cmd_export_model)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
