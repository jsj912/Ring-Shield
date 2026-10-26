"""Write the dashboard's ring fixtures (NFR-D55): synthetic rings in the API's own field names.

    python platform/frontend/fixtures/make_fixtures.py

Fixture Bank A (1001) gets one ring per AMLworld pattern type, a 120-account ring, a cross-bank
ring and 190 filler rings, so the queue pages through 200; Fixture Bank B (1002) gets one ring.
Every value is invented with a fixed seed. Nothing is real data, a label or a pattern id.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random

OUT = Path(__file__).resolve().parent / "rings"
DAY8 = datetime(2022, 9, 9, tzinfo=timezone.utc)          # test day 8 in the loader basis
PATTERNS = ["FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER", "CYCLE", "RANDOM", "BIPARTITE", "STACK"]
CURRENCIES = ["US Dollar", "Euro", "Yen", "UK Pound"]
FEATURES = [("fan_out", "Sender pays many accounts"), ("fan_in", "Receiver paid by many accounts"),
            ("Amount Sent", "Amount sent"), ("Amount Received", "Amount received"),
            ("Payment Format", "Payment format"), ("scatter_gather", "Scatter-gather motif"),
            ("deg_in_src", "Sender's incoming payments"), ("deg_out_dst", "Receiver's outgoing payments"),
            ("hour_of_day", "Hour of day"), ("temporal_cycle", "Money returns to its sender"),
            ("gather_scatter", "Gather-scatter motif")]


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _shape(pattern: str, n: int, rng: random.Random) -> list[tuple[int, int]]:
    """Directed edges (index pairs) giving the pattern's shape over n accounts."""
    if pattern == "FAN-OUT":
        return [(0, i) for i in range(1, n)]
    if pattern == "FAN-IN":
        return [(i, 0) for i in range(1, n)]
    if pattern == "GATHER-SCATTER":
        hub = n // 2
        return [(i, hub) for i in range(hub)] + [(hub, i) for i in range(hub + 1, n)]
    if pattern == "SCATTER-GATHER":
        return [(0, i) for i in range(1, n - 1)] + [(i, n - 1) for i in range(1, n - 1)]
    if pattern == "CYCLE":
        return [(i, (i + 1) % n) for i in range(n)]
    if pattern == "BIPARTITE":
        half = n // 2
        return [(i, j) for i in range(half) for j in range(half, n) if (i + j) % 2 == 0]
    if pattern == "STACK":
        third = n // 3
        layers = [range(0, third), range(third, 2 * third), range(2 * third, n)]
        return [(a, b) for left, right in zip(layers, layers[1:]) for a in left for b in right if rng.random() < 0.6]
    edges = [(i, i + 1) for i in range(n - 1)]                                    # RANDOM / large
    edges += [(rng.randrange(n), rng.randrange(n)) for _ in range(n // 3)]
    return [(a, b) for a, b in edges if a != b]


def _roles(pattern: str, n: int, edges: list[tuple[int, int]]) -> list[str]:
    outs = {a for a, _ in edges}
    ins = {b for _, b in edges}
    roles = []
    for i in range(n):
        if pattern == "CYCLE":
            roles.append("mule")
        elif i in outs and i not in ins:
            roles.append("source")
        elif i in ins and i not in outs:
            roles.append("sink")
        elif i in ins and i in outs:
            roles.append("mule")
        else:
            roles.append("peripheral")
    if n > 3:
        roles[-1] = "holder" if pattern in {"FAN-IN", "GATHER-SCATTER"} else roles[-1]
    return roles


def make_ring(*, tenant_id: int, index: int, pattern: str, n_members: int, rng: random.Random,
              cross_bank: bool = False, status: str = "open", conversion_loops: int = 1,
              undetermined: int = 0) -> dict:
    ring_id = f"full-gine_causal-1-{index}"
    accounts = [tenant_id * 1_000_000 + index * 1_000 + i for i in range(n_members)]
    shape = _shape(pattern, n_members, rng)
    roles = _roles(pattern, n_members, shape)
    for i in range(undetermined):
        roles[i + 1] = "undetermined"
    start = DAY8 + timedelta(hours=rng.uniform(0, 40))
    banks = [tenant_id] * n_members
    if cross_bank:
        for i in range(1, n_members, 2):
            banks[i] = 9100 + i
    edges, edge_weights = [], []
    for k, (a, b) in enumerate(shape):
        when = start + timedelta(minutes=17 * k + rng.randint(0, 9))
        amount = round(rng.uniform(800, 40_000), 2)
        currency = CURRENCIES[0] if rng.random() < 0.8 else rng.choice(CURRENCIES[1:])
        edge_id = index * 10_000 + k
        edges.append({"edge_id": edge_id, "source_account": accounts[a], "target_account": accounts[b],
                      "timestamp": _iso(when), "amount_sent": amount, "amount_received": amount,
                      "currency_sent": currency, "currency_received": currency,
                      "payment_format": rng.choice(["ACH", "Wire", "Cheque", "Credit Card"]),
                      "calibrated_score": round(rng.uniform(0.2, 0.99), 4), "is_seed": k % 3 == 0,
                      "is_conversion": False})
        w_score, w_flow, w_loo = round(rng.random(), 4), round(rng.random(), 4), round(rng.random(), 4)
        edge_weights.append({"edge_id": edge_id, "w_total": round(0.6 * w_score + 0.4 * w_flow, 4),
                             "w_score": w_score, "w_loo": w_loo, "w_flow": w_flow})
    for k in range(conversion_loops):                      # currency-conversion self-loops (change 2)
        account = accounts[(k + 1) % n_members]
        edges.append({"edge_id": index * 10_000 + 9_000 + k, "source_account": account, "target_account": account,
                      "timestamp": _iso(start + timedelta(minutes=5 + k)), "amount_sent": 1000.0,
                      "amount_received": 140000.0, "currency_sent": "US Dollar", "currency_received": "Yen",
                      "payment_format": "Reinvestment", "calibrated_score": 0.01, "is_seed": False,
                      "is_conversion": True})
    end = max(datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) for e in edges)
    member_edges = [e["edge_id"] for e in edges]
    seed_edges = [e["edge_id"] for e in edges if e["is_seed"]]
    closed_loop = pattern == "CYCLE"
    total = round(sum(e["amount_sent"] for e in edges if not e["is_conversion"]), 2)
    partial = any(e["currency_sent"] == "Yen" for e in edges if not e["is_conversion"]) and index % 2 == 0
    topology_prob = round(rng.uniform(0.35, 0.95), 16)
    nodes = [{"account_id": accounts[i], "bank_code": banks[i],
              "bank_label": f"Bank {banks[i]}" if banks[i] != tenant_id else None,
              "is_source": roles[i] == "source", "is_sink": roles[i] == "sink", "is_mule": roles[i] == "mule"}
             for i in range(n_members)]
    account_weights = [{"account_id": accounts[i], "role": roles[i],
                        "inflow": round(rng.uniform(0, 50_000), 2), "outflow": round(rng.uniform(0, 50_000), 2),
                        "hold_time_s": None if roles[i] in {"source", "sink"} else rng.randint(600, 90_000),
                        "w_account": round(rng.random(), 4)} for i in range(n_members)]
    feature_weights = [{"feature_name": name, "display_name": label, "mean_shap": round(rng.uniform(-2.2, 2.2), 4),
                        "top_edge_id": seed_edges[0] if seed_edges else member_edges[0]}
                       for name, label in FEATURES]
    counterparty = sorted({f"Bank {b}" for b in banks if b != tenant_id})
    summary = {
        "ring_id": ring_id, "tenant_id": tenant_id, "topology_type": pattern, "topology_prob": topology_prob,
        "n_members": n_members, "n_edges": len(edges), "total_amount": total, "total_currency": "US Dollar",
        "total_partial": partial, "n_currencies": 2 if partial else 1,
        "start_time": _iso(start), "end_time": _iso(end), "window_text": f"over {round((end - start).total_seconds() / 3600, 1):g} h",
        "confidence": round(rng.uniform(0.3, 0.99), 4), "cross_bank": bool(counterparty),
        "counterparty_banks": counterparty, "status": status,
    }
    detail = {**summary, "member_accounts": accounts, "member_edges": member_edges, "seed_edges": seed_edges,
              "expanded_edges": [e for e in member_edges if e not in seed_edges],
              "conservation_closure": None if closed_loop else round(rng.uniform(0.6, 1.0), 4),
              "source_accounts": [a for a, r in zip(accounts, roles) if r == "source"],
              "sink_accounts": [a for a, r in zip(accounts, roles) if r == "sink"],
              "mule_accounts": [a for a, r in zip(accounts, roles) if r == "mule"],
              "model_id": "gine_causal", "aggregator_id": "full"}
    narrative = (f"{pattern.title()} ring (most likely shape, p={topology_prob:.2f}): {n_members} accounts, "
                 f"{len(shape)} transactions over {summary['window_text'].removeprefix('over ')}. "
                 f"Fixture narrative for display tests; every number here is synthetic.")
    explanation = {
        "tenant_id": tenant_id, "ring_id": ring_id, "explainer_version": "0.5.0-review", "revision": 1,
        "regenerated": False, "edge_weights": edge_weights, "account_weights": account_weights,
        "feature_weights": feature_weights, "narrative": narrative,
        "evidence_summary": {"template": pattern.lower(), "values": {"currency_hub_name": "US Dollar",
                                                                      "closure_partial": False}},
        "latency_ms": rng.randint(150, 1900),
        "provenance": {"flow_total_ccy0": total, "flow_partial": partial, "rings_schema_version": 2,
                       "explainer_version": "0.5.0-review", "feature_scope": "tenant_view"},
        "created_at": _iso(end + timedelta(hours=1)), "regenerating": False,
    }
    evidence = {"tenant_id": tenant_id, "ring_id": ring_id, "nodes": nodes, "edges": edges,
                "next_before_edge_id": None, "missing_edge_ids": []}
    weights_by_account = {item["account_id"]: item for item in account_weights}
    weights_by_edge = {item["edge_id"]: item for item in edge_weights}
    subgraph = {
        "tenant_id": tenant_id, "ring_id": ring_id, "n_accounts": n_members,
        "nodes": [{"account_id": node["account_id"], "role": weights_by_account[node["account_id"]]["role"],
                   "bank_code": node["bank_code"], "bank_label": f"Bank {node['bank_code']}",
                   **{key: weights_by_account[node["account_id"]][key]
                      for key in ("inflow", "outflow", "hold_time_s", "w_account")}} for node in nodes],
        "edges": [{"edge_id": e["edge_id"], "from_id": e["source_account"], "to_id": e["target_account"],
                   "timestamp": e["timestamp"], "amount": e["amount_sent"], "currency": e["currency_sent"],
                   "amount_received": e["amount_received"], "currency_received": e["currency_received"],
                   "payment_format": e["payment_format"], "is_seed": e["is_seed"],
                   "is_conversion": e["is_conversion"],
                   **{key: weights_by_edge.get(e["edge_id"], {}).get(key)
                      for key in ("w_total", "w_score", "w_loo", "w_flow")}} for e in edges],
    }
    verdicts = []
    if status != "open":
        by_supervisor = tenant_id == 1001 and index % 4 == 3      # two analysts to filter on
        verdicts.append({"verdict_id": index * 10 + 1, "ring_id": ring_id,
                         "user_id": (2 if by_supervisor else 1) if tenant_id == 1001 else 3,
                         "user_name": ("supervisor@bank-a.fixture" if by_supervisor else "analyst@bank-a.fixture")
                         if tenant_id == 1001 else "analyst@bank-b.fixture",
                         "verdict": {"confirmed": "confirm", "rejected": "reject", "partial": "partial"}[status],
                         "corrected_members": accounts[:2] if status == "partial" else [],
                         "corrected_edges": [], "note": "<b>fixture</b> note, shown as text",
                         "is_simulated": index % 5 == 0, "created_at": _iso(end + timedelta(hours=3)),
                         "regeneration": None})
    return {"tenant_id": tenant_id, "summary": summary, "detail": detail, "evidence": evidence,
            "explanation": explanation, "subgraph": subgraph, "verdicts": verdicts}


def main() -> None:
    rng = random.Random(20261024)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    rings = []
    for index, pattern in enumerate(PATTERNS):
        rings.append(make_ring(tenant_id=1001, index=index, pattern=pattern, n_members=6 if pattern != "BIPARTITE" else 8,
                               rng=rng, undetermined=1 if pattern == "RANDOM" else 0,
                               status="confirmed" if pattern == "FAN-IN" else "open"))
    rings.append(make_ring(tenant_id=1001, index=8, pattern="RANDOM", n_members=120, rng=rng))
    rings.append(make_ring(tenant_id=1001, index=9, pattern="SCATTER-GATHER", n_members=7, rng=rng, cross_bank=True))
    for index in range(10, 200):
        rings.append(make_ring(tenant_id=1001, index=index, pattern=PATTERNS[index % 8], n_members=3 + index % 5,
                               rng=rng, conversion_loops=index % 2,
                               status=["open", "open", "open", "confirmed", "rejected", "partial"][index % 6]))
    rings.append(make_ring(tenant_id=1002, index=500, pattern="FAN-OUT", n_members=5, rng=rng))
    for ring in rings:
        name = f"{ring['tenant_id']}_{ring['summary']['ring_id']}.json"
        (OUT / name).write_text(json.dumps(ring, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(rings)} rings to {OUT}")


if __name__ == "__main__":
    main()
