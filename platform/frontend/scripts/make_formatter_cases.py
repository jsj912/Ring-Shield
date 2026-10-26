"""Write src/lib/formatters.python-cases.json: the Python formatters' output for a fixed set of values.

formatters.test.ts checks that the TypeScript port prints every one of them identically.

    python platform/frontend/scripts/make_formatter_cases.py
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys

FRONTEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRONTEND.parent / "dashboard"))
from formatters import fmt_amount, fmt_interval, fmt_percent, fmt_recall, fmt_seconds, fmt_weight  # noqa: E402

random.seed(7)
values = [0.2395, 0.4255, 0.125, 0.375, 2.5, 0.0, -0.0, -0.004, 0.005, 0.015, 0.025, 1234567.895, 0.9886,
          0.98851, 1e-7, 0.5, 1.5, 999.995, 0.7280946512826214, 0.6883, 0.0353, 0.3647, 172 / 174]
values += [round(random.uniform(-1e6, 1e6), random.randint(0, 6)) for _ in range(150)]
values += [random.random() for _ in range(150)]

cases = [{"v": v, "amount": fmt_amount(v), "percent": fmt_percent(v), "weight": fmt_weight(v),
          "recall": fmt_recall(v), "seconds": fmt_seconds(v)} for v in values]
cases.append({"interval": fmt_interval(0.3588, 0.2395, 0.5), "v": None})
(FRONTEND / "src" / "lib" / "formatters.python-cases.json").write_text(json.dumps(cases), encoding="utf-8")
