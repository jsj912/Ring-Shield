import numpy as np

from evaluation.q2_account_seeds import account_seed_mask

# edges: 0:(1,2) .9  1:(1,3) .8  2:(1,4) .7  3:(1,5) .6  4:(6,7) .85  5:(8,9) .1
E = np.arange(6)
F = np.array([1, 1, 1, 1, 6, 8])
T = np.array([2, 3, 4, 5, 7, 9])
S = np.array([.9, .8, .7, .6, .85, .1])


def test_exact_budget_and_cap_three():
    m = account_seed_mask(E, F, T, S, "max", 4)
    assert m.sum() == 4
    # account 1 (max .9) first: its top three edges 0,1,2; then account 2 (.9, edge 0 already taken)
    # contributes nothing new; next account 6/7 (.85) gives edge 4
    assert set(np.flatnonzero(m)) == {0, 1, 2, 4}


def test_top3_ranks_multi_edge_accounts_lower():
    # top3: account 1 = mean(.9,.8,.7) = .8 falls behind accounts 2 (.9) and 6/7 (.85)
    assert set(np.flatnonzero(account_seed_mask(E, F, T, S, "top3", 2))) == {0, 4}
    # max: account 1 (.9, smallest id among ties with account 2) takes edges 0 and 1
    assert set(np.flatnonzero(account_seed_mask(E, F, T, S, "max", 2))) == {0, 1}


def test_partial_last_account():
    m = account_seed_mask(E, F, T, S, "max", 2)
    assert set(np.flatnonzero(m)) == {0, 1}
