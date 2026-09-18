"""Evaluation windows (configs/eval_window.yaml): day index <-> loader-basis seconds, masks.

    W = load_windows()                      # {"primary": Window(...), "tail": ..., "whole": ..., "val": ...}
    m = W["primary"].mask(timestamps)      # boolean numpy mask
    lo, hi = W["primary"].bounds           # inclusive seconds in the loader basis
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_WINDOW_YAML = REPO_ROOT / "configs" / "eval_window.yaml"


@dataclass(frozen=True)
class Window:
    name: str
    split: str
    day_lo: int
    day_hi: int
    day_zero: int = 10
    seconds_per_day: int = 86400

    @property
    def bounds(self) -> tuple[int, int]:
        """Inclusive [t_lo, t_hi] in the loader basis covering days day_lo..day_hi."""
        return (self.day_zero + self.day_lo * self.seconds_per_day,
                self.day_zero + (self.day_hi + 1) * self.seconds_per_day - 1)

    def mask(self, timestamps) -> np.ndarray:
        t = np.asarray(timestamps, dtype=np.int64)
        lo, hi = self.bounds
        return (t >= lo) & (t <= hi)

    def days_of(self, timestamps) -> np.ndarray:
        return (np.asarray(timestamps, dtype=np.int64) - self.day_zero) // self.seconds_per_day

    def as_dict(self) -> dict:
        return {"name": self.name, "split": self.split, "days": [self.day_lo, self.day_hi], "bounds": list(self.bounds)}


def load_windows(path: Path = EVAL_WINDOW_YAML) -> dict[str, Window]:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    z, spd = int(cfg["day_zero_timestamp"]), int(cfg["seconds_per_day"])
    out = {}
    for name in cfg.get("report_order", list(cfg["windows"])):
        w = cfg["windows"][name]
        lo, hi = (int(x) for x in w["days"])
        assert lo <= hi, (name, w)
        out[name] = Window(name, w["split"], lo, hi, z, spd)
    return out


def test_windows(path: Path = EVAL_WINDOW_YAML) -> dict[str, Window]:
    """The windows evaluated on the test split, in report order."""
    return {k: w for k, w in load_windows(path).items() if w.split == "test"}
