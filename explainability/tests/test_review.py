"""Week 6 (XR-29): the review sample, packets, sheets and their aggregation."""
from __future__ import annotations

import csv
import json
import re
import shutil

import numpy as np
import pandas as pd
import pytest

from explainability.contract_io import load_config, repo_path
from explainability.review.aggregate import aggregate, fleiss_kappa, read_sheet
from explainability.review.sample import QUESTIONS, choose

CFG = load_config()
RC = CFG["review"]
DIR = repo_path(RC["out_dir"])


# ----------------------------------------------------------------------------- Fleiss' kappa
def test_fleiss_kappa_reproduces_the_published_example():
    """Fleiss (1971) / the standard worked example: 10 subjects, 14 raters, 5 categories -> kappa 0.210."""
    table = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
             [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    assert fleiss_kappa(table) == pytest.approx(0.20993, abs=1e-5)


def test_fleiss_kappa_edge_cases():
    assert fleiss_kappa([[3, 0], [0, 3], [3, 0]]) == pytest.approx(1.0)           # perfect agreement
    assert fleiss_kappa([[3, 0], [3, 0]]) is None                                  # one category only: undefined
    with pytest.raises(ValueError):
        fleiss_kappa([[3, 0], [1, 1]])                                             # unequal raters


# ----------------------------------------------------------------------------- the sampling rule
def test_choose_follows_the_spec_rule():
    """Four per type where available, the remainder from the two most frequent types in turn; one per truth ring."""
    rows, tid = [], 0
    for t, n in (("A", 10), ("B", 7), ("C", 5), ("D", 1)):
        for _ in range(n):
            tid += 1
            rows += [{"seed": s, "ring_id": f"r{tid}-{s}", "truth_ring_id": tid, "pattern_type": t, "jaccard": 1.0}
                     for s in (1, 2)]
    c = choose(pd.DataFrame(rows), n_items=16, per_type=4, n_most_frequent=2, rng_seed=7)
    assert len(c) == 16 and c["truth_ring_id"].is_unique
    assert c["pattern_type"].value_counts().to_dict() == {"A": 6, "B": 5, "C": 4, "D": 1}
    assert c.equals(choose(pd.DataFrame(rows), n_items=16, per_type=4, n_most_frequent=2, rng_seed=7))
    assert list(c["item_id"]) == [f"R-{i:02d}" for i in range(1, 17)]


# ----------------------------------------------------------------------------- the real packets
def test_real_sample_packets_and_sheets():
    """30 items, the stated counts by true type; three packets with the same items in different orders; blank sheets;
    nothing that reveals the truth (no ring id, seed, true type, Jaccard) in what reviewers get."""
    m = json.loads((DIR / "sample_manifest.json").read_text(encoding="utf-8"))
    assert m["n_items"] == 30
    assert m["chosen_by_type"] == {"BIPARTITE": 1, "CYCLE": 4, "FAN-IN": 4, "FAN-OUT": 4, "GATHER-SCATTER": 6,
                                   "RANDOM": 4, "SCATTER-GATHER": 6, "STACK": 1}
    key = pd.read_parquet(DIR / "answer_key.parquet")
    assert len(key) == 30 and key["truth_ring_id"].is_unique
    orders = []
    for r in RC["reviewers"]:
        text = (DIR / f"packet_{r}.md").read_text(encoding="utf-8")
        ids = re.findall(r"^## (R-\d\d)$", text, flags=re.M)
        assert sorted(ids) == sorted(key["item_id"])
        orders.append(ids)
        for leak in [*key["ring_id"], "truth", "Jaccard", "jaccard", "pattern_type", "seed"]:
            assert str(leak) not in text, (r, leak)
        sheet = pd.read_csv(DIR / f"answers_{r}.csv", dtype=str, keep_default_na=False)
        assert list(sheet.columns) == ["item_id", *[q for q, _ in QUESTIONS], "comment"]
        assert list(sheet["item_id"]) == ids and (sheet.drop(columns="item_id") == "").all().all()
    assert len({tuple(o) for o in orders}) == len(orders)                          # each reviewer has their own order
    import subprocess
    ignored = subprocess.run(["git", "check-ignore", "-q", str(DIR / "answer_key.parquet")], cwd=repo_path("."))
    assert ignored.returncode == 0                                       # the reviewers pull this branch: key never committed
    assert "answer_key" not in "".join(m["files"]) and not (DIR / "answer_key.csv").exists()
    from explainability.review.sample import candidates, pilot_truth_rings
    pilot = pilot_truth_rings(CFG, candidates(CFG, CFG["inputs"]["seeds"]))
    assert pilot and not pilot & set(key["truth_ring_id"])           # no ring whose answer the pilot file reveals
    assert m["excluded"]["n_truth_rings"] == len(pilot) == 7
    import hashlib
    for name, h in m["files"].items():
        assert hashlib.sha256((DIR / name).read_bytes()).hexdigest() == h, name


# ----------------------------------------------------------------------------- aggregation on made-up answers
def _fill(src, dst, rng):
    df = pd.read_csv(src, dtype=str, keep_default_na=False)
    for q, _ in QUESTIONS:
        df[q] = rng.integers(0, 2, len(df)).astype(str)
    df.to_csv(dst, index=False, lineterminator="\n")


def test_aggregate_on_made_up_sheets(tmp_path):
    shutil.copy(DIR / "answer_key.parquet", tmp_path / "answer_key.parquet")
    rng = np.random.default_rng(3)
    for r in RC["reviewers"]:
        _fill(DIR / f"answers_{r}.csv", tmp_path / f"answers_{r}.csv", rng)
    review, summary = aggregate(tmp_path, list(RC["reviewers"]))
    assert len(review) == 90 and set(review["reviewer"]) == set(RC["reviewers"])
    assert set(summary["per_question"]) == {q for q, _ in QUESTIONS}
    for v in summary["per_question"].values():
        assert 0 <= v["yes_rate"] <= 1 and 0 <= v["all_agree_rate"] <= 1
    key = pd.read_parquet(tmp_path / "answer_key.parquet")
    assert summary["reveal"]["narrated_shape_correct_rate"] == pytest.approx(
        (key["narrated_type"] == key["true_pattern_type"]).mean())
    assert not {"ring_id", "seed", "truth_ring_id"} & set(review.columns)      # review.csv: items and anonymised ids


def test_bad_sheets_are_refused(tmp_path):
    items = set(pd.read_parquet(DIR / "answer_key.parquet")["item_id"])
    src = DIR / f"answers_{RC['reviewers'][0]}.csv"
    with pytest.raises(ValueError, match="0 or 1"):
        read_sheet(src, items)                                                  # blank sheet
    df = pd.read_csv(src, dtype=str, keep_default_na=False)
    for q, _ in QUESTIONS:
        df[q] = "1"
    df.loc[0, QUESTIONS[0][0]] = "2"
    df.to_csv(tmp_path / "x.csv", index=False)
    with pytest.raises(ValueError, match="0 or 1"):
        read_sheet(tmp_path / "x.csv", items)
    df.loc[0, QUESTIONS[0][0]] = "1"
    df.iloc[:-1].to_csv(tmp_path / "y.csv", index=False)
    with pytest.raises(ValueError, match="items differ"):
        read_sheet(tmp_path / "y.csv", items)
