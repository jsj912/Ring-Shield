"""XR-08 / 09 / 10 / 11 / 12: account flows, degrees, w_account, roles and the role-disagreement log."""
from __future__ import annotations

import pytest

from explainability.account_weights import (account_weight_table, background_degree, research_roles, role_disagreements,
                                            spec_roles)
from explainability.contract_io import load_config, load_research_config, read_rings, read_scored_edges, repo_path
from explainability.tests import fixtures as fx

CFG = load_config()
ROLES_CFG = load_research_config(CFG, "roles")
SEEDS = [1, 2, 3, 4, 5]


def _real(seed):
    scores, rings = CFG["inputs"]["scored_edges"].format(seed=seed), CFG["inputs"]["rings"].format(seed=seed)
    if any(not repo_path(p).exists() for p in (scores, rings)):
        pytest.skip("real contract files not on disk")
    se = read_scored_edges(scores)
    return se, read_rings(rings, scored_edges=se)


# ----------------------------------------------------------------------------- research roles on real rings
@pytest.mark.parametrize("seed", SEEDS)
def test_research_roles_reproduce_the_contract_role_arrays(seed):
    """XR-11: the roles we narrate are the ones Joan shipped -- for every ring, the research roles regroup
    into exactly the contract's source_accounts / sink_accounts / mule_accounts (mule + holder)."""
    from ringshield.roles import role_arrays
    se, rings = _real(seed)
    sei = se.set_index("edge_id")
    for r in rings.itertuples(index=False):
        arrays = role_arrays(research_roles(r, sei))
        assert arrays["source_accounts"] == sorted(r.source_accounts), r.ring_id
        assert arrays["sink_accounts"] == sorted(r.sink_accounts), r.ring_id
        assert arrays["mule_accounts"] == sorted(r.mule_accounts), r.ring_id
        assert set(research_roles(r, sei)) == set(r.members), r.ring_id      # every member gets a role


def test_ring_degree_never_exceeds_background_degree():
    se, rings = _real(1)
    deg = background_degree(se)
    sei = se.set_index("edge_id")
    for r in rings.itertuples(index=False):
        member = sei.loc[list(r.member_edges)].reset_index()
        t = account_weight_table(r.members, member, member.assign(w_total=0.0)[["edge_id", "w_total"]], deg, None)
        assert ((t["deg_in_ring"] >= 1) & (t["deg_in_ring"] <= t["deg_background"])).all(), r.ring_id


# ----------------------------------------------------------------------------- roles on the fixture
def test_every_role_is_covered_and_matches_by_hand():
    """XR-10: one fixture ring holds a source, a sink, a mule, a holder and a peripheral account."""
    c = fx.roles_case()
    ring = c["rings"].iloc[0]
    got = {a: d["role"] for a, d in research_roles(ring, c["scored_edges"]).items()}
    assert got == c["research_roles"]
    assert set(got.values()) == {"source", "sink", "mule", "holder", "peripheral"}


def test_spec_rule_and_disagreement_log():
    """XR-12: the spec 4.3 rule, on the same edges, differs only on account X, because of the hold-time rule."""
    c = fx.roles_case()
    ring = c["rings"].iloc[0]
    se = c["scored_edges"]
    included = se[se["edge_id"].isin(set(ring.seed_edges) | set(ring.expanded_edges))]
    spec = spec_roles(included, ROLES_CFG)
    assert {a: d["role"] for a, d in spec.items()} == c["spec_roles"]
    log = role_disagreements(ring.ring_id, research_roles(ring, se), spec)
    assert set(log["account_id"]) == c["disagree"]
    assert log.iloc[0]["cause"] == "hold_time_definition"
    assert log.iloc[0]["research_role"] == "mule" and log.iloc[0]["spec_role"] == "holder"


def test_role_thresholds_come_from_config():
    """XR-10: tau_role and the hold limit are configuration. Raising the hold limit to 250 h turns the
    holder H and the disputed X into mules under the spec rule."""
    c = fx.roles_case()
    se = c["scored_edges"]
    loose = spec_roles(se, {**ROLES_CFG, "hold_seconds": 250 * 3600})
    holders = [a for a, r in c["spec_roles"].items() if r == "holder"]
    assert holders and all(loose[a]["role"] == "mule" for a in holders)


# ----------------------------------------------------------------------------- w_account by hand
def test_w_account_matches_the_hand_computation():
    """XR-08 / XR-09."""
    c = fx.account_weight_case()
    edge_table = c["edges"].assign(w_total=c["edges"]["edge_id"].map(c["w_total"]))[["edge_id", "w_total"]]
    t = account_weight_table([100, 101, 102], c["edges"], edge_table, c["deg_background"], None,
                             score_share=CFG["account_weights"]["score_share"],
                             degree_share=CFG["account_weights"]["degree_share"]).set_index("account_id")
    for a, v in c["w_account"].items():
        assert abs(t.at[a, "w_account"] - v) < 1e-6
    assert list(t.index) == [101, 102, 100]                     # sorted by w_account, high first
    assert t.at[101, "deg_in_ring"] == 2 and t.at[100, "deg_background"] == 4


# ----------------------------------------------------------------------------- migration: converted roles on real rings
def test_converted_roles_leave_exactly_three_undetermined_accounts_all_in_currency_1():
    """Joan's figure: under currency='converted' only 3 of 4,280 ring-accounts stay undetermined, all because
    they touch currency 1 (the one currency with no usable rate). Checked on all five seeds."""
    n_undet, n_accounts = 0, 0
    for seed in SEEDS:
        se, rings = _real(seed)
        sei = se.set_index("edge_id")
        for r in rings.itertuples(index=False):
            roles = research_roles(r, sei, currency="converted")
            n_accounts += len(roles)
            for a, d in roles.items():
                if d["role"] == "undetermined":
                    n_undet += 1
                    inc = sei.loc[list(r.seed_edges) + list(r.expanded_edges)]
                    touch = inc[(inc["from_id"] == a) | (inc["to_id"] == a)]
                    assert ((touch["currency_sent"] == 1) | (touch["currency_received"] == 1)).any(), (r.ring_id, a)
    assert n_undet == 3 and n_accounts == 4280
