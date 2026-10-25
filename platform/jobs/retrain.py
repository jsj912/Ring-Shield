"""Tenant-scoped, holdout-gated retraining orchestration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select, text, update

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
PRODUCTION_HOLDOUT_PATH = (PLATFORM_ROOT / "holdout" / "production" / "holdout_manifest.json").resolve()
PRODUCTION_HOLDOUT_CONTENT_KEYS = (
    "rule", "window", "split", "days", "t_min", "t_max", "scope",
    "min_visible_members", "truth_ring_ids",
)
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters import research_cli  # noqa: E402
from audit import add_audit_event  # noqa: E402
from db.models import ModelVersion, RetrainRun, Ring, Transaction, Verdict  # noqa: E402
from db.session import db_session, get_engine, loader_db_session  # noqa: E402
from jobs.training_evaluation import (TrainingEvaluationError, make_evaluation_manifest,
                                     training_ring_ids_from_version,
                                     validate_labels_disjoint_from_holdout)  # noqa: E402
from jobs.promotion_artifacts import write_manifest  # noqa: E402
from settings import configured_path, load_l6_config, load_platform_config  # noqa: E402


class RetrainError(RuntimeError):
    """A configured or validated L6 retraining stage could not proceed."""


def _is_production_holdout(manifest: dict[str, Any], manifest_path: Path) -> bool:
    return (Path(manifest_path).resolve() == PRODUCTION_HOLDOUT_PATH
            or "content_sha256" in manifest)


def _verify_production_holdout_content(manifest: dict[str, Any], manifest_path: Path) -> None:
    """Verify the research lead's canonical content digest and fixed window contract."""
    if not _is_production_holdout(manifest, manifest_path):
        return

    missing = [key for key in PRODUCTION_HOLDOUT_CONTENT_KEYS if key not in manifest]
    if missing:
        raise RetrainError(
            f"production holdout is missing content-hash fields: {', '.join(missing)}"
        )
    if len(manifest["truth_ring_ids"]) != 114:
        raise RetrainError("production holdout must contain exactly 114 truth ring IDs")
    if manifest["days"] != [6, 7]:
        raise RetrainError("production holdout days must be [6, 7]")

    body = {key: manifest[key] for key in PRODUCTION_HOLDOUT_CONTENT_KEYS}
    actual_content_sha256 = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if manifest.get("content_sha256") != actual_content_sha256:
        raise RetrainError("production holdout content_sha256 does not match its canonical content")


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
    is_production = isinstance(manifest, dict) and _is_production_holdout(manifest, manifest_path)
    ids = manifest.get("truth_ring_ids") if isinstance(manifest, dict) else None
    if not isinstance(ids, list) or not ids:
        raise RetrainError("holdout manifest requires non-empty truth_ring_ids and matching n")
    if (not is_production or "n" in manifest) and manifest.get("n") != len(ids):
        raise RetrainError("holdout manifest requires non-empty truth_ring_ids and matching n")
    try:
        numeric_ids = [int(item) for item in ids]
    except (TypeError, ValueError) as exc:
        raise RetrainError("holdout truth_ring_ids must be integer IDs") from exc
    if numeric_ids != sorted(set(numeric_ids)):
        raise RetrainError("holdout truth_ring_ids must be unique and sorted")
    if "pred_ring_ids" in manifest:
        raise RetrainError("holdout manifest must contain truth IDs only")
    _verify_production_holdout_content(manifest, manifest_path)
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
    key = "ringshield-l6-retrain"
    with get_engine().connect() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
                           {"tenant_id": str(int(tenant_id))})
        connection.execute(text("SELECT pg_advisory_lock(hashtextextended(:key || ':' || :tenant_id, 0))"),
                           {"key": key, "tenant_id": int(tenant_id)})
        connection.commit()
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key || ':' || :tenant_id, 0))"),
                               {"key": key, "tenant_id": int(tenant_id)})
            connection.commit()
            connection.execute(text("SELECT set_config('app.tenant_id', '', false)"))
            connection.commit()


@contextmanager
def _run_claim(tenant_id: int, run_id: str):
    """One worker per retrain run: a non-blocking session advisory lock on the run id, held for the
    whole job. Yields False when another worker already holds it (the API's or the experiment's
    caller and the worker supervisor can both start a worker for the same running row)."""
    key = f"ringshield-l6-retrain-run:{run_id}"
    with get_engine().connect() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
                           {"tenant_id": str(int(tenant_id))})
        claimed = bool(connection.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
                                          {"key": key}).scalar())
        connection.commit()
        try:
            yield claimed
        finally:
            if claimed:
                connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})
                connection.commit()
            connection.execute(text("SELECT set_config('app.tenant_id', '', false)"))
            connection.commit()


def _run_is_open(tenant_id: int, run_id: str) -> bool:
    """A run another worker has not finished: status running and no finished_at."""
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        row = session.execute(select(RetrainRun.status, RetrainRun.finished_at).where(
            RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
        )).one_or_none()
    return row is not None and row.status == "running" and row.finished_at is None


def _set_run_state(tenant_id: int, run_id: str, *, status: str,
                   model_version_id: int | None = None, finished: bool = False) -> None:
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        values: dict[str, Any] = {"status": status}
        if status == "running":
            values["started_at"] = datetime.now(timezone.utc)
        if model_version_id is not None or status in {"succeeded", "failed"}:
            values["model_version_id"] = model_version_id
        if finished:
            values["finished_at"] = datetime.now(timezone.utc)
        result = session.execute(update(RetrainRun).where(
            RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
        ).values(**values))
        if result.rowcount != 1:
            raise RetrainError("retrain run disappeared or tenant scope changed")
        if status in {"running", "succeeded", "failed"}:
            add_audit_event(session, tenant_id=tenant_id, actor="retrain_worker",
                            action="retrain.started" if status == "running" else f"retrain.{status}",
                            entity_type="retrain_run",
                            entity_id=run_id, details={"status": status,
                                                       "model_version_id": model_version_id})


def _promoted_version(session, tenant_id: int, component: str) -> ModelVersion | None:
    return session.scalar(select(ModelVersion).where(
        ModelVersion.tenant_id == tenant_id,
        ModelVersion.component == component,
        ModelVersion.promoted.is_(True),
    ).with_for_update())


def _insert_model_version(*, tenant_id: int, component: str, version_tag: str,
                          trained_at: datetime, label_count: int, f1: float | None,
                          promoted: bool, gate_reason: str | None, artifact_path: Path | None,
                          retrain_run_id: str | None = None) -> int:
    with loader_db_session(tenant_id=tenant_id) as session:
        old = _promoted_version(session, tenant_id, component)
        if promoted and old is not None:
            session.execute(update(ModelVersion).where(
                ModelVersion.tenant_id == tenant_id,
                ModelVersion.model_version_id == old.model_version_id,
            ).values(promoted=False))
            add_audit_event(session, tenant_id=tenant_id, actor="retrain_worker",
                            action="model_version.demoted", entity_type="model_version",
                            entity_id=old.model_version_id,
                            details={"component": component, "promoted": False})
        version = ModelVersion(
            tenant_id=tenant_id, component=component, version_tag=version_tag,
            trained_at=trained_at, train_label_count=label_count,
            holdout_ring_f1=f1, promoted=promoted, gate_reason=gate_reason,
            artifact_path=str(artifact_path) if artifact_path is not None else None,
            retrain_run_id=retrain_run_id,
        )
        session.add(version)
        session.flush()
        add_audit_event(session, tenant_id=tenant_id, actor="loader",
                        action="model_version.recorded", entity_type="model_version",
                        entity_id=version.model_version_id,
                        details={"component": component, "version_tag": version_tag,
                                 "promoted": promoted, "gate_reason": gate_reason})
        return int(version.model_version_id)


def _evaluate(cli, *, model_dir: Path, paths: dict[str, Path], l6: dict[str, Any],
              run_dir: Path, label: str,
              excluded_ring_ids: set[str] | None = None) -> float:
    output = run_dir / f"{label}-rings.parquet"
    run_result = cli.run_rings(
        scores=paths["val_scored_edges"], model_dir=model_dir, aggregator="full",
        gfp=paths["val_gfp"], embeddings=paths["val_embeddings"], out=output,
    )
    holdout_path = paths["holdout_manifest"]
    excluded = excluded_ring_ids or set()
    if excluded:
        manifest = verify_holdout(paths["holdout_manifest"], paths["holdout_sha256_file"])
        try:
            predicted_ids = pq.read_table(run_result.rings_path, columns=["ring_id"])[
                "ring_id"
            ].to_pylist()
        except (OSError, ValueError, KeyError) as exc:
            raise RetrainError("evaluation rings are missing their ring_id column") from exc
        filtered = make_evaluation_manifest(
            truth_ring_ids=manifest["truth_ring_ids"],
            predicted_ring_ids=predicted_ids,
            excluded_ring_ids=excluded,
        )
        if not filtered["truth_ring_ids"]:
            raise RetrainError("no holdout truth rings remain after excluding training labels")
        holdout_path = run_dir / f"{label}-evaluation-holdout.json"
        holdout_path.write_text(json.dumps(filtered, sort_keys=True), encoding="utf-8")
    evaluation = cli.eval_rings(
        rings=run_result.rings_path, truth=paths["truth_parquet"],
        holdout=holdout_path,
        window=l6["retrain"]["eval_window"], scope=l6["retrain"]["eval_scope"],
        out=run_dir / f"{label}-metrics.json",
    )
    return evaluation.ring_f1


def _validation_edge_ids(path: Path) -> set[int]:
    """Read only edge IDs from the validated day-6/7 scored-edge parquet."""
    try:
        parquet = pq.ParquetFile(path)
        if "edge_id" not in parquet.schema_arrow.names:
            raise RetrainError("validation scored edges are missing edge_id")
        edge_ids: set[int] = set()
        for batch in parquet.iter_batches(columns=["edge_id"], batch_size=100_000):
            edge_ids.update(map(int, batch.column(0).to_pylist()))
        return edge_ids
    except (OSError, ValueError) as exc:
        raise RetrainError("could not read validation scored-edge IDs") from exc


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


def label_context(config: dict[str, Any], l6: dict[str, Any], tenant_id: int) -> dict[str, Path]:
    """The scores and rings the tenant's verdicts were made on, plus that split's GFP and the
    base seed's embeddings: the real `ringshield train` rebuilds features in this context.
    Templates (l6.retrain.label_scores_template / label_rings_template) take {tenant_id},
    {model_id} and {seed}; unset templates are left to the research CLI to report."""
    retrain = l6["retrain"]
    fields = {"tenant_id": int(tenant_id), "model_id": config.get("active_model_id"),
              "seed": config.get("active_seed")}
    context: dict[str, Path] = {}
    for key, template_key in (("scores", "label_scores_template"), ("rings", "label_rings_template")):
        template = retrain.get(template_key)
        if template:
            path = Path(str(template).format(**fields))
            context[key] = path if path.is_absolute() else REPO_ROOT / path
            if not context[key].is_file():
                raise RetrainError(f"l6.retrain.{template_key} resolves to a missing file: {context[key]}")
    if context:
        for key in ("gfp", "embeddings"):
            if config.get(key):
                context[key] = configured_path(config, key)
    return context


def base_trained_at(base_dir: Path) -> datetime:
    """When the shipped base model was trained: its model.json's write time. Verdicts are "new"
    when made after this, so stamping the baseline row with the time the job first runs would
    discard every verdict recorded before a tenant's first retrain."""
    model_json = base_dir / "model.json"
    if not model_json.is_file():
        raise RetrainError(f"base model is missing model.json: {base_dir}")
    return datetime.fromtimestamp(model_json.stat().st_mtime, tz=timezone.utc)


def _ensure_baseline(*, tenant_id: int, component: str, base_dir: Path,
                     l6: dict[str, Any], paths: dict[str, Path], run_dir: Path,
                     cli, log_path: Path) -> ModelVersion:
    with loader_db_session(tenant_id=tenant_id) as session:
        promoted = _promoted_version(session, tenant_id, component)
        if promoted is not None:
            return promoted
    score = _evaluate(cli, model_dir=base_dir, paths=paths, l6=l6,
                      run_dir=run_dir, label=f"{component}-baseline")
    version_id = _insert_model_version(
        tenant_id=tenant_id, component=component, version_tag="base",
        trained_at=base_trained_at(base_dir), label_count=0, f1=score,
        promoted=True, gate_reason="initial holdout baseline", artifact_path=base_dir,
    )
    _write_log(log_path, f"{component}: recorded initial base holdout baseline ({score:.4f})")
    with loader_db_session(tenant_id=tenant_id) as session:
        return session.scalar(select(ModelVersion).where(
            ModelVersion.tenant_id == tenant_id,
            ModelVersion.model_version_id == version_id,
        ))


def _run_ring_refresh_process(*, tenant_id: int, model_version_id: int, run_id: str,
                              log_path: Path) -> Path:
    """Run refresh after the promotion transaction has committed, in a child process."""
    command = [
        sys.executable, "-m", "jobs.refresh_rings",
        str(int(tenant_id)), str(int(model_version_id)), run_id,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=PLATFORM_ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        _write_log(log_path, f"ring refresh failed to start: {type(exc).__name__}: {exc}")
        raise RetrainError(f"ring refresh failed to start: {exc}") from exc
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        reason = error or output or f"worker exited with code {result.returncode}"
        _write_log(log_path, f"ring refresh failed: {reason}")
        raise RetrainError(f"ring refresh failed: {reason}")
    try:
        # The worker's result is its last line: the research CLI it runs shares its stdout.
        response = json.loads(output.splitlines()[-1] if output else "")
        if not isinstance(response, dict):
            raise TypeError("refresh response must be an object")
        rings_path = Path(response["rings_path"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RetrainError("ring refresh returned no valid rings_path") from exc
    if (response.get("tenant_id") != int(tenant_id)
            or response.get("model_version_id") != int(model_version_id)
            or not rings_path.is_file()):
        raise RetrainError("ring refresh output does not match the promoted version or is missing")
    _write_log(log_path, f"ring refresh completed: {rings_path.name}")
    return rings_path.resolve()


def run_retrain_job(tenant_id: int, run_id: str, *, cli=research_cli,
                    min_new_labels: int | None = None) -> bool:
    """One gated retrain, run by whichever worker claims the run first. Returns False, without
    writing any state, when another worker holds the run or it has already finished.
    `min_new_labels` overrides l6.retrain.min_new_labels (R11 retrains once, on however many
    verdicts day 8 produced)."""
    with _run_claim(tenant_id, run_id) as claimed:
        if not claimed or not _run_is_open(tenant_id, run_id):
            _write_log(_run_log_path(run_id), f"tenant {tenant_id}: run {run_id} "
                       + ("is held by another worker" if not claimed else "is already finished")
                       + "; this worker exits without changing it")
            return False
        _run_claimed_retrain_job(tenant_id, run_id, cli=cli, min_new_labels=min_new_labels)
        return True


def _run_claimed_retrain_job(tenant_id: int, run_id: str, *, cli=research_cli,
                             min_new_labels: int | None = None) -> None:
    log_path = _run_log_path(run_id)
    relative_log_path = log_path.relative_to(REPO_ROOT)
    _write_log(log_path, f"tenant {tenant_id}: retrain run started")
    last_promoted_version_id = None
    promotions: list[dict[str, Any]] = []
    run_dir = log_path.parent / run_id
    try:
        config = load_platform_config()
        l6 = load_l6_config(config)
        paths = _validate_inputs(l6, config)
        holdout = verify_holdout(paths["holdout_manifest"], paths["holdout_sha256_file"])
        validation_edge_ids = _validation_edge_ids(paths["val_scored_edges"])
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"tenant_id": int(tenant_id), "run_id": run_id,
                    "status": "running", "promotions": promotions}
        write_manifest(run_dir, manifest)
        _set_run_state(tenant_id, run_id, status="running")
        with _tenant_lock(tenant_id):
            components = l6["retrain"]["components"]
            for component in components:
                base_dir = paths["base_model_dir"]
                with loader_db_session(tenant_id=tenant_id) as session:
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
                try:
                    validate_labels_disjoint_from_holdout(
                        labels, holdout_ring_ids=holdout["truth_ring_ids"],
                        validation_edge_ids=validation_edge_ids,
                    )
                except TrainingEvaluationError as exc:
                    raise RetrainError(str(exc)) from exc
                minimum = int(l6["retrain"]["min_new_labels"] if min_new_labels is None else min_new_labels)
                if len(labels) < minimum:
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
                                          base_dir=base_dir, out_dir=output_model,
                                          context=label_context(config, l6, tenant_id))
                trained_at = datetime.now(timezone.utc)
                model_version = train_result.version.get("version", "unknown")
                version_tag = f"v{model_version}-{run_id[:8]}"
                should_evaluate, disabled_reason = candidate_evaluation_policy(train_result.retrained)
                if not should_evaluate:
                    assert disabled_reason is not None
                    _insert_model_version(
                        tenant_id=tenant_id, component=component, version_tag=version_tag,
                        trained_at=trained_at, label_count=len(labels), f1=None,
                        promoted=False, gate_reason=disabled_reason, artifact_path=output_model,
                        retrain_run_id=run_id,
                    )
                    _write_log(log_path, f"{component}: candidate not promoted: {disabled_reason}")
                    continue
                try:
                    training_ring_ids = training_ring_ids_from_version(train_result.version)
                except TrainingEvaluationError as exc:
                    raise RetrainError(str(exc)) from exc
                candidate_f1 = _evaluate(
                    cli, model_dir=output_model, paths=paths, l6=l6,
                    run_dir=run_dir, label=f"{component}-candidate",
                    excluded_ring_ids=training_ring_ids,
                )
                promote, reason = should_promote(
                    candidate_f1, float(current.holdout_ring_f1), float(l6["retrain"]["epsilon"]),
                )
                candidate_version_id = _insert_model_version(
                    tenant_id=tenant_id, component=component, version_tag=version_tag,
                    trained_at=trained_at, label_count=len(labels), f1=candidate_f1,
                    promoted=promote, gate_reason=reason, artifact_path=output_model,
                    retrain_run_id=run_id,
                )
                _write_log(log_path, f"{component}: {reason}")
                if promote:
                    last_promoted_version_id = candidate_version_id
                    refresh_run_id = f"{run_id}-v{candidate_version_id}"
                    refreshed_rings = _run_ring_refresh_process(
                        tenant_id=tenant_id,
                        model_version_id=candidate_version_id,
                        run_id=refresh_run_id,
                        log_path=log_path,
                    )
                    promotions.append({
                        "component": component,
                        "model_version_id": candidate_version_id,
                        "version_tag": version_tag,
                        "training_ring_ids": sorted(training_ring_ids),
                        "rings_path": str(refreshed_rings),
                    })
                    manifest["promotions"] = promotions
                    write_manifest(run_dir, manifest)
            manifest["status"] = "succeeded"
            write_manifest(run_dir, manifest)
            _set_run_state(tenant_id, run_id, status="succeeded",
                           model_version_id=last_promoted_version_id, finished=True)
    except Exception as exc:
        manifest = {"tenant_id": int(tenant_id), "run_id": run_id,
                    "status": "failed", "promotions": promotions,
                    "failure": f"{type(exc).__name__}: {exc}"}
        if run_dir.is_dir():
            write_manifest(run_dir, manifest)
        _write_log(log_path, f"run failed: {type(exc).__name__}: {exc}")
        try:
            _set_run_state(tenant_id, run_id, status="failed",
                           model_version_id=last_promoted_version_id, finished=True)
        except Exception as state_error:
            _write_log(log_path, f"could not persist failed state: {type(state_error).__name__}")
    finally:
        # DB stores a repository-relative path; the API never returns machine paths.
        try:
            with db_session(tenant_id=tenant_id, role="supervisor") as session:
                session.execute(update(RetrainRun).where(
                    RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
                ).values(log_path=relative_log_path.as_posix()))
        except Exception:
            pass
