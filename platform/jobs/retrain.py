"""Tenant-scoped, holdout-gated retraining orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import func, select, text

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters import research_cli  # noqa: E402
from db.models import ModelVersion, RetrainRun, Ring, Transaction, Verdict  # noqa: E402
from db.session import db_session, get_engine, loader_db_session  # noqa: E402
from settings import load_l6_config, load_platform_config  # noqa: E402


class RetrainError(RuntimeError):
    """A configured or validated L6 retraining stage could not proceed."""


def verify_holdout(manifest_path: Path, checksum_path: Path) -> dict[str, Any]:
    try:
        payload = manifest_path.read_bytes()
        expected = checksum_path.read_text(encoding="ascii").split()[0]
        manifest = json.loads(payload)
    except (OSError, IndexError, UnicodeError, json.JSONDecodeError) as exc:
        raise RetrainError("holdout manifest or SHA-256 file is missing or invalid") from exc
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RetrainError("holdout manifest SHA-256 does not match its committed checksum")
    ids = manifest.get("truth_ring_ids") if isinstance(manifest, dict) else None
    if not isinstance(ids, list) or not ids or manifest.get("n") != len(ids):
        raise RetrainError("holdout manifest requires non-empty truth_ring_ids and matching n")
    try:
        numeric_ids = [int(item) for item in ids]
    except (TypeError, ValueError) as exc:
        raise RetrainError("holdout truth_ring_ids must be integer IDs") from exc
    if numeric_ids != sorted(set(numeric_ids)):
        raise RetrainError("holdout truth_ring_ids must be unique and sorted")
    if "pred_ring_ids" in manifest:
        raise RetrainError("holdout manifest must contain truth IDs only")
    return manifest


def should_promote(candidate_f1: float, current_f1: float, epsilon: float) -> tuple[bool, str]:
    if any(not 0 <= value <= 1 for value in (candidate_f1, current_f1)) or epsilon < 0:
        raise ValueError("F1 scores must be in [0, 1] and epsilon non-negative")
    minimum = current_f1 - epsilon
    if candidate_f1 >= minimum:
        return True, f"holdout ring_f1 {candidate_f1:.4f} >= current {current_f1:.4f} - {epsilon:g}"
    return False, f"holdout ring_f1 {candidate_f1:.4f} < current {current_f1:.4f} - {epsilon:g}"


def candidate_evaluation_policy(retrained: bool) -> tuple[bool, str | None]:
    if retrained:
        return True, None
    return False, "train CLI reported retrained=false; candidate identical to base"


def build_label_rows(verdict_ring_rows, transaction_endpoints: dict[int, tuple[int, int]]) -> list[dict[str, Any]]:
    """Convert latest (verdict, ring) pairs to the research labels contract."""
    output = []
    seen: set[str] = set()
    for verdict, ring in verdict_ring_rows:
        ring_id = str(ring.ring_id)
        if ring_id in seen:
            continue
        seen.add(ring_id)
        ring_members = sorted(map(int, ring.member_accounts or []))
        ring_edges = sorted(map(int, ring.member_edges or []))
        kind = str(verdict.verdict)
        if kind == "partial":
            members = sorted(set(map(int, verdict.corrected_members or [])))
            if not members:
                raise RetrainError(f"partial verdict {ring_id} has no corrected members")
            edges = sorted(set(map(int, verdict.corrected_edges or [])))
            edges = [edge_id for edge_id in edges if edge_id in set(ring_edges)]
            if not edges:
                corrected = set(members)
                edges = [edge_id for edge_id in ring_edges
                         if edge_id in transaction_endpoints
                         and set(transaction_endpoints[edge_id]) <= corrected]
        elif kind in {"confirm", "reject"}:
            members, edges = ring_members, ring_edges
        else:
            raise RetrainError(f"unsupported verdict value for ring {ring_id}")
        if kind in {"confirm", "partial"} and not members:
            raise RetrainError(f"{kind} verdict {ring_id} has no member accounts")
        output.append({"ring_id": ring_id, "member_accounts": members,
                       "member_edges": edges, "verdict": kind})
    return output


def assign_roll_forward_ring_ids(records: list[dict[str, Any]], existing_rows,
                                 *, model_id: str, seed: int, version: str) -> list[dict[str, Any]]:
    """Match only open rings by member Jaccard; give all other rings fresh IDs."""
    available = {
        str(row.ring_id): set(map(int, row.member_accounts or []))
        for row in existing_rows if row.status == "open"
    }
    all_ids = {str(row.ring_id) for row in existing_rows}
    assigned: set[str] = set()
    ordered = sorted(records, key=lambda item: (-float(item["confidence"]), str(item["ring_id"])))
    for idx, record in enumerate(ordered):
        members = set(map(int, record["members"]))
        candidates = []
        for old_id, old_members in available.items():
            if old_id in assigned:
                continue
            union = members | old_members
            score = len(members & old_members) / len(union) if union else 1.0
            if score >= 0.5:
                candidates.append((score, old_id))
        if candidates:
            _, identity = max(candidates, key=lambda item: (item[0], item[1]))
            assigned.add(identity)
        else:
            counter = idx
            identity = f"full-{model_id}-{seed}-v{version}-{counter}"
            while identity in all_ids:
                counter += 1
                identity = f"full-{model_id}-{seed}-v{version}-{counter}"
            all_ids.add(identity)
        record["ring_id"] = identity
    return records


def _validate_inputs(l6: dict[str, Any], config: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = l6["paths"]
    for key, path in paths.items():
        if not path.is_file() and key != "base_model_dir":
            raise RetrainError(f"configured L6 input is unavailable: {key}")
    if not paths["base_model_dir"].is_dir():
        raise RetrainError("configured base_model_dir is not a directory")
    score_log_path = Path(str(paths["val_scored_edges"]) + ".log.json")
    try:
        score_log = json.loads(score_log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetrainError("validation scored-edge run log is missing or invalid") from exc
    if (score_log.get("split") != "val"
            or score_log.get("model_id") != config["active_model_id"]
            or int(score_log.get("seed", -1)) != int(config["active_seed"])):
        raise RetrainError("validation scored-edge log does not match val and active model/seed")
    verify_holdout(paths["holdout_manifest"], paths["holdout_sha256_file"])
    return paths


def _run_log_path(run_id: str) -> Path:
    return PLATFORM_ROOT / "out" / "retrain" / f"{run_id}.log"


def _write_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}\n")


@contextmanager
def _tenant_lock(tenant_id: int):
    """Hold a PostgreSQL session advisory lock for this tenant's full job."""
    key = f"ringshield-l6-retrain:{int(tenant_id)}"
    with get_engine().connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
        connection.commit()
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
            connection.commit()


def _set_run_state(tenant_id: int, run_id: str, *, status: str,
                   model_version_id: int | None = None, finished: bool = False) -> None:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        run = session.get(RetrainRun, run_id)
        if run is None or run.tenant_id != tenant_id:
            raise RetrainError("retrain run disappeared or tenant scope changed")
        run.status = status
        if run.started_at is None:
            run.started_at = datetime.now(timezone.utc)
        if model_version_id is not None:
            run.model_version_id = model_version_id
        if finished:
            run.finished_at = datetime.now(timezone.utc)


def _promoted_version(session, tenant_id: int, component: str) -> ModelVersion | None:
    return session.scalar(select(ModelVersion).where(
        ModelVersion.tenant_id == tenant_id,
        ModelVersion.component == component,
        ModelVersion.promoted.is_(True),
    ).with_for_update())


def _insert_model_version(*, tenant_id: int, component: str, version_tag: str,
                          trained_at: datetime, label_count: int, f1: float | None,
                          promoted: bool, gate_reason: str | None, artifact_path: Path | None) -> int:
    with loader_db_session() as session:
        old = _promoted_version(session, tenant_id, component)
        if promoted and old is not None:
            old.promoted = False
            session.flush()
        version = ModelVersion(
            tenant_id=tenant_id, component=component, version_tag=version_tag,
            trained_at=trained_at, train_label_count=label_count,
            holdout_ring_f1=f1, promoted=promoted, gate_reason=gate_reason,
            artifact_path=str(artifact_path) if artifact_path is not None else None,
        )
        session.add(version)
        session.flush()
        return int(version.model_version_id)


def _evaluate(cli, *, model_dir: Path, paths: dict[str, Path], l6: dict[str, Any],
              run_dir: Path, label: str) -> float:
    config = load_platform_config()
    output = run_dir / f"{label}-rings.parquet"
    run_result = cli.run_rings(
        scores=paths["val_scored_edges"], model_dir=model_dir, aggregator="full",
        gfp=paths["val_gfp"], embeddings=paths["val_embeddings"], out=output,
    )
    evaluation = cli.eval_rings(
        rings=run_result.rings_path, truth=paths["truth_parquet"],
        holdout=paths["holdout_manifest"],
        window=l6["retrain"]["eval_window"], scope=l6["retrain"]["eval_scope"],
        out=run_dir / f"{label}-metrics.json",
    )
    return evaluation.ring_f1


def _new_verdicts(session, tenant_id: int, since: datetime):
    rows = list(session.execute(
        select(Verdict, Ring)
        .join(Ring, (Ring.tenant_id == Verdict.tenant_id) & (Ring.ring_id == Verdict.ring_id))
        .where(Verdict.tenant_id == tenant_id, Verdict.created_at > since)
        .order_by(Verdict.ring_id, Verdict.created_at.desc(), Verdict.verdict_id.desc())
    ))
    latest = []
    seen: set[str] = set()
    for verdict, ring in rows:
        if verdict.ring_id not in seen:
            latest.append((verdict, ring))
            seen.add(verdict.ring_id)
    edge_ids = sorted({int(edge_id) for _, ring in latest for edge_id in (ring.member_edges or [])})
    endpoints = {}
    if edge_ids:
        endpoints = {int(edge): (int(source), int(target)) for edge, source, target in session.execute(
            select(Transaction.edge_id, Transaction.from_id, Transaction.to_id)
            .where(Transaction.tenant_id == tenant_id, Transaction.edge_id.in_(edge_ids))
        )}
    return build_label_rows(latest, endpoints)


def _ensure_baseline(*, tenant_id: int, component: str, base_dir: Path,
                     l6: dict[str, Any], paths: dict[str, Path], run_dir: Path,
                     cli, log_path: Path) -> ModelVersion:
    with loader_db_session() as session:
        promoted = _promoted_version(session, tenant_id, component)
        if promoted is not None:
            return promoted
    score = _evaluate(cli, model_dir=base_dir, paths=paths, l6=l6,
                      run_dir=run_dir, label=f"{component}-baseline")
    version_id = _insert_model_version(
        tenant_id=tenant_id, component=component, version_tag="base",
        trained_at=datetime.now(timezone.utc), label_count=0, f1=score,
        promoted=True, gate_reason="initial holdout baseline", artifact_path=base_dir,
    )
    _write_log(log_path, f"{component}: recorded initial base holdout baseline ({score:.4f})")
    with loader_db_session() as session:
        return session.get(ModelVersion, version_id)


def _roll_forward(*, tenant_id: int, model_dir: Path, version_tag: str,
                  run_dir: Path, config: dict[str, Any]) -> None:
    from jobs.build_tenant_rings import build_tenant_rings
    from jobs.load_contract import load_rings

    paths = {key: Path(config[key]) for key in ("scored_edges", "model_dir", "gfp", "embeddings")}
    output_dir = run_dir / "tenant-test-rings"
    results = build_tenant_rings(
        scores_path=paths["scored_edges"], model_dir=model_dir,
        gfp_path=paths["gfp"], embeddings_path=paths["embeddings"],
        tenant_ids=[tenant_id], output_dir=output_dir, config=config,
    )
    ring_path = Path(results[0]["rings_path"])
    table = pq.read_table(ring_path)
    records = table.to_pylist()
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        existing = list(session.scalars(select(Ring).where(Ring.tenant_id == tenant_id)))
    model = json.loads((model_dir / "model.json").read_text(encoding="utf-8"))
    model_id = str(model["model_id"])
    seed = int(model["seed"])
    assign_roll_forward_ring_ids(records, existing, model_id=model_id, seed=seed, version=version_tag)
    if records:
        ring_id_column = table.schema.get_field_index("ring_id")
        table = table.set_column(ring_id_column, "ring_id",
                                 pa.array([row["ring_id"] for row in records], type=pa.string()))
        pq.write_table(table, ring_path)
    load_rings(ring_path, scope="tenant")


def run_retrain_job(tenant_id: int, run_id: str, *, cli=research_cli) -> None:
    log_path = _run_log_path(run_id)
    relative_log_path = log_path.relative_to(REPO_ROOT)
    _write_log(log_path, f"tenant {tenant_id}: retrain run started")
    last_version_id = None
    try:
        config = load_platform_config()
        l6 = load_l6_config(config)
        paths = _validate_inputs(l6, config)
        run_dir = log_path.parent / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _set_run_state(tenant_id, run_id, status="running")
        with _tenant_lock(tenant_id):
            components = l6["retrain"]["components"]
            for component in components:
                base_dir = paths["base_model_dir"]
                with loader_db_session() as session:
                    current = _promoted_version(session, tenant_id, component)
                    if current is not None and current.artifact_path:
                        candidate_base = Path(current.artifact_path)
                        if candidate_base.is_dir():
                            base_dir = candidate_base
                current = _ensure_baseline(
                    tenant_id=tenant_id, component=component, base_dir=base_dir,
                    l6=l6, paths=paths, run_dir=run_dir, cli=cli, log_path=log_path,
                )
                with db_session(tenant_id=tenant_id, role="supervisor") as session:
                    labels = _new_verdicts(session, tenant_id, current.trained_at)
                if len(labels) < int(l6["retrain"]["min_new_labels"]):
                    _write_log(log_path, f"{component}: skipped; only {len(labels)} new ring labels")
                    continue
                label_path = run_dir / f"{component}-labels.parquet"
                label_table = pa.Table.from_pylist(labels, schema=pa.schema([
                    ("ring_id", pa.string()), ("member_accounts", pa.list_(pa.int64())),
                    ("member_edges", pa.list_(pa.int64())), ("verdict", pa.string()),
                ]))
                pq.write_table(label_table, label_path, compression="zstd")
                output_model = run_dir / f"{component}-candidate"
                train_result = cli.train(component=component, labels=label_path,
                                          base_dir=base_dir, out_dir=output_model)
                trained_at = datetime.now(timezone.utc)
                model_version = train_result.version.get("version", "unknown")
                version_tag = f"v{model_version}-{run_id[:8]}"
                should_evaluate, disabled_reason = candidate_evaluation_policy(train_result.retrained)
                if not should_evaluate:
                    assert disabled_reason is not None
                    last_version_id = _insert_model_version(
                        tenant_id=tenant_id, component=component, version_tag=version_tag,
                        trained_at=trained_at, label_count=len(labels), f1=None,
                        promoted=False, gate_reason=disabled_reason, artifact_path=output_model,
                    )
                    _write_log(log_path, f"{component}: candidate not promoted: {disabled_reason}")
                    continue
                candidate_f1 = _evaluate(
                    cli, model_dir=output_model, paths=paths, l6=l6,
                    run_dir=run_dir, label=f"{component}-candidate",
                )
                promote, reason = should_promote(
                    candidate_f1, float(current.holdout_ring_f1), float(l6["retrain"]["epsilon"]),
                )
                last_version_id = _insert_model_version(
                    tenant_id=tenant_id, component=component, version_tag=version_tag,
                    trained_at=trained_at, label_count=len(labels), f1=candidate_f1,
                    promoted=promote, gate_reason=reason, artifact_path=output_model,
                )
                _write_log(log_path, f"{component}: {reason}")
                if promote:
                    _roll_forward(tenant_id=tenant_id, model_dir=output_model,
                                  version_tag=str(model_version), run_dir=run_dir, config=config)
                    _write_log(log_path, f"{component}: promoted candidate and refreshed open rings")
            _set_run_state(tenant_id, run_id, status="succeeded", model_version_id=last_version_id, finished=True)
    except Exception as exc:
        _write_log(log_path, f"run failed: {type(exc).__name__}: {exc}")
        try:
            _set_run_state(tenant_id, run_id, status="failed", model_version_id=last_version_id, finished=True)
        except Exception as state_error:
            _write_log(log_path, f"could not persist failed state: {type(state_error).__name__}")
    finally:
        # DB stores a repository-relative path; the API never returns machine paths.
        try:
            with db_session(tenant_id=tenant_id, role="supervisor") as session:
                run = session.get(RetrainRun, run_id)
                if run is not None:
                    run.log_path = relative_log_path.as_posix()
        except Exception:
            pass
