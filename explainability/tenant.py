"""Tenant-scoped explanations for the platform (Kashish's request; Week 9 integration work, done early).

    python -m explainability.tenant --bank 20           # -> results/xai/tenant/explanations_20_1.parquet + .log.json
    TenantExplainer(cfg, 20).regenerate(ring_id, tenant_id, excluded_members=(...), excluded_edges=(...))

The tenant (a bank) sees an edge only if from_bank or to_bank is that bank. Its own accounts are fully visible; a
foreign account appears only as the counterparty on visible edges. The tenant's rings were built by the platform with
the research ring layer on the visible edges only (her rings file and edge-id file, verified by SHA-256). This module
explains them so that nothing hidden is counted or mentioned:

  transactions   the shipped scored edges restricted to the visible edges (a filtered copy, written once), so every
                 count -- roles, flows, closure, and the w_account denominator (each account's activity, Kashish 4a)
                 -- uses visible edges only
  leave-one-out  the shared full-graph GFP features and embeddings, restricted to the ring's edges -- exactly what her
                 rings were built with, so the reruns reproduce them
  SHAP           the reference model's 10 graph features RECOMPUTED on the tenant's view (Kashish 4b): the same
                 research functions (graph/motif_features.py) over the visible history (train + val + test edges
                 visible to the bank). Recorded as feature_scope "tenant_view"; SHAP on a subgraph is less faithful
                 to the model, which was trained on full-graph features. The 7 transaction fields are the edge's own.

`gfp_check` proves the fast history index is the research one: on the full history, the recomputed features equal the
shipped amlworld_gfp_features_test.parquet exactly for a random sample of test edges plus every tenant seed edge.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from explainability.contract_io import load_config, read_rings, read_scored_edges, repo_path

GFP_COLS = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst", "scatter_gather",
            "gather_scatter", "temporal_cycle", "cycle_length"]


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(repo_path(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- the research GFP, on any edge set
def gfp_settings(cfg: dict) -> dict:
    """window / hops / look-back as recorded in the shipped GFP parquet's own metadata (never retyped here)."""
    meta = json.loads(pq.ParquetFile(repo_path(cfg["research_inputs"]["gfp"])).schema_arrow.metadata[b"gfp"])
    if not meta.get("trailing"):
        raise ValueError("the shipped GFP file is not the trailing version")
    return {"window": int(meta["window_s"]), "max_hops": int(meta["max_cycle_hops"]),
            "lookback_s": int(meta["cycle_lookback_s"])}


def history(cfg: dict, bank: int | None = None) -> pd.DataFrame:
    """All train + val + test edges (from_id, to_id, Timestamp) -- the research GFP's history -- or only those visible
    to `bank` (from_bank or to_bank == bank)."""
    frames = []
    for path in cfg["tenants"]["history"]:
        cols = ["from_id", "to_id", "Timestamp"] + (["from_bank", "to_bank"] if bank is not None else [])
        d = pd.read_parquet(repo_path(path), columns=cols)
        if bank is not None:
            d = d[(d["from_bank"] == bank) | (d["to_bank"] == bank)]
        frames.append(d[["from_id", "to_id", "Timestamp"]])
    return pd.concat(frames, ignore_index=True)


def adjacency(edges: pd.DataFrame):
    """The same four structures as graph/motif_features.build_adjacency (per account: (timestamp, other) tuples sorted,
    and the timestamps as int64 arrays), built with a sort instead of iterrows. Tested equal to it."""
    f = edges["from_id"].to_numpy(np.int64)
    t = edges["to_id"].to_numpy(np.int64)
    ts = edges["Timestamp"].to_numpy(np.int64)

    def build(node, other):
        order = np.lexsort((other, ts, node))
        n, o, s = node[order], other[order], ts[order]
        cut = np.flatnonzero(np.diff(n)) + 1
        starts = np.concatenate([[0], cut])
        ends = np.concatenate([cut, [len(n)]])
        adj, adj_ts = {}, {}
        for a, b in zip(starts.tolist(), ends.tolist()):
            key = int(n[a])
            adj[key] = list(zip(s[a:b].tolist(), o[a:b].tolist()))
            adj_ts[key] = s[a:b].copy()
        return adj, adj_ts
    adj_out, adj_out_ts = build(f, t)
    adj_in, adj_in_ts = build(t, f)
    return adj_out, adj_in, adj_out_ts, adj_in_ts


def gfp_for_edges(adj, rows: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """The 10 GFP features for `rows` (edge_id, from_id, to_id, timestamp), computed by the research functions
    themselves (graph/motif_features._process_chunk) over the given history index. Indexed by edge_id."""
    from graph import motif_features as mf
    mf._init_worker(*adj, settings["window"], settings["max_hops"], settings["lookback_s"])
    _, res = mf._process_chunk((rows["from_id"].to_numpy(np.int64), rows["to_id"].to_numpy(np.int64),
                                rows["timestamp"].to_numpy(np.int64), 0))
    return pd.DataFrame(res, columns=GFP_COLS, index=pd.Index(rows["edge_id"].to_numpy(np.int64), name="edge_id"))


def gfp_check(cfg: dict, edge_rows: pd.DataFrame, n_sample: int, seed: int) -> dict:
    """Full-history recomputation vs the shipped GFP file, on a random sample of test edges plus `edge_rows`."""
    se = read_scored_edges(cfg["inputs"]["scored_edges"].format(seed=cfg["tenants"]["seed"]))
    sample = se.sample(n=n_sample, random_state=seed)[["edge_id", "from_id", "to_id", "timestamp"]]
    rows = pd.concat([sample, edge_rows]).drop_duplicates("edge_id")
    mine = gfp_for_edges(adjacency(history(cfg)), rows, gfp_settings(cfg))
    shipped = pd.read_parquet(repo_path(cfg["research_inputs"]["gfp"]), filters=[("EdgeID", "in", rows["edge_id"].tolist())])
    shipped = shipped.set_index("EdgeID").loc[mine.index, GFP_COLS]
    diff = int((mine.to_numpy() != shipped.to_numpy()).any(axis=1).sum())
    return {"n_edges_checked": int(len(mine)), "n_random": int(n_sample), "n_rows_differing": diff,
            "identical": diff == 0, "settings": gfp_settings(cfg)}


# ----------------------------------------------------------------------------- tenant inputs
def tenant_paths(cfg: dict, bank: int) -> dict:
    t = cfg["tenants"]
    return {k: t[k].format(bank=bank, seed=t["seed"]) for k in ("rings", "edge_ids", "scored_edges", "out")}


VISIBLE_SOURCE_KEY = b"ringshield_visible_source"


def rings_scores_source(cfg: dict, bank: int) -> Path:
    """The scored edges the bank's rings were built from, as their .log.json records ("scores").

    Rings built from the bank's own-model scores must be explained with those scores, not the shipped ones: the
    is_seed flags differ. No log or no "scores" entry: the shipped scored edges. A recorded path that does not exist
    here (a log written on another machine) is taken to be the shipped file only if it has the same file name."""
    shipped = repo_path(cfg["inputs"]["scored_edges"].format(seed=cfg["tenants"]["seed"]))
    log = repo_path(tenant_paths(cfg, bank)["rings"] + ".log.json")
    recorded = json.loads(log.read_text()).get("scores") if log.exists() else None
    if recorded is None:
        return shipped
    recorded = Path(recorded)
    if recorded.exists():
        return recorded
    if recorded.name == shipped.name:
        return shipped
    raise FileNotFoundError(f"bank {bank}: the rings were built from {recorded}, which is not here")


def _visible_source(cfg: dict, bank: int) -> dict:
    return {"bank": int(bank), "scored_edges_sha256": sha256(rings_scores_source(cfg, bank))}


def visible_scored_edges_current(cfg: dict, bank: int) -> bool:
    """True only if the bank's visible-scores file exists and was cut from the scores its rings were built from."""
    out = repo_path(tenant_paths(cfg, bank)["scored_edges"])
    if not out.exists():
        return False
    stamp = (pq.ParquetFile(out).schema_arrow.metadata or {}).get(VISIBLE_SOURCE_KEY)
    return stamp is not None and json.loads(stamp) == _visible_source(cfg, bank)


def write_visible_scored_edges(cfg: dict, bank: int) -> Path:
    """The rings' scored edges (rings_scores_source) restricted to the edges the bank can see; must equal the
    platform's edge-id file. Stamped with its source (VISIBLE_SOURCE_KEY) so a copy cut from other scores is never
    reused."""
    p = tenant_paths(cfg, bank)
    src = rings_scores_source(cfg, bank)
    se = pd.read_parquet(src, columns=["edge_id", "from_bank", "to_bank"])
    vis = se[(se["from_bank"] == bank) | (se["to_bank"] == bank)].reset_index(drop=True)
    ids = pd.read_parquet(repo_path(p["edge_ids"]))["edge_id"].astype("int64")
    if set(ids) != set(vis["edge_id"]):
        raise ValueError(f"bank {bank}: the platform's edge-id file is not the from_bank/to_bank = {bank} edge set")
    out = repo_path(p["scored_edges"])
    out.parent.mkdir(parents=True, exist_ok=True)
    tbl = pq.read_table(src)
    visible = tbl.filter(np.isin(tbl.column("edge_id").to_numpy(), vis["edge_id"].to_numpy()))
    metadata = {**(visible.schema.metadata or {}), VISIBLE_SOURCE_KEY: json.dumps(_visible_source(cfg, bank)).encode()}
    pq.write_table(visible.replace_schema_metadata(metadata), out)      # same columns and types; source stamped
    return out


def tenant_cfg(cfg: dict, bank: int) -> dict:
    """The config for one tenant: the shipped detector's leave-one-out inputs (what the tenant rings were built with),
    the bank's visible transactions and rings, outputs under results/xai/tenant/. Mixing, narrative: unchanged."""
    p = tenant_paths(cfg, bank)
    out = copy.deepcopy(cfg)
    out["inputs"]["scored_edges"], out["inputs"]["rings"] = p["scored_edges"], p["rings"]
    out["tenant"] = int(bank)
    return out


def _json_safe(x):
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return _json_safe(float(x))
    return x


class TenantExplainer:
    """Everything one tenant's explanations share: its visible transactions, its rings, the leave-one-out inputs and
    the SHAP rows with tenant-view graph features. Build once; explain every ring or regenerate one."""

    def __init__(self, cfg: dict, bank: int):
        from explainability.explain import build_context
        from explainability.feature_weights import FeatureExplainer
        self.bank, self.paths = int(bank), tenant_paths(cfg, bank)
        if not visible_scored_edges_current(cfg, bank):         # missing, unstamped or cut from other scores
            write_visible_scored_edges(cfg, bank)
        self.cfg = tenant_cfg(cfg, bank)
        ctx, rings = build_context(self.cfg, self.cfg["inputs"]["scored_edges"], self.cfg["inputs"]["rings"],
                                   "converted", True)
        bad = sorted(set(rings["tenant_id"]) - {self.bank})
        if bad:
            raise ValueError(f"rings of other tenants in bank {bank}'s file: {bad}")
        rows = ctx.features.rows.copy()
        se = ctx.scored_edges.loc[list(rows.index)]
        se = se.assign(edge_id=se.index.to_numpy(np.int64))
        view = gfp_for_edges(adjacency(history(self.cfg, self.bank)), se[["edge_id", "from_id", "to_id", "timestamp"]],
                             gfp_settings(self.cfg))
        rows.loc[view.index, GFP_COLS] = view[GFP_COLS].astype(np.float32).to_numpy()
        ctx.features = FeatureExplainer(ctx.features.booster, rows)
        full = pd.read_parquet(repo_path(self.cfg["research_inputs"]["gfp"]),
                               filters=[("EdgeID", "in", view.index.tolist())]).set_index("EdgeID").loc[view.index, GFP_COLS]
        self.n_gfp_changed = int((view[GFP_COLS].to_numpy() != full.to_numpy()).any(axis=1).sum())
        ctx.extra_provenance = {"scope": "tenant", "tenant_id": self.bank, "fx_rates_sha256": ctx.fx_sha256,
                                "feature_scope": "tenant_view",
                                "feature_scope_note": "SHAP graph features recomputed on the tenant's visible edges; "
                                                      "less faithful to the reference model, trained on full-graph features",
                                "visibility": "edges with from_bank or to_bank == tenant_id"}
        self.ctx, self.rings = ctx, rings.set_index("ring_id", drop=False)

    def explain_all(self):
        from explainability.explain import explain_rings
        return explain_rings(self.rings.reset_index(drop=True), self.ctx)

    def regenerate(self, ring_id: str, tenant_id: int, excluded_members=(), excluded_edges=()) -> dict:
        """A partial verdict's correction -> one explanation row (the explanations parquet columns), JSON-safe (NaN ->
        null), provenance extended with regenerated / excluded ids / scope / tenant_id / fx_rates_sha256."""
        from explainability.api import InvalidEdit, RingNotFound, edit_ring
        from explainability.explain import explain_ring
        if int(tenant_id) != self.bank or ring_id not in self.rings.index:
            raise RingNotFound(f"no ring {ring_id!r} for tenant {tenant_id}")
        if not excluded_members and not excluded_edges:
            raise InvalidEdit("nothing to exclude")
        tup = next(self.rings.loc[[ring_id]].itertuples(index=False))
        edited, touching = edit_ring(tup, self.ctx.scored_edges, set(map(int, excluded_members)),
                                     set(map(int, excluded_edges)))
        row, _, _ = explain_ring(edited, self.ctx)
        prov = json.loads(row["provenance"])
        prov.update(regenerated=True, excluded_members=sorted(map(int, excluded_members)),
                    excluded_edges=sorted(map(int, excluded_edges)),
                    edges_removed_with_members=sorted(touching - set(map(int, excluded_edges))))
        prov["loo"]["reproduces_shipped_ring"] = False
        row["provenance"] = json.dumps(prov, sort_keys=True)
        return _json_safe(row)


def run_tenant(cfg: dict, bank: int) -> dict:
    """Explain every ring of one tenant; write the parquet and its .log.json (with scope, tenant, input hashes)."""
    import pyarrow as pa
    from explainability.explain import EXPLANATIONS_SCHEMA
    te = TenantExplainer(cfg, bank)
    table, _, diags = te.explain_all()
    out = repo_path(te.paths["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(table.to_pylist(), schema=EXPLANATIONS_SCHEMA), out)
    c = te.cfg
    lat = np.array([d["latency_ms"] for d in diags], dtype=float)
    inputs = {"rings": te.paths["rings"], "edge_ids": te.paths["edge_ids"],
              "scored_edges_shipped": cfg["inputs"]["scored_edges"].format(seed=c["tenants"]["seed"]),
              "scored_edges_visible": te.paths["scored_edges"], "gfp": c["research_inputs"]["gfp"],
              "embeddings": c["research_inputs"]["embeddings"].format(seed=c["tenants"]["seed"]),
              "affinity": c["research_inputs"]["affinity_dir"] + "/affinity.json",
              "partition_config": c["research_inputs"]["partition_config"].format(seed=c["tenants"]["seed"]),
              "fx_rates": c["amounts"]["fx_rates"]}
    log = {"scope": "tenant", "tenant_id": te.bank, "explainer_version": c["explainer_version"],
           "visibility": "edges with from_bank or to_bank == tenant_id",
           "input_sha256": {k: {"path": v, "sha256": sha256(v)} for k, v in inputs.items()},
           "fx_rates_sha256": te.ctx.fx_sha256, "feature_scope": "tenant_view",
           "n_tenant_seed_edges_with_changed_graph_features": te.n_gfp_changed,
           "n_rings": len(te.rings), "n_explained": table.num_rows,
           "n_reproduces_shipped_ring": int(sum(d["reproduces_shipped_ring"] for d in diags)),
           "not_reproduced": [d["ring_id"] for d in diags if not d["reproduces_shipped_ring"]],
           "rerun": te.ctx.loo.params, "mixing": c["edge_weights"]["mixing_tuned"],
           "latency_ms": {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95)), "max": float(lat.max())},
           "outputs": {"explanations": te.paths["out"]}}
    out.with_name(out.name + ".log.json").write_text(json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                                     newline="\n")
    return log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bank", type=int, required=True)
    a = ap.parse_args(argv)
    log = run_tenant(load_config(), a.bank)
    print(f"bank {a.bank}: {log['n_explained']}/{log['n_rings']} explained; reproduce {log['n_reproduces_shipped_ring']}"
          f"/{log['n_rings']}; graph features changed on the tenant view for "
          f"{log['n_tenant_seed_edges_with_changed_graph_features']} seed edges; fx {log['fx_rates_sha256'][:12]}… "
          f"-> {log['outputs']['explanations']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
