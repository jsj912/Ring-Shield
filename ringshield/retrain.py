"""Real retraining behind `python -m ringshield train --component {expansion,affinity}`.

Analyst verdicts on predicted rings become extra training rows, appended to the ORIGINAL training
set of the component, and the component is retrained with the same settings and the same grouped
cross-validation it was first trained with. Nothing is fine-tuned in place: a retrained model is
"the shipped model, trained on more data", so an empty label file must reproduce the shipped model
exactly, and does (tests/test_retrain.py).

Label semantics (labels parquet: ring_id, member_accounts, member_edges, verdict):

    confirm   every edge in member_edges is a member of the ring
    partial   member_edges is the analyst's CORRECTED member set
    reject    the ring is not a ring: no edge is a member

What becomes a training row:

    expansion  candidates are generated around the ring's SEED edges with the same generator and
               the same feature code that built the original training set (candidates(),
               compute_features(); delta_t_h and max_hops read from the training set's own json).
               label = 1 iff the candidate is in member_edges of a confirm / partial; every
               candidate of a reject is 0.
    affinity   pairs among the ring's included edges (seed + expanded, plus any corrected member
               the pipeline did not include), with the pair builder the aggregator uses at
               inference. label = 1 only when BOTH edges are confirmed members (confirm, or the
               corrected set of a partial); every pair of a reject is 0.

The seed and expanded edges come from the rings parquet the labels refer to (`--rings`): the label
file carries the members, not the anchors the pipeline used. Features are computed in the
operating context the labels came from (`--scores`, `--gfp`, `--embeddings`), which is exactly the
context the model sees at inference.

Each labelled ring is its own CV group, so a ring's rows never straddle a train/validation fold.
Rows accumulate: a model dir produced by a retrain carries its label rows, and the next retrain
from it includes them, with a later verdict on the same ring_id replacing the earlier one.

Leakage guard: the retraining gate scores on the validation-period holdout in
configs/holdout_manifest.json. A label is refused if its ring_id is one of the holdout's truth ring
ids, or if any of its edges falls inside the holdout's validation days -- unless
`--allow-holdout-overlap` is passed. Predicted val ring ids are not used: the contract ring_id has
no split in it, so every predicted test ring id also names a val ring; the edge-day check is what
catches a predicted val ring, and it catches all of them.
Test-window labels are allowed: that is the operating period. The check is recorded in version.json
whether it passes or is overridden.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_MANIFEST = REPO_ROOT / "configs" / "holdout_manifest.json"
GROUP_OFFSET = 1_000_000_000          # label groups sit far above any truth ring id / component id
POSITIVE_VERDICTS = ("confirm", "partial")
HASHED_KEYS = ("rule", "window", "split", "days", "t_min", "t_max", "scope", "min_visible_members",
               "truth_ring_ids")
ROWS_FILE = {"expansion": "retrain_rows_expansion.parquet", "affinity": "retrain_rows_affinity.parquet"}
LABELS_FILE = "retrain_labels.parquet"


class RetrainError(ValueError):
    """A refusal the CLI turns into exit code 2 with the message."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------- holdout manifest
def manifest_content_sha256(m: dict) -> str:
    """sha256 of the manifest's defining content, canonicalised. Stored in the file and re-checked
    on every load, so an edited id list cannot pass silently as the committed holdout."""
    body = {k: m[k] for k in HASHED_KEYS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_holdout_manifest(valrings_dir: Path, out: Path = HOLDOUT_MANIFEST, *, seeds=(1, 2, 3, 4, 5),
                           min_visible_members: int = 3) -> dict:
    """Write configs/holdout_manifest.json ONCE. Never re-run to "update" it: the point of a holdout
    is that it does not move. The rule is stored in the file next to the ids it produced."""
    from contract.make_scored_edges import load_paths
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    if Path(out).exists():
        raise RetrainError(f"{out} already exists; the holdout is fixed once and never regenerated")
    w = load_windows()["val"]
    t_min, t_max = (int(x) for x in w.bounds)
    gt = load_paths()["processed_dir"] / "amlworld_ring_ground_truth.parquet"
    truth, _ = load_ground_truth(gt, t_min, t_max, "test_visible", verbose=False)
    truth_ids = sorted(int(r) for r, acc in truth.items() if len(acc) >= min_visible_members)
    # Predicted val ring ids are NOT listed. The contract ring_id rule is
    # f"{aggregator}-{model_id}-{seed}-{idx}" with no split in it, so every predicted TEST ring id
    # also exists as a val ring id (560 of 560 shipped test rings collide). Guarding by predicted id
    # would refuse every operating-period label. A predicted val ring always has edges in the val
    # days, so the edge-day check catches all of them exactly; ids guard only the truth rings, whose
    # ids are unique across the dataset.
    sources = []
    for s_ in seeds:
        f = Path(valrings_dir) / "average" / f"seed{s_}" / "rings_val.parquet"
        if f.exists():
            sources.append({"path": str(f.relative_to(Path(valrings_dir).parent)).replace("\\", "/"),
                            "sha256": file_sha256(f),
                            "n_rings": int(len(pd.read_parquet(f, columns=["ring_id"])))})
    m = {"rule": (f"truth_ring_ids: every ground-truth ring in scope of the 'val' window "
                  f"(configs/eval_window.yaml, days {list(range(w.day_lo, w.day_hi + 1))}) under the test_visible convention "
                  f"with >= {min_visible_members} visible members -- the scoring set of the holdout ring-F1. "
                  f"The training guard refuses a label whose ring_id is one of these ids, or any of whose edges "
                  f"falls in days {list(range(w.day_lo, w.day_hi + 1))} (t_min..t_max). Predicted val ring ids are "
                  f"not listed because predicted ring ids carry no split and collide with test ring ids; the "
                  f"edge-day check covers every predicted val ring. Chosen once on {_now()[:10]}; never regenerated."),
         "window": "val", "split": w.split, "days": list(range(int(w.day_lo), int(w.day_hi) + 1)), "t_min": t_min, "t_max": t_max,
         "scope": "test_visible", "min_visible_members": int(min_visible_members),
         "truth_ring_ids": truth_ids,
         "eval_usage": ("`ringshield eval --holdout configs/holdout_manifest.json` reads truth_ring_ids. There "
                        "is deliberately no pred_ring_ids key: eval would filter a retrained model's rings by "
                        "the shipped model's ids, and a retrained model numbers its rings afresh."),
         "val_rings_provenance": sources, "created_utc": _now()}
    m["content_sha256"] = manifest_content_sha256(m)
    Path(out).write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def load_holdout_manifest(path: Path = HOLDOUT_MANIFEST) -> dict:
    path = Path(path)
    if not path.exists():
        raise RetrainError(f"holdout manifest not found: {path}")
    m = json.loads(path.read_text(encoding="utf-8"))
    got = manifest_content_sha256(m)
    if got != m.get("content_sha256"):
        raise RetrainError(f"{path}: content hash mismatch (file says {m.get('content_sha256')}, content is {got}); "
                           f"the holdout has been edited and cannot be trusted")
    return m


def holdout_check(labels: pd.DataFrame, edge_ts: pd.Series, manifest: dict, manifest_path: Path,
                  allow_overlap: bool) -> dict:
    """Which labels touch the holdout, by ring_id or by edge day. Raises unless allowed."""
    guard_ids = {str(x) for x in manifest["truth_ring_ids"]}
    t_min, t_max = int(manifest["t_min"]), int(manifest["t_max"])
    by_id, by_day = [], []
    for r in labels.itertuples(index=False):
        if str(r.ring_id) in guard_ids:
            by_id.append(str(r.ring_id))
        ts = edge_ts.reindex([int(e) for e in r.member_edges]).dropna().to_numpy(np.int64)
        if len(ts) and bool(((ts >= t_min) & (ts <= t_max)).any()):
            by_day.append(str(r.ring_id))
    offending = sorted(set(by_id) | set(by_day))
    rec = {"manifest": str(manifest_path).replace("\\", "/"), "manifest_content_sha256": manifest["content_sha256"],
           "manifest_file_sha256": file_sha256(Path(manifest_path)), "verified": True,
           "holdout_days": manifest["days"], "t_min": t_min, "t_max": t_max,
           "n_labels_checked": int(len(labels)), "n_ring_id_in_holdout": len(by_id),
           "n_with_edges_in_holdout_days": len(by_day), "offending_ring_ids": offending,
           "allow_holdout_overlap": bool(allow_overlap), "passed": not offending}
    if offending and not allow_overlap:
        raise RetrainError(f"{len(offending)} label(s) overlap the holdout ({len(by_id)} by ring_id, {len(by_day)} by an edge "
                           f"in val days {manifest['days']}): {offending[:5]}. Retraining on them would let the "
                           f"retraining gate score a model on its own training data. Pass --allow-holdout-overlap to "
                           f"override; the override is recorded in version.json.")
    return rec


# --------------------------------------------------------------------------- label -> rows
def _ring_lookup(rings_parquet: Path) -> dict[str, dict]:
    cols = ["ring_id", "seed_edges", "expanded_edges"]
    df = pd.read_parquet(rings_parquet, columns=cols)
    return {str(r.ring_id): {"seed_edges": [int(e) for e in r.seed_edges],
                             "expanded_edges": [int(e) for e in r.expanded_edges]} for r in df.itertuples(index=False)}


def _positives(row) -> set[int]:
    return {int(e) for e in row.member_edges} if row.verdict in POSITIVE_VERDICTS else set()


def policy_rows(labels: pd.DataFrame, ring_of: dict, se: pd.DataFrame, ctx, columns: list[str], group_of: dict,
                delta_t_h: float, max_hops: int) -> tuple[pd.DataFrame, list[dict]]:
    """Training rows in the original training set's columns, one block per labelled ring."""
    from ringshield.expand.candidates import candidates
    from ringshield.expand.features import compute_features
    parts, per = [], []
    for r in labels.itertuples(index=False):
        seeds = ring_of[str(r.ring_id)]["seed_edges"]
        pos = _positives(r)
        rec = {"ring_id": str(r.ring_id), "verdict": r.verdict, "n_member_edges": len(r.member_edges),
               "n_seed_edges": len(seeds), "group_id": group_of[str(r.ring_id)], "n_rows": 0, "n_positive": 0}
        if seeds:
            c = candidates(se, seeds, delta_t_h, max_hops, index=ctx.idx).reset_index(drop=True)
            if len(c):
                X = compute_features(ctx, c, seeds, delta_t_h)
                lab = c["candidate_edge_id"].astype(np.int64).isin(pos).astype(np.int64).to_numpy()
                X["label"] = lab
                X["is_member_edge"] = lab
                X["ring_id"] = group_of[str(r.ring_id)]
                X["pattern_type"] = f"LABEL:{r.verdict}"
                X["fold"] = -1
                X["day"] = ((X["candidate_ts"].to_numpy(np.int64) - 10) // 86400).astype(np.int64)
                for col in ("shared_account", "via_edge_id", "gap_via_s"):
                    X[col] = c[col].to_numpy() if col in c.columns else np.nan
                missing = [k for k in columns if k not in X.columns]
                if missing:
                    raise RetrainError(f"policy rows lack training-set columns {missing}")
                parts.append(X[columns])
                rec.update(n_rows=int(len(X)), n_positive=int(lab.sum()))
        per.append(rec)
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)
    return rows, per


def affinity_rows(labels: pd.DataFrame, ring_of: dict, ctx, columns: list[str],
                  group_of: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Pair rows in pairs_train.parquet's columns, one CV group per labelled ring."""
    from ringshield.partition.pairs import components_of, pair_features
    idx = ctx.idx
    emb_of = None
    if ctx.emb is not None:
        def emb_of(pa, pb):
            return ctx.emb.get(idx.edge_id[pa]), ctx.emb.get(idx.edge_id[pb])
    parts, per = [], []
    for r in labels.itertuples(index=False):
        ring = ring_of[str(r.ring_id)]
        pos = _positives(r)
        seeds = set(ring["seed_edges"])
        inc_ids = np.array(sorted(seeds | set(ring["expanded_edges"]) | pos), dtype=np.int64)
        rec = {"ring_id": str(r.ring_id), "verdict": r.verdict, "n_member_edges": len(r.member_edges),
               "n_included_edges": int(len(inc_ids)), "group_id": group_of[str(r.ring_id)], "n_rows": 0, "n_positive": 0}
        if len(inc_ids) >= 2:
            inc_pos = idx.pos_of(inc_ids)
            is_seed = np.isin(inc_ids, list(seeds))
            comp = components_of(idx, inc_pos)
            ring_arr = np.where(np.isin(inc_ids, list(pos)), 1, -1).astype(np.int64)
            P = pair_features(idx, ctx.gfp, inc_pos, is_seed, comp, emb_of=emb_of, ring_id=ring_arr)
            if len(P):
                P["component"] = group_of[str(r.ring_id)]
                if "fold_a" in columns:
                    P["fold_a"] = -1
                missing = [k for k in columns if k not in P.columns]
                if missing:
                    raise RetrainError(f"affinity rows lack pairs_train columns {missing}")
                parts.append(P[columns])
                rec.update(n_rows=int(len(P)), n_positive=int(P["label"].sum()))
        per.append(rec)
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)
    return rows, per


# --------------------------------------------------------------------------- the retrain itself
def _cv_summary(cv) -> dict | None:
    if isinstance(cv, str):                        # the shipped json stores a repr for older models
        import ast
        try:
            cv = ast.literal_eval(cv)
        except Exception:
            return {"raw": cv[:200]}
    if not isinstance(cv, dict):
        return None
    keep = ("n_rows", "n_pos", "n_neg", "n_rings", "n_components", "cv_auc_pr_mean", "cv_auc_pr_std",
            "cv_auc_pr_min", "cv_auc_pr_max", "oof_auc_pr", "final_num_boost_round", "scale_pos_weight_chosen", "train_seed")
    return {k: cv[k] for k in keep if k in cv}


def _merge_labels(new: pd.DataFrame, base_dir: Path) -> tuple[pd.DataFrame, list[str]]:
    """Inherited labels from a previously retrained base, with a later verdict replacing an earlier one."""
    f = base_dir / LABELS_FILE
    if not f.exists():
        return new.reset_index(drop=True), []
    old = pd.read_parquet(f)
    replaced = sorted(set(old["ring_id"].astype(str)) & set(new["ring_id"].astype(str)))
    old = old[~old["ring_id"].astype(str).isin(replaced)]
    return pd.concat([old, new], ignore_index=True), replaced


def retrain(component: str, *, labels: pd.DataFrame, labels_path: Path, base_dir: Path, out_dir: Path,
            scores: Path | None, rings: Path | None, gfp: Path | None, embeddings: Path | None,
            holdout_manifest: Path = HOLDOUT_MANIFEST, allow_holdout_overlap: bool = False,
            training_set: Path | None = None, train_seed: int = 1, version_base: dict | None = None,
            git_commit: str | None = None) -> dict:
    from ringshield.expand.context import build_context
    from ringshield.expand.policy import Policy, train_policy
    from ringshield.model_dir import read_model
    from ringshield.partition.affinity import Affinity, train_affinity
    from ringshield.__main__ import _load_scored_edges

    sub = {"expansion": "policy", "affinity": "affinity"}[component]
    base_dir, out_dir = Path(base_dir), Path(out_dir)
    model = read_model(base_dir)
    if not (base_dir / sub).is_dir():
        raise RetrainError(f"{base_dir} has no {sub}/ -- a '{model.get('aggregator')}' model dir has no "
                           f"{component} component to retrain (use a full model dir)")
    manifest = load_holdout_manifest(holdout_manifest)

    all_labels, replaced = _merge_labels(labels, base_dir)
    labels_new = labels.reset_index(drop=True)
    if len(labels_new) and (scores is None or rings is None):
        raise RetrainError("--scores and --rings are required when the label file is not empty "
                           "(features are built in the labels' operating context, and seeds come from the rings file)")

    # ---- the guard, on the NEW labels (inherited ones were checked when they were added) ----------
    se = _load_scored_edges(Path(scores), None) if scores else None
    edge_ts = se.set_index("edge_id")["timestamp"] if se is not None else pd.Series(dtype=np.int64)
    if se is not None and len(labels_new):
        unknown = sorted({int(e) for es in labels_new["member_edges"] for e in es} - set(edge_ts.index.astype(int)))
        if unknown:
            raise RetrainError(f"{len(unknown)} label edge(s) are not in --scores (e.g. {unknown[:5]}): the scores must "
                               f"cover the period the labels were made on")
    check = holdout_check(labels_new, edge_ts, manifest, holdout_manifest, allow_holdout_overlap)

    # ---- the original training set + inherited rows ------------------------------------------------
    meta = json.loads((base_dir / sub / f"{sub}.json").read_text(encoding="utf-8"))
    ts_path = Path(training_set) if training_set else Path(meta["training_set"] if component == "expansion" else meta["pairs"])
    if not ts_path.is_absolute():
        # recorded relative to the research repo root (e.g. "experiments/R4_partition/pairs_train.parquet"):
        # resolve against the configured experiments_dir's parent, so a checkout without the
        # gitignored experiments/ still finds them through RINGSHIELD_PATHS
        from contract.make_scored_edges import load_paths
        root = load_paths()["experiments_dir"].parent
        ts_path = (root / ts_path) if (root / ts_path).exists() else (REPO_ROOT / ts_path)
    if not ts_path.exists():
        raise RetrainError(f"original training set not found: {ts_path} (pass --training-set)")
    base_rows = pd.read_parquet(ts_path)
    columns = list(base_rows.columns)
    inherited = pd.DataFrame(columns=columns)
    if (base_dir / ROWS_FILE[component]).exists():
        inherited = pd.read_parquet(base_dir / ROWS_FILE[component])
        grp_col = "ring_id" if component == "expansion" else "component"
        drop_groups = set()
        if replaced:
            prev = pd.read_parquet(base_dir / LABELS_FILE)
            drop_groups = set(prev.loc[prev["ring_id"].astype(str).isin(replaced), "group_id"].astype(int))
        inherited = inherited[~inherited[grp_col].isin(drop_groups)]

    # ---- group ids: stable per ring_id across versions ------------------------------------------------
    prev_groups = {}
    if (base_dir / LABELS_FILE).exists():
        prev = pd.read_parquet(base_dir / LABELS_FILE)
        prev_groups = dict(zip(prev["ring_id"].astype(str), prev["group_id"].astype(int)))
    nxt = max(prev_groups.values(), default=GROUP_OFFSET - 1) + 1
    group_of = {}
    for rid in labels_new["ring_id"].astype(str):
        group_of[rid] = prev_groups.get(rid, nxt)
        if rid not in prev_groups:
            nxt += 1

    # ---- rows from the new labels ---------------------------------------------------------------------
    new_rows, per = pd.DataFrame(columns=columns), []
    if len(labels_new):
        ring_of = _ring_lookup(Path(rings))
        absent = sorted(set(labels_new["ring_id"].astype(str)) - set(ring_of))
        if absent:
            raise RetrainError(f"{len(absent)} labelled ring_id(s) not in --rings: {absent[:5]}")
        ctx = build_context(se, gfp_parquet=Path(gfp) if gfp else None,
                            embeddings_parquet=Path(embeddings) if embeddings else None,
                            head_constants=model["params"].get("head_constants"))
        if component == "expansion":
            tsj = ts_path.with_suffix(".json")
            p = json.loads(tsj.read_text(encoding="utf-8"))["params"] if tsj.exists() else {}
            new_rows, per = policy_rows(labels_new, ring_of, se, ctx, columns, group_of,
                                        float(p.get("delta_t_h", 72.0)), int(p.get("max_hops", 2)))
        else:
            new_rows, per = affinity_rows(labels_new, ring_of, ctx, columns, group_of)

    frames = [f for f in (base_rows, inherited, new_rows) if len(f)]
    train = pd.concat(frames, ignore_index=True) if len(frames) > 1 else base_rows

    # ---- retrain with the shipped settings --------------------------------------------------------------
    if component == "expansion":
        old = Policy.load(base_dir / "policy")
        new = train_policy(train, drop_groups=tuple(old.drop_groups), hop1_only=bool(old.hop1_only),
                           seed=train_seed, verbose=False)
        new.meta.update({"training_set": str(ts_path), "retrained_from": str(base_dir)})
    else:
        from ringshield.partition.pairs import FEATURE_GROUPS as PAIR_GROUPS
        old = Affinity.load(base_dir / "affinity")
        # Derived from the shipped affinity's own feature list, not from metadata: a detector whose
        # affinity was trained without embeddings (gfpxgb) must be retrained without them too.
        dropped = [g for g, cols in PAIR_GROUPS.items() if not any(c in old.features for c in cols)]
        new = train_affinity(train, drop_groups=tuple(dropped), seed=train_seed, verbose=False)
        new.meta.update({"pairs": str(ts_path), "retrained_from": str(base_dir)})

    # ---- write ----------------------------------------------------------------------------------------
    if out_dir.resolve() == base_dir.resolve():
        raise RetrainError("--out-model-dir must differ from --base-model-dir")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(base_dir, out_dir)
    shutil.rmtree(out_dir / sub)
    new.save(out_dir / sub)
    keep_rows = pd.concat([f for f in (inherited, new_rows) if len(f)], ignore_index=True) if (len(inherited) or len(new_rows)) \
        else pd.DataFrame(columns=columns)
    keep_rows.to_parquet(out_dir / ROWS_FILE[component], index=False)
    lab_out = all_labels.copy()
    lab_out["group_id"] = [group_of.get(str(r), prev_groups.get(str(r), -1)) for r in lab_out["ring_id"].astype(str)]
    lab_out["component"] = component
    lab_out.to_parquet(out_dir / LABELS_FILE, index=False)

    counts = labels_new["verdict"].value_counts().to_dict()
    old_cv = _cv_summary(meta.get("cv"))
    new_cv = _cv_summary(new.meta.get("cv"))
    version = {
        "version": int((version_base or {}).get("version", model.get("version", 1))) + 1,
        "created_utc": _now(), "git_commit": git_commit, "component": component, "retrained": True,
        "train_seed": int(train_seed), "base_model_dir": str(base_dir),
        "labels": {"path": str(labels_path), "sha256": file_sha256(Path(labels_path)),
                   "n_by_verdict": {v: int(counts.get(v, 0)) for v in ("confirm", "partial", "reject")}},
        "inputs": {"scores": str(scores) if scores else None, "rings": str(rings) if rings else None,
                   "gfp": str(gfp) if gfp else None, "embeddings": str(embeddings) if embeddings else None},
        "base_training_set": {"path": str(ts_path), "sha256": file_sha256(ts_path), "n_rows": int(len(base_rows)),
                              "n_positive": int(base_rows["label"].sum())},
        "appended": {"n_rows_new": int(len(new_rows)), "n_positive_new": int(new_rows["label"].sum()) if len(new_rows) else 0,
                     "n_rows_inherited": int(len(inherited)), "n_rows_total_trained_on": int(len(train)),
                     "n_labels_replaced": len(replaced), "replaced_ring_ids": replaced},
        "cv": {"old": old_cv, "new": new_cv,
               "delta_cv_auc_pr_mean": (new_cv["cv_auc_pr_mean"] - old_cv["cv_auc_pr_mean"])
               if (old_cv and new_cv and "cv_auc_pr_mean" in old_cv and "cv_auc_pr_mean" in new_cv) else None},
        "holdout_check": check,
        "training_labels": {
            "note": ("every ring_id whose verdict is in this model's training data, cumulative over versions. "
                     "Downstream test-window metrics after retraining must exclude these rings (docs/CLI.md)."),
            "n_rings": int(len(lab_out)),
            "rings": [{"ring_id": str(r.ring_id), "verdict": r.verdict, "n_member_edges": int(len(r.member_edges)),
                       "n_member_accounts": int(len(r.member_accounts)), "group_id": int(r.group_id)}
                      for r in lab_out.itertuples(index=False)],
            "this_round": per},
    }
    (out_dir / "version.json").write_text(json.dumps(version, indent=2, default=str), encoding="utf-8")
    m = json.loads((out_dir / "model.json").read_text(encoding="utf-8"))
    m["version"] = version["version"]
    (out_dir / "model.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    return version


# --------------------------------------------------------------------------- holdout ring-F1
def holdout_ring_f1(model_dir: Path, *, val_scores: Path, gfp: Path, embeddings: Path,
                    truth: Path, manifest_path: Path = HOLDOUT_MANIFEST) -> dict:
    """Ring metrics of a model dir on the holdout: val window, test_visible, the manifest's truth ids.
    The quantity the retraining gate compares before and after a retrain."""
    from ringshield.__main__ import _aggregate, _load_scored_edges
    from ringshield.evaluate import restrict_rings, ring_metrics_full
    from ringshield.model_dir import read_model
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    man = load_holdout_manifest(manifest_path)
    model = read_model(Path(model_dir))
    se = _load_scored_edges(Path(val_scores), None)
    rings = _aggregate(model["aggregator"], se, dict(model["params"]), model["model_id"], int(model["seed"]),
                       model_dir=Path(model_dir), gfp=Path(gfp), embeddings=Path(embeddings), report={})
    w = load_windows()["val"]
    tr, pats = load_ground_truth(Path(truth), int(man["t_min"]), int(man["t_max"]), man["scope"], verbose=False)
    ids = set(int(x) for x in man["truth_ring_ids"])
    tr = {k: v for k, v in tr.items() if int(k) in ids}
    pats = {k: v for k, v in pats.items() if int(k) in ids}
    pred = restrict_rings(rings, se, w)
    return ring_metrics_full(pred, tr, pats, 0.5, [0.3, 0.7])


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="one-off: write configs/holdout_manifest.json")
    ap.add_argument("command", choices=["build-holdout"])
    ap.add_argument("--valrings-dir", type=Path, required=True, help="the experiments_valrings/ directory")
    a = ap.parse_args(argv)
    m = build_holdout_manifest(a.valrings_dir)
    print(f"[retrain] holdout manifest: {len(m['truth_ring_ids'])} truth rings in val days {m['days']}, "
          f"content_sha256 {m['content_sha256']}")


if __name__ == "__main__":
    main()
