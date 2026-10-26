"""Shrink the PNGs under docs/screenshots/ in place (palette quantisation, then optimise).

    python scripts/compress_screenshots.py               # .venv312 has Pillow

UI screenshots are flat colour, so a 256-colour palette is visually lossless for them. A file is
rewritten only when the result is smaller. Prints each file's size and the folder total.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
TARGET = 400 * 1024


def compress(path: Path) -> tuple[int, int]:
    before = path.stat().st_size
    with Image.open(path) as im:
        im.load()
        rgb = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    best = None
    for colors in (256, 128):
        buf = io.BytesIO()
        rgb.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE) \
           .save(buf, format="PNG", optimize=True)
        best = buf.getvalue()
        if len(best) <= TARGET:
            break
    if best is not None and len(best) < before:
        path.write_bytes(best)
    return before, path.stat().st_size


def main() -> int:
    total = 0
    for path in sorted(ROOT.rglob("*.png")):
        before, after = compress(path)
        total += after
        flag = "" if after <= TARGET else "  (over 400 KB)"
        print(f"{path.relative_to(ROOT)}: {before // 1024} KB -> {after // 1024} KB{flag}")
    print(f"docs/screenshots total: {total / 2**20:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
