"""The rings contract as a dataclass (exactly contract/schema.py::RINGS_COLUMNS, same order).

`Ring` is what every aggregator returns; `rings_to_table` / `write_rings_parquet` serialise a
list of rings with the contract's pyarrow schema (empty lists keep their element type), and
`rings_to_dataframe` gives a pandas view. Field meanings are documented in contract/schema.py
and contract/README.md; nothing here redefines them.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from contract.schema import RINGS_COLUMNS, RINGS_ORDER, RINGS_SCHEMA_VERSION, TOPOLOGY_TYPES

_PA_TYPES = {
    "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(),
    "list<int64>": pa.list_(pa.int64()), "list<float64>": pa.list_(pa.float64()),
}
RINGS_PA_SCHEMA = pa.schema([(c, _PA_TYPES[t]) for c, (t, _) in RINGS_COLUMNS.items()])
UNIFORM_TOPOLOGY = [1.0 / len(TOPOLOGY_TYPES)] * len(TOPOLOGY_TYPES)


@dataclass
class Ring:
    """One predicted ring. Field order == contract order (asserted at import)."""
    ring_id: str
    tenant_id: int
    aggregator_id: str
    members: list[int]
    n_members: int
    member_edges: list[int]
    seed_edges: list[int]
    expanded_edges: list[int]
    expanded_edge_probs: list[float]
    n_edges: int
    start_time: int
    end_time: int
    duration_hours: float
    confidence: float
    max_edge_prob: float
    density: float
    conservation_closure: float
    topology_type: str
    topology_probs: list[float]
    source_accounts: list[int]
    sink_accounts: list[int]
    mule_accounts: list[int]
    # ---- schema v2 (Step 14): currency-aware companions of the four fields above ---------------
    # Defaulted so that every v1 construction site keeps working unchanged: a ring built without
    # them is a ring whose currency-partitioned view was not computed, which reads as NaN / empty
    # rather than as zero. `conservation_closure` and `confidence` above stay RAW cross-currency.
    conservation_closure_ccy: float = math.nan
    n_accounts_ccy_undefined: int = 0
    source_accounts_ccy: list[int] = field(default_factory=list)
    sink_accounts_ccy: list[int] = field(default_factory=list)
    mule_accounts_ccy: list[int] = field(default_factory=list)
    undetermined_accounts_ccy: list[int] = field(default_factory=list)
    n_roles_changed_ccy: int = 0
    n_currencies: int = 0

    def to_dict(self) -> dict:
        return {c: getattr(self, c) for c in RINGS_ORDER}

    @property
    def member_set(self) -> set[int]:
        return set(self.members)

    @classmethod
    def baseline(cls, *, ring_id: str, tenant_id: int, aggregator_id: str, members: list[int],
                 member_edges: list[int], seed_edges: list[int], n_edges: int, start_time: int, end_time: int,
                 confidence: float, max_edge_prob: float, density: float) -> "Ring":
        """A ring before Steps 6-8: nothing expanded, topology UNKNOWN / uniform, roles empty."""
        members = sorted(int(m) for m in members)
        return cls(
            ring_id=ring_id, tenant_id=int(tenant_id), aggregator_id=aggregator_id,
            members=members, n_members=len(members),
            member_edges=[int(e) for e in member_edges], seed_edges=[int(e) for e in seed_edges],
            expanded_edges=[], expanded_edge_probs=[], n_edges=int(n_edges),
            start_time=int(start_time), end_time=int(end_time),
            duration_hours=(int(end_time) - int(start_time)) / 3600.0,
            confidence=float(confidence), max_edge_prob=float(max_edge_prob), density=float(density),
            conservation_closure=math.nan, topology_type="UNKNOWN", topology_probs=list(UNIFORM_TOPOLOGY),
            source_accounts=[], sink_accounts=[], mule_accounts=[],
        )


assert [f.name for f in dataclasses.fields(Ring)] == RINGS_ORDER, "Ring fields drifted from contract/schema.py"


def rings_to_table(rings: list[Ring]) -> pa.Table:
    return pa.Table.from_pylist([r.to_dict() for r in rings], schema=RINGS_PA_SCHEMA)


def rings_to_dataframe(rings: list[Ring]) -> pd.DataFrame:
    return pd.DataFrame([r.to_dict() for r in rings], columns=RINGS_ORDER)


def finish_contract_ids(rings: list["Ring"], scored_edges, *, aggregator_id: str, model_id: str, seed: int) -> None:
    """Apply the Step 5 contract rules for `ring_id` and `tenant_id`, in place.

    ring_id   f"{aggregator}-{model_id}-{seed}-{idx}"
    tenant_id the sender bank (from_bank) of the ring's earliest seed edge, ties -> smallest edge_id

    Shared by `contract/make_rings_full.py` and the validation-rings path so the two cannot drift
    (they produced the same strings by copy before this existed)."""
    se = scored_edges.set_index("edge_id") if scored_edges.index.name != "edge_id" else scored_edges
    ts, bank = se["timestamp"], se["from_bank"]
    for i, r in enumerate(rings):
        r.ring_id = f"{aggregator_id}-{model_id}-{seed}-{i}"
        if r.seed_edges:
            first = min(r.seed_edges, key=lambda e: (int(ts.loc[e]), e))
            r.tenant_id = int(bank.loc[first])


def write_rings_parquet(rings: list[Ring], path: Path) -> Path:
    """Write the rings table, stamping the contract schema version into the parquet metadata.

    A v1 file carries no `rings_schema_version` key; a v2 file carries b"2". Readers that need to
    tell the two apart should check the metadata rather than the column list -- a v1 file read
    through a v2 code path otherwise just looks like a file with columns missing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = rings_to_table(rings)
    meta = dict(table.schema.metadata or {})
    meta[b"rings_schema_version"] = str(RINGS_SCHEMA_VERSION).encode()
    pq.write_table(table.replace_schema_metadata(meta), path)
    return path


def rings_schema_version(path: Path) -> int:
    """The contract schema version a rings parquet was written with (1 when the key is absent)."""
    meta = pq.read_schema(path).metadata or {}
    return int(meta.get(b"rings_schema_version", b"1"))


def read_rings_parquet(path: Path) -> list[Ring]:
    rows = pq.read_table(path).to_pylist()
    return [Ring(**{c: row[c] for c in RINGS_ORDER}) for row in rows]
