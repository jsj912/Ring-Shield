from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.survey_tenants import select_candidate_banks  # noqa: E402


def test_survey_unions_visible_and_seed_rankings_with_stable_ties():
    banks, reasons, visible_top, seed_top = select_candidate_banks(
        {20: 100, 10: 100, 30: 50}, {20: 1, 10: 5, 30: 5}, top=2,
    )

    assert visible_top == [10, 20]
    assert seed_top == [10, 30]
    assert banks == [10, 20, 30]
    assert reasons == {
        10: ["top_visible_edges", "top_seed_edges_at_active_cutoff"],
        20: ["top_visible_edges"],
        30: ["top_seed_edges_at_active_cutoff"],
    }
