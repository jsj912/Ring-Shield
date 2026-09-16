"""Convert a legacy E7 ring CSV (models/ring_aggregator.py) into the rings contract.

Usage (PowerShell):

    python contract/make_rings_stub.py ^
        --e7-csv experiments/legacy_E7_test_tuned/rings_gine.csv ^
        --scored-edges contract/out/scored_edges_gine_1.parquet ^
        --aggregator-id cc

Output: contract/out/rings_stub_<aggregator_id>.parquet (+ .log.json). Add --dry-run to
process a deterministic 1% (at least one) of the rings, sampled with random_state=--seed.

This is the connected-components *baseline*: nothing expands yet (expanded_edges = []),
conservation_closure is NaN, topology is UNKNOWN with uniform probabilities, and the
source/sink/mule arrays are empty. Steps 6-8 replace it.

Time basis: the E7 CSV's start_time/end_time are in the legacy CSV basis; this script
adds configs/paths.yaml:legacy_csv_time_offset_s so everything in the contract is in
loader basis, and asserts that every ring's start_time equals the min timestamp of its
member_edges.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths, write_log  # noqa: E402
from contract.schema import (  # noqa: E402
    E7_RING_CSV_COLUMNS,
    RINGS_COLUMNS,
    RINGS_ORDER,
    TOPOLOGY_TYPES,
)

DRY_RUN_FRAC = 0.01

_PA_TYPES = {
    "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(),
    "list<int64>": pa.list_(pa.int64()), "list<float64>": pa.list_(pa.float64()),
}
RINGS_PA_SCHEMA = pa.schema([(c, _PA_TYPES[t]) for c, (t, _) in RINGS_COLUMNS.items()])


def _mode_smallest(values: np.ndarray) -> int:
    """Most common value; ties broken by the smallest value (deterministic)."""
    vals, counts = np.unique(values, return_counts=True)
    return int(vals[np.argmax(counts)])  # np.unique is sorted, argmax returns first max


def make_rings_stub(
    e7_csv: Path,
    scored_edges_parquet: Path,
    aggregator_id: str,
    out_path: Path,
    *,
    account_map_path: Path | None = None,
    seed: int = 1,
    dry_run: bool = False,
) -> dict:
    """Build the rings contract parquet from an E7 CSV. Returns the log dict."""
    e7_csv, scored_edges_parquet, out_path = map(Path, (e7_csv, scored_edges_parquet, out_path))
    paths = load_paths()
    account_map_path = Path(account_map_path) if account_map_path else paths["account_bank_map"]
    offset = int(paths["legacy_csv_time_offset_s"])

    # 1. E7 csv ---------------------------------------------------------------
    e7 = pd.read_csv(e7_csv)
    assert list(e7.columns) == E7_RING_CSV_COLUMNS, (
        f"unexpected E7 columns {list(e7.columns)}; expected {E7_RING_CSV_COLUMNS}")
    assert e7["ring_idx"].is_unique, "ring_idx is not unique"
    n_in = len(e7)
    if dry_run:
        n_keep = max(1, round(DRY_RUN_FRAC * n_in))
        e7 = e7.sample(n=n_keep, random_state=seed).sort_values("ring_idx").reset_index(drop=True)
    e7["members"] = e7["members"].map(lambda s: [int(x) for x in str(s).split("|")])
    assert (e7["members"].map(len) == e7["n_members"]).all(), "n_members != len(members)"
    e7["start_time"] = e7["start_time"].astype("int64") + offset
    e7["end_time"] = e7["end_time"].astype("int64") + offset

    # 2. member / seed edges from scored_edges (loader basis) ------------------
    se = pd.read_parquet(scored_edges_parquet, columns=["edge_id", "from_id", "to_id", "timestamp", "is_seed"])
    edge_id = se["edge_id"].values
    from_id = se["from_id"].values
    to_id = se["to_id"].values
    ts = se["timestamp"].values
    is_seed = se["is_seed"].values

    bank_of = pd.read_parquet(account_map_path).set_index("account_id")["bank_id"]

    rows = []
    for r in e7.itertuples(index=False):
        members = np.asarray(r.members, dtype=np.int64)
        in_ring = np.isin(from_id, members) & np.isin(to_id, members)
        in_win = (ts >= r.start_time) & (ts <= r.end_time)
        sel = in_ring & in_win
        member_edges = edge_id[sel]
        assert len(member_edges) > 0, f"ring {r.ring_idx}: no member_edges"
        seed_edges = edge_id[sel & is_seed]
        t_min = int(ts[sel].min())
        assert t_min == r.start_time, (
            f"ring {r.ring_idx}: start_time {r.start_time} != min member_edges timestamp {t_min}")
        banks = bank_of.reindex(members)
        assert not banks.isna().any(), f"ring {r.ring_idx}: member without a bank: {members[banks.isna().values]}"
        rows.append({
            "ring_id": f"{aggregator_id}-{r.ring_idx}",
            "tenant_id": _mode_smallest(banks.values.astype(np.int64)),
            "aggregator_id": aggregator_id,
            "members": members.tolist(),
            "n_members": int(r.n_members),
            "member_edges": member_edges.tolist(),
            "seed_edges": seed_edges.tolist(),
            "expanded_edges": [],
            "n_edges": int(r.n_edges),
            "start_time": int(r.start_time),
            "end_time": int(r.end_time),
            "duration_hours": float(r.duration_hours),
            "confidence": float(r.confidence),
            "max_edge_prob": float(r.max_edge_prob),
            "density": float(r.density),
            "conservation_closure": float("nan"),
            "topology_type": "UNKNOWN",
            "topology_probs": [1.0 / len(TOPOLOGY_TYPES)] * len(TOPOLOGY_TYPES),
            "source_accounts": [],
            "sink_accounts": [],
            "mule_accounts": [],
        })

    # 5. write with an explicit schema so empty lists keep their element type ----
    table = pa.Table.from_pylist([{c: row[c] for c in RINGS_ORDER} for row in rows], schema=RINGS_PA_SCHEMA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path)

    log = {
        "aggregator_id": aggregator_id,
        "seed": seed,
        "dry_run": dry_run,
        "dry_run_frac": DRY_RUN_FRAC if dry_run else None,
        "inputs": {"e7_csv": str(e7_csv), "scored_edges": str(scored_edges_parquet),
                   "account_map": str(account_map_path)},
        "timestamp_offset_added_seconds": offset,
        "n_rings_in": n_in,
        "n_rings_out": len(rows),
        "n_members_total": int(sum(r["n_members"] for r in rows)),
        "n_member_edges_total": int(sum(len(r["member_edges"]) for r in rows)),
        "n_seed_edges_total": int(sum(len(r["seed_edges"]) for r in rows)),
        "min_members": int(min(r["n_members"] for r in rows)),
        "columns": RINGS_ORDER,
        "out_path": str(out_path),
    }
    write_log(out_path, log)
    print(f"[make_rings_stub] wrote {len(rows)} rings -> {out_path}  "
          f"(member_edges: {log['n_member_edges_total']}, seed_edges: {log['n_seed_edges_total']}, "
          f"offset +{offset}s)")
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--e7-csv", type=Path, required=True)
    ap.add_argument("--scored-edges", type=Path, required=True)
    ap.add_argument("--aggregator-id", required=True, help="e.g. cc")
    ap.add_argument("--seed", type=int, default=None,
                    help="only used to sample rings under --dry-run; default configs/seeds.yaml[0]")
    ap.add_argument("--out", type=Path, default=None, help="default contract/out/rings_stub_<aggregator>.parquet")
    ap.add_argument("--dry-run", action="store_true", help=f"process {DRY_RUN_FRAC:.0%} of rings (at least 1)")
    args = ap.parse_args(argv)

    if args.seed is None:
        import yaml
        with open(REPO_ROOT / "configs" / "seeds.yaml") as f:
            args.seed = int(yaml.safe_load(f)["seeds"][0])
    suffix = "_dryrun" if args.dry_run else ""
    out = args.out or (REPO_ROOT / "contract" / "out" / f"rings_stub_{args.aggregator_id}{suffix}.parquet")
    make_rings_stub(args.e7_csv, args.scored_edges, args.aggregator_id, out, seed=args.seed, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
