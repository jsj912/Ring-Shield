"""Week 3 narrative (spec 5, XR-15..19, XR-31) on hand-made rings, one per pattern type."""
from __future__ import annotations

import json
import math
import re

import pytest

from contract.schema import TOPOLOGY_TYPES
from explainability.contract_io import load_config, repo_path
from explainability.feature_weights import load_feature_model, model_features
from explainability.narrative import (CLAUSES, DROP_ORDER, NUMBER, build_narrative, duration, id_list, load_names,
                                      load_phrasing, narrative_values, regenerate, sig, summary_json, word_count)
from explainability.tests.fixtures import NARRATIVE_SHAPES, narrative_case

CFG = load_config()
SETTINGS = CFG["narrative"]
PHRASING = load_phrasing(repo_path(SETTINGS["phrasing"]))
MAX_WORDS = int(SETTINGS["max_words"])
RAW_NAMES = model_features(load_feature_model(CFG, 1)) + list(TOPOLOGY_TYPES) + ["UNKNOWN"]
NAMES = load_names({k: repo_path(v) for k, v in SETTINGS["names"].items()})


def narrate(kind, **kw):
    return build_narrative(narrative_values(**narrative_case(kind, names=NAMES, **kw)), PHRASING, SETTINGS)


def assert_clean(text: str):
    """Spec 5 rules: at most 90 words, no blank, 'None' or 'nan', no raw feature / type name (XR-15)."""
    assert word_count(text) <= MAX_WORDS
    for bad in ("None", "nan", "{", "}", "()", "  ", " .", ", ,"):
        assert bad not in text, bad
    for raw in RAW_NAMES:
        assert raw not in text, raw
    assert not re.search(r"currency \d", text), "a currency code instead of its name"


# ----------------------------------------------------------------------------- W3-3 phrasing
@pytest.mark.parametrize("seed", CFG["inputs"]["seeds"])
def test_phrasing_covers_exactly_the_model_features_and_every_type(seed):
    assert set(PHRASING["features"]) == set(model_features(load_feature_model(CFG, seed)))
    assert set(PHRASING["types"]) == set(TOPOLOGY_TYPES) | {"UNKNOWN"}
    assert all(isinstance(p, str) and p.strip() for p in [*PHRASING["features"].values(), *PHRASING["types"].values()])


# ----------------------------------------------------------------------------- W3-4 formatting
def test_number_and_time_formatting():
    assert [sig(x) for x in (12345.6, 6.0, 6.5, 0.56789, 999.6, 1234567, 0)] == \
           ["12,300", "6", "6.5", "0.568", "1,000", "1,230,000", "0"]
    assert duration(1800, 48) == "under 1 h" and duration(6 * 3600, 48) == "6 h"
    assert duration(47.5 * 3600, 48) == "47.5 h" and duration(48 * 3600, 48) == "2 days"
    assert duration(100 * 3600, 48) == "4.17 days" and duration(None, 48) is None and duration(math.nan, 48) is None
    assert id_list([11, 12, 13, 14, 15], 3) == "11, 12, 13 +2 more" and id_list([7], 3) == "7" and id_list([], 3) is None
    assert word_count("a b\tc  d") == 4


# ----------------------------------------------------------------------------- W3-5 templates
def test_fan_out_narrative_by_hand():
    text, summary = narrate("FAN-OUT")
    assert text == ("Fan-out ring (most likely shape, p = 0.65): 4 accounts, 3 transactions over 6 h. "
                    "Across the ring's 3 transactions, account 1 paid 3 different accounts. Money starts at 1 and ends "
                    "at 2, 3, 4. Total moved: 6,000 (US Dollar). Across the ring, 96% of the sources' money reached the "
                    "sinks. "
                    "Strongest evidence: 1→2 (1,000, weight 0.90); 1→3 (2,000, weight 0.80); 1→4 (3,000, weight 0.70). "
                    "Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop "
                    "scatter-gather paths; "
                    "that lowered it: the hour of the day.")
    assert summary["template"] == "FAN-OUT"


def test_stack_narrative_by_hand():
    text, _ = narrate("STACK", features=False)
    assert text == ("Layered chain ring (most likely shape, p = 0.65): 4 accounts, 3 transactions over 6 h. "
                    "Across the ring's 3 transactions, funds moved along a chain of 3 hops. Each intermediary passed "
                    "money on within a median of 5 h. Money starts at 1 and ends at 4. Intermediaries: 2, 3. "
                    "Total moved: 6,000 (US Dollar). Across the ring, 80% of the sources' money reached the sinks. "
                    "Strongest evidence: 1→2 (1,000, weight 0.90); 2→3 (2,000, weight 0.80); 3→4 (3,000, weight 0.70).")


@pytest.mark.parametrize("kind", list(NARRATIVE_SHAPES))
def test_every_type_and_the_fallback_give_a_clean_narrative(kind):
    text, summary = narrate(kind)
    assert_clean(text)
    head = PHRASING["types"][kind] + " ring (most likely shape, p = 0.65)"
    if kind == "UNKNOWN":
        assert text.startswith("Suspected ring:") and summary["template"] == "FALLBACK"
    elif kind == "RANDOM":                      # Fix A1: an irregular shape has no shape sentence -> stated as a guess
        assert text.startswith("Suspected ring:") and "most likely shape is irregular (p = 0.65)" in text
    else:
        assert text.startswith(head) and summary["template"] == kind
    assert "Strongest evidence:" in text


def test_each_type_states_its_own_shape():
    expect = {"FAN-OUT": "Across the ring's 3 transactions, account 1 paid 3 different accounts.",
              "FAN-IN": "Across the ring's 3 transactions, account 1 was paid by 3 different accounts.",
              "GATHER-SCATTER": "Across the ring's 4 transactions, account 1 gathered money from 2 accounts and passed "
                                "it on to 2.",
              "SCATTER-GATHER": "Across the ring's 4 transactions, money spread from account 1 to 2 accounts and "
                                "gathered at account 4.",
              "CYCLE": "Across the ring's 3 transactions, money travelled in a loop.",
              "STACK": "Across the ring's 3 transactions, funds moved along a chain of 3 hops.",
              "BIPARTITE": "It splits into 2 separate sender-receiver pairs."}
    for kind, sentence in expect.items():
        assert sentence in narrate(kind)[0], kind


def test_a_shape_sentence_is_only_stated_when_the_transactions_show_it():
    """The type is a guess (typing accuracy 0.219); the shape sentence is a fact and must hold on the graph."""
    for kind, shape, absent in [("FAN-OUT", "CYCLE", "loop"), ("BIPARTITE", "FAN-OUT", "different accounts"),
                                ("FAN-OUT", "GATHER-SCATTER", "gathered"), ("CYCLE", "STACK", "hops")]:
        case = narrative_case(kind, names=NAMES)
        case["topology_type"] = shape
        text, _ = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
        # Fix A1 (review): the unsupported shape is not the headline, only a stated guess
        assert text.startswith("Suspected ring:") and absent not in text, (kind, shape)
        guess = (f"most likely shape is {PHRASING['types'][shape].lower()} (p = 0.65), but the ring's transactions "
                 "do not show that shape.")
        assert guess in text
        assert_clean(text)


def test_undefined_closure_takes_the_no_closure_branch():
    text, summary = narrate("CYCLE")
    assert "Conservation cannot be measured" in text and "%" not in text
    assert summary["values"]["closure"] is None and "no_closure" in summary["clauses"]


def test_partial_currency_ring_says_so():
    text, _ = narrate("FAN-OUT", currencies={3: 1}, partial=True)
    assert "Total moved: 3,000 (US Dollar), partial: transactions in Bitcoin have no exchange rate." in text
    assert "1→4 (amount in Bitcoin, weight 0.70)" in text
    assert_clean(text)


def test_undetermined_accounts_are_named_never_called_peripheral():
    case = narrative_case("FAN-OUT", names=NAMES)
    case["account_weights"][3]["role"] = "undetermined"
    text, _ = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert "Account 4 uses Bitcoin, which has no exchange rate, so its role cannot be checked." in text
    case["account_weights"][2]["role"] = "undetermined"
    text, _ = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert "Accounts 3, 4 use Bitcoin" in text and "peripheral" not in text


def test_cross_bank_clause_only_when_banks_differ():
    """XR-18: a ring across two banks names them (Joan's contract/bank_names.json); a one-bank ring has no bank clause."""
    two, _ = narrate("BIPARTITE", banks={3: 70, 4: 70})
    assert f"The accounts span 2 banks ({NAMES['bank'][1]}, {NAMES['bank'][70]})." in two
    one, _ = narrate("BIPARTITE")
    assert "bank" not in one


def test_missing_probability_or_features_drop_their_clauses():
    text, summary = narrate("FAN-OUT", p=None, features=False)
    assert text.startswith("Suspected ring:") and "reference transaction-level model" not in text
    assert_clean(text)


def test_a_large_ring_is_cut_to_90_words_by_the_drop_order():
    case = narrative_case("GATHER-SCATTER", banks={2: 1000001, 3: 1000002, 4: 1000003, 5: 1000004}, names=NAMES)
    big = {a: 9_000_000 + a for a in range(1, 6)}                      # long account ids, as in the real data
    e = case["evidence"]                                                # the same frame as member_edges here
    e["from_id"], e["to_id"] = e["from_id"].map(big), e["to_id"].map(big)
    for a in case["account_weights"]:
        a["account_id"] = big[a["account_id"]]
    case["account_weights"][1]["role"] = "undetermined"
    text, summary = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert_clean(text)
    full = [c for c in CLAUSES if c in ("roles_both", "roles_mule", "banks")]
    dropped = [c for c in DROP_ORDER if c in full and c not in summary["clauses"]]
    assert dropped == [c for c in DROP_ORDER if c in dropped]           # dropped strictly in the stated order
    assert "evidence" in summary["clauses"] and "head" in summary["clauses"]


def test_the_bank_list_shrinks_to_a_count_before_the_bank_clause_is_dropped():
    """XR-18 under the word limit: when the bank list does not fit, the bank COUNT is kept if that fits."""
    from explainability.tests.fixtures import NARRATIVE_FEATURES
    case = narrative_case("GATHER-SCATTER", banks={2: 1000001, 3: 1000002, 4: 1000003, 5: 1000004}, names=NAMES)
    case["feature_weights"] = NARRATIVE_FEATURES[:2]
    big = {a: 9_000_000 + a for a in range(1, 6)}
    e = case["evidence"]
    e["from_id"], e["to_id"] = e["from_id"].map(big), e["to_id"].map(big)
    for a in case["account_weights"]:
        a["account_id"] = big[a["account_id"]]
    text, summary = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert "banks_short" in summary["clauses"] and "banks" not in summary["clauses"]
    assert text.endswith("The accounts span 5 banks.") and word_count(text) <= MAX_WORDS
    assert regenerate(summary_json(summary), PHRASING, SETTINGS) == text


# ----------------------------------------------------------------------------- W3-6 evidence_summary, XR-31
@pytest.mark.parametrize("kind", list(NARRATIVE_SHAPES))
def test_narrative_regenerates_from_the_stored_summary(kind):
    text, summary = narrate(kind, banks={1: 5})
    stored = summary_json(summary)
    assert regenerate(stored, PHRASING, SETTINGS) == text
    assert json.loads(stored)["slots"] == summary["slots"]


@pytest.mark.parametrize("kind", list(NARRATIVE_SHAPES))
def test_every_number_in_the_sentence_is_in_the_summary(kind):
    text, summary = narrate(kind, banks={1: 5}, currencies={2: 1}, partial=True)
    in_slots = {t for s in summary["slots"].values() for t in NUMBER.findall(s)}
    assert set(NUMBER.findall(text)) <= in_slots


def test_a_tampered_summary_is_caught():
    text, summary = narrate("FAN-OUT")
    s = json.loads(summary_json(summary))
    s["slots"]["total"] = "7,000"
    with pytest.raises(ValueError, match="differ"):
        regenerate(s, PHRASING, SETTINGS)
    s = json.loads(summary_json(summary))
    s["values"]["total_ccy0"] = 7000.0
    with pytest.raises(ValueError):
        regenerate(s, PHRASING, SETTINGS)


# ----------------------------------------------------------------------------- W3-7 topology source, XR-19
@pytest.mark.parametrize("kind", [k for k in NARRATIVE_SHAPES if k != "UNKNOWN"])
def test_swapping_the_topology_source_changes_only_p(kind):
    a, _ = narrate(kind)
    case = narrative_case(kind, p=0.42, names=NAMES)
    case["type_source"] = "rule_scorer"
    b, _ = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert a.replace("p = 0.65", "p = 0.42") == b


# ----------------------------------------------------------------------------- names (sync with v2 b35b233)
def test_names_are_joans_maps():
    """Currency 0 = US Dollar, the unconvertible currency 1 = Bitcoin, payment format 3 = ACH, 15 / 7 / 30,470 entries:
    read from Joan's files, not typed here."""
    assert NAMES["currency"][0] == "US Dollar" and NAMES["currency"][1] == "Bitcoin" and len(NAMES["currency"]) == 15
    assert NAMES["payment_format"][3] == "ACH" and len(NAMES["payment_format"]) == 7
    assert len(NAMES["bank"]) == 30470


def test_bank_names_are_display_only_shared_names_get_their_id_and_unknown_ids_fall_back():
    from explainability.narrative import format_slots
    v = narrative_values(**narrative_case("BIPARTITE", banks={3: 70, 4: 70}, names=NAMES))
    v["bank_names"] = ["Same Bank", "Same Bank"]
    assert format_slots(v, PHRASING, SETTINGS)["bank_list"] == "Same Bank (1), Same Bank (70)"
    w = narrative_values(**narrative_case("BIPARTITE", banks={3: 999999999, 4: 999999999}, names=NAMES))
    assert w["bank_names"][-1] == "Bank 999999999"


def test_code_valued_features_name_the_top_edges_value():
    """'the payment method (ACH)': the name of the payment format of the feature's top edge."""
    v = narrative_values(**narrative_case("FAN-OUT", names=NAMES))
    pf = [f for f in v["top_features"] if f["feature"] == "Payment Format"][0]
    assert pf["detail"] == "ACH" and all(f["detail"] is None for f in v["top_features"] if f["feature"] != "Payment Format")


# ----------------------------------------------------------------------------- Week 8: fixes from the review
def test_fix_a1_unsupported_shape_is_a_guess_not_a_headline():
    """Review Fix A1: a typed ring whose transactions show no shape sentence opens with "Suspected ring" and states
    the typing model's shape as a guess; a ring whose shape sentence holds keeps its typed headline."""
    case = narrative_case("BIPARTITE", names=NAMES)
    case["topology_type"] = "FAN-OUT"                                    # no account pays two others here
    text, summary = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert summary["clauses"][:2] == ["head_untyped", "type_guess"]
    assert text.startswith("Suspected ring: 4 accounts, 2 transactions over 6 h. The typing model's most likely shape "
                           "is fan-out (p = 0.65), but the ring's transactions do not show that shape.")
    assert narrate("FAN-OUT")[1]["clauses"][:2] == ["head", "fan_out"]


def test_a_shape_sentence_must_agree_with_the_hub_role():
    """Review (R-12, R-30): a hub is named only when its money role agrees with the sentence -- a 'gathering' hub must
    pass money on, a fan-out hub must send, a fan-in hub must receive. Otherwise Fix A1 applies."""
    case = narrative_case("GATHER-SCATTER", names=NAMES)
    case["account_weights"][0]["role"] = "source"                      # account 1, the gather-scatter hub
    text, summary = build_narrative(narrative_values(**case), PHRASING, SETTINGS)
    assert "gather_scatter" not in summary["clauses"] and "gathered" not in text
    assert summary["values"]["shape"]["gs_hub_role"] == "source"
    case = narrative_case("FAN-OUT", names=NAMES)
    case["account_weights"][0]["role"] = "sink"                        # account 1, the fan-out hub
    assert "fan_out" not in build_narrative(narrative_values(**case), PHRASING, SETTINGS)[1]["clauses"]


def test_shape_sentences_and_closure_state_their_scope():
    """Review (R-02, R-06, R-25, R-30): counts and conservation cover the whole ring, and say so."""
    for kind in ("FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER", "CYCLE", "STACK"):
        text, summary = narrate(kind)
        assert "Across the ring's " in text, kind
        if summary["values"]["closure"] is not None:
            assert "Across the ring, " in text, kind


def test_a_self_payment_is_never_cited_as_evidence():
    """Review (R-04): the narrative's strongest evidence skips a payment from an account to itself and says so; the
    ranked edge weights themselves are untouched."""
    import pandas as pd
    case = narrative_case("FAN-OUT", names=NAMES)
    ev = case["evidence"]
    self_row = ev.iloc[[0]].assign(edge_id=99, to_id=1)                   # account 1 paying itself
    case["evidence"] = case["member_edges"] = pd.concat([self_row, ev], ignore_index=True)
    case["edge_weights"] = [{"edge_id": 99, "w_total": 0.99}] + case["edge_weights"]
    v = narrative_values(**case)
    text, summary = build_narrative(v, PHRASING, SETTINGS)
    assert all(e["from_id"] != e["to_id"] for e in v["top_edges"]) and len(v["top_edges"]) == 3
    assert v["self_payments_skipped"] == 1 and "1→1" not in text
    assert "One stronger-ranked payment from an account to itself is not cited." in text
    assert regenerate(summary_json(summary), PHRASING, SETTINGS) == text
