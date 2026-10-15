"""One ring in, one explanation row out (spec section 3.1, XR-21 / 30 / 32). Week 2: the weights; Week 3: SHAP + narrative.

    python -m explainability.explain                         # all seeds, weights + SHAP + narrative -> results/xai/
    python -m explainability.explain --no-narrative          # weights only (the migrated Week 2 files)
    python -m explainability.explain --samples               # the PILOT review sample, one narrative per type
    python -m explainability.explain --seeds 1 --rings contract/out/rings_stub_cc.parquet \
        --name "explanations_week2_stub_cc_seed{seed}.parquet" --disagreement-name "roles_disagreement_stub_cc_seed{seed}.csv"

For every ring of a rings file:
    edge_weights     every member edge: (edge_id, w_total, w_score, w_loo, w_flow), sorted by w_total
    account_weights  every member account: (account_id, role, inflow, outflow, hold_time_s, w_account)
    feature_weights  top 10 features by |mean SHAP| over the ring's seed edges (conversions left out); [] without narrative
    topology_type / topology_prob   copied from the ring
    narrative / evidence_summary    the filled template and every value it used (null without narrative, and always
                                    under policy raw, which only reproduces Week 2)
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
from ringshield.roles import ring_conservation_converted

from explainability.account_weights import (ACCOUNT_WEIGHT_COLUMNS, DISAGREEMENT_COLUMNS, account_weight_table,
                                            background_degree, research_roles, role_disagreements, spec_roles)
from explainability.contract_io import (REPO_ROOT, load_config, load_research_config, provenance, read_rings,
                                        read_scored_edges, repo_path)
from explainability.edge_weights import EDGE_WEIGHT_COLUMNS, LooInputs, edge_weight_table, load_fx, load_loo_inputs, w_loo
from explainability.feature_weights import (FeatureExplainer, load_feature_model, load_feature_rows, ring_feature_weights,
                                            verify_rows)
from explainability.narrative import (build_narrative, load_names, load_phrasing, narrative_values, summary_json,
                                      word_count)

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
    file_provenance: dict               # model_id, seed, aggregator_id, rings_schema_version
    policy: str = "converted"           # "converted" (current) or "raw" (reproduces Week 2 exactly)
    fx: dict | None = None              # exchange-rate table (policy converted)
    fx_sha256: str | None = None
    features: FeatureExplainer | None = None   # Week 3: SHAP; None = no feature weights / narrative
    phrasing: dict | None = None
    names: dict | None = None                  # Joan's code -> name maps (currency, payment format, bank)
    topology_source: str = "rings"             # "rings" (shipped type) or "rule_scorer" (XR-19 check)


def _included(ring) -> list[int]:
    return sorted(set(map(int, ring.seed_edges)) | set(map(int, ring.expanded_edges)))


def active_mixing(cfg: dict, policy: str) -> tuple[dict, str]:
    """(alpha, beta, gamma) and where they came from. `raw` always uses the untuned default (it exists only
    to reproduce Week 2); `converted` uses the validation-tuned weights once XR-05 has written them."""
    ew = cfg["edge_weights"]
    if policy == "converted" and ew.get("mixing_tuned"):
        return {k: float(v) for k, v in ew["mixing_tuned"].items()}, "tuned on validation (XR-05)"
    return {k: float(v) for k, v in ew["mixing_default"].items()}, "default, untuned"


def _row_provenance(ctx: ExplainContext, loo: pd.DataFrame, ring, extra: dict) -> str:
    cfg, ew = ctx.cfg, ctx.cfg["edge_weights"]
    c0 = float(loo["c0"].iloc[0]) if len(loo) else math.nan
    shipped = float(ring.confidence)
    same_conf = (math.isnan(c0) and math.isnan(shipped)) or abs(c0 - shipped) < 1e-9
    reproduces = bool(len(loo) and bool(loo["base_is_input"].iloc[0]) and same_conf)
    mixing, mixing_source = active_mixing(cfg, ctx.policy)
    converted = ctx.policy == "converted"
    prov = {**ctx.file_provenance, "explainer_version": cfg["explainer_version"],
            "mixing": mixing, "mixing_source": mixing_source, "lambda_split": float(ew["lambda_split"]),
            "loo_edges": ew["loo_edges"], "loo_nan_policy": ew["loo_nan_policy"],
            "currency_policy": ctx.policy,
            "evidence_edges": "member edges minus currency conversions" if converted else "all member edges",
            "w_flow_mode": "share of the ring's total converted to currency 0" if converted else "raw cross-currency share",
            "flow_amount_column": cfg["amounts"]["flow_amount_column"],
            "fx_rates": {"path": cfg["amounts"]["fx_rates"], "sha256": ctx.fx_sha256} if converted else None,
            "roles_source": f"ringshield.roles.account_roles(edges='included', currency='{'converted' if converted else 'raw'}')",
            "account_weight_shares": {k: float(v) for k, v in cfg["account_weights"].items()},
            "rerun": ctx.loo.params, "features_degraded": False,
            "loo": {"c0": None if math.isnan(c0) else c0, "shipped_confidence": None if math.isnan(shipped) else shipped,
                    "reproduces_shipped_ring": reproduces},
            **extra}
    return json.dumps(prov, sort_keys=True)


def explain_ring(ring, ctx: ExplainContext) -> tuple[dict, pd.DataFrame, dict]:
    """(explanation row, role-disagreement rows, diagnostics) for one ring."""
    t0 = time.perf_counter()
    cfg, ew = ctx.cfg, ctx.cfg["edge_weights"]
    converted = ctx.policy == "converted"
    se = ctx.scored_edges
    member = se.loc[sorted(map(int, ring.member_edges))].reset_index()
    included = se.loc[_included(ring)].reset_index()
    loo = w_loo(included, ctx.loo.rerunner, lambda_split=float(ew["lambda_split"]), nan_policy=ew["loo_nan_policy"])
    mixing, _ = active_mixing(cfg, ctx.policy)
    table = edge_weight_table(member, loo, mixing, amount_col=cfg["amounts"]["flow_amount_column"],
                              tol=float(ew["mixing_sum_tolerance"]), policy=ctx.policy, fx=ctx.fx)
    evidence = member[member["edge_id"].isin(table["edge_id"])]
    roles = research_roles(ring, se, currency="converted" if converted else "raw")
    missing = set(map(int, ring.members)) - set(roles)
    if missing:
        raise ValueError(f"{ring.ring_id}: members without a research role {sorted(missing)[:5]}")
    acc = account_weight_table(ring.members, evidence, table, ctx.deg_background, roles,
                               score_share=float(cfg["account_weights"]["score_share"]),
                               degree_share=float(cfg["account_weights"]["degree_share"]))
    # XR-12 compares two DEFINITIONS of a role (research vs spec 4.3) on the same raw flows, whatever the policy
    raw_roles = roles if not converted else research_roles(ring, se, currency="raw")
    disagreements = role_disagreements(ring.ring_id, raw_roles, spec_roles(included, ctx.roles_cfg))
    ttype, tprob = topology_of(ring, ctx, included, raw_roles)
    flow = table.attrs.get("flow") or {}
    n_undet = sum(1 for d in roles.values() if d["role"] == "undetermined")
    extra = {"n_conversions_dropped": int(table.attrs.get("n_conversions_dropped", 0)),
             "flow_partial": bool(flow.get("partial", False)),
             "n_unconvertible_edges": int(flow.get("n_unconvertible_edges", 0)),
             "flow_total_ccy0": flow.get("total_ccy0"), "n_undetermined_accounts": n_undet}
    edge_rows = table[EDGE_WEIGHT_COLUMNS].to_dict("records")
    acc_rows = acc[ACCOUNT_WEIGHT_COLUMNS].to_dict("records")
    feature_weights, narrative, summary = [], None, None
    if ctx.features is not None:
        fwc, nc = cfg["feature_weights"], cfg["narrative"]
        ranked = set(table["edge_id"])
        shap_edges = [e for e in sorted(map(int, ring.seed_edges)) if e in ranked]      # seed edges minus conversions
        feature_weights = ring_feature_weights(ctx.features.shap_values(shap_edges), int(fwc["top_n"]))
        values = narrative_values(
            topology_type=ttype, topology_prob=tprob, type_source=ctx.topology_source,
            duration_s=float(ring.duration_hours) * 3600, evidence=evidence, member_edges=member,
            edge_weights=edge_rows, account_weights=acc_rows, flow=flow,
            conservation=ring_conservation_converted(ring, se, edges="included", config=ctx.roles_cfg),
            closure_raw=float(ring.conservation_closure), feature_weights=feature_weights, fx=ctx.fx,
            n_top_edges=int(nc["top_edges"]), n_top_features=int(nc["top_features"]), names=ctx.names)
        narrative, summary = build_narrative(values, ctx.phrasing, nc)
        extra = {**extra, "n_shap_edges": len(shap_edges), "topology_source": ctx.topology_source,
                 "feature_model": fwc["model"].format(seed=ctx.file_provenance["seed"]),
                 "name_maps": dict(nc["names"])}
    row = {"ring_id": ring.ring_id, "tenant_id": int(ring.tenant_id),
           "edge_weights": edge_rows, "account_weights": acc_rows,
           "feature_weights": feature_weights, "topology_type": ttype, "topology_prob": tprob,
           "narrative": narrative, "evidence_summary": None if summary is None else summary_json(summary),
           "latency_ms": 0, "provenance": _row_provenance(ctx, loo, ring, extra)}
    diag = {"reproduces_shipped_ring": json.loads(row["provenance"])["loo"]["reproduces_shipped_ring"],
            "mixed_currency": int(evidence["currency_received"].nunique() > 1), "n_member_edges": len(member),
            "role_counts": {r: sum(1 for d in roles.values() if d["role"] == r) for r in sorted({d["role"] for d in roles.values()})},
            "narrative_words": None if narrative is None else word_count(narrative),
            "clauses": None if summary is None else summary["clauses"],
            "template": None if summary is None else summary["template"], **extra}
    row["latency_ms"] = int(round((time.perf_counter() - t0) * 1000))
    return row, disagreements, diag


def topology_of(ring, ctx: ExplainContext, included: pd.DataFrame, raw_roles: dict) -> tuple[str, float]:
    """(type, probability). `rings`: as delivered (the Step 8 typing head). `rule_scorer`: research's hand-written
    rules on the same ring (ringshield.typing), used only to show the wording does not depend on the source (XR-19)."""
    if ctx.topology_source == "rule_scorer":
        from ringshield.typing.features import ring_features
        from ringshield.typing.rules import rule_probs, rule_type
        f = ring_features(included, raw_roles)
        t = rule_type(f)
        return t, float(rule_probs(f)[TOPOLOGY_TYPES.index(t)])
    t = ring.topology_type
    return t, float(ring.topology_probs[TOPOLOGY_TYPES.index(t)]) if t in TOPOLOGY_TYPES else math.nan


def build_context(cfg: dict, scores: str, rings_path: str, policy: str | None = None, narrate: bool | None = None,
                  topology_source: str | None = None) -> tuple[ExplainContext, pd.DataFrame]:
    import hashlib
    policy = policy or cfg["amounts"]["currency_policy"]
    narrate = policy == "converted" if narrate is None else narrate
    if narrate and policy != "converted":
        raise ValueError("narratives need policy 'converted' (amounts in one currency); 'raw' only reproduces Week 2")
    se = read_scored_edges(scores)
    rings = read_rings(rings_path, scored_edges=se)
    prov = provenance(se, rings)
    ids = [e for r in rings.itertuples(index=False) for e in _included(r)]
    loo = load_loo_inputs(cfg, prov["seed"], prov["aggregator_id"], rings_path, ids)
    fx = sha = None
    if policy == "converted":
        fx = load_fx(cfg)
        sha = hashlib.sha256(repo_path(cfg["amounts"]["fx_rates"]).read_bytes()).hexdigest()
    ctx = ExplainContext(se.set_index("edge_id"), background_degree(se, exclude_conversions=policy == "converted"), loo, cfg,
                         load_research_config(cfg, "roles"), prov, policy, fx, sha)
    if narrate:
        booster = load_feature_model(cfg, prov["seed"])
        seed_ids = sorted({int(e) for r in rings.itertuples(index=False) for e in r.seed_edges})
        rows = load_feature_rows(cfg, booster, seed_ids)
        gap = verify_rows(booster, rows, cfg["feature_weights"]["shipped_scores"].format(seed=prov["seed"]))
        if gap > 1e-6:
            raise ValueError(f"feature rows do not reproduce the shipped GFP+XGBoost scores (max gap {gap})")
        ctx.features, ctx.phrasing = FeatureExplainer(booster, rows), load_phrasing(repo_path(cfg["narrative"]["phrasing"]))
        ctx.names = load_names({k: repo_path(v) for k, v in cfg["narrative"]["names"].items()})
        ctx.topology_source = topology_source or cfg["narrative"]["topology_source"]
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


def run_file(cfg: dict, scores: str, rings_path: str, out_parquet, out_csv, policy: str | None = None,
             narrate: bool | None = None) -> dict:
    """Explain every ring of one rings file; write the parquet, the disagreement CSV and a .log.json."""
    ctx, rings = build_context(cfg, scores, rings_path, policy, narrate)
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
           "policy": ctx.policy, "mixing": dict(zip(("values", "source"), active_mixing(cfg, ctx.policy))),
           "n_rings_mixed_currency": int(sum(d["mixed_currency"] for d in diags)),
           "n_conversions_dropped": int(sum(d["n_conversions_dropped"] for d in diags)),
           "n_rings_with_conversions": int(sum(d["n_conversions_dropped"] > 0 for d in diags)),
           "n_rings_flow_partial": int(sum(d["flow_partial"] for d in diags)),
           "n_undetermined_accounts": int(sum(d["n_undetermined_accounts"] for d in diags)),
           "role_counts": {r: int(sum(d["role_counts"].get(r, 0) for d in diags))
                           for r in sorted({r for d in diags for r in d["role_counts"]})},
           "narrative": None if ctx.features is None else {
               "n_narratives": int(sum(d["narrative_words"] is not None for d in diags)),
               "feature_model": cfg["feature_weights"]["model"].format(seed=ctx.file_provenance["seed"]),
               "topology_source": ctx.topology_source,
               "n_rings_without_shap_edges": int(sum(d.get("n_shap_edges", 0) == 0 for d in diags)),
               "words": {"p50": float(np.percentile([d["narrative_words"] for d in diags], 50)) if diags else None,
                         "max": max((d["narrative_words"] for d in diags), default=None)},
               "templates": {k: int(v) for k, v in sorted(pd.Series([d["template"] for d in diags]).value_counts().items())},
               "rings_with_clause": {k: int(v) for k, v in
                                     sorted(pd.Series([c for d in diags for c in d["clauses"]]).value_counts().items())}},
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


def review_samples(cfg: dict, seeds, out_path) -> dict:
    """Week 3 deliverable: one narrative per pattern type for the team to review (spec 7 in miniature).

    Per predicted type (TOPOLOGY_TYPES order): among the rings of all seeds that MATCHED a truth ring on the primary
    window, the one with the highest topology probability (ties: lower seed, then ring_id). Each entry shows what the
    spec's reviewers see -- the narrative, the top-5 evidence edges, the account roles -- and NOT the truth; the true
    pattern type is listed separately at the end, to be read only after reviewing."""
    from explainability.match import match_in_window, matching_rule, window_from_config
    W, (thr, scope) = window_from_config(cfg), matching_rule(cfg)
    out_dir = repo_path(cfg["output_dir"])
    names = load_names({k: repo_path(v) for k, v in cfg["narrative"]["names"].items()})
    cand = []
    for s in seeds:
        se = read_scored_edges(cfg["inputs"]["scored_edges"].format(seed=s))
        rings = read_rings(cfg["inputs"]["rings"].format(seed=s), scored_edges=se)
        m = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=cfg["inputs"]["truth"]).matches
        truth = m.set_index("ring_id")
        rows = pq.read_table(out_dir / cfg["explanations_name_week3"].format(seed=s)).to_pylist()
        sei = se.set_index("edge_id")
        for r in rows:
            if r["ring_id"] in truth.index:
                cand.append((r["topology_type"], -(r["topology_prob"] or 0.0), s, r["ring_id"], r, sei,
                             truth.loc[r["ring_id"]]))
    chosen = {}
    for c in sorted(cand, key=lambda c: c[:4]):
        chosen.setdefault(c[0], c)
    lines = ["# Week 3 narrative review -- PILOT (7 rings; not the spec's 30-ring review, no kappa)", "",
             "One matched ring per predicted pattern type (highest type probability; all five seeds). For each, read",
             "the narrative against the evidence and roles shown, and answer the four questions of spec section 7 (0/1).",
             "The true pattern types are at the very end: do not read them before answering.", ""]
    key = []
    for t in TOPOLOGY_TYPES:
        if t not in chosen:
            lines += [f"## {t}", "", "_No matched ring of this predicted type in any seed._", ""]
            continue
        _, _, s, rid, r, sei, tr = chosen[t]
        lines += [f"## {t} — `{rid}` (detector seed {s}, p = {r['topology_prob']:.2f})", "", f"> {r['narrative']}", "",
                  "| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |",
                  "|---|---|---|---|---|---|---|---|"]
        for i, e in enumerate(r["edge_weights"][:5], start=1):
            x = sei.loc[e["edge_id"]]
            lines.append(f"| {i} | {int(x.from_id)}→{int(x.to_id)} (edge {e['edge_id']}) | {x.amount_received:,.2f} | "
                         f"{names['currency'].get(int(x.currency_received), int(x.currency_received))} | {e['w_total']:.3f} | {e['w_score']:.3f} | {e['w_loo']:.3f} | "
                         f"{e['w_flow']:.3f} |")
        roles = {}
        for a in r["account_weights"]:
            roles.setdefault(a["role"], []).append(str(a["account_id"]))
        lines += ["", "Roles: " + "; ".join(f"**{k}** {', '.join(v)}" for k, v in sorted(roles.items())), "",
                  "Reviewer answers (0/1): topology plausible __ · named accounts matter __ · "
                  "evidence enough to start __ · anything misleading __", ""]
        key.append(f"| {t} | `{rid}` | {tr['pattern_type']} | {tr['jaccard']:.2f} |")
    lines += ["---", "", "## Answer key (read after reviewing)", "",
              "| predicted type | ring | true pattern type | Jaccard with the truth ring |", "|---|---|---|---|", *key, ""]
    out_path = repo_path(out_path)
    out_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {t: chosen[t][3] for t in chosen}


def main(argv=None) -> int:
    cfg = load_config()
    inp = cfg["inputs"]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", default=inp["scored_edges"], help="scored_edges parquet; '{seed}' is filled in")
    ap.add_argument("--rings", default=inp["rings"], help="rings parquet; '{seed}' is filled in")
    ap.add_argument("--seeds", type=int, nargs="+", default=inp["seeds"])
    ap.add_argument("--policy", choices=["converted", "raw"], default=cfg["amounts"]["currency_policy"],
                    help="converted = current; raw = reproduce Week 2 exactly (use with the v1 rings)")
    ap.add_argument("--no-narrative", action="store_true",
                    help="weights only, no SHAP / narrative (reproduces the migrated Week 2 files)")
    ap.add_argument("--samples", action="store_true",
                    help="only write the Week 3 PILOT review sample (one narrative per type) from the Week 3 files")
    ap.add_argument("--out", default=cfg["output_dir"])
    ap.add_argument("--name", default=None)
    ap.add_argument("--disagreement-name", default=None)
    a = ap.parse_args(argv)
    if a.samples:
        picked = review_samples(cfg, a.seeds, repo_path(a.out) / cfg["narrative_samples_name"])
        print(f"pilot review sample: {len(picked)} types -> {cfg['narrative_samples_name']}: {picked}")
        return 0
    raw = a.policy == "raw"
    narrate = not raw and not a.no_narrative
    kind = "" if raw else ("_week3" if narrate else "_converted")
    a.name = a.name or cfg["explanations_name" + kind]
    a.disagreement_name = a.disagreement_name or cfg["disagreement_name" + kind]
    for s in a.seeds:
        log = run_file(cfg, a.scores.format(seed=s), a.rings.format(seed=s), repo_path(a.out) / a.name.format(seed=s),
                       repo_path(a.out) / a.disagreement_name.format(seed=s), policy=a.policy, narrate=narrate)
        L = log["latency_ms"]
        print(f"seed {s} [{log['policy']}]: {log['n_explained']}/{log['n_rings']} explained; reproduce shipped ring "
              f"{log['n_reproduces_shipped_ring']}/{log['n_rings']}; conversions dropped {log['n_conversions_dropped']} "
              f"in {log['n_rings_with_conversions']} rings; partial-flow rings {log['n_rings_flow_partial']}; "
              f"undetermined accounts {log['n_undetermined_accounts']}; roles {log['role_counts']}; "
              f"latency p50 {L['p50']:.0f} / p95 {L['p95']:.0f} / max {L['max']:.0f} ms -> {log['outputs']['explanations']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
