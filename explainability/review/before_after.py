"""Week 8: the 30 reviewed narratives before and after the review fixes.

    python -m explainability.review.before_after        # -> results/xai/review/before_after.md

"Before" is the narrative exactly as the reviewers read it, taken from the packet they were sent (packet_R1.md; all
three packets hold the same 30 narratives). "After" is the same ring's narrative in the current explanation files.
For each item the page lists which review fixes changed it and the reviewers' verdict on the old text (flagged by
the majority on q4 "misleading" or q1 "implausible").
"""
from __future__ import annotations

import json
import re
import sys

import pandas as pd
import pyarrow.parquet as pq

from explainability.contract_io import load_config, repo_path
from explainability.narrative import SHAPE_SENTENCES

FIXES = {"A1 shape stated as a guess": lambda c: "type_guess" in c or "type_guess_random" in c,
         "scope words": lambda c: bool(SHAPE_SENTENCES & set(c)) or "closure" in c,
         "self-payment not cited": lambda c: "self_one" in c or "self_many" in c}


def reviewed_narratives(review_dir) -> dict:
    text = (review_dir / "packet_R1.md").read_text(encoding="utf-8")
    out = {}
    for sec in re.split(r"^## ", text, flags=re.M)[1:]:
        item = sec.split("\n", 1)[0].strip()
        m = re.search(r"^> (.*)$", sec, flags=re.M)
        if m:
            out[item] = m.group(1)
    return out


def build(cfg: dict) -> tuple[str, list[dict]]:
    d = repo_path(cfg["review"]["out_dir"])
    key = pd.read_parquet(d / "answer_key.parquet").sort_values("item_id")
    before = reviewed_narratives(d)
    review = pd.read_csv(d / "review.csv")
    m = int(cfg["review"]["rules"]["flag_majority"])
    q4 = review.groupby("item_id")["q4_misleading"].sum() >= m
    q1 = (1 - review.set_index("item_id")["q1_topology_plausible"]).groupby(level=0).sum() >= m
    rows, lines = [], ["# The 30 reviewed narratives, before and after the review fixes (Week 8)", "",
                       "Before = exactly as the reviewers read it (their packet). After = the current explanation "
                       f"(explainer {cfg['explainer_version']}). Weights, evidence ranking and fidelity are unchanged; "
                       "only the wording moved.", ""]
    for it in key.itertuples(index=False):
        tbl = pq.read_table(repo_path(cfg["output_dir"]) / cfg["explanations_name_week3"].format(seed=int(it.seed)),
                            columns=["ring_id", "narrative", "evidence_summary"]).to_pylist()
        row = [r for r in tbl if r["ring_id"] == it.ring_id][0]
        clauses = json.loads(row["evidence_summary"])["clauses"]
        fixes = [name for name, hit in FIXES.items() if hit(clauses)]
        verdict = [x for x, flag in (("misleading", bool(q4[it.item_id])), ("shape implausible", bool(q1[it.item_id])))
                   if flag]
        rows.append({"item_id": it.item_id, "changed": before[it.item_id] != row["narrative"], "fixes": fixes,
                     "flagged": verdict})
        lines += [f"## {it.item_id}", "",
                  f"Reviewers (majority): {', '.join(verdict) if verdict else 'not flagged'}. "
                  f"Fixes applied: {', '.join(fixes) if fixes else 'none'}.", "",
                  f"**Before:** {before[it.item_id]}", "", f"**After:** {row['narrative']}", ""]
    n_changed = sum(r["changed"] for r in rows)
    flagged = [r for r in rows if r["flagged"]]
    per_fix = "; ".join(f"{name}: {sum(name in r['fixes'] for r in flagged)} of {len(flagged)} flagged items, "
                        f"{sum(name in r['fixes'] for r in rows)} of {len(rows)} overall" for name in FIXES)
    lines[4:4] = [f"{n_changed} of {len(rows)} narratives changed (the scope words reach almost every narrative). "
                  f"Per fix — {per_fix}.", ""]
    return "\n".join(lines), rows


def main(argv=None) -> int:
    cfg = load_config()
    text, rows = build(cfg)
    out = repo_path(cfg["review"]["out_dir"]) / "before_after.md"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{sum(r['changed'] for r in rows)}/{len(rows)} changed -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
