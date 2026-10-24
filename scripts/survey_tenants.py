"""Rank candidate banks and run tenant-scoped rings without writing to PostgreSQL.

PR-01 selection rule: visible edge count is the number of unique scored-edge rows
where from_bank or to_bank equals the bank. Candidates sort by visible edge count
descending, then numeric bank id ascending; the first N are surveyed. A separate
selection ranks banks by visible seed-edge count at the active fixed score cutoff.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "platform"))

from jobs.build_tenant_rings import build_tenant_rings  # noqa: E402
from settings import configured_path, load_platform_config  # noqa: E402

SELECTION_RULE = (
    "Count unique scored-edge rows incident to each bank (from_bank == bank_id or "
    "to_bank == bank_id); sort visible_edge_count descending then bank_id ascending; "
    "survey the first N banks."
)
FIELDS = [
    "bank_id", "selection_rules", "visible_edges", "seed_edges", "rings", "rings_with_at_least_5_members",
    "total_member_accounts", "share_ring_edges_cross_bank",
]


def select_candidate_banks(
    bank_counts: dict[int, int], seed_counts: dict[int, int], top: int,
) -> tuple[list[int], dict[int, list[str]], list[int], list[int]]:
    visible_order = sorted(bank_counts, key=lambda bank: (-bank_counts[bank], bank))
    seed_order = sorted(bank_counts, key=lambda bank: (-seed_counts.get(bank, 0), bank))
    visible_selection = visible_order[:top]
    seed_selection = seed_order[:top]
    candidate_rules: dict[int, list[str]] = {}
    for bank_id in visible_selection:
        candidate_rules.setdefault(bank_id, []).append("top_visible_edges")
    for bank_id in seed_selection:
        candidate_rules.setdefault(bank_id, []).append("top_seed_edges_at_active_cutoff")
    return sorted(candidate_rules), candidate_rules, visible_selection, seed_selection


def survey(config: dict, *, top: int, output_path: Path, output_dir: Path) -> list[dict]:
    scores_path = configured_path(config, "scored_edges")
    scores = pq.read_table(scores_path, columns=["edge_id", "from_bank", "to_bank", "score_raw"])
    edge_banks = {
        int(edge_id): (int(from_bank), int(to_bank))
        for edge_id, from_bank, to_bank in zip(
            scores["edge_id"].to_pylist(), scores["from_bank"].to_pylist(), scores["to_bank"].to_pylist(),
        )
    }
    bank_counts: dict[int, int] = {}
    seed_counts: dict[int, int] = {}
    cutoff = float(config["seed_score_cutoff"])
    for from_bank, to_bank, score in zip(
        scores["from_bank"].to_pylist(), scores["to_bank"].to_pylist(), scores["score_raw"].to_pylist(),
    ):
        bank_counts[int(from_bank)] = bank_counts.get(int(from_bank), 0) + 1
        if int(to_bank) != int(from_bank):
            bank_counts[int(to_bank)] = bank_counts.get(int(to_bank), 0) + 1
        if score is not None and float(score) > cutoff:
            seed_counts[int(from_bank)] = seed_counts.get(int(from_bank), 0) + 1
            if int(to_bank) != int(from_bank):
                seed_counts[int(to_bank)] = seed_counts.get(int(to_bank), 0) + 1
    candidates, candidate_rules, visible_selection, seed_selection = select_candidate_banks(
        bank_counts, seed_counts, top,
    )
    if not candidates:
        raise ValueError("scored-edge input contains no candidate banks")

    runs = build_tenant_rings(
        scores_path=scores_path,
        model_dir=configured_path(config, "model_dir"),
        gfp_path=configured_path(config, "gfp"),
        embeddings_path=configured_path(config, "embeddings"),
        tenant_ids=candidates,
        output_dir=output_dir,
        config=config,
    )
    rows = []
    for bank_id in candidates:
        visible_edges = bank_counts[bank_id]
        run = next(result for result in runs if result["tenant_id"] == bank_id)
        ring_table = pq.read_table(run["rings_path"], columns=[
            "member_edges", "members", "n_members",
        ])
        rings = ring_table.to_pylist()
        total_member_accounts: set[int] = set()
        member_edge_appearances = cross_bank_edge_appearances = 0
        at_least_five = 0
        for ring in rings:
            members = list(map(int, ring.get("members") or []))
            total_member_accounts.update(members)
            at_least_five += len(members) >= 5
            member_edges = list(map(int, ring.get("member_edges") or []))
            member_edge_appearances += len(member_edges)
        for ring in rings:
            for edge_id in map(int, ring.get("member_edges") or []):
                from_bank, to_bank = edge_banks[edge_id]
                cross_bank_edge_appearances += from_bank != to_bank
        rows.append({
            "bank_id": bank_id,
            "visible_edges": visible_edges,
            "selection_rules": ";".join(candidate_rules[bank_id]),
            "seed_edges": seed_counts.get(bank_id, 0),
            "rings": run["rings"],
            "rings_with_at_least_5_members": at_least_five,
            "total_member_accounts": len(total_member_accounts),
            "share_ring_edges_cross_bank": (
                cross_bank_edge_appearances / member_edge_appearances
                if member_edge_appearances else 0.0
            ),
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    log = {
        "selection_rule": SELECTION_RULE,
        "top": top,
        "visible_edge_selection_rule": (
            "Count unique scored-edge rows incident to each bank; sort count descending, then bank_id ascending; take first N."
        ),
        "seed_edge_selection_rule": (
            "Count unique scored-edge rows incident to each bank with score_raw > active seed_score_cutoff; "
            "sort count descending, then bank_id ascending; take first N."
        ),
        "top_visible_bank_ids": visible_selection,
        "top_seed_edge_bank_ids": seed_selection,
        "selected_bank_ids_union_sorted": candidates,
        "active_model_id": config["active_model_id"],
        "active_seed": config["active_seed"],
        "seed_score_cutoff": config["seed_score_cutoff"],
        "seed_score_cutoff_source": config["seed_score_cutoff_source"],
        "total_member_accounts_definition": "number of unique account IDs across the bank's rings",
        "share_ring_edges_cross_bank_definition": (
            "cross-bank member-edge appearances divided by all member-edge appearances; "
            "an edge repeated across rings is counted once per ring"
        ),
        "output_csv": output_path.name,
    }
    Path(str(output_path) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print("Selection rule (PR-01): " + SELECTION_RULE)
    print("Top 10 surveyed banks by ring count:")
    for row in sorted(rows, key=lambda item: (-item["rings"], item["bank_id"]))[:10]:
        print(f"bank={row['bank_id']} rings={row['rings']} visible_edges={row['visible_edges']}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--top", "--candidate-count", dest="top", type=int)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "reports" / "tenant_survey.csv")
    parser.add_argument("--output-dir", type=Path,
                        default=REPO_ROOT / "data" / "platform_tenant_runs" / "tenant_survey")
    args = parser.parse_args(argv)
    config = load_platform_config(str(args.config) if args.config else None)
    top = args.top or int(config.get("survey_candidate_count", 30))
    if top < 1:
        parser.error("--top must be at least 1")
    try:
        survey(config, top=top,
               output_path=args.output.resolve(), output_dir=args.output_dir.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
