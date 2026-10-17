"""Shared provenance, input checks and report writers for L6 experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]


class ExperimentInputError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ExperimentInputError(f"required experiment input is unavailable: {path}") from exc
    return digest.hexdigest()


def git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_run_manifest(output_dir: Path, *, experiment: str, config: dict,
                       inputs: Iterable[Path], details: dict) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_file = config.get("_path")
    input_hashes = {}
    for value in sorted(set(Path(item).resolve() for item in inputs)):
        try:
            label = value.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            label = value.name
        input_hashes[label] = sha256_file(value)
    config_label = None
    if config_file:
        try:
            config_label = Path(config_file).resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            config_label = Path(config_file).name
    manifest = {
        "experiment": experiment,
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "git_commit": git_commit(),
        "config_path": config_label,
        "config_sha256": sha256_file(Path(config_file)) if config_file else None,
        "input_sha256": input_hashes,
        **details,
    }
    destination = output_dir / "run.json"
    destination.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return destination


def write_csv_and_markdown(rows: list[dict], csv_path: Path, markdown_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(csv_path, index=False)
    columns = list(frame.columns)
    markdown_lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        markdown_lines.append("| " + " | ".join(str(value) for value in row) + " |")
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
