"""Record sha256 / size / row count of the raw Kaggle files and formatted_transactions.csv.

    python scripts/data_manifest.py            # writes docs/data_manifest.json
    python scripts/data_manifest.py --check    # exits 1 if any file differs from the manifest

edge_id is defined by the row order of formatted_transactions.csv, so its hash is pinned
here. Since Step 3a scripts/format_kaggle_files.py sorts with kind="mergesort" (stable), so
the numbering is reproducible from HI-Small_Trans.csv alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from contract.make_scored_edges import git_commit, load_paths  # noqa: E402

FILES = ["HI-Small_Trans.csv", "HI-Small_accounts.csv", "HI-Small_Patterns.txt", "formatted_transactions.csv"]
MANIFEST = REPO_ROOT / "docs" / "data_manifest.json"


def describe(path: Path) -> dict:
    h = hashlib.sha256()
    n_lines = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
            n_lines += chunk.count(b"\n")
    return {"sha256": h.hexdigest(), "bytes": path.stat().st_size, "lines": n_lines}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    raw_dir = load_paths()["raw_dir"]
    current = {name: describe(raw_dir / name) for name in FILES}

    if args.check:
        recorded = json.loads(MANIFEST.read_text())["files"]
        bad = [n for n in FILES if recorded.get(n, {}).get("sha256") != current[n]["sha256"]]
        for n in bad:
            print(f"MISMATCH {n}: manifest {recorded.get(n, {}).get('sha256')} != disk {current[n]['sha256']}")
        print("data manifest OK" if not bad else f"{len(bad)} file(s) differ")
        sys.exit(1 if bad else 0)

    manifest = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "raw_dir": str(raw_dir.relative_to(REPO_ROOT)),
        "note": ("formatted_transactions.csv row order defines edge_id. Since Step 3a it is produced with "
                 "sort_values(kind='mergesort') (stable), so the numbering is reproducible from the raw "
                 "file; the pre-Step-3a (introsort) numbering is mapped by data/processed/edge_id_remap.parquet."),
        "files": current,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST}")
    for n, d in current.items():
        print(f"  {n:32s} {d['bytes']:>12,} B  {d['lines']:>10,} lines  {d['sha256'][:16]}…")


if __name__ == "__main__":
    main()
