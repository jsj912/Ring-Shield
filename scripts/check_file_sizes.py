"""Fail when a change adds or grows a file over the size limit.

    python scripts/check_file_sizes.py origin/main        # compare HEAD with a base ref

Large artefacts belong outside git (README, "Data"). The five GFP-XGBoost models were committed
before this check and stay: L4 reads them (explainability/config.yaml), and regenerating them would
mean retraining. They are allowed as they are, not to grow.
"""
from __future__ import annotations

import subprocess
import sys

LIMIT = 5 * 1024 * 1024
ALLOWED = {f"experiments/R2_b0/gfpxgb_scores/model_seed{s}.json" for s in range(1, 6)}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def sizes(ref: str) -> dict[str, int]:
    """Every blob's size at `ref`, in one call."""
    out = {}
    for entry in git("ls-tree", "-r", "-l", "-z", ref).split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            kind, size = meta.split()[1], meta.split()[3]
            if kind == "blob":
                out[path] = int(size)
    return out


def main(argv: list[str]) -> int:
    base = argv[0] if argv else "origin/main"
    merge_base = git("merge-base", base, "HEAD").strip()
    changed = [line.split("\t", 1)[1] for line in git("diff", "--name-status", "--no-renames",
                                                      "--diff-filter=AM", merge_base, "HEAD").splitlines()]
    head, before = sizes("HEAD"), sizes(merge_base)
    failures = []
    for path in changed:
        new = head.get(path)
        if new is None or new <= LIMIT:
            continue
        old = before.get(path)
        if path in ALLOWED and (old is None or new <= old):
            continue
        failures.append(f"{path}: {new / 2**20:.1f} MB" + ("" if old is None else f" (was {old / 2**20:.1f} MB)"))
    if failures:
        print(f"Files over {LIMIT // 2**20} MB added or grown since {base}:")
        print("\n".join(f"  {line}" for line in failures))
        return 1
    print(f"OK: no file over {LIMIT // 2**20} MB added or grown since {base} ({len(changed)} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
