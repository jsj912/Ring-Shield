"""Week 5 (XR-33 / XR-34): the Python functions behind the four explanation endpoints (spec 3.3).

    svc = ExplanationService(cfg, scores="contract/out/scored_edges_gine_causal_1.parquet",
                             rings="contract/out/rings_full_gine_causal_1.parquet",
                             explanations="results/xai/explanations_week3_seed1.parquet")
    svc.get_explanation(tenant_id, ring_id)          -> api_schemas.Explanation
    svc.get_evidence_edges(tenant_id, ring_id)       -> list[api_schemas.EvidenceEdge]
    svc.get_evidence_accounts(tenant_id, ring_id)    -> list[api_schemas.EvidenceAccount]
    svc.regenerate(tenant_id, ring_id, request)      -> api_schemas.Explanation   (request: RegenerateRequest)

The platform's FastAPI service owns the routes, authentication and tenant isolation (spec 3.3: "tenant scoping is
enforced by the platform layer"). These functions still refuse a ring whose tenant differs from the one asked for,
with the SAME RingNotFound as an unknown ring, so a caller can never learn that another tenant's ring exists.

Regenerate (XR-34). A partial verdict removes accounts and/or transactions. The ring is rebuilt without them --
members, member / seed / expanded edges (with their expansion probabilities) and the time span -- and explained from
scratch by explain.explain_ring: new leave-one-out reruns, weights, roles, SHAP and narrative. The shape stays the
typing head's original guess (marked in provenance), and the shipped confidence no longer applies. It needs the same
research files as a normal run (GFP features, embeddings, affinity model), loaded on the first regenerate call.
Nothing here reads ground truth.
"""
from __future__ import annotations

import json
import math

import pyarrow.parquet as pq

from explainability.api_schemas import (EvidenceAccount, EvidenceEdge, Explanation, FeatureWeight,
                                        RegenerateRequest)
from explainability.contract_io import read_rings, read_scored_edges, repo_path
from explainability.narrative import load_names, load_phrasing


class RingNotFound(LookupError):
    """Unknown ring, or a ring of another tenant (deliberately indistinguishable)."""


class InvalidEdit(ValueError):
    """A regenerate request that names accounts / transactions not in the ring, or leaves nothing to explain."""


def _none_if_nan(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


class ExplanationService:
    def __init__(self, cfg: dict, *, scores: str, rings: str, explanations: str):
        self.cfg, self._scores, self._rings_path = cfg, scores, rings
        self.se = read_scored_edges(scores).set_index("edge_id")
        self.rings = read_rings(rings, scored_edges=self.se.reset_index()).set_index("ring_id", drop=False)
        self.rows = {r["ring_id"]: r for r in pq.read_table(repo_path(explanations)).to_pylist()}
        nc = cfg["narrative"]
        self.phrasing = load_phrasing(repo_path(nc["phrasing"]))
        self.names = load_names({k: repo_path(v) for k, v in nc["names"].items()})
        fx = json.loads(repo_path(cfg["amounts"]["fx_rates"]).read_text(encoding="utf-8"))
        hub = int(fx.get("hub_currency", 0))
        self._fx = {int(k): v["rate_to_ccy0"] for k, v in fx["rate_to_ccy0"].items()}
        self._hub_name = self.names["currency"].get(hub, f"currency {hub}")
        self._ctx = None

    # ------------------------------------------------------------------ lookups
    def _ring(self, tenant_id: int, ring_id: str):
        if ring_id not in self.rings.index or int(self.rings.at[ring_id, "tenant_id"]) != int(tenant_id):
            raise RingNotFound(f"no ring {ring_id!r} for tenant {tenant_id}")
        return self.rings.loc[ring_id]

    def _name(self, kind: str, code) -> str:
        code = int(code)
        return self.names[kind].get(code, f"Bank {code}" if kind == "bank" else f"{kind.replace('_', ' ')} {code}")

    def _explanation(self, row: dict) -> Explanation:
        feats = [FeatureWeight(feature_name=f["feature_name"],
                               display_name=self.phrasing["features"].get(f["feature_name"], f["feature_name"]),
                               mean_shap=f["mean_shap"], top_edge_id=f["top_edge_id"]) for f in row["feature_weights"]]
        prov = json.loads(row["provenance"])
        accounts = [{**a, "hold_time_s": _none_if_nan(a["hold_time_s"])} for a in row["account_weights"]]
        return Explanation(ring_id=row["ring_id"], tenant_id=row["tenant_id"], edge_weights=row["edge_weights"],
                           account_weights=accounts, feature_weights=feats, topology_type=row["topology_type"],
                           topology_prob=_none_if_nan(row["topology_prob"]), narrative=row["narrative"],
                           evidence_summary=None if row["evidence_summary"] is None else json.loads(row["evidence_summary"]),
                           explainer_version=prov["explainer_version"], latency_ms=row["latency_ms"], provenance=prov)

    # ------------------------------------------------------------------ the four endpoints
    def get_explanation(self, tenant_id: int, ring_id: str) -> Explanation:
        self._ring(tenant_id, ring_id)
        return self._explanation(self.rows[ring_id])

    def get_evidence_edges(self, tenant_id: int, ring_id: str) -> list[EvidenceEdge]:
        ring = self._ring(tenant_id, ring_id)
        seeds, expanded = set(map(int, ring["seed_edges"])), set(map(int, ring["expanded_edges"]))
        out = []
        for w in self.rows[ring_id]["edge_weights"]:
            e = self.se.loc[int(w["edge_id"])]
            rate = self._fx.get(int(e["currency_received"]))
            out.append(EvidenceEdge(
                edge_id=int(w["edge_id"]), from_id=int(e["from_id"]), to_id=int(e["to_id"]), timestamp=int(e["timestamp"]),
                amount_sent=float(e["amount_sent"]), amount_received=float(e["amount_received"]),
                amount_received_converted=None if rate is None else float(e["amount_received"]) * float(rate),
                converted_currency_name=self._hub_name,
                currency_sent=int(e["currency_sent"]), currency_sent_name=self._name("currency", e["currency_sent"]),
                currency_received=int(e["currency_received"]),
                currency_received_name=self._name("currency", e["currency_received"]),
                payment_format=int(e["payment_format"]), payment_format_name=self._name("payment_format", e["payment_format"]),
                from_bank=int(e["from_bank"]), from_bank_name=self._name("bank", e["from_bank"]),
                to_bank=int(e["to_bank"]), to_bank_name=self._name("bank", e["to_bank"]),
                is_seed=int(w["edge_id"]) in seeds, is_expanded=int(w["edge_id"]) in expanded,
                w_total=w["w_total"], w_score=w["w_score"], w_loo=w["w_loo"], w_flow=w["w_flow"]))
        return out

    def get_evidence_accounts(self, tenant_id: int, ring_id: str) -> list[EvidenceAccount]:
        ring = self._ring(tenant_id, ring_id)
        member = self.se.loc[sorted(map(int, ring["member_edges"]))]
        bank = {}
        for r in member.itertuples():
            bank.setdefault(int(r.from_id), int(r.from_bank))
            bank.setdefault(int(r.to_id), int(r.to_bank))
        accounts = sorted(self.rows[ring_id]["account_weights"], key=lambda a: (-a["w_account"], a["account_id"]))
        return [EvidenceAccount(account_id=a["account_id"], bank_id=bank.get(a["account_id"]),
                                bank_name=self._name("bank", bank[a["account_id"]]) if a["account_id"] in bank else None,
                                role=a["role"], inflow=a["inflow"], outflow=a["outflow"],
                                hold_time_s=_none_if_nan(a["hold_time_s"]), w_account=a["w_account"]) for a in accounts]

    def regenerate(self, tenant_id: int, ring_id: str, request: RegenerateRequest) -> Explanation:
        from explainability.explain import build_context, explain_ring
        ring = self._ring(tenant_id, ring_id)
        members = set(map(int, ring["members"]))
        member_edges = set(map(int, ring["member_edges"]))
        drop_acc, drop_edges = set(request.remove_accounts), set(request.remove_edges)
        if not drop_acc <= members or not drop_edges <= member_edges:
            raise InvalidEdit(f"accounts {sorted(drop_acc - members)} / transactions {sorted(drop_edges - member_edges)} "
                              f"are not in ring {ring_id}")
        touching = set(self.se.index[self.se.index.isin(list(member_edges)) & (
            self.se["from_id"].isin(drop_acc) | self.se["to_id"].isin(drop_acc))])
        gone = drop_edges | touching

        def keep(ids):
            return [int(e) for e in ids if int(e) not in gone]
        new_member_edges = keep(ring["member_edges"])
        exp_pairs = [(int(e), float(p)) for e, p in zip(ring["expanded_edges"], ring["expanded_edge_probs"]) if int(e) not in gone]
        new_seeds = keep(ring["seed_edges"])
        new_members = sorted(members - drop_acc)
        if len(new_members) < 2 or not (new_seeds or exp_pairs):
            raise InvalidEdit("the edit leaves fewer than two accounts or no seed / expanded transaction to explain")
        ts = self.se.loc[new_member_edges, "timestamp"] if new_member_edges else None
        if self._ctx is None:
            self._ctx = build_context(self.cfg, self._scores, self._rings_path, "converted", True)[0]
        tup = next(self.rings.loc[[ring_id]].itertuples(index=False))
        edited = tup._replace(members=new_members, n_members=len(new_members), member_edges=new_member_edges,
                              seed_edges=new_seeds, expanded_edges=[e for e, _ in exp_pairs],
                              expanded_edge_probs=[p for _, p in exp_pairs],
                              duration_hours=float((ts.max() - ts.min()) / 3600) if ts is not None else 0.0)
        row, _, _ = explain_ring(edited, self._ctx)
        prov = json.loads(row["provenance"])
        prov["regenerated"] = {"removed_accounts": sorted(drop_acc), "removed_transactions": sorted(drop_edges),
                               "transactions_removed_with_accounts": sorted(touching - drop_edges), "note": request.note,
                               "topology": "the typing head's type of the ORIGINAL ring (not re-typed)",
                               "confidence": "the shipped ring confidence no longer applies"}
        prov["loo"]["reproduces_shipped_ring"] = False
        row["provenance"] = json.dumps(prov, sort_keys=True)
        return self._explanation(row)


# ----------------------------------------------------------------------------- sample fixtures for the platform
STUB = {"scores": "contract/out/scored_edges_gine_causal_1.parquet", "rings": "contract/out/rings_stub_cc.parquet",
        "explanations": "results/xai/explanations_week3_stub_cc_seed1.parquet"}


def write_examples(cfg: dict, out_dir=None) -> list:
    """Real responses of the four functions on the stub data, as JSON, for the platform engineer
    (explainability/schemas/examples/). The ring is the stub ring with the most accounts; the regenerate example removes
    its sink with the largest id. latency_ms differs between runs; everything else is deterministic."""
    from pathlib import Path
    from explainability.api_schemas import SCHEMA_DIR, ErrorBody
    out = Path(out_dir) if out_dir else SCHEMA_DIR / "examples"
    out.mkdir(parents=True, exist_ok=True)
    svc = ExplanationService(cfg, **STUB)
    rid = max(svc.rows, key=lambda r: len(svc.rows[r]["account_weights"]))
    t = int(svc.rings.at[rid, "tenant_id"])
    e = svc.get_explanation(t, rid)
    gone = max(a.account_id for a in e.account_weights if a.role == "sink")
    req = RegenerateRequest(remove_accounts=[gone], note="analyst: this account is not part of the ring")
    files = {
        "explanation.json": e.model_dump(mode="json"),
        "evidence_edges.json": [x.model_dump(mode="json") for x in svc.get_evidence_edges(t, rid)],
        "evidence_accounts.json": [x.model_dump(mode="json") for x in svc.get_evidence_accounts(t, rid)],
        "regenerate_request.json": req.model_dump(mode="json"),
        "regenerate_response.json": svc.regenerate(t, rid, req).model_dump(mode="json"),
        "error_not_found.json": ErrorBody(code="not_found", message="ring not found").model_dump(mode="json"),
        "error_invalid_edit.json": ErrorBody(code="invalid_edit", message=str(InvalidEdit(
            f"accounts [-5] / transactions [] are not in ring {rid}"))).model_dump(mode="json"),
    }
    paths = []
    for name, obj in files.items():
        p = out / name
        p.write_text(json.dumps({"_example": {"ring_id": rid, "tenant_id": t, "source": STUB}, "body": obj}, indent=2,
                                sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        paths.append(p)
    return paths


if __name__ == "__main__":
    import sys
    from explainability.contract_io import load_config
    if "--examples" in sys.argv:
        for p in write_examples(load_config()):
            print(p.name)
