from evaluation.q7_tie_audit import count_forced_ties, greedy_count, optimal_count

# two 2-member truth rings, each at Jaccard 2/3 with a shared 3-account prediction
T = {"A": {1, 2}, "B": {2, 3}}


def test_tie_on_shared_prediction_counts_both_rings():
    assert count_forced_ties([{1, 2, 3}], T) == {"A", "B"}


def test_no_tie_when_jaccards_differ():
    assert count_forced_ties([{1, 2}, {2, 3, 4}], T) == set()   # A at 1.0, B at 2/3: different levels


def test_tie_already_resolved_by_higher_level_not_counted():
    # A is taken at Jaccard 1.0 by prediction 0, so B's 2/3 pair against prediction 1 is not contested
    assert count_forced_ties([{1, 2}, {1, 2, 3}], T) == set()


def test_order_dependence_and_optimal():
    # prediction 0 = {1,2,3} ties A and B at 2/3; prediction 1 = {1,2,9} matches only A at 2/3
    p_bad = [{1, 2, 3}, {1, 2, 9}]           # greedy gives pred 0 to A (truth-id order), then pred 1 has only A -> 1 pair
    p_good = [{1, 2, 9}, {1, 2, 3}]          # greedy gives pred 0 to A, pred 1 to B -> 2 pairs
    assert greedy_count(p_bad, T) == 1
    assert greedy_count(p_good, T) == 2
    assert optimal_count(p_bad, T) == optimal_count(p_good, T) == 2
    assert count_forced_ties(p_bad, T) == {"A", "B"}
