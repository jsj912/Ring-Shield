from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.retrain import RetrainError, verify_holdout


PRODUCTION_DIR = PLATFORM_ROOT / "holdout" / "production"
PRODUCTION_MANIFEST = PRODUCTION_DIR / "holdout_manifest.json"
PRODUCTION_CHECKSUM = PRODUCTION_DIR / "holdout_manifest.sha256"
FIXTURE_DIR = PLATFORM_ROOT / "tests" / "fixtures"
EXPECTED_FILE_SHA256 = "32f7443a4dc5c6d3658f668bc269620cb2a284bb94d3e0197a651232cb267686"
EXPECTED_CONTENT_SHA256 = "a1e1c13c5588407ac31fb1f6b13745b25bec94bbc699a699a8e678ead4795f06"
CONTENT_KEYS = (
    "rule", "window", "split", "days", "t_min", "t_max", "scope",
    "min_visible_members", "truth_ring_ids",
)


def _write_copy(tmp_path, manifest: dict, *, refresh_content_hash: bool = False):
    copy_dir = tmp_path / "production"
    copy_dir.mkdir()
    if refresh_content_hash:
        body = {key: manifest[key] for key in CONTENT_KEYS if key in manifest}
        manifest["content_sha256"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_path = copy_dir / PRODUCTION_MANIFEST.name
    checksum_path = copy_dir / PRODUCTION_CHECKSUM.name
    manifest_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    checksum_path.write_text(f"{digest}  {manifest_path.name}\n", encoding="ascii")
    return manifest_path, checksum_path


def test_production_manifest_matches_pinned_hashes_and_verifies():
    manifest_bytes = PRODUCTION_MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)

    assert hashlib.sha256(manifest_bytes).hexdigest() == EXPECTED_FILE_SHA256
    assert manifest["content_sha256"] == EXPECTED_CONTENT_SHA256
    assert len(manifest["truth_ring_ids"]) == 114
    assert len(set(manifest["truth_ring_ids"])) == 114
    assert manifest["days"] == [6, 7]
    assert len(verify_holdout(PRODUCTION_MANIFEST, PRODUCTION_CHECKSUM)["truth_ring_ids"]) == 114


def test_production_manifest_byte_change_fails_file_hash(tmp_path):
    changed = tmp_path / "holdout_manifest.json"
    changed.write_bytes(PRODUCTION_MANIFEST.read_bytes() + b" ")

    with pytest.raises(RetrainError, match="SHA-256 does not match"):
        verify_holdout(changed, PRODUCTION_CHECKSUM)


def test_production_manifest_id_change_fails_content_hash(tmp_path):
    manifest = json.loads(PRODUCTION_MANIFEST.read_text(encoding="utf-8"))
    manifest["truth_ring_ids"][0] = 28
    manifest_path, checksum_path = _write_copy(tmp_path, manifest)

    with pytest.raises(RetrainError, match="content_sha256 does not match"):
        verify_holdout(manifest_path, checksum_path)


def test_production_manifest_missing_hashed_key_is_refused(tmp_path):
    manifest = json.loads(PRODUCTION_MANIFEST.read_text(encoding="utf-8"))
    del manifest["scope"]
    manifest_path, checksum_path = _write_copy(tmp_path, manifest)

    with pytest.raises(RetrainError, match="missing content-hash fields: scope"):
        verify_holdout(manifest_path, checksum_path)


def test_production_manifest_requires_114_unique_ids(tmp_path):
    manifest = json.loads(PRODUCTION_MANIFEST.read_text(encoding="utf-8"))
    manifest["truth_ring_ids"].pop()
    manifest["n"] = len(manifest["truth_ring_ids"])
    manifest_path, checksum_path = _write_copy(tmp_path, manifest, refresh_content_hash=True)

    with pytest.raises(RetrainError, match="exactly 114 truth ring IDs"):
        verify_holdout(manifest_path, checksum_path)


def test_production_manifest_requires_days_six_and_seven(tmp_path):
    manifest = json.loads(PRODUCTION_MANIFEST.read_text(encoding="utf-8"))
    manifest["days"] = [6, 8]
    manifest_path, checksum_path = _write_copy(tmp_path, manifest, refresh_content_hash=True)

    with pytest.raises(RetrainError, match=r"days must be \[6, 7\]"):
        verify_holdout(manifest_path, checksum_path)


def test_three_ring_fixture_still_verifies_unchanged():
    manifest = FIXTURE_DIR / "holdout_manifest_fixture.json"
    checksum = FIXTURE_DIR / "holdout_manifest_fixture.sha256"

    assert verify_holdout(manifest, checksum)["truth_ring_ids"] == [12, 38, 104]
