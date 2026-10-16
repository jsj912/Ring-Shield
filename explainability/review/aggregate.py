"""Week 6 / 7 (XR-29): score the three filled answer sheets of the explanation review (spec 7).

    python -m explainability.review.aggregate       # reads results/xai/review/answers_R*.csv + answer_key.parquet

1. Check every sheet: the same 30 items as the answer key, every answer 0 or 1, nothing blank.
2. Per question: the share of "yes", the share of items on which all three reviewers agree, and Fleiss' kappa --
   agreement beyond what three people answering at random with the same yes-rates would reach (1 = perfect,
   0 = chance level, < 0 = worse than chance).
3. Reveal the truth: per item, whether the narrated shape is the true pattern type, and whether each reviewer's
   "plausible" (q1) judgement matched that -- 1 when they called a correct shape plausible or a wrong one implausible.
4. Write review.csv (one row per item and reviewer, reviewer ids anonymised, free-text comments kept) and
   review_summary.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from explainability.contract_io import load_config, repo_path
from explainability.review.sample import QUESTIONS

QCOLS = [q for q, _ in QUESTIONS]


def fleiss_kappa(counts) -> float | None:
    """Fleiss' kappa for an items x categories table of how many raters chose each category (every row sums to the
    same number of raters). None when every rating is in one category (agreement by chance is then 1)."""
    m = np.asarray(counts, dtype=float)
    n_items, n_raters = m.shape[0], m[0].sum()
    if n_items == 0 or not np.allclose(m.sum(axis=1), n_raters) or n_raters < 2:
        raise ValueError("every item needs the same number of raters (at least 2)")
    p_j = m.sum(axis=0) / (n_items * n_raters)
    p_i = (np.square(m).sum(axis=1) - n_raters) / (n_raters * (n_raters - 1))
    p_bar, p_e = p_i.mean(), float(np.square(p_j).sum())
    if np.isclose(p_e, 1.0):
        return None
    return float((p_bar - p_e) / (1 - p_e))


def read_sheet(path: Path, items: set[str]) -> pd.DataFrame:
    """One filled sheet; refuses missing items, unknown items, blanks and anything but 0 / 1."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in ["item_id", *QCOLS] if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    got = set(df["item_id"])
    if got != items or len(df) != len(items):
        raise ValueError(f"{path.name}: items differ from the answer key (missing {sorted(items - got)}, "
                         f"unknown {sorted(got - items)}, rows {len(df)})")
    bad = [(r.item_id, q, getattr(r, q)) for r in df.itertuples(index=False) for q in QCOLS
           if str(getattr(r, q)).strip() not in ("0", "1")]
    if bad:
        raise ValueError(f"{path.name}: answers must be 0 or 1; e.g. {bad[:3]}")
    for q in QCOLS:
        df[q] = df[q].str.strip().astype(int)
    if "comment" not in df.columns:
        df["comment"] = ""
    return df[["item_id", *QCOLS, "comment"]]


def aggregate(review_dir: Path, reviewers: list[str]) -> tuple[pd.DataFrame, dict]:
    key = pd.read_parquet(review_dir / "answer_key.parquet")
    items = set(key["item_id"])
    sheets = {r: read_sheet(review_dir / f"answers_{r}.csv", items) for r in reviewers}
    key["narrated_correct"] = (key["narrated_type"] == key["true_pattern_type"]).astype(int)
    rows = []
    for r, df in sheets.items():
        m = df.merge(key[["item_id", "true_pattern_type", "narrated_type", "narrated_correct"]], on="item_id")
        m["q1_matches_truth"] = (m["q1_topology_plausible"] == m["narrated_correct"]).astype(int)
        rows.append(m.assign(reviewer=r))
    review = pd.concat(rows, ignore_index=True)[["item_id", "reviewer", *QCOLS, "true_pattern_type", "narrated_type",
                                                 "narrated_correct", "q1_matches_truth", "comment"]]
    review = review.sort_values(["item_id", "reviewer"]).reset_index(drop=True)
    per_q = {}
    for q in QCOLS:
        wide = review.pivot(index="item_id", columns="reviewer", values=q)
        yes = wide.sum(axis=1).to_numpy()
        counts = np.column_stack([len(reviewers) - yes, yes])
        per_q[q] = {"yes_rate": float(wide.to_numpy().mean()),
                    "all_agree_rate": float(((yes == 0) | (yes == len(reviewers))).mean()),
                    "fleiss_kappa": fleiss_kappa(counts)}
    majority_plausible = (review.pivot(index="item_id", columns="reviewer", values=QCOLS[0]).sum(axis=1)
                          > len(reviewers) / 2).astype(int)
    k = key.set_index("item_id")
    summary = {
        "what": "XR-29 internal review of explanations (spec 7): a structured check by the three team members, "
                "not an analyst study",
        "n_items": int(len(key)), "reviewers": reviewers, "per_question": per_q,
        "reveal": {"narrated_shape_correct_rate": float(key["narrated_correct"].mean()),
                   "reviewer_q1_matches_truth_rate": float(review["q1_matches_truth"].mean()),
                   "majority_q1_matches_truth_rate": float((majority_plausible == k.loc[majority_plausible.index,
                                                                                       "narrated_correct"]).mean()),
                   "by_true_type": {t: {"n": int(len(g)), "narrated_correct": float(g["narrated_correct"].mean())}
                                    for t, g in key.groupby("true_pattern_type")}},
    }
    return review, summary


def main(argv=None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=cfg["review"]["out_dir"])
    a = ap.parse_args(argv)
    d = repo_path(a.dir)
    review, summary = aggregate(d, list(cfg["review"]["reviewers"]))
    review.to_csv(d / "review.csv", index=False, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    (d / "review_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                           newline="\n")
    for q, v in summary["per_question"].items():
        k = "n/a" if v["fleiss_kappa"] is None else f"{v['fleiss_kappa']:.3f}"
        print(f"{q:26s} yes {v['yes_rate']:.2f}  all agree {v['all_agree_rate']:.2f}  Fleiss kappa {k}")
    print(f"reveal: {summary['reveal']['narrated_shape_correct_rate']:.2f} of narrated shapes correct; reviewers' "
          f"plausibility matched the truth {summary['reveal']['reviewer_q1_matches_truth_rate']:.2f}")
    print(f"-> {d / 'review.csv'}, {d / 'review_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
