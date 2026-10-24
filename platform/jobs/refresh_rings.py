"""Rebuild one tenant's rings from a promoted model and preserve stable identities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))

from db.models import ModelVersion, Ring, Verdict  # noqa: E402
from audit import add_audit_event  # noqa: E402
from db.session import db_session, loader_db_session  # noqa: E402
from jobs.build_tenant_rings import build_tenant_rings  # noqa: E402
from jobs.load_contract import load_rings  # noqa: E402
from jobs.ring_roll_forward import assign_roll_forward_ring_ids  # noqa: E402
from settings import configured_path, load_platform_config  # noqa: E402


class RingRefreshError(RuntimeError):
    """The tenant ring refresh could not safely complete."""


def _promoted_model(tenant_id: int, model_version_id: int) -> ModelVersion:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        version = session.scalar(select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.model_version_id == model_version_id,
            ModelVersion.promoted.is_(True),
        ))
        if version is None or not version.artifact_path:
            raise RingRefreshError("promoted model version is missing or has no artifact path")
        return version


def refresh_tenant_rings(tenant_id: int, model_version_id: int, run_id: str) -> dict[str, Any]:
    """Build rings for one tenant and write them through the restricted loader path."""
    if tenant_id < 1:
        raise RingRefreshError("tenant_id must be a positive tenant identifier")
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        add_audit_event(session, tenant_id=tenant_id, actor="ring_refresh_worker",
                        action="rings.refresh_started", entity_type="ring_refresh",
                        entity_id=run_id, details={"run_id": run_id,
                                                   "model_version_id": model_version_id,
                                                   "status": "running"})
    version = _promoted_model(tenant_id, model_version_id)
    config = load_platform_config()
    model_dir = Path(version.artifact_path)
    if not model_dir.is_absolute():
        model_dir = REPO_ROOT / model_dir
    output_dir = PLATFORM_ROOT / "out" / "ring-refresh" / run_id / str(tenant_id)
    scores_path = configured_path(config, "scored_edges")
    gfp_path = configured_path(config, "gfp")
    embeddings_path = configured_path(config, "embeddings")

    built = build_tenant_rings(
        scores_path=scores_path,
        model_dir=model_dir,
        gfp_path=gfp_path,
        embeddings_path=embeddings_path,
        tenant_ids=[tenant_id],
        output_dir=output_dir,
        config=config,
    )
    if len(built) != 1 or int(built[0]["tenant_id"]) != tenant_id:
        raise RingRefreshError("tenant ring builder returned an unexpected tenant result")
    rings_path = Path(built[0]["rings_path"])
    if not rings_path.is_file():
        raise RingRefreshError("tenant ring builder did not produce the ring parquet")

    table = pq.read_table(rings_path)
    records = table.to_pylist()
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        existing = list(session.scalars(select(Ring).where(Ring.tenant_id == tenant_id)))
        verdict_ring_ids = set(session.scalars(select(Verdict.ring_id).where(
            Verdict.tenant_id == tenant_id,
        )))

    version_tag = str(version.version_tag)
    version_part = version_tag[1:] if version_tag.startswith("v") else version_tag
    assign_roll_forward_ring_ids(
        records,
        existing,
        model_id=str(config["active_model_id"]),
        seed=int(config["active_seed"]),
        version=version_part,
        protected_ring_ids=verdict_ring_ids,
    )
    ring_id_index = table.schema.get_field_index("ring_id")
    table = table.set_column(
        ring_id_index,
        "ring_id",
        pa.array([record["ring_id"] for record in records], type=pa.string()),
    )
    pq.write_table(table, rings_path)

    # load_rings owns a distinct loader transaction and counts successful upserts
    # with RETURNING; it never relies on rowcount.
    counts = load_rings(rings_path, scope="tenant", tenant_id=tenant_id,
                        audit_action="rings.refresh_completed", audit_entity_id=run_id)
    return {
        "tenant_id": tenant_id,
        "model_version_id": model_version_id,
        "version_tag": version_tag,
        "rings_path": str(rings_path.resolve()),
        **counts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tenant_id", type=int)
    parser.add_argument("model_version_id", type=int)
    parser.add_argument("run_id")
    args = parser.parse_args(argv)
    try:
        result = refresh_tenant_rings(args.tenant_id, args.model_version_id, args.run_id)
    except Exception as exc:
        try:
            with loader_db_session(tenant_id=args.tenant_id) as session:
                add_audit_event(session, tenant_id=args.tenant_id, actor="ring_refresh_worker",
                                action="rings.refresh_failed", entity_type="ring_refresh",
                                entity_id=args.run_id,
                                details={"run_id": args.run_id, "status": "failed"})
        except Exception:
            pass
        print(f"ring refresh failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
