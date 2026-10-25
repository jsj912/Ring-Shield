"""An instrumented copy of river 0.22's ADWIN (river/drift/adwin_c.pyx), for diagnosing R12.

Same buckets, compression, tick/clock gate and cut rule as the Cython original; the only addition
is a record of every step: whether ADWIN tested for change, and for each cut it evaluated the two
window sizes, the mean difference and the threshold epsilon. `assert_matches_river` replays a
series through both and checks width and detection agree at every step.

    epsilon = sqrt(2 m var_W delta') + (2/3) delta' m,
    m = 1/(n0 - L + 1) + 1/(n1 - L + 1),  delta' = ln(2 ln(width) / delta),  L = min_window_length.
"""
from __future__ import annotations

import math


class TracedADWIN:
    def __init__(self, delta=0.002, clock=32, max_buckets=5, min_window_length=5, grace_period=10):
        self.delta, self.clock, self.max_buckets = float(delta), int(clock), int(max_buckets)
        self.min_window_length, self.grace_period = int(min_window_length), int(grace_period)
        self.rows = [[]]            # rows[i] = [(total, variance), ...] buckets of size 2**i, newest first
        self.width, self.total, self.variance, self.tick = 0, 0.0, 0.0, 0
        self.drift_detected = False

    # --- river's _insert_element / _compress_buckets / _delete_element -------------------------------
    def _insert(self, value: float) -> None:
        self.rows[0].insert(0, (value, 0.0))
        self.width += 1
        if self.width > 1:
            prior = self.total / (self.width - 1)
            self.variance += (self.width - 1) * (value - prior) ** 2 / self.width
        self.total += value
        idx = 0
        while idx < len(self.rows) and len(self.rows[idx]) == self.max_buckets + 1:
            if idx + 1 == len(self.rows):
                self.rows.append([])
            n = 2 ** idx
            (t1, v1), (t2, v2) = self.rows[idx][-1], self.rows[idx][-2]   # the two oldest
            merged = (t1 + t2, v1 + v2 + n * n * (t1 / n - t2 / n) ** 2 / (2 * n))
            del self.rows[idx][-2:]
            self.rows[idx + 1].insert(0, merged)
            if len(self.rows[idx + 1]) <= self.max_buckets:
                break
            idx += 1

    def _delete_oldest(self) -> float:
        idx = len(self.rows) - 1
        n = 2 ** idx
        total, var = self.rows[idx].pop()
        self.width -= n
        self.total -= total
        mu, mu_w = total / n, self.total / self.width
        self.variance -= var + n * self.width * (mu - mu_w) ** 2 / (n + self.width)
        if not self.rows[idx]:
            self.rows.pop()
        return n

    def _epsilon(self, n0: float, n1: float) -> float:
        delta_prime = math.log(2 * math.log(self.width) / self.delta)
        m = 1 / (n0 - self.min_window_length + 1) + 1 / (n1 - self.min_window_length + 1)
        return math.sqrt(2 * m * (self.variance / self.width) * delta_prime) + 2 / 3 * delta_prime * m

    def cuts(self) -> list[dict]:
        """Every cut ADWIN would evaluate now, oldest bucket first, with n0, n1, |mean diff|, epsilon."""
        out, n0, u0, n1, u1 = [], 0.0, 0.0, float(self.width), self.total
        for idx in range(len(self.rows) - 1, -1, -1):
            for k, (total, _var) in enumerate(reversed(self.rows[idx])):
                n = 2 ** idx
                n0, n1, u0, u1 = n0 + n, n1 - n, u0 + total, u1 - total
                if idx == 0 and k == len(self.rows[0]) - 1:
                    return out
                eligible = n0 >= self.min_window_length and n1 >= self.min_window_length
                diff = u0 / n0 - u1 / n1
                eps = self._epsilon(n0, n1) if eligible else None
                out.append({"n0": int(n0), "n1": int(n1), "mean_diff": diff, "epsilon": eps,
                            "cut": bool(eligible and abs(diff) > eps)})
        return out

    def update(self, value: float) -> dict:
        """One step, as river's ADWIN.update; returns the trace record for it."""
        if self.drift_detected:     # river's wrapper starts a fresh window after a detection (adwin.py)
            self.__init__(self.delta, self.clock, self.max_buckets, self.min_window_length, self.grace_period)
        self._insert(float(value))
        self.tick += 1
        tested = self.tick % self.clock == 0 and self.width > self.grace_period
        considered = self.cuts()
        self.drift_detected = False
        record = {"tick": self.tick, "width_before": self.width, "tested": tested, "cuts": considered}
        if tested:
            reduce = True
            while reduce:
                reduce = False
                for cut in self.cuts():
                    if cut["cut"]:
                        self._delete_oldest()
                        self.drift_detected = reduce = True
                        break
        record.update({"width_after": self.width, "drift_detected": self.drift_detected})
        best = max((c for c in considered if c["epsilon"] is not None),
                   key=lambda c: abs(c["mean_diff"]) / c["epsilon"], default=None)
        record["best_cut"] = best
        return record


def assert_matches_river(values, **params) -> None:
    """Replay `values` through river's ADWIN and the traced copy; width and detection must agree."""
    from river.drift import ADWIN
    river_adwin, traced = ADWIN(**params), TracedADWIN(**params)
    for step, value in enumerate(values, start=1):
        river_adwin.update(value)
        record = traced.update(value)
        if (int(river_adwin.width) != record["width_after"]
                or bool(river_adwin.drift_detected) != record["drift_detected"]):
            raise AssertionError(f"step {step}: river width {river_adwin.width} drift {river_adwin.drift_detected}, "
                                 f"traced width {record['width_after']} drift {record['drift_detected']}")
