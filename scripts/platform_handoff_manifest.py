"""Record path / size / sha256 of every research artefact the platform reads, from platform/config.yaml.

    python scripts/platform_handoff_manifest.py            # writes docs/HANDOFF_PLATFORM.md
    python scripts/platform_handoff_manifest.py --check    # exits 1 if a file is missing or differs

The files themselves are gitignored (data/, experiments/, models/artifacts/, contract/out/); this
manifest is what pins them. Inputs covered: the active model and its scored edges (test and val),
GFP features, embeddings, account map, ring ground truth, the R12 held-out model, and the R10
tenant-visible score files for the registered tenants (docs/TENANT_SIZES.md) and all five seeds.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "HANDOFF_PLATFORM.md"
SEEDS = (1, 2, 3, 4, 5)
# docs/TENANT_SIZES.md: primary 1, 20, 11, 118, 12; robustness 70, 12, 11, 1, 10.
R10_TENANTS = (1, 10, 11, 12, 20, 70, 118)
ROW = re.compile(r"^\| `(?P<path>[^`]+)` \| (?P<size>[\d,]+) \| `(?P<sha>[0-9a-f]{64})` \|")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artefacts(config: dict) -> list[tuple[str, str]]:
    """(group, repo-relative path) for every file the platform reads."""
    retrain, r10, r12 = config["l6"]["retrain"], config["r10"], config["r12"]
    model_id, seed = config["active_model_id"], config["active_seed"]
    rows = [("active pair", config["scored_edges"]),
            ("active pair", config["scored_edges"] + ".log.json"),
            ("active pair", retrain["val_scored_edges"]),
            ("features", config["gfp"]),
            ("features", retrain["val_gfp"]),
            ("features", config["embeddings"]),
            ("features", retrain["val_embeddings"]),
            ("ground truth", retrain["truth_parquet"]),
            ("ground truth", config["account_map"])]
    for model_dir, group in ((config["model_dir"], "active model"), (r12["model_dir"], "R12 held-out model")):
        rows += [(group, p.relative_to(REPO_ROOT).as_posix())
                 for p in sorted((REPO_ROOT / model_dir).rglob("*")) if p.is_file()]
    for s in SEEDS:
        pooled = r10["pooled_scores_template"].format(model_id=model_id, seed=s)
        rows += [("R10 pooled scores", pooled), ("R10 pooled scores", pooled + ".log.json")]
    for tenant in R10_TENANTS:
        for s in SEEDS:
            visible = r10["tenant_visible_scores_template"].format(tenant_id=tenant, model_id=model_id, seed=s)
            rows += [("R10 tenant-visible scores", visible), ("R10 tenant-visible scores", visible + ".log.json")]
    assert seed in SEEDS
    return rows


def render(rows: list[tuple[str, str]]) -> str:
    lines = [
        "# Platform hand-off: research artefacts",
        "",
        "Every research file the platform reads, as configured in `platform/config.yaml`. The files are",
        "gitignored; this table pins them. Regenerate with `python scripts/platform_handoff_manifest.py`,",
        "verify a machine with `--check`.",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "## Decisions behind the config",
        "",
        "- **R10 score source: `tenant_visible`** (option b, fixed pooled cutoff), as registered in",
        "  `docs/TENANT_SIZES.md`. Pooled scores are the secondary row: `--tenant-score-source pooled`.",
        "  Primary tenants 1, 20, 11, 118, 12; robustness set 70, 12, 11, 1, 10 (reported as degenerate:",
        "  bank 70 has no visible ring laundering edge). Files from `scripts/tenant_visible_scores.py`.",
        "- **R12 held-out pattern: CYCLE**, model `models/artifacts/l3only_cycle_full_seed1` =",
        "  `experiments/R7_l3only_cycle/runs/full/seed1` through `python -m ringshield export-model`.",
        "  BIPARTITE was the v1.0 default; holding it out removes no training rows.",
        "- **Retraining inputs:** validation GFP, seed-1 validation embeddings and the ring ground truth.",
        "  The frozen holdout is `platform/holdout/production/holdout_manifest.json` (chosen 2026-10-17).",
        "",
    ]
    group = None
    for name, rel in rows:
        if name != group:
            lines += ["", f"## {name}", "", "| path | bytes | sha256 |", "|---|---:|---|"]
            group = name
        path = REPO_ROOT / rel
        if path.is_file():
            lines.append(f"| `{rel}` | {path.stat().st_size:,} | `{sha256(path)}` |")
        else:
            lines.append(f"| `{rel}` | missing | — |")
    return "\n".join(lines) + "\n"


def check() -> int:
    bad = 0
    for line in OUT.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if not match:
            continue
        path = REPO_ROOT / match["path"]
        if not path.is_file():
            print(f"MISSING {match['path']}")
            bad += 1
        elif sha256(path) != match["sha"]:
            print(f"DIFFERS {match['path']}")
            bad += 1
    print("OK" if not bad else f"{bad} file(s) missing or different")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    if ap.parse_args(argv).check:
        return check()
    config = yaml.safe_load((REPO_ROOT / "platform" / "config.yaml").read_text(encoding="utf-8"))
    text = render(artefacts(config))
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}; missing: {text.count('| missing |')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
