"""Create deterministic, simulated verdicts for one tenant and cycle day."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import sys

import numpy as np
from sqlalchemy import select

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters.ground_truth import load_val_truth, match_ring  # noqa: E402
from api.identity import Principal  # noqa: E402
from db.models import Ring, Transaction, User  # noqa: E402
from db.session import db_session, simulator_db_session  # noqa: E402
from services.verdicts import record_verdict  # noqa: E402
from settings import load_l6_config  # noqa: E402

DAY_ZERO_TIMESTAMP = 10
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class SimulatedDecision:
    verdict: str
    corrected_members: tuple[int, ...]
    is_simulated: bool = True
    note: str | None = None


def deterministic_rng(tenant_id: int, cycle_day: int, seed: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence([int(seed), int(tenant_id), int(cycle_day)]))


def review_limit(open_count: int, review_fraction: float) -> int:
    if not 0 <= review_fraction <= 1:
        raise ValueError("review_fraction must be in [0, 1]")
    return min(open_count, math.ceil(review_fraction * open_count))


def simulate_decision(*, ring_members: set[int], truth_rings: dict,
                      match_jaccard: float, full_confirm_jaccard: float,
                      accuracy: float, rng: np.random.Generator) -> SimulatedDecision:
    if not 0 <= accuracy <= 1:
        raise ValueError("accuracy must be in [0, 1]")
    match = match_ring(ring_members, truth_rings, match_jaccard, full_confirm_jaccard)
    corrected = set(ring_members) & set(match.members) if match.verdict == "partial" else set()
    true = SimulatedDecision(
        verdict=match.verdict,
        corrected_members=tuple(sorted(corrected)),
        note="simulated partial verdict" if match.verdict == "partial" else None,
    )
    if rng.random() < accuracy:
        return true
    if true.verdict in {"confirm", "reject"}:
        flipped = "reject" if true.verdict == "confirm" else "confirm"
        return SimulatedDecision(verdict=flipped, corrected_members=(), note=None)

    perturbed = set(true.corrected_members)
    ring_accounts = set(map(int, ring_members))
    if len(perturbed) > 1 and (len(perturbed) == len(ring_accounts) or rng.random() < 0.5):
        perturbed.remove(sorted(perturbed)[int(rng.integers(len(perturbed)))])
    else:
        additions = sorted(ring_accounts - perturbed)
        if additions:
            perturbed.add(additions[int(rng.integers(len(additions)))])
        elif len(perturbed) > 1:
            perturbed.remove(sorted(perturbed)[int(rng.integers(len(perturbed)))])
        else:
            # With one corrected account and no other ring member, make an explicit
            # one-account perturbation while keeping the partial correction nonempty.
            perturbed.add(next(iter(perturbed)) + 1)
    return SimulatedDecision(
        verdict="partial", corrected_members=tuple(sorted(perturbed)),
        note="simulated partial verdict",
    )


def _cycle_bounds(cycle_day: int, cycle_days: int) -> tuple[int, int]:
    if cycle_day < 0 or cycle_days < 1:
        raise ValueError("cycle_day must be non-negative and cycle_days positive")
    start = DAY_ZERO_TIMESTAMP + cycle_day * cycle_days * SECONDS_PER_DAY
    return start, start + cycle_days * SECONDS_PER_DAY


def simulate_cycle(*, tenant_id: int, cycle_day: int, actor: Principal,
                   truth_path: Path, seed: int, accuracy: float, review_fraction: float,
                   match_jaccard: float, full_confirm_jaccard: float,
                   cycle_days: int = 1) -> dict[str, int]:
    if actor.role == "admin" or actor.tenant_id != tenant_id:
        raise PermissionError("simulation requires a non-admin actor for the requested tenant")
    truth_rings = load_val_truth(truth_path)
    start, end = _cycle_bounds(cycle_day, cycle_days)
    rng = deterministic_rng(tenant_id, cycle_day, seed)
    with simulator_db_session(tenant_id=tenant_id) as session:
        analyst = session.scalar(select(User).where(
            User.tenant_id == tenant_id,
            User.email == f"simulated.analyst@tenant{tenant_id}.local",
            User.role == "analyst",
            User.disabled.is_(False),
        ))
        if analyst is None:
            raise RuntimeError(f"simulated analyst is not seeded for tenant {tenant_id}")
        open_rings = list(session.scalars(
            select(Ring).where(
                Ring.tenant_id == tenant_id,
                Ring.scope == "tenant",
                Ring.status == "open",
                Ring.start_time >= start,
                Ring.start_time < end,
            ).order_by(Ring.confidence.desc(), Ring.ring_id.asc())
        ))
        reviewed = open_rings[:review_limit(len(open_rings), review_fraction)]
        for ring in reviewed:
            decision = simulate_decision(
                ring_members=set(ring.member_accounts), truth_rings=truth_rings,
                match_jaccard=match_jaccard, full_confirm_jaccard=full_confirm_jaccard,
                accuracy=accuracy, rng=rng,
            )
            corrected_members = set(decision.corrected_members)
            corrected_edges = []
            if decision.verdict == "partial":
                rows = session.execute(select(Transaction.edge_id, Transaction.from_id, Transaction.to_id).where(
                    Transaction.tenant_id == tenant_id,
                    Transaction.edge_id.in_(list(map(int, ring.member_edges))),
                ))
                corrected_edges = [int(edge_id) for edge_id, from_id, to_id in rows
                                   if int(from_id) in corrected_members and int(to_id) in corrected_members]
            record_verdict(
                session, ring=ring, tenant_id=tenant_id, ring_id=ring.ring_id,
                user_id=analyst.user_id, verdict=decision.verdict,
                corrected_members=decision.corrected_members,
                corrected_edges=corrected_edges, note=decision.note, is_simulated=True,
            )
    return {"open_rings": len(open_rings), "reviewed": len(reviewed),
            "simulated": len(reviewed)}


def main(argv: list[str] | None = None) -> int:
    config = load_l6_config(require_retrain_paths=False)
    simulator = config["simulator"]
    retrain = config["retrain"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--cycle-day", type=int, required=True)
    parser.add_argument("--seed", type=int, default=int(simulator["seed"]))
    parser.add_argument("--accuracy", type=float, default=float(simulator["accuracy"]))
    parser.add_argument("--review-fraction", type=float, default=float(simulator["review_fraction"]))
    args = parser.parse_args(argv)
    truth_path = config["paths"].get("truth_parquet")
    if truth_path is None or not truth_path.is_file():
        parser.error("platform config l6.retrain.truth_parquet is missing or unavailable")
    try:
        with db_session(tenant_id=args.tenant_id, role="analyst") as session:
            user = session.scalar(select(User).where(
                User.tenant_id == args.tenant_id,
                User.email == f"simulated.analyst@tenant{args.tenant_id}.local",
                User.role == "analyst",
            ))
        if user is None:
            raise RuntimeError(f"simulated analyst is not seeded for tenant {args.tenant_id}")
        actor = Principal(user_id=user.user_id, tenant_id=args.tenant_id,
                          role="analyst", email=user.email)
        result = simulate_cycle(
            tenant_id=args.tenant_id, cycle_day=args.cycle_day, actor=actor,
            truth_path=truth_path, seed=args.seed,
            accuracy=args.accuracy, review_fraction=args.review_fraction,
            match_jaccard=float(simulator["match_jaccard"]),
            full_confirm_jaccard=float(simulator["full_confirm_jaccard"]),
            cycle_days=int(simulator["cycle_days"]),
        )
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        parser.error(str(exc))
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
