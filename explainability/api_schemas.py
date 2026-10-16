"""Week 5 (XR-33): the shapes of what the four explanation endpoints return (spec 3.3), for the platform's FastAPI
service and the dashboard. The functions that fill them are in api.py.

    GET  /tenants/{t}/rings/{r}/explanation            -> Explanation
    GET  /tenants/{t}/rings/{r}/evidence/edges         -> list[EvidenceEdge]
    GET  /tenants/{t}/rings/{r}/evidence/accounts      -> list[EvidenceAccount]
    POST /tenants/{t}/rings/{r}/explanation/regenerate  RegenerateRequest -> Explanation
    errors                                              -> ErrorBody (404 not_found, 422 invalid_edit)

Field lists follow the dashboard requirements (Explanation, Subgraph) plus names from Joan's maps: currency,
payment format and bank names are for DISPLAY only -- a bank name is not unique, never join on it. Roles include
`undetermined` (an account touching Bitcoin, whose rate cannot be recovered): the dashboard needs a sixth role style.
No field carries ground truth (platform PR-50).

`python -m explainability.api_schemas` rewrites explainability/schemas/*.schema.json from these models; a test fails
if the files and the models ever differ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["source", "sink", "mule", "holder", "peripheral", "undetermined"]
TopologyType = Literal["FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER", "CYCLE", "RANDOM", "BIPARTITE", "STACK",
                       "UNKNOWN"]
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EdgeWeight(_Strict):
    """One evidence transaction's weights (currency conversions are never evidence)."""
    edge_id: int
    w_total: float = Field(description="alpha*w_score + beta*w_loo + gamma*w_flow, the ranking weight")
    w_score: float = Field(description="the detector's calibrated score")
    w_loo: float = Field(description="how much the ring depends on this transaction (leave-one-out + bridge), 0-1")
    w_flow: float = Field(description="share of the ring's money, converted to US Dollar")


class AccountWeight(_Strict):
    account_id: int
    role: Role
    inflow: float = Field(description="money in, US Dollar")
    outflow: float = Field(description="money out, US Dollar")
    hold_time_s: float | None = Field(description="median wait from a payment in to the next payment out; null if none")
    w_account: float


class FeatureWeight(_Strict):
    """A feature of the reference transaction-level model (GFP+XGBoost), averaged SHAP over the ring's seed edges.
    It explains that reference model, not the GNN that produced the seeds."""
    feature_name: str
    display_name: str = Field(description="plain-English phrase (explainability/phrasing.yaml)")
    mean_shap: float = Field(description="> 0 raised suspicion, < 0 lowered it (log-odds)")
    top_edge_id: int


class Explanation(_Strict):
    ring_id: str
    tenant_id: int
    edge_weights: list[EdgeWeight] = Field(description="highest w_total first")
    account_weights: list[AccountWeight]
    feature_weights: list[FeatureWeight] = Field(description="top 10 by |mean_shap|")
    topology_type: TopologyType = Field(description="the ring's most likely shape (typing head); a guess, not a fact")
    topology_prob: float | None
    narrative: str | None = Field(description="filled template, at most 90 words; never free text")
    evidence_summary: dict | None = Field(description="every value the narrative used; it regenerates the sentence")
    explainer_version: str
    latency_ms: int
    provenance: dict

    @model_validator(mode="after")
    def _narrative_limit(self):
        if self.narrative is not None and len(self.narrative.split()) > 90:
            raise ValueError("narrative longer than 90 words")
        return self


class EvidenceEdge(_Strict):
    """An evidence transaction with its raw fields joined (spec 3.3), in the explanation's w_total order."""
    edge_id: int
    from_id: int
    to_id: int
    timestamp: int = Field(description="seconds since dataset start")
    amount_sent: float
    amount_received: float
    amount_received_converted: float | None = Field(description="amount_received in the hub currency (US Dollar); "
                                                                "null when its currency (Bitcoin) has no rate")
    converted_currency_name: str
    currency_sent: int
    currency_sent_name: str
    currency_received: int
    currency_received_name: str
    payment_format: int
    payment_format_name: str
    from_bank: int
    from_bank_name: str = Field(description="display only; not unique")
    to_bank: int
    to_bank_name: str = Field(description="display only; not unique")
    is_seed: bool
    is_expanded: bool
    w_total: float
    w_score: float
    w_loo: float
    w_flow: float


class EvidenceAccount(_Strict):
    """A member account, highest w_account first (dashboard Accounts tab)."""
    account_id: int
    bank_id: int | None
    bank_name: str | None = Field(description="display only; not unique")
    role: Role
    inflow: float
    outflow: float
    hold_time_s: float | None
    w_account: float


class RegenerateRequest(_Strict):
    """A partial verdict's correction: accounts and/or transactions the analyst removed (platform FR-D52 / PR-13)."""
    remove_accounts: list[int] = Field(default_factory=list)
    remove_edges: list[int] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def _something_removed(self):
        if not self.remove_accounts and not self.remove_edges:
            raise ValueError("a regenerate request must remove at least one account or transaction")
        return self


class ErrorBody(_Strict):
    code: Literal["not_found", "invalid_edit"]
    message: str


MODELS = (Explanation, EvidenceEdge, EvidenceAccount, RegenerateRequest, ErrorBody)


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export_schemas(out_dir: Path = SCHEMA_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for m in MODELS:
        p = out_dir / f"{m.__name__}.schema.json"
        p.write_text(schema_text(m), encoding="utf-8", newline="\n")
        paths.append(p)
    return paths


if __name__ == "__main__":
    for p in export_schemas():
        print(p.name)
    sys.exit(0)
