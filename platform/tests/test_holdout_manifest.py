from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from scripts.make_holdout_manifest import make_manifest


def test_fixture_manifest_sha256_matches_committed_sidecar():
    fixture = PLATFORM_ROOT / "tests/fixtures/holdout_manifest_fixture.json"
    checksum = PLATFORM_ROOT / "tests/fixtures/holdout_manifest_fixture.sha256"
    expected = checksum.read_text(encoding="ascii").split()[0]

    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected
    manifest = json.loads(fixture.read_text(encoding="utf-8"))
    assert manifest["truth_ring_ids"] == sorted(manifest["truth_ring_ids"])
    assert manifest["n"] == len(manifest["truth_ring_ids"])


def test_holdout_builder_refuses_overwrite(tmp_path):
    truth = tmp_path / "truth.parquet"
    truth.write_bytes(b"fixture")
    manifest = tmp_path / "holdout_manifest.json"
    checksum = tmp_path / "holdout_manifest.sha256"
    manifest.write_text("already committed")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        make_manifest(truth, manifest, checksum)


def test_missing_truth_does_not_create_a_manifest(tmp_path):
    manifest = tmp_path / "holdout_manifest.json"
    checksum = tmp_path / "holdout_manifest.sha256"

    with pytest.raises(FileNotFoundError, match="truth parquet not found"):
        make_manifest(tmp_path / "missing_truth.parquet", manifest, checksum)

    assert not manifest.exists()
    assert not checksum.exists()
