"""Week 6 (XR-29): choose the 30 review rings and write one packet + one blank answer sheet per reviewer.

    python -m explainability.review.sample          # -> results/xai/review/

Which rings (spec 7). Matched rings of the shipped detector on the primary window, pooled over the five detector
seeds, leaving out every truth ring the committed Week 3 PILOT file shows (its answer key is public on the branch the
reviewers pull, so it would give those answers away), ONE per truth ring (a truth ring matched in several seeds is picked once, its seed drawn at random). Stratified
by the TRUE pattern type: four per type where available, the remainder from the two most frequent types (by number of
distinct truth rings), taken in turn. Every draw uses one fixed random seed, so the sample is the same on every run.

What a reviewer sees (spec 7): the narrative, the top-5 evidence transactions and the account roles -- as the app
shows them -- and nothing that reveals the truth: no ring id, no seed, no true pattern type, no match score. Items are
numbered R-01..R-30 (the same item number for every reviewer); each reviewer gets the items in their own shuffled
order. The answer key (true types) is a separate file, opened only after all three sheets are in.

Files written:
    packet_R1.md / packet_R2.md / packet_R3.md       what each reviewer reads
    answers_R1.csv / answers_R2.csv / answers_R3.csv  the blank sheets they fill (0 / 1 per question)
    answer_key.parquet                                the truth, for aggregate.py -- a .parquet, so git never commits it
                                                      (the reviewers pull this branch); never send it to reviewers
    sample_manifest.json                              how the sample was drawn, and the SHA-256 of every file
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from explainability.contract_io import load_config, read_rings, read_scored_edges, repo_path
from explainability.match import match_in_window, matching_rule, window_from_config
from explainability.narrative import load_names

QUESTIONS = [
    ("q1_topology_plausible", "Is the stated topology (shape) plausible from the evidence shown?"),
    ("q2_named_accounts_matter", "Are the named accounts the ones that matter in the shown evidence?"),
    ("q3_evidence_enough", "Would the evidence transactions be enough to start an investigation?"),
    ("q4_misleading", "Is anything in the sentence misleading or unsupported by the evidence shown? (1 = yes)"),
]


def candidates(cfg: dict, seeds) -> pd.DataFrame:
    """Every matched ring-instance: seed, ring_id, truth_ring_id, true pattern type, Jaccard."""
    W = window_from_config(cfg)
    thr, scope = matching_rule(cfg)
    rows = []
    for s in seeds:
        se = read_scored_edges(cfg["inputs"]["scored_edges"].format(seed=s))
        rings = read_rings(cfg["inputs"]["rings"].format(seed=s), scored_edges=se)
        m = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=cfg["inputs"]["truth"]).matches
        rows.append(m.assign(seed=int(s)))
    return pd.concat(rows, ignore_index=True)[["seed", "ring_id", "truth_ring_id", "pattern_type", "jaccard"]]


def choose(cands: pd.DataFrame, *, n_items: int, per_type: int, n_most_frequent: int, rng_seed: int) -> pd.DataFrame:
    """The spec-7 rule. Returns the chosen ring-instances with a `stratum` column ('per_type' or 'remainder')."""
    rng = np.random.default_rng(rng_seed)
    one = []
    for tid, g in cands.sort_values(["truth_ring_id", "seed"]).groupby("truth_ring_id", sort=True):
        one.append(g.iloc[int(rng.integers(0, len(g)))])
    pool = pd.DataFrame(one).reset_index(drop=True)
    sizes = pool["pattern_type"].value_counts()
    types = sorted(sizes.index, key=lambda t: (-sizes[t], t))
    chosen, left = [], {}
    for t in sorted(types):
        g = pool[pool["pattern_type"] == t].sort_values("truth_ring_id")
        take = rng.permutation(len(g))
        k = min(per_type, len(g))
        chosen.append(g.iloc[take[:k]].assign(stratum="per_type"))
        left[t] = g.iloc[take[k:]]
    picked = pd.concat(chosen, ignore_index=True)
    if len(picked) > n_items:
        raise ValueError(f"{len(picked)} rings at {per_type} per type exceeds {n_items}; lower per_type")
    top = [t for t in types if len(left[t])][:n_most_frequent]
    extra, i = [], 0
    while len(picked) + len(extra) < n_items:
        if not any(len(left[t]) for t in top):
            raise ValueError("not enough matched truth rings in the most frequent types to reach the sample size")
        t = top[i % len(top)]
        if len(left[t]):
            extra.append(left[t].iloc[[0]].assign(stratum="remainder"))
            left[t] = left[t].iloc[1:]
        i += 1
    out = pd.concat([picked, *extra], ignore_index=True)
    order = rng.permutation(len(out))                         # item numbers R-01.. in a random order, not by type
    out = out.iloc[order].reset_index(drop=True)
    out["item_id"] = [f"R-{i + 1:02d}" for i in range(len(out))]
    return out


def _role_lines(account_weights: list[dict]) -> list[str]:
    order = ["source", "mule", "holder", "sink", "peripheral", "undetermined"]
    by = {}
    for a in sorted(account_weights, key=lambda a: (-a["w_account"], a["account_id"])):
        by.setdefault(a["role"], []).append(str(a["account_id"]))
    return [f"- **{r}** ({len(by[r])}): {', '.join(by[r])}" for r in order if r in by]


def item_markdown(item_id: str, row: dict, se: pd.DataFrame, names: dict, fx: dict, n_top: int) -> str:
    """One review item: narrative, top transactions, roles. Nothing that identifies the ring or its truth."""
    lines = [f"## {item_id}", "", f"> {row['narrative']}", "",
             f"**Top {n_top} evidence transactions** (strongest first):", "",
             "| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |",
             "|---|---|---|---|---|---|---|"]
    rates = fx["rate_to_ccy0"]
    for i, w in enumerate(row["edge_weights"][:n_top], start=1):
        e = se.loc[int(w["edge_id"])]
        cur = names["currency"].get(int(e.currency_received), str(e.currency_received))
        rate = rates.get(int(e.currency_received))
        usd = "n/a (no rate)" if rate is None else f"{float(e.amount_received) * float(rate):,.2f}"
        fb = names["bank"].get(int(e.from_bank), f"Bank {int(e.from_bank)}")
        tb = names["bank"].get(int(e.to_bank), f"Bank {int(e.to_bank)}")
        pf = names["payment_format"].get(int(e.payment_format), str(e.payment_format))
        lines.append(f"| {i} | {int(e.from_id)} → {int(e.to_id)} | {float(e.amount_received):,.2f} {cur} | {usd} | {pf} | "
                     f"{fb} → {tb} | {w['w_total']:.2f} |")
    lines += ["", f"**Account roles** ({len(row['account_weights'])} accounts, strongest first):", "",
              *_role_lines(row["account_weights"]), "",
              "Your answers for this item go in the row **" + item_id + "** of your answer sheet.", "", "---", ""]
    return "\n".join(lines)


def packet_header(reviewer: str, n_items: int) -> str:
    qs = "\n".join(f"{i}. **{name}** — {text}" for i, (name, text) in enumerate(QUESTIONS, start=1))
    return "\n".join([
        f"# RingShield explanation review — reviewer {reviewer}", "",
        f"{n_items} suspected laundering rings, one per section. For each, read the narrative, the top evidence "
        "transactions and the account roles, then answer four questions with **1 (yes)** or **0 (no)** in your "
        f"answer sheet (`answers_{reviewer}.csv`, one row per item):", "", qs, "",
        "Judge only from what is shown here; do not look anything up in other files. "
        "Your items are in your own order; the item number (R-01 …) is what links a section to its row.", "", "---", ""])


def write_packets(cfg: dict, chosen: pd.DataFrame, out_dir: Path) -> dict:
    rc = cfg["review"]
    names = load_names({k: repo_path(v) for k, v in cfg["narrative"]["names"].items()})
    fx_raw = json.loads(repo_path(cfg["amounts"]["fx_rates"]).read_text(encoding="utf-8"))
    fx = {"rate_to_ccy0": {int(k): v["rate_to_ccy0"] for k, v in fx_raw["rate_to_ccy0"].items()}}
    rows, ses = {}, {}
    for s in sorted(chosen["seed"].unique()):
        ses[s] = read_scored_edges(cfg["inputs"]["scored_edges"].format(seed=s)).set_index("edge_id")
        tbl = pq.read_table(repo_path(cfg["output_dir"]) / cfg["explanations_name_week3"].format(seed=s)).to_pylist()
        want = set(chosen.loc[chosen["seed"] == s, "ring_id"])
        rows.update({(s, r["ring_id"]): r for r in tbl if r["ring_id"] in want})
    blocks = {it.item_id: item_markdown(it.item_id, rows[(it.seed, it.ring_id)], ses[it.seed], names, fx, int(rc["top_edges"]))
              for it in chosen.itertuples(index=False)}
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for j, reviewer in enumerate(rc["reviewers"]):
        order = list(np.random.default_rng([int(rc["rng_seed"]), j]).permutation(sorted(blocks)))
        md = out_dir / f"packet_{reviewer}.md"
        md.write_text(packet_header(reviewer, len(blocks)) + "\n".join(blocks[i] for i in order), encoding="utf-8",
                      newline="\n")
        sheet = out_dir / f"answers_{reviewer}.csv"
        with sheet.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["item_id"] + [q for q, _ in QUESTIONS] + ["comment"])
            for i in order:
                w.writerow([i] + [""] * len(QUESTIONS) + [""])
        files[md.name], files[sheet.name] = md, sheet
    key = out_dir / "answer_key.parquet"
    k = chosen.copy()
    k["narrated_type"] = [rows[(s, r)]["topology_type"] for s, r in zip(k["seed"], k["ring_id"])]
    k["narrated_prob"] = [rows[(s, r)]["topology_prob"] for s, r in zip(k["seed"], k["ring_id"])]
    k.rename(columns={"pattern_type": "true_pattern_type"}).sort_values("item_id")[
        ["item_id", "seed", "ring_id", "truth_ring_id", "true_pattern_type", "narrated_type", "narrated_prob", "jaccard",
         "stratum"]].reset_index(drop=True).to_parquet(key, index=False)
    files[key.name] = key
    return files


def pilot_truth_rings(cfg: dict, cands: pd.DataFrame) -> set[int]:
    """Truth rings behind the rings named in the pilot review file (its answer key reveals their true types)."""
    import re
    text = repo_path(cfg["output_dir"]).joinpath(cfg["narrative_samples_name"]).read_text(encoding="utf-8")
    pilot = set(re.findall(r"`(full-[^`]+)`", text))
    return {int(t) for t in cands.loc[cands["ring_id"].isin(pilot), "truth_ring_id"]}


def run(cfg: dict, out_dir: Path | None = None) -> dict:
    rc = cfg["review"]
    out_dir = Path(out_dir) if out_dir else repo_path(rc["out_dir"])
    cands = candidates(cfg, cfg["inputs"]["seeds"])
    excluded = pilot_truth_rings(cfg, cands)
    cands = cands[~cands["truth_ring_id"].isin(excluded)].reset_index(drop=True)
    chosen = choose(cands, n_items=int(rc["n_items"]), per_type=int(rc["per_type"]),
                    n_most_frequent=int(rc["n_most_frequent"]), rng_seed=int(rc["rng_seed"]))
    files = write_packets(cfg, chosen, out_dir)
    distinct = cands.drop_duplicates("truth_ring_id")["pattern_type"].value_counts()
    manifest = {
        "what": "XR-29 review sample (spec 7): matched primary-window rings of the shipped detector, one per truth ring, "
                "stratified by true pattern type: per_type each where available, the remainder from the most frequent types",
        "rule": {k: rc[k] for k in ("n_items", "per_type", "n_most_frequent", "rng_seed", "top_edges")},
        "reviewers": rc["reviewers"],
        "excluded": {"why": "truth rings shown in the Week 3 pilot file, whose answer key is committed",
                     "n_truth_rings": len(excluded)},
        "available_truth_rings_by_type": {t: int(v) for t, v in sorted(distinct.items())},
        "chosen_by_type": {t: int(v) for t, v in sorted(chosen["pattern_type"].value_counts().items())},
        "n_items": int(len(chosen)),
        "files": {name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in sorted(files.items())
                  if not name.startswith("answer_key")},
        "send_to_reviewers": sorted(n for n in files if n.startswith(("packet_", "answers_"))),
        "do_not_send": "answer_key.parquet (git-ignored: stays on this machine until the review is scored)"}
    (out_dir / "sample_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                                  newline="\n")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    m = run(load_config(), a.out)
    print(f"{m['n_items']} items by true type {m['chosen_by_type']} (available {m['available_truth_rings_by_type']})")
    print(f"send: {m['send_to_reviewers']}; keep: {m['do_not_send']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
