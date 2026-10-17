"""Build the validation holdout ID manifest once; never overwrite it."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))

from adapters.ground_truth import load_val_truth  # noqa: E402


def make_manifest(truth_path: Path, manifest_path: Path, sha256_path: Path) -> dict:
    if manifest_path.exists() or sha256_path.exists():
        raise FileExistsError("holdout manifest or checksum already exists; refusing to overwrite")
    if not truth_path.is_file():
        raise FileNotFoundError(f"validation truth parquet not found: {truth_path}")
    truth = load_val_truth(truth_path)
    ring_ids = sorted((int(value) for value in truth), key=int)
    manifest = {
        "truth_ring_ids": ring_ids,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": truth_path.name,
        "n": len(ring_ids),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    manifest_path.write_bytes(payload)
    sha256_path.write_text(f"{digest}  {manifest_path.name}\n", encoding="ascii")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=PLATFORM_ROOT / "holdout/holdout_manifest.json")
    parser.add_argument("--sha256", type=Path, default=PLATFORM_ROOT / "holdout/holdout_manifest.sha256")
    args = parser.parse_args(argv)
    try:
        result = make_manifest(args.truth, args.manifest, args.sha256)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"created": True, "n": result["n"], "manifest": args.manifest.name}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
