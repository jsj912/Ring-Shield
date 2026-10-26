"""FINDINGS C11: how much of a global seed quantile does each test day take? (label-free)

    python evaluation/c11_seed_share.py
    python evaluation/c11_seed_share.py --run-dir experiments/R1_gine_causal --seeds 1 2 3 4 5

For each seed: the top 0.1 % of `score_raw` over the whole test split (strict cut, as the shipped
seed rule), and each day's share of those seeds beside its share of the split's edges. Uses only
`score_raw` and `timestamp`; no label is read. Days are `timestamp // 86400` on the loader basis.

The volume ratios C11 quotes (spike day against the weekday median of earlier days) come from
`results/tables/v3_day_profile_HI-{Small,Medium,Large}.csv`, which `--profiles` prints.

Prints only; writes nothing.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SPIKE_DAY = {"HI-Small": 8, "HI-Medium": 15, "HI-Large": 95}


def seed_share(scores: pd.DataFrame, frac: float = 0.001) -> pd.DataFrame:
    """Per test day: share of the split's edges and of the global top-`frac` seeds."""
    day = (scores["timestamp"] // 86400).astype(int)
    k = math.ceil(len(scores) * frac)
    seeds = scores["score_raw"] > scores["score_raw"].nlargest(k).min()
    return pd.DataFrame({"edge_share": day.value_counts(normalize=True),
                         "seed_share": day[seeds].value_counts(normalize=True)}).fillna(0.0).sort_index()


def volume_ratio(profile: pd.DataFrame, spike_day: int) -> float:
    """Spike-day edges over the median of the weekdays from day 1 up to the spike day."""
    dow = pd.to_datetime(profile["date"]).dt.dayofweek
    norm = profile.loc[(profile["day"] >= 1) & (profile["day"] < spike_day) & (dow < 5), "edges"].median()
    return float(profile.loc[profile["day"] == spike_day, "edges"].iloc[0] / norm)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", default="experiments/R1_gine_causal")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--profiles", action="store_true", help="also print the C11 volume ratios")
    args = ap.parse_args()

    if args.profiles:
        for ds, d in SPIKE_DAY.items():
            prof = pd.read_csv(REPO / f"results/tables/v3_day_profile_{ds}.csv")
            print(f"{ds} day {d}: {volume_ratio(prof, d):.3f}x the weekday median")
    for s in args.seeds:
        sh = seed_share(pd.read_parquet(REPO / args.run_dir / f"scores_test_seed{s}.parquet",
                                        columns=["timestamp", "score_raw"]))
        print(f"seed {s}:", ", ".join(f"day {d} {r.seed_share:.1%} of seeds / {r.edge_share:.1%} of edges"
                                      for d, r in sh.head(2).iterrows()))


if __name__ == "__main__":
    main()
