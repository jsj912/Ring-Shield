"""Week 3: the ring's narrative -- a filled template, never free text (spec 5, XR-15..19, XR-31).

    values = narrative_values(...)                 # every number / id the sentence may use, from stored weights
    text, summary = build_narrative(values, phrasing, settings)
    regenerate(summary, phrasing, settings) == text    # XR-31: the sentence is a pure function of the summary

How a narrative is made, in three steps:
1. VALUES. Collect the facts: type and probability, counts, time span, money total in currency 0, conservation,
   the accounts of each role, the three strongest transactions, the three strongest detector features, the banks,
   and a few shape facts (the hub account of a fan, the depth of a chain, ...). Every one comes from a stored
   weight or a ring field; nothing is invented. They are stored in `evidence_summary["values"]`.
2. SLOTS. Turn each value into the exact text it will appear as (`format_slots`): amounts to 3 significant
   figures with thousands separators, times in hours below 48 h and days from there, at most 3 accounts per list
   then "+N more". A slot whose value is missing is None.
3. CLAUSES. Each topology type has an ordered list of clauses; a clause is used only if all of its slots are
   present, so no sentence ever shows a blank, "None" or "nan". If the result is over 90 words, optional clauses
   are dropped in a fixed order until it fits.

Because steps 2 and 3 depend only on the stored values, the sentence can always be regenerated from
`evidence_summary` and compared character for character (XR-31). No language model is used anywhere.

Which topology. The ring's `topology_type` as delivered (the Step 8 typing head); the template wording does
not depend on where the type came from -- only the type and its p appear in the text (XR-19).
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import yaml

NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")     # a number as written in a narrative: 12,300 / 0.93 / 7

# ----------------------------------------------------------------------------- formatting (W3-4)


def sig(x: float, n: int = 3) -> str:
    """`x` to n significant figures, thousands separators, no trailing zeros: 12345.6 -> '12,300', 6.0 -> '6'."""
    if x == 0:
        return "0"
    d = n - 1 - math.floor(math.log10(abs(x)))
    r = round(x, d)
    if d <= 0:
        return f"{int(round(r)):,}"
    return f"{r:,.{d}f}".rstrip("0").rstrip(".")


def duration(seconds: float | None, days_from_hours: float, n: int = 3) -> str | None:
    """'under 1 h', '6.5 h', '2 days'. Hours below `days_from_hours`, days from there on."""
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return None
    hours = seconds / 3600
    if hours < 1:
        return "under 1 h"
    if hours < days_from_hours:
        return f"{sig(hours, n)} h"
    return f"{sig(hours / 24, n)} days"


def id_list(ids, list_max: int) -> str | None:
    """'11, 12, 13 +4 more'; None for an empty list."""
    ids = list(ids)
    if not ids:
        return None
    head = ", ".join(str(i) for i in ids[:list_max])
    return head + (f" +{len(ids) - list_max} more" if len(ids) > list_max else "")


def word_count(text: str) -> int:
    return len(text.split())


# ----------------------------------------------------------------------------- values (step 1)


def load_phrasing(path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def shape_facts(edges: pd.DataFrame) -> dict:
    """Shape facts of the ring's evidence graph (distinct sender -> receiver pairs, self-loops left out).

    out_hub / in_hub: the account paying / paid by the most different accounts (ties -> smaller id).
    gs_hub: among accounts with >= 2 senders AND >= 2 receivers, the one with the most of both (gather-scatter).
    depth: longest chain of payments (edges) when the graph has no loop, else None.
    has_cycle: the payments contain a directed loop (money can return to an account it left).
    n_pairs: separate pieces that are exactly one sender and one receiver (bipartite fragments)."""
    pairs = edges.loc[edges["from_id"] != edges["to_id"], ["from_id", "to_id"]].drop_duplicates()
    G = nx.DiGraph()
    G.add_edges_from((int(a), int(b)) for a, b in pairs.itertuples(index=False))
    out = {"out_hub": None, "n_out": None, "in_hub": None, "n_in": None,
           "gs_hub": None, "gs_n_in": None, "gs_n_out": None, "depth": None, "n_pairs": 0,
           "has_cycle": False}
    if G.number_of_nodes() == 0:
        return out
    nodes = sorted(G.nodes)
    o = max(nodes, key=lambda a: (G.out_degree(a), -a))
    i = max(nodes, key=lambda a: (G.in_degree(a), -a))
    out.update(out_hub=o, n_out=G.out_degree(o), in_hub=i, n_in=G.in_degree(i))
    both = [a for a in nodes if G.in_degree(a) >= 2 and G.out_degree(a) >= 2]
    if both:
        h = max(both, key=lambda a: (G.in_degree(a) + G.out_degree(a), -a))
        out.update(gs_hub=h, gs_n_in=G.in_degree(h), gs_n_out=G.out_degree(h))
    if nx.is_directed_acyclic_graph(G):
        out["depth"] = int(nx.dag_longest_path_length(G))
    else:
        out["has_cycle"] = True
    out["n_pairs"] = sum(1 for c in nx.weakly_connected_components(G) if len(c) == 2)
    return out


def _by_weight(accounts: list[dict], roles: set[str]) -> list[int]:
    chosen = [a for a in accounts if a["role"] in roles]
    return [int(a["account_id"]) for a in sorted(chosen, key=lambda a: (-a["w_account"], a["account_id"]))]


def narrative_values(*, topology_type: str, topology_prob: float | None, type_source: str, duration_s: float,
                     evidence: pd.DataFrame, member_edges: pd.DataFrame, edge_weights: list[dict],
                     account_weights: list[dict], flow: dict, conservation: dict, closure_raw: float | None,
                     feature_weights: list[dict], fx: dict | None, n_top_edges: int, n_top_features: int) -> dict:
    """Every fact the narrative may state, as plain JSON-able values.

    evidence      the ring's evidence edges (member edges minus conversions) with from_id, to_id, amount_received,
                  currency_received; member_edges: all member edges with from_bank / to_bank (for the banks).
    edge_weights  the explanation's edge weights, already sorted by w_total (highest first).
    flow          {"total_ccy0", "partial"} from the converted w_flow; conservation: Joan's
                  ring_conservation_converted (closure in currency 0, NaN = no source or no sink)."""
    def num(x):
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)

    ev = evidence.set_index("edge_id")
    rates = (fx or {}).get("rate_to_ccy0", {})
    top_edges = []
    for e in edge_weights[:n_top_edges]:
        r = ev.loc[int(e["edge_id"])]
        rate = rates.get(int(r["currency_received"]))
        top_edges.append({"edge_id": int(e["edge_id"]), "from_id": int(r["from_id"]), "to_id": int(r["to_id"]),
                          "amount_ccy0": None if rate is None else float(r["amount_received"]) * float(rate),
                          "currency": int(r["currency_received"]), "w_total": float(e["w_total"])})
    holds = [a["hold_time_s"] for a in account_weights
             if a["role"] in ("mule", "holder") and a["hold_time_s"] is not None and not math.isnan(a["hold_time_s"])]
    bank_of = {}
    for r in member_edges.itertuples(index=False):
        bank_of.setdefault(int(r.from_id), int(r.from_bank))
        bank_of.setdefault(int(r.to_id), int(r.to_bank))
    members = [int(a["account_id"]) for a in account_weights]
    banks = sorted({bank_of[a] for a in members if a in bank_of})
    return {
        "topology_type": topology_type, "p_type": num(topology_prob), "type_source": type_source,
        "n_members": len(account_weights), "n_edges": len(edge_weights), "duration_s": num(duration_s),
        "currency_hub": int((fx or {}).get("hub", 0)), "currency_unconvertible": sorted((fx or {}).get("unconvertible", [])),
        "total_ccy0": num(flow.get("total_ccy0")), "flow_partial": bool(flow.get("partial", False)),
        "closure": num(conservation.get("closure")), "closure_partial": bool(conservation.get("unconvertible", False)),
        "closure_raw": num(closure_raw),
        "sources": _by_weight(account_weights, {"source"}), "sinks": _by_weight(account_weights, {"sink"}),
        "mules": _by_weight(account_weights, {"mule", "holder"}),
        "undetermined": _by_weight(account_weights, {"undetermined"}),
        "hold_median_s": float(np.median(holds)) if holds else None,
        "top_edges": top_edges,
        "top_features": [{"feature": f["feature_name"], "mean_shap": float(f["mean_shap"])}
                         for f in feature_weights[:n_top_features]],
        "banks": banks,
        "shape": shape_facts(evidence),
    }


# ----------------------------------------------------------------------------- slots (step 2)


def format_slots(v: dict, phrasing: dict, s: dict) -> dict:
    """Every slot as the exact text it appears as; None when it has no value."""
    sf, dfh, lm = int(s["sig_figs"]), float(s["days_from_hours"]), int(s["list_max"])
    sh = v["shape"]

    def n(x):
        return None if x is None else str(int(x))

    def amount(x, ccy):
        return sig(x, sf) if x is not None else f"amount in currency {ccy}"

    unconv = v["currency_unconvertible"]
    slots = {
        "type_name": phrasing["types"].get(v["topology_type"]) if v["topology_type"] != "UNKNOWN" else None,
        "p": None if v["p_type"] is None else f"{v['p_type']:.2f}",
        "n_members": n(v["n_members"]), "n_edges": n(v["n_edges"]),
        "window": duration(v["duration_s"], dfh, sf),
        "total": None if v["total_ccy0"] is None else sig(v["total_ccy0"], sf),
        "ccy0": str(v["currency_hub"]), "ccy1": ", ".join(map(str, unconv)) or None,
        "partial": "yes" if v["flow_partial"] or v["closure_partial"] else None,
        "closure_pct": None if v["closure"] is None else str(int(round(v["closure"] * 100))),
        "no_closure": "yes" if v["closure"] is None else None,
        "src_list": id_list(v["sources"], lm), "sink_list": id_list(v["sinks"], lm),
        "mule_list": id_list(v["mules"], lm), "undet_list": id_list(v["undetermined"], lm),
        "undet_one": "yes" if len(v["undetermined"]) == 1 else None,
        "undet_many": "yes" if len(v["undetermined"]) > 1 else None,
        "hold": duration(v["hold_median_s"], dfh, sf),
        "out_hub": n(sh["out_hub"]) if (sh["n_out"] or 0) >= 2 else None, "n_out": n(sh["n_out"]),
        "in_hub": n(sh["in_hub"]) if (sh["n_in"] or 0) >= 2 else None, "n_in": n(sh["n_in"]),
        "gs_hub": n(sh["gs_hub"]), "gs_n_in": n(sh["gs_n_in"]), "gs_n_out": n(sh["gs_n_out"]),
        "depth": n(sh["depth"]) if (sh["depth"] or 0) >= 2 else None,
        "n_pairs": n(sh["n_pairs"]) if sh["n_pairs"] >= 2 else None,
        "loop": "yes" if sh["has_cycle"] else None,
        "top_edges": "; ".join(f"{e['from_id']}→{e['to_id']} ({amount(e['amount_ccy0'], e['currency'])}, "
                               f"weight {e['w_total']:.2f})" for e in v["top_edges"]) or None,
        "features_up": ", ".join(phrasing["features"][f["feature"]] for f in v["top_features"] if f["mean_shap"] > 0) or None,
        "features_down": ", ".join(phrasing["features"][f["feature"]] for f in v["top_features"] if f["mean_shap"] <= 0) or None,
        "n_banks": str(len(v["banks"])) if len(v["banks"]) >= 2 else None,
        "bank_list": id_list(v["banks"], lm) if len(v["banks"]) >= 2 else None,
    }
    return slots


# ----------------------------------------------------------------------------- clauses (step 3)

# (clause id, text, required slots). Slots are written {name}; a clause is used only if every slot it names
# and every slot in `required` has a value. Order in the sentence = order here.
CLAUSES = {
    "head": ("{type_name} ring (most likely shape, p = {p}): {n_members} accounts, {n_edges} transactions over {window}.", ()),
    "head_untyped": ("Suspected ring: {n_members} accounts, {n_edges} transactions over {window}.", ()),
    "fan_out": ("Account {out_hub} paid {n_out} different accounts.", ()),
    "fan_in": ("Account {in_hub} was paid by {n_in} different accounts.", ()),
    "gather_scatter": ("Account {gs_hub} gathered money from {gs_n_in} accounts and passed it on to {gs_n_out}.", ()),
    "scatter_gather": ("Money spread out from {src_list}, passed through {mule_list} and came together at {sink_list}.", ()),
    "cycle": ("Money travelled in a loop through the accounts.", ("loop",)),
    "stack": ("Funds moved {depth} hops from {src_list} to {sink_list} through {mule_list}.", ()),
    "stack_hold": ("Each intermediary passed money on within a median of {hold}.", ()),
    "bipartite": ("It splits into {n_pairs} separate sender-receiver pairs.", ()),
    "roles_both": ("Money starts at {src_list} and ends at {sink_list}.", ()),
    "roles_src": ("Money starts at {src_list}.", ("no_sink",)),
    "roles_sink": ("Money ends at {sink_list}.", ("no_src",)),
    "roles_mule": ("Intermediaries: {mule_list}.", ()),
    "undet_one": ("Account {undet_list} uses currency {ccy1}, which has no exchange rate, so its role cannot be checked.", ("undet_one",)),
    "undet_many": ("Accounts {undet_list} use currency {ccy1}, which has no exchange rate, so their roles cannot be checked.", ("undet_many",)),
    "money": ("Total moved: {total} in currency {ccy0}.", ("no_partial",)),
    "money_partial": ("Total moved: {total} in currency {ccy0}, partial: transactions in currency {ccy1} have no exchange rate.", ("partial",)),
    "closure": ("{closure_pct}% of the money sent by the sources reached the sinks.", ()),
    "no_closure": ("Conservation cannot be measured: no account only sends or only receives.", ("no_closure",)),
    "evidence": ("Strongest evidence: {top_edges}.", ()),
    "features_both": ("Signals from a reference transaction-level model that raised suspicion: {features_up}; that lowered it: {features_down}.", ()),
    "features_up": ("Signals from a reference transaction-level model that raised suspicion: {features_up}.", ("no_down",)),
    "features_down": ("Signals from a reference transaction-level model that lowered suspicion: {features_down}.", ("no_up",)),
    "banks": ("The accounts span {n_banks} banks ({bank_list}).", ()),
    "banks_short": ("The accounts span {n_banks} banks.", ()),     # only as the shorter stand-in for "banks"
}

COMMON_TAIL = ["undet_one", "undet_many", "money", "money_partial", "closure", "no_closure", "evidence", "features_both",
               "features_up", "features_down", "banks"]
ROLE_CLAUSES = ["roles_both", "roles_src", "roles_sink", "roles_mule"]
TEMPLATES = {
    "FAN-OUT": ["head", "fan_out", *ROLE_CLAUSES, *COMMON_TAIL],
    "FAN-IN": ["head", "fan_in", *ROLE_CLAUSES, *COMMON_TAIL],
    "GATHER-SCATTER": ["head", "gather_scatter", *ROLE_CLAUSES, *COMMON_TAIL],
    "SCATTER-GATHER": ["head", "scatter_gather", *ROLE_CLAUSES, *COMMON_TAIL],
    "CYCLE": ["head", "cycle", *ROLE_CLAUSES, *COMMON_TAIL],
    "STACK": ["head", "stack", "stack_hold", *ROLE_CLAUSES, *COMMON_TAIL],
    "BIPARTITE": ["head", "bipartite", *ROLE_CLAUSES, *COMMON_TAIL],
    "RANDOM": ["head", *ROLE_CLAUSES, *COMMON_TAIL],
}
FALLBACK = ["head_untyped", *ROLE_CLAUSES, *COMMON_TAIL]       # 'UNKNOWN' or a type without a template
# Dropped one at a time, in this order, while the narrative is over max_words. A clause listed in SHORTER is first
# replaced by its shorter form (the bank count without the list) and only dropped when it comes up again.
DROP_ORDER = ["roles_mule", "roles_both", "roles_src", "roles_sink", "stack_hold", "banks", "banks_short",
              "features_both", "features_up", "features_down", "closure", "no_closure"]
SHORTER = {"banks": "banks_short"}
# Role clauses are left out where the type clause already names the roles.
ROLES_IN_TYPE_CLAUSE = {"scatter_gather", "stack"}

SLOT = re.compile(r"{(\w+)}")


def _flags(slots: dict) -> dict:
    return {**slots, "no_sink": "yes" if slots["sink_list"] is None else None,
            "no_src": "yes" if slots["src_list"] is None else None,
            "no_partial": None if slots["partial"] else "yes",
            "no_up": "yes" if slots["features_up"] is None else None,
            "no_down": "yes" if slots["features_down"] is None else None}


def choose_clauses(v: dict, slots: dict, max_words: int) -> list[str]:
    """The clause ids used, in order: every clause whose slots all have values, then the drop rule."""
    f = _flags(slots)
    names = TEMPLATES.get(v["topology_type"], FALLBACK) if f["type_name"] else FALLBACK
    if f["type_name"] and f["p"] is None:
        names = ["head_untyped" if c == "head" else c for c in names]
    usable = []
    for c in names:
        text, required = CLAUSES[c]
        if all(f.get(k) is not None for k in (*SLOT.findall(text), *required)):
            usable.append(c)
    if ROLES_IN_TYPE_CLAUSE & set(usable):
        usable = [c for c in usable if c not in ROLE_CLAUSES]
    for c in DROP_ORDER:
        if word_count(render(usable, slots)) <= max_words:
            break
        if c in usable:
            if c in SHORTER:
                usable[usable.index(c)] = SHORTER[c]
            else:
                usable.remove(c)
    return usable


def render(clause_ids: list[str], slots: dict) -> str:
    return " ".join(CLAUSES[c][0].format(**slots) for c in clause_ids)


def build_narrative(v: dict, phrasing: dict, settings: dict) -> tuple[str, dict]:
    """(narrative, evidence_summary). evidence_summary holds the values, the slots as substituted, the clauses."""
    slots = format_slots(v, phrasing, settings)
    clauses = choose_clauses(v, slots, int(settings["max_words"]))
    text = render(clauses, slots)
    if word_count(text) > int(settings["max_words"]):
        raise ValueError(f"narrative has {word_count(text)} words after every optional clause was dropped")
    used = sorted({k for c in clauses for k in SLOT.findall(CLAUSES[c][0])})
    summary = {"values": v, "clauses": clauses, "slots": {k: slots[k] for k in used}, "template": v["topology_type"]
               if TEMPLATES.get(v["topology_type"]) and "head" in clauses else "FALLBACK"}
    return text, summary


def summary_json(summary: dict) -> str:
    return json.dumps(summary, sort_keys=True, ensure_ascii=False, allow_nan=False)


def regenerate(summary: dict | str, phrasing: dict, settings: dict) -> str:
    """XR-31: rebuild the sentence from the stored values only."""
    if isinstance(summary, str):
        summary = json.loads(summary)
    text, again = build_narrative(summary["values"], phrasing, settings)
    if again["clauses"] != summary["clauses"] or again["slots"] != summary["slots"]:
        raise ValueError("stored clauses / slots differ from what the stored values give")
    return text
