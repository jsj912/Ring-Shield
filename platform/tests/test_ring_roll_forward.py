from __future__ import annotations

from types import SimpleNamespace

from jobs.ring_roll_forward import assign_roll_forward_ring_ids


def test_matching_updates_only_open_unverdictated_ring_and_allocates_collision_free_ids():
    existing = [
        SimpleNamespace(ring_id="open-one", status="open", member_accounts=[1, 2, 3]),
        SimpleNamespace(ring_id="full-gine_causal-1-v2-runabc-1", status="confirmed", member_accounts=[8, 9]),
        SimpleNamespace(ring_id="open-with-verdict", status="open", member_accounts=[20, 21]),
    ]
    original_meanings = {row.ring_id: tuple(row.member_accounts) for row in existing}
    records = [
        {"ring_id": "candidate-open", "confidence": 0.9, "members": [1, 2, 4]},
        {"ring_id": "candidate-collision", "confidence": 0.8, "members": [8, 9, 10]},
        {"ring_id": "candidate-verdict", "confidence": 0.7, "members": [20, 21]},
    ]

    result = assign_roll_forward_ring_ids(
        records,
        existing,
        model_id="gine_causal",
        seed=1,
        version="2-runabc",
        protected_ring_ids={"open-with-verdict"},
    )

    assert [record["ring_id"] for record in result][0] == "open-one"
    assert result[1]["ring_id"].startswith("full-gine_causal-1-v2-runabc-")
    assert result[1]["ring_id"] == "full-gine_causal-1-v2-runabc-2"
    assert result[2]["ring_id"].startswith("full-gine_causal-1-v2-runabc-")
    assert len({record["ring_id"] for record in result}) == len(result)
    assert original_meanings == {row.ring_id: tuple(row.member_accounts) for row in existing}


def test_one_open_ring_identity_cannot_be_assigned_to_two_new_rings():
    existing = [SimpleNamespace(ring_id="open-one", status="open", member_accounts=[1, 2])]
    records = [
        {"ring_id": "candidate-a", "confidence": 0.9, "members": [1, 2]},
        {"ring_id": "candidate-b", "confidence": 0.8, "members": [1, 2]},
    ]

    result = assign_roll_forward_ring_ids(
        records, existing, model_id="model", seed=5, version="3",
    )

    assert result[0]["ring_id"] == "open-one"
    assert result[1]["ring_id"] == "full-model-5-v3-1"
