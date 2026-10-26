from __future__ import annotations

from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from services.verdicts import (  # noqa: E402
    PartialCorrectionError,
    map_partial_correction_to_exclusions,
)


MEMBERS = [1, 2, 3, 4, 5]
EDGES = [10, 11, 12, 13]
ENDPOINTS = {10: (1, 2), 11: (2, 3), 12: (3, 4), 13: (4, 5)}


def test_partial_correction_maps_two_of_five_members_and_infers_edges():
    excluded_members, excluded_edges = map_partial_correction_to_exclusions(
        member_accounts=MEMBERS, member_edges=EDGES, edge_endpoints=ENDPOINTS,
        corrected_members=[1, 2], corrected_edges=None,
    )

    assert excluded_members == [3, 4, 5]
    assert excluded_edges == []


def test_partial_correction_maps_explicit_kept_edges_to_exclusions():
    excluded_members, excluded_edges = map_partial_correction_to_exclusions(
        member_accounts=MEMBERS, member_edges=EDGES, edge_endpoints=ENDPOINTS,
        corrected_members=[1, 2, 3], corrected_edges=[10, 11],
    )

    assert excluded_members == [4, 5]
    assert excluded_edges == [12, 13]


@pytest.mark.parametrize(("members", "edges", "endpoints", "kept", "kept_edges", "message"), [
    (MEMBERS, EDGES, ENDPOINTS, [], None, "At least two"),
    (MEMBERS, EDGES, ENDPOINTS, [1], None, "At least two"),
    (MEMBERS, EDGES, ENDPOINTS, MEMBERS, None, "remove at least one"),
    (MEMBERS, EDGES, ENDPOINTS, [1, 2, 8], None, "belong to this ring"),
    (MEMBERS, EDGES, ENDPOINTS, [1, 2, 2], None, "must be unique"),
    (MEMBERS, EDGES, ENDPOINTS, [1, 2], [], "At least one ring edge"),
    (MEMBERS, EDGES, ENDPOINTS, [1, 2, 3], [10, 10], "must be unique"),
    (MEMBERS, EDGES, ENDPOINTS, [1, 2, 3], [99], "belong to this ring"),
    (MEMBERS, EDGES, ENDPOINTS, [1, 2, 3], [12, 13], "connect corrected members"),
    (MEMBERS, EDGES, {10: (1, 2)}, [1, 2], None, "edge data is incomplete"),
])
def test_invalid_partial_correction_is_rejected(members, edges, endpoints, kept,
                                               kept_edges, message):
    with pytest.raises(PartialCorrectionError, match=message):
        map_partial_correction_to_exclusions(
            member_accounts=members, member_edges=edges, edge_endpoints=endpoints,
            corrected_members=kept, corrected_edges=kept_edges,
        )
