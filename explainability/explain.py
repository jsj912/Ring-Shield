"""One ring in, one explanation row out (spec section 3.1, XR-21 / 30 / 32). Week 2: the weights.

    python -m explainability.explain                         # all seeds in config.yaml -> results/xai/
    python -m explainability.explain --seeds 1 --rings contract/out/rings_stub_cc.parquet \
        --name "explanations_week2_stub_cc_seed{seed}.parquet" --disagreement-name "roles_disagreement_stub_cc_seed{seed}.csv"

For every ring of a rings file:
    edge_weights     every member edge: (edge_id, w_total, w_score, w_loo, w_flow), sorted by w_total
    account_weights  every member account: (account_id, role, inflow, outflow, hold_time_s, w_account)
    feature_weights  empty until Week 3 (SHAP)
    topology_type / topology_prob   copied from the ring
    narrative / evidence_summary    empty (null) until Week 3
    latency_ms       wall-clock time to build this row
    provenance       JSON: model, aggregator, seed, explainer version, mixing weights and every other setting

Determinism (XR-30): every column except latency_ms is identical on every run. latency_ms is a timing and
can never repeat exactly; the spec asks for both in one file, so the determinism check excludes that column.
Alongside each parquet: a role-disagreement CSV (XR-12) and a .log.json summary (counts, latency).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from contract.schema import TOPOLOGY_TYPES
from explainability.account_weights import (ACCOUNT_WEIGHT_COLUMNS, DISAGREEMENT_COLUMNS, account_weight_table,
                                            background_degree, research_roles, role_disagreements, spec_roles)
from explainability.contract_io import (REPO_ROOT, load_config, load_research_config, provenance, read_rings,
                                        read_scored_edges, repo_path)
from explainability.edge_weights import EDGE_WEIGHT_COLUMNS, LooInputs, edge_weight_table, load_loo_inputs, w_loo

EDGE_STRUCT = pa.struct([("edge_id", pa.int64()), ("w_total", pa.float64()), ("w_score", pa.float64()),
                         ("w_loo", pa.float64()), ("w_flow", pa.float64())])
ACCOUNT_STRUCT = pa.struct([("account_id", pa.int64()), ("role", pa.string()), ("inflow", pa.float64()),
                            ("outflow", pa.float64()), ("hold_time_s", pa.float64()), ("w_account", pa.float64())])
FEATURE_STRUCT = pa.struct([("feature_name", pa.string()), ("mean_shap", pa.float64()), ("top_edge_id", pa.int64())])
EXPLANATIONS_SCHEMA = pa.schema([
    ("ring_id", pa.string()), ("tenant_id", pa.int64()),
    ("edge_weights", pa.list_(EDGE_STRUCT)), ("account_weights", pa.list_(ACCOUNT_STRUCT)),
    ("feature_weights", pa.list_(FEATURE_STRUCT)),
    ("topology_type", pa.string()), ("topology_prob", pa.float64()),
    ("narrative", pa.string()), ("evidence_summary", pa.string()),
    ("latency_ms", pa.int64()), ("provenance", pa.string()),
])


@dataclass
class ExplainContext:
    """What every ring of one file shares: the transactions, background degrees, rerun inputs, settings."""
    scored_edges: pd.DataFrame          # indexed by edge_id
    deg_background: pd.Series
    loo: LooInputs
    cfg: dict
    roles_cfg: dict
    file_provenance: dict               # model_id, seed, aggregator_id


def _included(ring) -> list[int]:
    return sorted(set(map(int, ring.seed_edges)) | set(map(int, ring.expanded_edges)))


def _row_provenance(ctx: ExplainContext, loo: pd.DataFrame, ring) -> str:
    cfg, ew = ctx.cfg, ctx.cfg["edge_weights"]
    c0 = float(loo["c0"].iloc[0]) if len(loo) else math.nan
    shipped = float(ring.confidence)
    same_conf = (math.isnan(c0) and math.isnan(shipped)) or abs(c0 - shipped) < 1e-9
    reproduces = bool(len(loo) and bool(loo["base_is_input"].iloc[0]) and same_conf)
    prov = {**ctx.file_provenance, "explainer_version": cfg["explainer_version"],
            "mixing": {k: float(v) for k, v in ew["mixing_default"].items()}, "lambda_split": float(ew["lambda_split"]),
            "loo_edges": ew["loo_edges"], "loo_nan_policy": ew["loo_nan_policy"],
            "currency_policy": cfg["amounts"]["currency_policy"], "currency_policy_status": "provisional",
            "flow_amount_column": cfg["amounts"]["flow_amount_column"],
            "roles_source": "ringshield.roles.account_roles(edges='included')",
            "account_weight_shares": {k: float(v) for k, v in cfg["account_weights"].items()},
            "rerun": ctx.loo.params, "features_degraded": False,
            "loo": {"c0": None if math.isnan(c0) else c0, "shipped_confidence": None if math.isnan(shipped) else shipped,
                    "reproduces_shipped_ring": reproduces}}
    return json.dumps(prov, sort_keys=True)


def explain_ring(ring, ctx: ExplainContext) -> tuple[dict, pd.DataFrame, dict]:
    """(explanation row, role-disagreement rows, diagnostics) for one ring."""
    t0 = time.perf_counter()
    cfg, ew = ctx.cfg, ctx.cfg["edge_weights"]
    se = ctx.scored_edges
    member = se.loc[sorted(map(int, ring.member_edges))].reset_index()
    included = se.loc[_included(ring)].reset_index()
    loo = w_loo(included, ctx.loo.rerunner, lambda_split=float(ew["lambda_split"]), nan_policy=ew["loo_nan_policy"])
    table = edge_weight_table(member, loo, ew["mixing_default"], amount_col=cfg["amounts"]["flow_amount_column"],
                              tol=float(ew["mixing_sum_tolerance"]))
    roles = research_roles(ring, se)
    missing = set(map(int, ring.members)) - set(roles)
    if missing:
        raise ValueError(f"{ring.ring_id}: members without a research role {sorted(missing)[:5]}")
    acc = account_weight_table(ring.members, member, table, ctx.deg_background, roles,
                               score_share=float(cfg["account_weights"]["score_share"]),
                               degree_share=float(cfg["account_weights"]["degree_share"]))
    disagreements = role_disagreements(ring.ring_id, roles, spec_roles(included, ctx.roles_cfg))
    ttype = ring.topology_type
    tprob = float(ring.topology_probs[TOPOLOGY_TYPES.index(ttype)]) if ttype in TOPOLOGY_TYPES else math.nan
    row = {"ring_id": ring.ring_id, "tenant_id": int(ring.tenant_id),
           "edge_weights": table[EDGE_WEIGHT_COLUMNS].to_dict("records"),
           "account_weights": acc[ACCOUNT_WEIGHT_COLUMNS].to_dict("records"),
           "feature_weights": [], "topology_type": ttype, "topology_prob": tprob,
           "narrative": None, "evidence_summary": None, "latency_ms": 0,
           "provenance": _row_provenance(ctx, loo, ring)}
    diag = {"reproduces_shipped_ring": json.loads(row["provenance"])["loo"]["reproduces_shipped_ring"],
            "mixed_currency": int(member["currency_received"].nunique() > 1), "n_member_edges": len(member)}
    row["latency_ms"] = int(round((time.perf_counter() - t0) * 1000))
    return row, disagreements, diag


def build_context(cfg: dict, scores: str, rings_path: str) -> tuple[ExplainContext, pd.DataFrame]:
    se = read_scored_edges(scores)
    rings = read_rings(rings_path, scored_edges=se)
    prov = provenance(se, rings)
    ids = [e for r in rings.itertuples(index=False) for e in _included(r)]
    loo = load_loo_inputs(cfg, prov["seed"], prov["aggregator_id"], rings_path, ids)
    ctx = ExplainContext(se.set_index("edge_id"), background_degree(se), loo, cfg,
                         load_research_config(cfg, "roles"), prov)
    return ctx, rings


def explain_rings(rings: pd.DataFrame, ctx: ExplainContext) -> tuple[pa.Table, pd.DataFrame, list[dict]]:
    rows, dis, diags = [], [], []
    for r in rings.itertuples(index=False):
        row, d, g = explain_ring(r, ctx)
        rows.append(row)
        dis.append(d)
        diags.append({"ring_id": r.ring_id, "latency_ms": row["latency_ms"], **g})
    table = pa.Table.from_pylist(rows, schema=EXPLANATIONS_SCHEMA)
    dis = [d for d in dis if len(d)]
    disagreements = pd.concat(dis, ignore_index=True) if dis else pd.DataFrame(columns=DISAGREEMENT_COLUMNS)
    return table, disagreements, diags


def _rel(p) -> str:
    p = repo_path(p)
    try:
        return p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def run_file(cfg: dict, scores: str, rings_path: str, out_parquet, out_csv) -> dict:
    """Explain every ring of one rings file; write the parquet, the disagreement CSV and a .log.json."""
    ctx, rings = build_context(cfg, scores, rings_path)
    table, disagreements, diags = explain_rings(rings, ctx)
    out_parquet, out_csv = repo_path(out_parquet), repo_path(out_csv)
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_parquet)
    disagreements.to_csv(out_csv, index=False, lineterminator="\n")
    lat = np.array([d["latency_ms"] for d in diags], dtype=float)
    log = {"experiment_id": cfg["explanations_experiment_id"], "explainer_version": cfg["explainer_version"],
           "inputs": {"scored_edges": _rel(scores), "rings": _rel(rings_path)}, "provenance": ctx.file_provenance,
           "rerun": ctx.loo.params, "n_rings": len(rings), "n_explained": table.num_rows,
           "n_reproduces_shipped_ring": int(sum(d["reproduces_shipped_ring"] for d in diags)),
           "not_reproduced": [d["ring_id"] for d in diags if not d["reproduces_shipped_ring"]],
           "n_rings_mixed_currency": int(sum(d["mixed_currency"] for d in diags)),
           "role_disagreements": {"n_rows": len(disagreements),
                                  "by_cause": {k: int(v) for k, v in disagreements["cause"].value_counts().sort_index().items()}},
           "latency_ms": {"p50": float(np.percentile(lat, 50)) if len(lat) else None,
                          "p95": float(np.percentile(lat, 95)) if len(lat) else None,
                          "max": float(lat.max()) if len(lat) else None,
                          "rings_over_5000_ms": [d["ring_id"] for d in diags if d["latency_ms"] > 5000]},
           "outputs": {"explanations": _rel(out_parquet), "role_disagreements": _rel(out_csv)}}
    out_parquet.with_name(out_parquet.name + ".log.json").write_text(json.dumps(log, indent=2, sort_keys=True) + "\n",
                                                                     encoding="utf-8", newline="\n")
    return log


def main(argv=None) -> int:
    cfg = load_config()
    inp = cfg["inputs"]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", default=inp["scored_edges"], help="scored_edges parquet; '{seed}' is filled in")
    ap.add_argument("--rings", default=inp["rings"], help="rings parquet; '{seed}' is filled in")
    ap.add_argument("--seeds", type=int, nargs="+", default=inp["seeds"])
    ap.add_argument("--out", default=cfg["output_dir"])
    ap.add_argument("--name", default=cfg["explanations_name"])
    ap.add_argument("--disagreement-name", default=cfg["disagreement_name"])
    a = ap.parse_args(argv)
    for s in a.seeds:
        log = run_file(cfg, a.scores.format(seed=s), a.rings.format(seed=s),
                       repo_path(a.out) / a.name.format(seed=s), repo_path(a.out) / a.disagreement_name.format(seed=s))
        L = log["latency_ms"]
        print(f"seed {s}: {log['n_explained']}/{log['n_rings']} rings explained; reproduce shipped ring "
              f"{log['n_reproduces_shipped_ring']}/{log['n_rings']}; role disagreements {log['role_disagreements']}; "
              f"latency p50 {L['p50']:.0f} ms p95 {L['p95']:.0f} ms max {L['max']:.0f} ms -> {log['outputs']['explanations']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
