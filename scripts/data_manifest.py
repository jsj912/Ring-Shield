"""Record sha256 / size / row count of the raw Kaggle files, formatted_transactions.csv and
the derived GFP feature parquets (current trailing set and the legacy forward-cycle set).

    python scripts/data_manifest.py            # writes docs/data_manifest.json
    python scripts/data_manifest.py --check    # exits 1 if any file differs from the manifest

edge_id is defined by the row order of formatted_transactions.csv, so its hash is pinned
here. Since Step 3a scripts/format_kaggle_files.py sorts with kind="mergesort" (stable), so
the numbering is reproducible from HI-Small_Trans.csv alone. Since Step 3b-z the GFP
parquets are pinned too: data/processed/amlworld_gfp_features_<split>.parquet (trailing
closes_cycle, look-back 14 d; schema metadata key "gfp" holds the parameters) and
amlworld_gfp_features_<split>_legacy_forwardcycle.parquet (the pre-3b-z files, forward
temporal_cycle with unbounded look-ahead; kept for the legacyfeat rows of
results/tables/r1_edge_metrics.csv). A derived file that is missing is recorded as null.
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
DERIVED = [f"amlworld_gfp_features_{s}{tag}.parquet" for tag in ("", "_legacy_forwardcycle")
           for s in ("train", "val", "test")]
# Step V3.1: the larger releases, recorded under a separate key and hashed only on demand --
# HI-Large_Trans.csv alone is ~17 GB, and the routine `--check` used by the table audit must stay
# cheap. A default run preserves whatever is already recorded here.
DATASET_FILES = {ds: [f"{ds}_Trans.csv", f"{ds}_Patterns.txt"] for ds in ("HI-Medium", "HI-Large")}
# Step V3.2: the artefacts an isolated preprocessing run produces, hashed alongside the raw files
# so the HI-Medium split is pinned the way HI-Small's is. Paths are repo-relative.
DATASET_DERIVED = {
    "HI-Medium": ["data/raw_hi_medium/formatted_transactions.csv"]
    + [f"data/processed_hi_medium/{n}" for n in
       ("account_bank.parquet", "amlworld_train.parquet", "amlworld_val.parquet",
        "amlworld_test.parquet", "amlworld_ring_ground_truth.parquet",
        "amlworld_gfp_features_train.parquet", "amlworld_gfp_features_val.parquet",
        "amlworld_gfp_features_test.parquet")],
}
MANIFEST = REPO_ROOT / "docs" / "data_manifest.json"


def describe(path: Path) -> dict:
    h = hashlib.sha256()
    n_lines = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
            n_lines += chunk.count(b"\n")
    return {"sha256": h.hexdigest(), "bytes": path.stat().st_size, "lines": n_lines}


def describe_parquet(path: Path) -> dict | None:
    """sha256 / bytes / rows / columns / gfp schema metadata of a derived parquet (None if absent)."""
    if not path.exists():
        return None
    import pyarrow.parquet as pq
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    pf = pq.ParquetFile(path)
    meta = pf.schema_arrow.metadata or {}
    gfp = json.loads(meta[b"gfp"]) if b"gfp" in meta else None
    return {"sha256": h.hexdigest(), "bytes": path.stat().st_size, "rows": pf.metadata.num_rows,
            "columns": pf.schema_arrow.names, "gfp_metadata": gfp}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--datasets", nargs="*", default=None, metavar="NAME",
                    help="also hash the larger AMLworld releases (default: all of "
                         f"{', '.join(DATASET_FILES)}). ~19 GB of reading.")
    args = ap.parse_args(argv)
    paths = load_paths()
    raw_dir, processed_dir = paths["raw_dir"], paths["processed_dir"]
    current = {name: describe(raw_dir / name) for name in FILES}
    derived = {name: describe_parquet(processed_dir / name) for name in DERIVED}
    want = (list(DATASET_FILES) if args.datasets == [] else args.datasets) or []
    datasets = {}
    for ds in want:
        if ds not in DATASET_FILES:
            raise SystemExit(f"unknown dataset {ds!r}; known: {', '.join(DATASET_FILES)}")
        for name in DATASET_FILES[ds]:
            p = raw_dir / name
            if not p.exists():
                print(f"  {name}: MISSING", file=sys.stderr)
                continue
            print(f"  hashing {name} ({p.stat().st_size / 1e9:.1f} GB)…", flush=True)
            datasets[name] = describe(p)
        for rel in DATASET_DERIVED.get(ds, []):
            p = REPO_ROOT / rel
            if not p.exists():
                print(f"  {rel}: MISSING (not yet produced)", file=sys.stderr)
                continue
            print(f"  hashing {rel} ({p.stat().st_size / 1e9:.2f} GB)…", flush=True)
            d = describe(p)
            if p.suffix == ".parquet":
                import pyarrow.parquet as pq
                d = {"sha256": d["sha256"], "bytes": d["bytes"],
                     "rows": pq.ParquetFile(p).metadata.num_rows}
            datasets[rel] = d

    if args.check:
        rec = json.loads(MANIFEST.read_text())
        recorded, rec_derived = rec["files"], rec.get("derived", {})
        bad = [n for n in FILES if recorded.get(n, {}).get("sha256") != current[n]["sha256"]]
        bad += [n for n in DERIVED if (rec_derived.get(n) or {}).get("sha256") != (derived[n] or {}).get("sha256")]
        rec_ds = rec.get("datasets", {})
        bad += [n for n in datasets if (rec_ds.get(n) or {}).get("sha256") != datasets[n]["sha256"]]
        for n in bad:
            print(f"MISMATCH {n}")
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
        "derived_note": ("Step 3b-z (2026-09-17): temporal_cycle / cycle_length regenerated with the trailing "
                         "closes_cycle definition (graph/motif_features.py; backward BFS, edges < t only, <= 5 hops, "
                         "look-back 14 d). The eight count features are bit-identical to the legacy files. The "
                         "*_legacy_forwardcycle.parquet files are the pre-3b-z outputs (forward BFS over edges after "
                         "t, unbounded look-ahead, static SCC gate) and back the legacyfeat rows of "
                         "results/tables/r1_edge_metrics.csv; they are not used for new training."),
        "derived": derived,
    }
    # a default run must not drop a `datasets` block someone paid 19 GB of reading for
    prev = json.loads(MANIFEST.read_text()).get("datasets", {}) if MANIFEST.exists() else {}
    merged = {**prev, **datasets}
    if merged:
        manifest["datasets_note"] = (
            "Step V3.1 (2026-09-30): the larger AMLworld releases, hashed with "
            "`python scripts/data_manifest.py --datasets`. Not verified by a plain `--check`, "
            "which stays cheap for the table audit; pass --datasets to check them too.")
        manifest["datasets"] = merged
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST}")
    for n, d in current.items():
        print(f"  {n:32s} {d['bytes']:>12,} B  {d['lines']:>10,} lines  {d['sha256'][:16]}…")
    for n, d in derived.items():
        if d is None:
            print(f"  {n:58s} MISSING")
        else:
            print(f"  {n:58s} {d['bytes']:>12,} B  {d['rows']:>10,} rows   {d['sha256'][:16]}…")
    for n, d in datasets.items():
        # raw CSV / text entries carry `lines`, derived parquet entries carry `rows`
        unit = "lines" if "lines" in d else "rows"
        print(f"  {n:46s} {d['bytes']:>14,} B  {d.get('lines', d.get('rows', 0)):>12,} "
              f"{unit}  {d['sha256'][:16]}…")


if __name__ == "__main__":
    main()
