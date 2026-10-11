"""Read and validate the two contract files the L4 layer consumes (XR-01).

    cfg = load_config()
    se = read_scored_edges("contract/out/scored_edges_gine_causal_1.parquet")
    rings = read_rings("contract/out/rings_full_gine_causal_1.parquet", scored_edges=se)
    prov = provenance(se, rings)        # {"model_id": "gine_causal", "seed": 1, "aggregator_id": "full"}

The column lists, types and orders come from `contract/schema.py` (Joan's file, which declares itself
the authority over every spec). Nothing here redefines them. Any problem raises `ContractError` with
every violation listed, so a broken file fails loudly instead of producing a quietly wrong number.

Named `contract_io.py`, not `io.py`: a module called `io` shadows Python's standard library when a
script is run from inside this folder (the same trap as `ringshield/typing/`, docs/PITFALLS.md §9).
"""
from __future__ import annotations

import math
import numbers
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from contract.schema import RINGS_COLUMNS, SCORED_EDGES_COLUMNS, TOPOLOGY_TYPES

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).resolve().with_name("config.yaml")
LIST_COLUMNS = [c for c, (t, _) in RINGS_COLUMNS.items() if t.startswith("list<")]
EDGE_LIST_COLUMNS = ["member_edges", "seed_edges", "expanded_edges"]
ROLE_LIST_COLUMNS = ["source_accounts", "sink_accounts", "mule_accounts"]
MAX_ERRORS_SHOWN = 20


class ContractError(ValueError):
    """A contract file (or an in-memory frame standing in for one) breaks the contract."""


# ----------------------------------------------------------------------------- config
def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_research_config(cfg: dict, name: str) -> dict:
    """One of the research-side YAMLs named under `research_configs` (read, never copied)."""
    return yaml.safe_load((REPO_ROOT / cfg["research_configs"][name]).read_text(encoding="utf-8"))


def repo_path(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else REPO_ROOT / p


# ----------------------------------------------------------------------------- column + type checks
def check_columns(names, spec: dict, what: str) -> None:
    """The exact column set of `spec`: every field present, nothing extra."""
    names = list(names)
    missing = [c for c in spec if c not in names]
    extra = [c for c in names if c not in spec]
    problems = []
    if missing:
        problems.append(f"missing field(s) {missing}")
    if extra:
        problems.append(f"unexpected field(s) {extra}")
    if problems:
        raise ContractError(f"{what}: " + "; ".join(problems))


def _arrow_type_ok(t: pa.DataType, spec_type: str) -> bool:
    if spec_type == "int64":
        return pa.types.is_int64(t)
    if spec_type == "float64":
        return pa.types.is_float64(t)
    if spec_type == "bool":
        return pa.types.is_boolean(t)
    if spec_type == "string":
        return pa.types.is_string(t) or pa.types.is_large_string(t)
    if spec_type.startswith("list<"):
        if not (pa.types.is_list(t) or pa.types.is_large_list(t)):
            return False
        return _arrow_type_ok(t.value_type, spec_type[len("list<"):-1])
    raise AssertionError(f"unknown contract type {spec_type!r}")


def check_arrow_schema(schema: pa.Schema, spec: dict, what: str) -> None:
    check_columns(schema.names, spec, what)
    bad = [f"{f.name}: file has {f.type}, contract says {spec[f.name][0]}"
           for f in schema if not _arrow_type_ok(f.type, spec[f.name][0])]
    if bad:
        raise ContractError(f"{what}: wrong type(s): " + "; ".join(bad))


def _is_int(x) -> bool:
    return isinstance(x, numbers.Integral) and not isinstance(x, (bool, np.bool_))


def _is_real(x) -> bool:
    return isinstance(x, numbers.Real) and not isinstance(x, (bool, np.bool_))


def _column_type_ok(s: pd.Series, spec_type: str) -> bool:
    if spec_type == "int64":
        return pd.api.types.is_integer_dtype(s) and not pd.api.types.is_bool_dtype(s)
    if spec_type == "float64":
        return pd.api.types.is_float_dtype(s)
    if spec_type == "bool":
        return pd.api.types.is_bool_dtype(s)
    if spec_type == "string":
        return pd.api.types.is_string_dtype(s) and all(isinstance(v, str) for v in s)
    if spec_type.startswith("list<"):
        elem_ok = _is_int if spec_type == "list<int64>" else _is_real
        return all(isinstance(v, (list, tuple, np.ndarray)) and all(elem_ok(x) for x in v) for v in s)
    raise AssertionError(f"unknown contract type {spec_type!r}")


def check_frame_types(df: pd.DataFrame, spec: dict, what: str) -> None:
    check_columns(df.columns, spec, what)
    bad = [f"{c}: expected {t}, got {df[c].dtype}" for c, (t, _) in spec.items() if not _column_type_ok(df[c], t)]
    if bad:
        raise ContractError(f"{what}: wrong type(s): " + "; ".join(bad))


def _raise_if(errors: list[str], what: str) -> None:
    if errors:
        shown = errors[:MAX_ERRORS_SHOWN]
        more = f" (+{len(errors) - len(shown)} more)" if len(errors) > len(shown) else ""
        raise ContractError(f"{what}: {len(errors)} violation(s){more}:\n  " + "\n  ".join(shown))


# ----------------------------------------------------------------------------- scored_edges
def validate_scored_edges(se: pd.DataFrame, what: str = "scored_edges") -> pd.DataFrame:
    check_frame_types(se, SCORED_EDGES_COLUMNS, what)
    errors = []
    if not se["edge_id"].is_unique:
        errors.append(f"edge_id is not unique ({int(se['edge_id'].duplicated().sum())} duplicates)")
    for c in ("edge_id", "from_id", "to_id", "timestamp"):
        if se[c].isna().any():
            errors.append(f"{c} has missing values")
    cal = se["score_calibrated"]
    if ((cal < 0) | (cal > 1)).any():
        errors.append("score_calibrated outside [0, 1]")
    if (se["is_seed"] & se["score_raw"].isna()).any():
        errors.append("is_seed is True on an edge without score_raw")
    for c in ("model_id", "seed"):
        if se[c].nunique(dropna=False) != 1:
            errors.append(f"{c} is not a single value per file: {sorted(map(str, se[c].unique()))[:5]}")
    _raise_if(errors, what)
    return se


def read_scored_edges(path) -> pd.DataFrame:
    path = repo_path(path)
    what = f"scored_edges {path.name}"
    check_arrow_schema(pq.read_schema(path), SCORED_EDGES_COLUMNS, what)
    se = pd.read_parquet(path)
    se["model_id"] = se["model_id"].astype(object)      # plain str values whatever the arrow string kind
    return validate_scored_edges(se, what)


# ----------------------------------------------------------------------------- rings
def _as_plain_lists(rings: pd.DataFrame) -> pd.DataFrame:
    """List columns as python lists of int / float (parquet hands back numpy arrays)."""
    out = rings.copy()
    for c in LIST_COLUMNS:
        conv = float if RINGS_COLUMNS[c][0] == "list<float64>" else int
        out[c] = [[conv(x) for x in v] for v in out[c]]
    return out


def validate_rings(rings: pd.DataFrame, scored_edges: pd.DataFrame | None = None, *, what: str = "rings",
                   topology_tolerance: float | None = None) -> pd.DataFrame:
    """Contract invariants per ring; with `scored_edges`, also that every edge exists there and agrees."""
    check_frame_types(rings, RINGS_COLUMNS, what)
    tol = topology_tolerance if topology_tolerance is not None else \
        float(load_config()["contract_checks"]["topology_probs_sum_tolerance"])
    se = scored_edges.set_index("edge_id") if scored_edges is not None else None
    errors = []
    if not rings["ring_id"].is_unique:
        errors.append("ring_id is not unique")
    for r in rings.itertuples(index=False):
        rid = r.ring_id
        members, member_edges = set(r.members), set(r.member_edges)
        seeds, expanded = set(r.seed_edges), set(r.expanded_edges)
        if not rid:
            errors.append("empty ring_id")
        if len(members) != len(r.members):
            errors.append(f"{rid}: duplicate account in members")
        if r.n_members != len(r.members):
            errors.append(f"{rid}: n_members {r.n_members} != len(members) {len(r.members)}")
        if not seeds <= member_edges:
            errors.append(f"{rid}: seed_edges not a subset of member_edges ({sorted(seeds - member_edges)[:5]})")
        if not expanded <= member_edges:
            errors.append(f"{rid}: expanded_edges not a subset of member_edges ({sorted(expanded - member_edges)[:5]})")
        if seeds & expanded:
            errors.append(f"{rid}: an edge is both seed and expanded ({sorted(seeds & expanded)[:5]})")
        if len(r.expanded_edge_probs) != len(r.expanded_edges):
            errors.append(f"{rid}: {len(r.expanded_edge_probs)} expanded_edge_probs for {len(r.expanded_edges)} expanded_edges")
        if any(not math.isnan(p) and not 0.0 <= p <= 1.0 for p in r.expanded_edge_probs):
            errors.append(f"{rid}: an expanded_edge_prob is outside [0, 1]")
        if len(r.topology_probs) != len(TOPOLOGY_TYPES):
            errors.append(f"{rid}: {len(r.topology_probs)} topology_probs, contract says {len(TOPOLOGY_TYPES)}")
        elif any(p < 0 for p in r.topology_probs) or abs(sum(r.topology_probs) - 1.0) > tol:
            errors.append(f"{rid}: topology_probs do not form a distribution (sum {sum(r.topology_probs):.6f})")
        if r.topology_type not in TOPOLOGY_TYPES and r.topology_type != "UNKNOWN":
            errors.append(f"{rid}: topology_type {r.topology_type!r} is not a contract type")
        for c in ROLE_LIST_COLUMNS:
            extra = set(getattr(r, c)) - members
            if extra:
                errors.append(f"{rid}: {c} holds non-members {sorted(extra)[:5]}")
        cc = r.conservation_closure
        if not (math.isnan(cc) or 0.0 <= cc <= 1.0):       # NaN is legitimate (no source or no sink): kept as NaN
            errors.append(f"{rid}: conservation_closure {cc} outside [0, 1]")
        if r.start_time > r.end_time:
            errors.append(f"{rid}: start_time after end_time")
        if se is not None:
            all_edges = member_edges | seeds | expanded
            unknown = sorted(e for e in all_edges if e not in se.index)
            if unknown:
                errors.append(f"{rid}: {len(unknown)} edge(s) not in scored_edges ({unknown[:5]})")
                continue
            if member_edges:
                ends = se.loc[sorted(member_edges), ["from_id", "to_id"]].to_numpy().ravel()
                outside = set(ends.tolist()) - members
                if outside:
                    errors.append(f"{rid}: member_edges touch non-member accounts {sorted(outside)[:5]}")
            if seeds and not se.loc[sorted(seeds), "is_seed"].all():
                errors.append(f"{rid}: a seed_edge is not is_seed in scored_edges")
            if expanded and se.loc[sorted(expanded), "is_seed"].any():
                errors.append(f"{rid}: an expanded_edge is is_seed in scored_edges")
    _raise_if(errors, what)
    return rings


def read_rings(path, scored_edges: pd.DataFrame | None = None) -> pd.DataFrame:
    path = repo_path(path)
    what = f"rings {path.name}"
    check_arrow_schema(pq.read_schema(path), RINGS_COLUMNS, what)
    rings = _as_plain_lists(pd.read_parquet(path))
    return validate_rings(rings, scored_edges, what=what)


# ----------------------------------------------------------------------------- provenance
def provenance(scored_edges: pd.DataFrame, rings: pd.DataFrame) -> dict:
    """model_id / seed come from scored_edges (rings carry neither column); aggregator_id from rings.
    Cross-checked against the ring_id rule f'{aggregator}-{model_id}-{seed}-{idx}' (contract/schema.py)."""
    model_id = str(scored_edges["model_id"].iloc[0])
    seed = int(scored_edges["seed"].iloc[0])
    aggs = sorted(rings["aggregator_id"].unique()) if len(rings) else []
    if len(aggs) > 1:
        raise ContractError(f"rings: more than one aggregator_id {aggs}")
    aggregator_id = aggs[0] if aggs else None
    prefix = f"{aggregator_id}-{model_id}-{seed}-"
    wrong = [rid for rid in rings["ring_id"] if not rid.startswith(prefix)]
    if wrong:
        raise ContractError(f"rings do not belong to these scored_edges: expected ring_id prefix {prefix!r}, "
                            f"got e.g. {wrong[:3]}")
    return {"model_id": model_id, "seed": seed, "aggregator_id": aggregator_id}
