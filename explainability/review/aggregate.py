"""Week 6 / 7 (XR-29): score the three filled answer sheets of the explanation review (spec 7).

    python -m explainability.review.aggregate       # reads results/xai/review/answers_R*.csv + answer_key.parquet

1. Check every sheet: the same 30 items as the answer key, every answer 0 or 1, nothing blank.
2. Per question: the share of "yes", the share of items on which all three reviewers agree, and Fleiss' kappa --
   agreement beyond what three people answering at random with the same yes-rates would reach (1 = perfect,
   0 = chance level, < 0 = worse than chance).
3. Reveal the truth: per item, whether the narrated shape is the true pattern type, and whether each reviewer's
   "plausible" (q1) judgement matched that -- 1 when they called a correct shape plausible or a wrong one implausible.
3b. The analysis plan (results/xai/review/analysis_plan.md, written before scoring; rules in config review.rules):
   flagged items, yes-rates by narrative feature and by true type, and the fix triggers.
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


FEATURES = ("shape_sentence", "self_payment_top3", "partial_currency", "bank_list", "undetermined_named",
            "narrated_shape_correct")
PROBLEM_WHEN = {"q1_topology_plausible": 0, "q2_named_accounts_matter": 0, "q3_evidence_enough": 0, "q4_misleading": 1}


def kappa_band(kappa: float | None, bands) -> str | None:
    """Landis & Koch label: below 0 'poor', else the first band whose upper bound is >= kappa."""
    if kappa is None:
        return None
    if kappa < 0:
        return bands[0][1]
    for upper, label in bands[1:]:
        if kappa <= upper:
            return label
    return bands[-1][1]


def item_features(cfg: dict, key: pd.DataFrame) -> pd.DataFrame:
    """The analysis plan's narrative features per item, read from each item's own explanation (never the answers)."""
    import pyarrow.parquet as pq
    from explainability.evaluate import SHAPE_CLAUSES
    rows = {}
    for s in sorted(key["seed"].unique()):
        tbl = pq.read_table(repo_path(cfg["output_dir"]) / cfg["explanations_name_week3"].format(seed=int(s)),
                            columns=["ring_id", "evidence_summary"]).to_pylist()
        rows.update({(int(s), r["ring_id"]): json.loads(r["evidence_summary"]) for r in tbl})
    out = []
    for it in key.itertuples(index=False):
        es = rows[(int(it.seed), it.ring_id)]
        cl, v = set(es["clauses"]), es["values"]
        out.append({"item_id": it.item_id,
                    "shape_sentence": int(bool(cl & set(SHAPE_CLAUSES))),
                    "self_payment_top3": int(any(e["from_id"] == e["to_id"] for e in v["top_edges"])),
                    "partial_currency": int("money_partial" in cl),
                    "bank_list": int("banks" in cl),
                    "undetermined_named": int(bool(cl & {"undet_one", "undet_many"})),
                    "narrated_shape_correct": int(it.narrated_type == it.true_pattern_type)})
    return pd.DataFrame(out).set_index("item_id")


def flags_breakdowns_triggers(review: pd.DataFrame, feats: pd.DataFrame, key: pd.DataFrame, rules: dict,
                              n_reviewers: int) -> dict:
    """The analysis plan, section 3: flagged items, yes-rates by feature and by true type, and the fix triggers."""
    problem = {q: review.assign(p=(review[q] == bad).astype(int)).pivot(index="item_id", columns="reviewer", values="p")
               .sum(axis=1) for q, bad in PROBLEM_WHEN.items()}
    flagged = {q: sorted(problem[q].index[problem[q] >= int(rules["flag_majority"])]) for q in QCOLS}
    yes = {q: review.pivot(index="item_id", columns="reviewer", values=q).mean(axis=1) for q in QCOLS}
    by_feature = {}
    for f in FEATURES:
        ids = feats.index[feats[f] == 1]
        by_feature[f] = {"n_items": int(len(ids)),
                         **{q: {"yes_rate": float(yes[q].loc[ids].mean()) if len(ids) else None,
                                "n_flagged": int(len(set(flagged[q]) & set(ids)))} for q in QCOLS}}
    tt = key.set_index("item_id")["true_pattern_type"]
    by_type = {t: {"n_items": int((tt == t).sum()), **{q: float(yes[q].loc[tt.index[tt == t]].mean()) for q in QCOLS}}
               for t in sorted(tt.unique())}
    triggers = []
    low = float(rules["low_yes_rate"])
    for q in QCOLS[:3]:
        if float(yes[q].mean()) < low:
            triggers.append({"rule": "q1-q3 overall", "question": q, "yes_rate": float(yes[q].mean()),
                             "items": flagged[q]})
        for f in FEATURES:
            b = by_feature[f]
            if b["n_items"] >= int(rules["min_group_items"]) and b[q]["yes_rate"] is not None and b[q]["yes_rate"] < low:
                triggers.append({"rule": "q1-q3 within a feature", "question": q, "feature": f,
                                 "n_items": b["n_items"], "yes_rate": b[q]["yes_rate"],
                                 "items": sorted(set(flagged[q]) & set(feats.index[feats[f] == 1]))})
    q4 = QCOLS[3]
    for f in FEATURES:
        b = by_feature[f]
        n_flag, n = b[q4]["n_flagged"], b["n_items"]
        if n_flag >= int(rules["q4_pattern_min_items"]) or (
                n and n_flag >= int(rules["q4_share_min_items"]) and n_flag / n >= float(rules["q4_pattern_min_share"])):
            triggers.append({"rule": "q4 within a feature", "question": q4, "feature": f, "n_items": n,
                             "n_flagged": n_flag, "items": sorted(set(flagged[q4]) & set(feats.index[feats[f] == 1]))})
    comments = {i: [c for c in g["comment"].tolist() if isinstance(c, str) and c.strip()]
                for i, g in review.groupby("item_id")}
    return {"flagged_items": flagged, "by_feature": by_feature, "by_true_type": by_type, "triggers": triggers,
            "comments": {i: c for i, c in sorted(comments.items()) if c}, "rules": rules,
            "item_features": {f: int(feats[f].sum()) for f in FEATURES}}


def aggregate(review_dir: Path, reviewers: list[str], cfg: dict | None = None) -> tuple[pd.DataFrame, dict]:
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
    cfg = cfg or load_config()
    for q in QCOLS:
        per_q[q]["kappa_band"] = kappa_band(per_q[q]["fleiss_kappa"], cfg["review"]["rules"]["kappa_bands"])
    feats = item_features(cfg, key)
    summary["analysis"] = flags_breakdowns_triggers(review, feats, key, cfg["review"]["rules"], len(reviewers))
    summary["exploratory"] = exploratory(review, feats, cfg["review"]["rules"])
    summary["analysis_plan"] = "results/xai/review/analysis_plan.md"
    return review, summary


def exploratory(review: pd.DataFrame, feats: pd.DataFrame, rules: dict) -> dict:
    """NOT pre-registered: how the q1 / q4 flags split by shape sentence x bank list, the overlap behind the
    pre-registered triggers. Reported separately and labelled as exploratory."""
    m = int(rules["flag_majority"])
    q4 = review.groupby("item_id")["q4_misleading"].sum() >= m
    q1 = (1 - review.set_index("item_id")["q1_topology_plausible"]).groupby(level=0).sum() >= m
    f = feats.assign(q4_flag=q4, q1_flag=q1)
    cells = []
    for (s, b), g in f.groupby(["shape_sentence", "bank_list"]):
        cells.append({"shape_sentence": int(s), "bank_list": int(b), "n_items": int(len(g)),
                      "q4_flagged": int(g["q4_flag"].sum()), "q1_flagged": int(g["q1_flag"].sum()),
                      "narrated_shape_correct": int(g["narrated_shape_correct"].sum())})
    return {"label": "exploratory -- not in the analysis plan", "cells": cells}


def summary_markdown(s: dict) -> str:
    """review_summary.md: a plain-language reading of review_summary.json. Every number comes from `s`."""
    pq_ = s["per_question"]
    a = s["analysis"]
    names = {"q1_topology_plausible": "q1  the stated shape is plausible",
             "q2_named_accounts_matter": "q2  the named accounts are the ones that matter",
             "q3_evidence_enough": "q3  the evidence is enough to start an investigation",
             "q4_misleading": "q4  something in the sentence is misleading (1 = a problem)"}

    def k(v):
        return "n/a (every answer the same)" if v["fleiss_kappa"] is None else f"{v['fleiss_kappa']:.3f} ({v['kappa_band']})"
    lines = ["# Review of 30 explanations — summary", "",
             "A structured check by the three team members (spec section 7), **not an analyst study**. Reviewer R1 also "
             "built the explanations. The rules for reading the answers were written and committed before two of the "
             f"three sheets came back (`{s['analysis_plan']}`).", "",
             f"{s['n_items']} items, reviewers {', '.join(s['reviewers'])}, four yes/no questions each.", "",
             "## 1. Answers and agreement", "",
             "| question | yes-rate | all three agree | Fleiss' κ |", "|---|---|---|---|"]
    for q, v in pq_.items():
        lines.append(f"| {names[q]} | {v['yes_rate']:.2f} | {v['all_agree_rate']:.0%} | {k(v)} |")
    lines += ["", "Fleiss' κ is agreement beyond chance (Landis & Koch bands). Where every reviewer gave the same answer "
              "to every item, κ is undefined.", "",
              "## 2. What triggered a fix (rules from the analysis plan)", ""]
    if not a["triggers"]:
        lines.append("No rule fired.")
    for t in a["triggers"]:
        what = (f"yes-rate {t['yes_rate']:.2f}" if "yes_rate" in t else f"{t['n_flagged']} of {t['n_items']} items flagged")
        lines.append(f"- **{t['rule']}** — {t['question']}" + (f", feature `{t['feature']}`" if t.get("feature") else "")
                     + f": {what}; items {', '.join(t['items'])}")
    lines += ["", "## 3. Breakdown by narrative feature", "",
              "| feature | items | q1 yes | q2 yes | q3 yes | q4 yes (misleading) | q4 flagged |", "|---|---|---|---|---|---|---|"]
    for f, b in a["by_feature"].items():
        if b["n_items"]:
            r = [b[q]["yes_rate"] for q in pq_]
            lines.append(f"| `{f}` | {b['n_items']} | {r[0]:.2f} | {r[1]:.2f} | {r[2]:.2f} | {r[3]:.2f} | "
                         f"{b['q4_misleading']['n_flagged']} |")
    ex = s.get("exploratory")
    if ex:
        lines += ["", "## 4. Exploratory (not in the analysis plan): shape sentence × bank list", "",
                  "| shape sentence | bank list | items | flagged misleading (q4) | flagged implausible (q1) | narrated shape correct |",
                  "|---|---|---|---|---|---|"]
        for c in ex["cells"]:
            lines.append(f"| {'yes' if c['shape_sentence'] else 'no'} | {'yes' if c['bank_list'] else 'no'} | "
                         f"{c['n_items']} | {c['q4_flagged']} | {c['q1_flagged']} | {c['narrated_shape_correct']} |")
    rv = s["reveal"]
    lines += ["", "## 5. The reveal", "",
              f"- The narrated shape was the true pattern type for **{rv['narrated_shape_correct_rate']:.0%}** of the 30 items.",
              f"- Reviewers' \"plausible\" answer matched that (plausible when right, implausible when wrong) "
              f"**{rv['reviewer_q1_matches_truth_rate']:.0%}** of the time; the majority answer **{rv['majority_q1_matches_truth_rate']:.0%}**.",
              "", "| true type | items | narrated shape correct |", "|---|---|---|"]
    for t, v in rv["by_true_type"].items():
        lines.append(f"| {t} | {v['n']} | {v['narrated_correct']:.0%} |")
    n_comments = sum(len(c) for c in a["comments"].values())
    lines += ["", f"Reviewer comments: {n_comments}.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=cfg["review"]["out_dir"])
    a = ap.parse_args(argv)
    d = repo_path(a.dir)
    review, summary = aggregate(d, list(cfg["review"]["reviewers"]), cfg)
    review.to_csv(d / "review.csv", index=False, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    stored = json.loads(json.dumps(summary, sort_keys=True))           # render exactly what review_summary.json holds
    (d / "review_summary.md").write_text(summary_markdown(stored), encoding="utf-8", newline="\n")
    (d / "review_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                           newline="\n")
    for q, v in summary["per_question"].items():
        k = "n/a" if v["fleiss_kappa"] is None else f"{v['fleiss_kappa']:.3f}"
        print(f"{q:26s} yes {v['yes_rate']:.2f}  all agree {v['all_agree_rate']:.2f}  Fleiss kappa {k}")
    for t in summary["analysis"]["triggers"]:
        print(f"TRIGGER {t['rule']}: {t['question']} {t.get('feature', '')} items {t['items']}")
    print(f"reveal: {summary['reveal']['narrated_shape_correct_rate']:.2f} of narrated shapes correct; reviewers' "
          f"plausibility matched the truth {summary['reveal']['reviewer_q1_matches_truth_rate']:.2f}")
    print(f"-> {d / 'review.csv'}, {d / 'review_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
