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

from contract.schema import RINGS_SCHEMA_VERSION, RINGS_ORDER, SCORED_EDGES_ORDER  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, aggregate_cc, threshold_for_pct  # noqa: E402
from ringshield.evaluate import restrict_rings, ring_metrics_full  # noqa: E402
from ringshield.model_dir import AGGREGATORS, _git_commit, from_run_dir, read_model  # noqa: E402
from ringshield.rings import Ring, read_rings_parquet, write_rings_parquet  # noqa: E402
from ringshield.roles import fill_currency_fields  # noqa: E402
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


def _aggregate(name: str, se: pd.DataFrame, params: dict, model_id: str, seed: int, *, model_dir: Path | None = None,
               gfp: Path | None = None, embeddings: Path | None = None, report: dict | None = None) -> list[Ring]:
    if name == "cc":
        rings = aggregate_cc(se, float(params["seed_frac_pct"]), int(params["min_size"]), params.get("max_gap_hours"),
                             aggregator_id="cc")
    elif name == "expand":
        from ringshield.aggregators.expand import aggregate_expand
        from ringshield.expand.context import build_context
        from ringshield.expand.policy import Policy
        for k in ("delta_t_h", "p_min", "policy_kind"):
            if k not in params:
                raise UsageError(f"model dir has no params.{k}: not an 'expand' model (export one from a run_expand output)")
        if params["policy_kind"] == "model":
            if model_dir is None or not (Path(model_dir) / "policy" / "policy.txt").exists():
                raise UsageError(f"{model_dir}: policy/policy.txt missing")
            policy = Policy.load(Path(model_dir) / "policy")
        else:
            policy = Policy.rule(params["policy_kind"])
        if gfp is None:
            print("[ringshield run] note: --gfp not given; the policy's GFP features are zero", file=sys.stderr)
        if embeddings is None and policy.kind == "model":
            print("[ringshield run] note: --embeddings not given; cosine features are missing (NaN)", file=sys.stderr)
        ctx = build_context(se, gfp_parquet=gfp, embeddings_parquet=embeddings, head_constants=params.get("head_constants"))
        rings = aggregate_expand(se, float(params["seed_frac_pct"]), int(params["min_size"]), params.get("max_gap_hours"),
                                 policy=policy, ctx=ctx, p_min=float(params["p_min"]), delta_t_h=float(params["delta_t_h"]),
                                 max_hops=int(params.get("max_hops", 2)), aggregator_id="expand", report=report)
    elif name == "full":
        from ringshield.aggregators.full import aggregate_full
        from ringshield.expand.context import build_context
        from ringshield.expand.policy import Policy
        from ringshield.partition.affinity import Affinity
        for k in ("delta_t_h", "p_min", "partition"):
            if k not in params:
                raise UsageError(f"model dir has no params.{k}: not a 'full' model (export one from a run_partition output)")
        md = Path(model_dir) if model_dir is not None else None
        if md is None or not (md / "policy" / "policy.txt").exists():
            raise UsageError(f"{model_dir}: policy/policy.txt missing")
        policy = Policy.load(md / "policy")
        affinity = None
        if params["partition"] in ("b4", "pivot", "average"):
            if not (md / "affinity" / "affinity.txt").exists():
                raise UsageError(f"{model_dir}: affinity/affinity.txt missing for partition {params['partition']!r}")
            affinity = Affinity.load(md / "affinity")
        if gfp is None:
            print("[ringshield run] note: --gfp not given; GFP features are zero", file=sys.stderr)
        if embeddings is None:
            print("[ringshield run] note: --embeddings not given; cosine features are missing (NaN)", file=sys.stderr)
        ctx = build_context(se, gfp_parquet=gfp, embeddings_parquet=embeddings, head_constants=params.get("head_constants"))
        rings = aggregate_full(se, float(params["seed_frac_pct"]), int(params["min_size"]), params.get("max_gap_hours"),
                               policy=policy, ctx=ctx, p_min=float(params["p_min"]), delta_t_h=float(params["delta_t_h"]),
                               affinity=affinity, method=params["partition"], seed=int(params.get("cluster_seed", 0)),
                               max_hops=int(params.get("max_hops", 2)), aggregator_id="full", report=report,
                               **{k: v for k, v in (params.get("partition_cell") or {}).items()})
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
    tenant_n = None
    if a.tenant_id is not None:
        # One tenant's view: the edges whose contract `tenant_id` is N (= the sending bank). Applied
        # BEFORE seed selection, so the seed quantile is computed within the tenant's own edges --
        # the same rule as --edge-subset, and what a tenant-only deployment would actually do.
        if "tenant_id" not in se.columns:
            raise UsageError("--tenant-id needs a scored_edges file with a tenant_id column")
        se = se[se["tenant_id"].astype(np.int64) == int(a.tenant_id)].reset_index(drop=True)
        tenant_n = int(len(se))
        if se.empty:
            raise UsageError(f"--tenant-id {a.tenant_id}: no edges with that tenant_id")
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
    report: dict = {}
    rings = _aggregate(aggregator, se, params, model_id, seed, model_dir=Path(a.model_dir),
                       gfp=Path(a.gfp) if a.gfp else None, embeddings=Path(a.embeddings) if a.embeddings else None, report=report)

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
    # Schema v2: the `*_ccy` fields are computed here, not left at their defaults. A rings file
    # stamped version 2 whose currency fields are empty is worse than a v1 file, because a reader
    # cannot tell "no currency effect" from "never computed".
    ccy = fill_currency_fields(out_rings, se)
    write_rings_parquet(out_rings, out)
    log = {"created_utc": _now(), "git_commit": _git_commit(), "command": "run", "scores": str(a.scores),
           "contract_version": f"rings.parquet v{RINGS_SCHEMA_VERSION}", "currency_v2": ccy,
           "edge_subset": str(a.edge_subset) if a.edge_subset else None,
           "tenant_id": int(a.tenant_id) if a.tenant_id is not None else None, "n_edges_tenant": tenant_n,
           "n_edges_in_file": n_in,
           "n_edge_subset_ids": subset_n, "n_edges_used": int(len(se)), "n_scored": int(se[SELECT_COL].notna().sum()),
           "model_dir": str(a.model_dir), "model": {k: model.get(k) for k in ("model_id", "seed", "aggregator", "version", "feature_set")},
           "aggregator": aggregator, "params": params, "selection_column": SELECT_COL,
           "quantile_cut": {"q": q, "rule": "strict: score_raw > q, computed within the edges given (after --edge-subset)",
                            "n_seeds": int((se[SELECT_COL] > q).sum()), "n_on_boundary": int((se[SELECT_COL] == q).sum())},
           "n_rings": len(out_rings), "n_seed_edges": int(sum(len(r.seed_edges) for r in out_rings)),
           "n_member_edges": int(sum(len(r.member_edges) for r in out_rings)),
           "n_expanded_edges": int(sum(len(r.expanded_edges) for r in out_rings)),
           "expansion": report or None, "gfp": str(a.gfp) if a.gfp else None, "embeddings": str(a.embeddings) if a.embeddings else None,
           "partition": params.get("partition"), "partition_cell": params.get("partition_cell"),
           "ring_id_rule": "f'{aggregator}-{model_id}-{seed}-{idx}'",
           "tenant_rule": "sender bank (from_bank) of the ring's earliest seed edge; ties -> smallest edge_id",
           "out": str(out)}
    Path(str(out) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"[ringshield run] {len(out_rings)} rings from {len(se):,} edges ({log['quantile_cut']['n_seeds']:,} seeds, "
          f"q={q:.6f}, {log['quantile_cut']['n_on_boundary']} tied on the boundary"
          + (f", {log['n_expanded_edges']} expanded edges" if aggregator in ("expand", "full") else "") + f") -> {out}")
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


def _cmd_retrain(a, base: Path, model: dict, labels: pd.DataFrame) -> int:
    """Real retraining (ringshield/retrain.py): rows from the verdicts, appended to the original
    training set, the component retrained with its shipped settings and grouped CV."""
    from ringshield.retrain import HOLDOUT_MANIFEST, RetrainError, retrain
    out = Path(a.out_model_dir)
    if out.resolve() == base.resolve():
        raise UsageError("--out-model-dir must differ from --base-model-dir")
    prev = json.loads((base / "version.json").read_text(encoding="utf-8")) if (base / "version.json").exists() else {}
    try:
        v = retrain(a.component, labels=labels, labels_path=Path(a.labels), base_dir=base, out_dir=out,
                    scores=Path(a.scores) if a.scores else None, rings=Path(a.rings) if a.rings else None,
                    gfp=Path(a.gfp) if a.gfp else None, embeddings=Path(a.embeddings) if a.embeddings else None,
                    holdout_manifest=Path(a.holdout_manifest) if a.holdout_manifest else HOLDOUT_MANIFEST,
                    allow_holdout_overlap=bool(a.allow_holdout_overlap),
                    training_set=Path(a.training_set) if a.training_set else None,
                    train_seed=int(a.train_seed), version_base=prev or {"version": model.get("version", 1)},
                    git_commit=_git_commit())
    except RetrainError as e:
        raise UsageError(str(e)) from None
    cv = v["cv"]
    fmt = lambda d: f"{d['cv_auc_pr_mean']:.4f}" if d and d.get("cv_auc_pr_mean") is not None else "?"  # noqa: E731
    print(f"[ringshield train] {a.component} RETRAINED -> {out} (version {v['version']}): "
          f"{v['appended']['n_rows_new']:,} new rows ({v['appended']['n_positive_new']} positive) from "
          f"{sum(v['labels']['n_by_verdict'].values())} labels, {v['appended']['n_rows_total_trained_on']:,} rows in total; "
          f"CV AUC-PR {fmt(cv['old'])} -> {fmt(cv['new'])}; holdout check "
          f"{'passed' if v['holdout_check']['passed'] else 'OVERRIDDEN by --allow-holdout-overlap'}")
    return 0


def cmd_train(a) -> int:
    if a.component not in COMPONENTS:
        raise UsageError(f"--component must be one of {COMPONENTS}")
    base = Path(a.base_model_dir)
    model = read_model(base)  # validates the base dir
    labels = validate_labels(Path(a.labels))
    if a.component in ("expansion", "affinity"):
        return _cmd_retrain(a, base, model, labels)
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
               "note": "typing is not retrained by this command: the base model was copied unchanged and the "
                       "confirmed rings appended to extra_labels.parquet. expansion and affinity ARE retrained "
                       "(ringshield/retrain.py)"}
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
    r.add_argument("--tenant-id", type=int, default=None,
                   help="run on one tenant's edges only: scored_edges.tenant_id == N (the sending bank); seeds are "
                        "selected within the tenant. Combines with --edge-subset (intersection)")
    r.add_argument("--model-dir", required=True)
    r.add_argument("--aggregator", choices=AGGREGATORS, default=None, help="default: the model dir's aggregator")
    r.add_argument("--out", required=True, help="rings.parquet; a .log.json is written beside it")
    r.add_argument("--split", choices=["val", "test"], default=None,
                   help="research convenience: lets --scores be a bare models/score.py file for this split")
    r.add_argument("--seed-frac-pct", type=float, default=None, help="override the model dir's quantile (rarely)")
    r.add_argument("--min-size", type=int, default=None)
    r.add_argument("--max-gap-hours", type=float, default=None)
    r.add_argument("--gfp", default=None, help="expand: the split's GFP parquet (amlworld_gfp_features_<split>.parquet)")
    r.add_argument("--embeddings", default=None, help="expand: R1 embeddings parquet of the same detector seed and split")
    r.set_defaults(fn=cmd_run)

    t = sub.add_parser("train", help="retrain a component from analyst verdicts (expansion, affinity); typing: copy + append")
    t.add_argument("--component", required=True, choices=COMPONENTS)
    t.add_argument("--labels", required=True, help="parquet: ring_id, member_accounts, member_edges, verdict")
    t.add_argument("--base-model-dir", required=True)
    t.add_argument("--out-model-dir", required=True)
    t.add_argument("--scores", default=None, help="scored_edges of the period the labels were made on (features, edge days)")
    t.add_argument("--rings", default=None, help="the rings parquet the labels refer to (seed / expanded edges)")
    t.add_argument("--gfp", default=None, help="that split's GFP parquet")
    t.add_argument("--embeddings", default=None, help="that split's embeddings for the base model's detector seed")
    t.add_argument("--holdout-manifest", default=None, help="default configs/holdout_manifest.json")
    t.add_argument("--allow-holdout-overlap", action="store_true",
                   help="train on labels that touch the holdout anyway (recorded in version.json)")
    t.add_argument("--training-set", default=None, help="override the original training set path recorded in the model")
    t.add_argument("--train-seed", type=int, default=1, help="LightGBM / fold-shuffle seed (the shipped models used 1)")
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
