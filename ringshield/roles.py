"""Account roles inside a ring and a cheap re-grouping call for the XAI layer (Step 8.1).

    roles = account_roles(ring, scored_edges)
    # {account_id: {"role": "mule", "inflow": 9990.0, "outflow": 9980.0, "hold_time_s": 7200.0,
    #               "closure": 0.999, "n_in": 1, "n_out": 1}}

    out = rerun_ring(subgraph_edges, "full", affinity=aff, cut=0.5, min_size=3)
    # {"confidence": 0.83, "n_rings": 2, "largest_ring_edges": [1001, 1002, 1005]}

Both are the functions promised to the XAI layer (`docs/CLI.md` section 6).

`account_roles(ring, scored_edges)` sums the flows of the ring's edges inside
[start_time, end_time] per account, with amounts **deduplicated** on
(from_id, to_id, timestamp, amount) -- AMLworld repeats a few transactions and a duplicate
would double one side of a balance. Roles and thresholds come from `configs/roles.yaml`
(tau_role 0.25, hold 72 h), the same values the Step 7 pair features use. `edges="included"`
(default) scores the ring's seed + expanded edges -- what the aggregator actually used;
`edges="member"` scores every member edge instead.

`rerun_ring(subgraph_edges, aggregator_id)` re-runs **only the grouping stage** on the edges
given, never the expansion and never a read of the full graph: for `cc` it is connected
components plus the size filter, for `full` it is the pair affinity plus average linkage at the
val-chosen cut. `confidence` follows the contract: mean `score_calibrated` over the group's seed
edges x its conservation closure.

For leave-one-out the XAI layer should build a `RingRerunner` once per ring and call
`.without(edge_id)` per member edge: the index, the GFP / embedding context and the amount
percentile are then computed once for the whole ring instead of once per call (a 30-edge ring:
~34 ms per call standalone, ~8 ms through the cache), and every call sees the same feature
scaling, as the aggregator did when it built the ring.

The result carries **`features_degraded`**: True when the `full` grouping ran without the GFP
table or without embeddings, so `cos_gfp` / `cos_emb` were zero / NaN rather than the values the
rings were built with. Leave-one-out weights computed on a degraded feature set are not
comparable with the shipped rings -- pass `gfp=` and `emb=` (slices restricted to the ring are
enough) to get `features_degraded: False`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES_YAML = REPO_ROOT / "configs" / "roles.yaml"
ROLES = ("source", "sink", "mule", "holder", "peripheral")
_CFG: dict | None = None


def load_roles_config(path: Path = ROLES_YAML) -> dict:
    global _CFG
    if _CFG is None or path != ROLES_YAML:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert tuple(cfg["roles"]) == ROLES, cfg["roles"]
        if path == ROLES_YAML:
            _CFG = cfg
        return cfg
    return _CFG


def dedup_edges(df: pd.DataFrame, amount_col: str | None = None) -> pd.DataFrame:
    """Drop repeated transactions on (from_id, to_id, timestamp, amount)."""
    amount_col = amount_col or ("amount_received" if "amount_received" in df.columns else "amount")
    return df[~df.duplicated(["from_id", "to_id", "timestamp", amount_col])]


def _hold_times(ins: np.ndarray, outs: np.ndarray) -> float:
    """Median over inflows of the wait to the first outflow at or after it (NaN if none)."""
    if len(ins) == 0 or len(outs) == 0:
        return math.nan
    ins, outs = np.sort(ins), np.sort(outs)
    j = np.searchsorted(outs, ins, side="left")
    ok = j < len(outs)
    if not ok.any():
        return math.nan
    return float(np.median(outs[j[ok]] - ins[ok]))


def next_outflow_gaps(acc_in: np.ndarray, ts_in: np.ndarray, acc_out: np.ndarray, ts_out: np.ndarray):
    """For every inflow, the wait to the first outflow at or after it AT THE SAME account (NaN if
    none). Vectorised through the composite key account * 2**32 + timestamp, as in
    ringshield/expand/index.py -- the per-account python loop it replaces dominated rerun_ring."""
    if len(acc_in) == 0 or len(acc_out) == 0:
        return np.full(len(acc_in), np.nan)
    shift = np.int64(1) << np.int64(32)
    order = np.argsort(acc_out.astype(np.int64) * shift + ts_out, kind="stable")
    ao, to = acc_out[order], ts_out[order]
    keys = ao.astype(np.int64) * shift + to
    j = np.searchsorted(keys, acc_in.astype(np.int64) * shift + ts_in, side="left")
    ok = (j < len(keys))
    gaps = np.full(len(acc_in), np.nan)
    if ok.any():
        jj = j[ok]
        same = ao[jj] == acc_in[ok]
        idx = np.flatnonzero(ok)[same]
        gaps[idx] = to[jj[same]] - ts_in[idx]
    return gaps


def flows_of(edges: pd.DataFrame, amount_col: str | None = None) -> pd.DataFrame:
    """Per account: inflow / outflow sums and counts, closure and hold time over `edges`."""
    amount_col = amount_col or ("amount_received" if "amount_received" in edges.columns else "amount")
    e = dedup_edges(edges, amount_col)
    cols = ["account", "inflow", "outflow", "n_in", "n_out", "closure", "hold_time_s"]
    if len(e) == 0:
        return pd.DataFrame(columns=cols)
    f = e["from_id"].to_numpy(np.int64)
    t = e["to_id"].to_numpy(np.int64)
    ts = e["timestamp"].to_numpy(np.int64)
    amt = e[amount_col].to_numpy(float)
    accounts, inv = np.unique(np.concatenate([f, t]), return_inverse=True)
    n = len(accounts)
    fi, ti = inv[:len(f)], inv[len(f):]
    out_sum = np.bincount(fi, weights=amt, minlength=n)
    in_sum = np.bincount(ti, weights=amt, minlength=n)
    out_cnt = np.bincount(fi, minlength=n)
    in_cnt = np.bincount(ti, minlength=n)
    hi = np.maximum(in_sum, out_sum)
    with np.errstate(divide="ignore", invalid="ignore"):
        closure = np.where(hi > 0, np.minimum(in_sum, out_sum) / np.where(hi > 0, hi, 1.0), 0.0)
    gaps = next_outflow_gaps(ti, ts, fi, ts)
    hold = np.full(n, np.nan)
    ok = ~np.isnan(gaps)
    if ok.any():
        hold_by = pd.Series(gaps[ok]).groupby(ti[ok]).median()
        hold[hold_by.index.to_numpy()] = hold_by.to_numpy()
    return pd.DataFrame({"account": accounts, "inflow": in_sum, "outflow": out_sum, "n_in": in_cnt, "n_out": out_cnt,
                         "closure": closure, "hold_time_s": hold}, columns=cols)


CURRENCY_MODES = ("raw", "partitioned", "converted")
# Fixed by construction and deliberately not swept: an account must spend at least this
# share of BOTH its inflow and its outflow in currencies present on both sides before a
# same-currency balance is treated as decisive. Below it the role is `undetermined`.
CCY_MIN_TWO_SIDED_SHARE = 0.5
CURRENCY_COLS = ("currency_received", "received_currency", "Received Currency", "currency_sent")


def _currency_column(edges: pd.DataFrame) -> str | None:
    for c in CURRENCY_COLS:
        if c in edges.columns:
            return c
    return None


def flows_by_currency(edges: pd.DataFrame, amount_col: str | None = None) -> pd.DataFrame:
    """Per (account, currency): inflow / outflow sums and counts.

    Why this exists (Step 14). AMLworld amounts carry a currency code and **55.2 % of test rings
    span more than one**, with median amounts differing by ~140x between codes, so `inflow /
    outflow` over raw sums compares mismatched units. This splits the flows so a ratio is only ever
    taken within one currency.

    SUPERSEDED 2026-10-14; kept because the published v2 artefacts were computed with it.
    Two claims in the original docstring were false, both found by the XAI teammate:

      * "no single edge is cross-currency" -- 13,627 test edges (1.58 %) have
        `currency_sent != currency_received`, 96.95 % of them self-loops: one account converting.
        Neither claim had ever been measured before it was written down.
      * "51.9 % of ring-accounts ... disjoint in/out currency sets" -- not reproducible. It is 521
        of 881 two-sided ring-accounts (59.1 %), or 521 of 4,280 (12.2 %).

    Prefer `flows_converted` / `account_roles(..., currency="converted")`: it books the sender's
    leg from `amount_sent` / `currency_sent` (this function books BOTH legs from the receiver's
    column pair) and converts with the generator's own fixed rates, leaving 3 of 4,280 accounts
    undetermined instead of 571. See docs/PITFALLS.md 3b and 3c.
    """
    amount_col = amount_col or ("amount_received" if "amount_received" in edges.columns else "amount")
    cur = _currency_column(edges)
    e = dedup_edges(edges, amount_col)
    cols = ["account", "currency", "inflow", "outflow", "n_in", "n_out"]
    if len(e) == 0 or cur is None:
        return pd.DataFrame(columns=cols)
    inn = pd.DataFrame({"account": e["to_id"].to_numpy(np.int64), "currency": e[cur].to_numpy(),
                        "amt": e[amount_col].to_numpy(float)})
    out = pd.DataFrame({"account": e["from_id"].to_numpy(np.int64), "currency": e[cur].to_numpy(),
                        "amt": e[amount_col].to_numpy(float)})
    gi = inn.groupby(["account", "currency"])["amt"].agg(["sum", "size"])
    go = out.groupby(["account", "currency"])["amt"].agg(["sum", "size"])
    j = gi.join(go, how="outer", lsuffix="_in", rsuffix="_out").fillna(0.0)
    j = j.reset_index().rename(columns={"sum_in": "inflow", "sum_out": "outflow",
                                        "size_in": "n_in", "size_out": "n_out"})
    j["n_in"] = j["n_in"].astype(np.int64)
    j["n_out"] = j["n_out"].astype(np.int64)
    return j[cols]


FX_RATES_PATH = Path(__file__).resolve().parents[1] / "contract" / "fx_rates.json"
_FX: dict | None = None


def load_fx_rates(path: Path | None = None) -> dict:
    """`contract/fx_rates.json`: {currency -> rate to currency 0}, plus the unconvertible list.

    Built by `contract/make_fx_rates.py` from the train split's own cross-currency transactions.
    The rates are the generator's fixed constants, not estimates -- round trip and triangle close
    to 3e-5 -- so there is nothing here to tune or seed. See docs/FX_RATES.md.
    """
    global _FX
    if _FX is not None and path is None:
        return _FX
    f = path or FX_RATES_PATH
    if not f.exists():
        raise FileNotFoundError(
            f"{f} missing; run `python contract/make_fx_rates.py` (currency='converted' needs it)")
    d = json.loads(f.read_text(encoding="utf-8"))
    table = {int(k): v["rate_to_ccy0"] for k, v in d["rate_to_ccy0"].items()}
    out = {"rate_to_ccy0": table,
           "unconvertible": {int(c) for c in d.get("unconvertible", [])},
           "hub": int(d.get("hub_currency", 0)), "meta": d}
    if path is None:
        _FX = out
    return out


def _to_hub(amount: np.ndarray, currency: np.ndarray, fx: dict) -> tuple[np.ndarray, np.ndarray]:
    """(converted amounts, convertible mask). An unconvertible currency yields NaN, never a guess."""
    rates = np.full(len(amount), np.nan)
    table = fx["rate_to_ccy0"]
    for c in np.unique(currency):
        r = table.get(int(c))
        if r is not None:
            rates[currency == c] = float(r)
    return amount.astype(float) * rates, np.isfinite(rates)


def flows_converted(edges: pd.DataFrame, amount_col: str | None = None,
                    fx: dict | None = None) -> pd.DataFrame:
    """`flows_of`'s columns, with the two defects of the raw path repaired.

    1. **Leg booking.** The raw path sums one amount column over both legs, so a sender's outflow
       is recorded at the *receiver's* amount and currency. AMLworld has 13,627 cross-currency test
       edges (1.58 %), 96.95 % of them self-loops -- an account converting currency. On those the
       raw booking reports one currency on both sides at one amount, which reads as a perfectly
       balanced mule. Here the sender's leg is `amount_sent` in `currency_sent` and the receiver's
       is `amount_received` in `currency_received`.
    2. **Comparability.** Both legs are converted to currency 0 with the generator's own fixed
       rates (`contract/fx_rates.json`), so inflow and outflow are in one unit and the raw role
       rule applies unchanged.

    An account touching a currency with no usable rate (in HI-Small that is Bitcoin, code 1: one
    BTC is ~11,900 USD, so a typical amount is a two-decimal fraction and the implied rate is
    rounding noise) gets `closure` NaN and `ccy_unconvertible` True, and
    `account_roles` reports it `undetermined`. Withholding, not guessing -- the same discipline the
    partitioned mode introduced, now needed for far fewer accounts.
    """
    amount_col = amount_col or ("amount_received" if "amount_received" in edges.columns else "amount")
    fx = fx or load_fx_rates()
    e = dedup_edges(edges, amount_col)
    cols = ["account", "inflow", "outflow", "n_in", "n_out", "closure", "hold_time_s"]
    if len(e) == 0:
        return pd.DataFrame(columns=cols + ["ccy_unconvertible", "n_currencies"])

    has = "currency_sent" in e.columns and "currency_received" in e.columns
    if not has:                       # no currency columns: fall back to raw and say so
        base = flows_of(edges, amount_col)
        return base.assign(ccy_unconvertible=False, n_currencies=0)

    amt_in = e["amount_received"].to_numpy(float)
    amt_out = (e["amount_sent"].to_numpy(float) if "amount_sent" in e.columns else amt_in)
    cur_in = e["currency_received"].to_numpy()
    cur_out = e["currency_sent"].to_numpy()
    v_in, ok_in = _to_hub(amt_in, cur_in, fx)
    v_out, ok_out = _to_hub(amt_out, cur_out, fx)

    rin = pd.DataFrame({"acc": e["to_id"].to_numpy(np.int64), "v": v_in, "ok": ok_in,
                        "ccy": cur_in, "ts": e["timestamp"].to_numpy(np.int64)})
    rout = pd.DataFrame({"acc": e["from_id"].to_numpy(np.int64), "v": v_out, "ok": ok_out,
                         "ccy": cur_out, "ts": e["timestamp"].to_numpy(np.int64)})
    gi = rin.groupby("acc").agg(inflow=("v", "sum"), n_in=("v", "size"), ok_in=("ok", "all"))
    go = rout.groupby("acc").agg(outflow=("v", "sum"), n_out=("v", "size"), ok_out=("ok", "all"))
    j = gi.join(go, how="outer")
    j[["inflow", "outflow"]] = j[["inflow", "outflow"]].fillna(0.0)
    j[["n_in", "n_out"]] = j[["n_in", "n_out"]].fillna(0).astype(np.int64)
    # `where`, not `fillna`: the outer join gives an account present on only one side an
    # OBJECT-dtype ok_in/ok_out (bool mixed with NaN), and filling an object column is what
    # pandas 2.2 deprecates ("Downcasting object dtype arrays on .fillna ... is deprecated").
    # The NaN means "no edges on that side", and `all()` over no edges is vacuously True, which
    # is what the fill encoded. Verified identical on raw, partitioned and converted.
    for c in ("ok_in", "ok_out"):
        j[c] = j[c].where(j[c].notna(), True).astype(bool)
    bad = ~(j["ok_in"] & j["ok_out"])

    hi = np.maximum(j["inflow"].to_numpy(float), j["outflow"].to_numpy(float))
    lo = np.minimum(j["inflow"].to_numpy(float), j["outflow"].to_numpy(float))
    with np.errstate(divide="ignore", invalid="ignore"):
        closure = np.where(hi > 0, lo / np.where(hi > 0, hi, 1.0), 0.0)
    closure = np.where(bad.to_numpy(), np.nan, closure)       # no rate -> no closure

    ccy = pd.concat([rin[["acc", "ccy"]], rout[["acc", "ccy"]]]).groupby("acc")["ccy"].nunique()
    base = flows_of(edges, amount_col).set_index("account")    # hold times are currency-free
    out = pd.DataFrame({
        "account": j.index.to_numpy(np.int64),
        "inflow": j["inflow"].to_numpy(float), "outflow": j["outflow"].to_numpy(float),
        "n_in": j["n_in"].to_numpy(np.int64), "n_out": j["n_out"].to_numpy(np.int64),
        "closure": closure,
        "hold_time_s": base["hold_time_s"].reindex(j.index).to_numpy(float),
        "ccy_unconvertible": bad.to_numpy(),
        "n_currencies": ccy.reindex(j.index).fillna(0).to_numpy(np.int64)})
    return out[cols + ["ccy_unconvertible", "n_currencies"]]


def flows_partitioned(edges: pd.DataFrame, amount_col: str | None = None) -> pd.DataFrame:
    """`flows_of`'s columns, but closure is computed per currency and pooled over the currencies
    that appear on BOTH sides of the account. `closure` is NaN when no currency does -- the account
    received in one set of currencies and paid out in a disjoint set, and no ratio is meaningful.
    `inflow` / `outflow` remain the raw totals, for continuity with the v1 fields."""
    base = flows_of(edges, amount_col)
    per = flows_by_currency(edges, amount_col)
    cols = list(base.columns) + ["n_currencies", "ccy_undefined"]
    # note: flows_partitioned returns cols + ["ccy_undetermined"]
    if base.empty:
        return pd.DataFrame(columns=cols + ["ccy_undetermined"])
    if per.empty:                       # no currency column: fall back to raw, and say so
        base = base.assign(n_currencies=0, ccy_undefined=False, ccy_undetermined=False)
        return base[cols + ["ccy_undetermined"]]
    both = per[(per["inflow"] > 0) & (per["outflow"] > 0)].copy()
    # Vectorised on purpose: a groupby-apply returns a (0, n) frame rather than an empty Series
    # when no account has a two-sided currency, and the caller then maps a frame onto a column.
    both["_lo"] = np.minimum(both["inflow"].to_numpy(float), both["outflow"].to_numpy(float))
    both["_hi"] = np.maximum(both["inflow"].to_numpy(float), both["outflow"].to_numpy(float))
    g = both.groupby("account")[["_lo", "_hi"]].sum()
    closure = g["_lo"] / g["_hi"].replace(0.0, np.nan) if len(g) else pd.Series(dtype=float)
    ncur = per.groupby("account")["currency"].nunique()
    out = base.copy()
    out["closure"] = out["account"].map(closure)
    out["n_currencies"] = out["account"].map(ncur).fillna(0).astype(np.int64)
    # `undetermined`: no currency appears on both sides, OR the ones that do carry less than
    # ccy_min_two_sided_share of each side's flow. Either way the balance cannot be checked without
    # an exchange rate, so the role is WITHHELD rather than guessed.
    two_in = both.groupby("account")["inflow"].sum()
    two_out = both.groupby("account")["outflow"].sum()
    share_in = out["account"].map(two_in).fillna(0.0) / out["inflow"].replace(0.0, np.nan)
    share_out = out["account"].map(two_out).fillna(0.0) / out["outflow"].replace(0.0, np.nan)
    thin = (share_in.fillna(0.0) < CCY_MIN_TWO_SIDED_SHARE) | (share_out.fillna(0.0) < CCY_MIN_TWO_SIDED_SHARE)
    two_sided = (out["n_in"] > 0) & (out["n_out"] > 0)
    out["ccy_undefined"] = out["closure"].isna() & two_sided
    out["ccy_undetermined"] = two_sided & (out["closure"].isna() | thin)
    return out[cols + ["ccy_undetermined"]]


def role_of(inflow: float, outflow: float, closure: float, hold_time_s: float, cfg: dict) -> str:
    tau, hold = float(cfg["tau_role"]), float(cfg["hold_seconds"])
    if outflow <= 0:
        return "sink"
    if inflow <= 0:
        return "source"
    if closure >= 1 - tau:
        return "mule" if (not math.isnan(hold_time_s) and hold_time_s <= hold) else "holder"
    if inflow / outflow < tau:
        return "source"
    if outflow / inflow < tau:
        return "sink"
    return "peripheral"


def ring_edges_frame(ring, scored_edges: pd.DataFrame, edges: str = "included") -> pd.DataFrame:
    """The ring's edges inside its window, as rows of `scored_edges`."""
    assert edges in ("included", "member"), edges
    ids = (list(ring.seed_edges) + list(ring.expanded_edges)) if edges == "included" else list(ring.member_edges)
    se = scored_edges.set_index("edge_id") if scored_edges.index.name != "edge_id" else scored_edges
    sub = se.loc[[e for e in ids if e in se.index]].reset_index()
    return sub[(sub["timestamp"] >= ring.start_time) & (sub["timestamp"] <= ring.end_time)]


def account_roles(ring, scored_edges: pd.DataFrame, *, edges: str = "included",
                  config: dict | None = None, currency: str = "raw") -> dict[int, dict]:
    """{account: {role, inflow, outflow, hold_time_s, closure, n_in, n_out}} for the ring.

    `currency` (Step 14) selects the flow convention and **defaults to the shipped one**:

        "raw"          sums amounts across currency codes, as every artefact up to Step 13 does.
                       Byte-identical to the previous behaviour. This is what `conservation_closure`
                       and `confidence` in the rings contract are computed from, and what
                       `explainability/` treats as authoritative (`currency_policy: raw`).
        "partitioned"  compares inflow with outflow only within a currency; an account whose in and
                       out currency sets are disjoint gets closure NaN and is counted in
                       `n_accounts_ccy_undefined`. Feeds the v2 `*_ccy` contract fields.
                       **SUPERSEDED by "converted"** -- it was built on the false premise that no
                       edge is cross-currency and no rate is recoverable (docs/PITFALLS.md 3c).
        "converted"    the sender's leg from amount_sent / currency_sent and the receiver's from
                       amount_received / currency_received, both converted to currency 0 with the
                       generator's own fixed rates, then raw's role rule. This is the correct
                       convention. `undetermined` survives only for an account touching a currency
                       with no usable rate.

    The default is deliberately *not* the more correct option: changing it would silently move
    every shipped closure, confidence and role array, and the downstream XAI layer compares against
    this function's output. The correction ships beside the original, not in place of it.
    """
    assert currency in CURRENCY_MODES, f"currency must be one of {CURRENCY_MODES}, got {currency!r}"
    cfg = config or load_roles_config()
    frame = ring_edges_frame(ring, scored_edges, edges)
    f = {"raw": flows_of, "partitioned": flows_partitioned, "converted": flows_converted}[currency](frame)
    out = {}
    for r in f.itertuples(index=False):
        closure = float(r.closure)
        # role_of() reads closure >= 1 - tau as a mule/holder; an undefined closure must not be
        # allowed to masquerade as 0.0 (which would read as a source or sink), so it stays NaN and
        # role_of falls through on the inflow/outflow ratio alone.
        undet = ((currency == "partitioned" and bool(getattr(r, "ccy_undetermined", False)))
                 or (currency == "converted" and bool(getattr(r, "ccy_unconvertible", False))))
        # An undetermined account must NOT fall through to role_of: a NaN closure there would be
        # read as "unbalanced" and land on peripheral / source / sink, which asserts something the
        # evidence does not support.
        role = "undetermined" if undet else role_of(r.inflow, r.outflow, closure, r.hold_time_s, cfg)
        rec = {"role": role,
               "inflow": float(r.inflow), "outflow": float(r.outflow), "hold_time_s": float(r.hold_time_s),
               "closure": closure, "n_in": int(r.n_in), "n_out": int(r.n_out)}
        if currency == "partitioned":
            rec["n_currencies"] = int(getattr(r, "n_currencies", 0))
            rec["ccy_undefined"] = bool(getattr(r, "ccy_undefined", False))
            rec["ccy_undetermined"] = undet
        elif currency == "converted":
            rec["n_currencies"] = int(getattr(r, "n_currencies", 0))
            rec["ccy_unconvertible"] = undet
        out[int(r.account)] = rec
    return out


def role_arrays(roles: dict[int, dict], config: dict | None = None, *, currency: str = "raw") -> dict[str, list[int]]:
    """The rings contract's account arrays.

    `currency="raw"` fills the v1 trio (source_accounts / sink_accounts / mule_accounts).
    `currency="partitioned"` fills the v2 `*_ccy` quartet, including
    `undetermined_accounts_ccy` -- which exists so that an account whose balance cannot be checked
    is reported as such instead of being absorbed into another role."""
    cfg = config or load_roles_config()
    # "converted" deliberately reuses the v1 array names: it is the corrected version of the same
    # quantity, and there is no schema bump in this change.
    key = "contract_arrays_ccy" if currency == "partitioned" else "contract_arrays"
    return {col: sorted(a for a, d in roles.items() if d["role"] in set(members))
            for col, members in cfg[key].items()}


def conservation_totals(roles: dict[int, dict]) -> dict:
    """The parts `conservation_closure` reduces to one number, so a narrative can state them.

    Same definition, same NaN rule; this just returns the two sums and the counts behind the ratio
    instead of only the ratio. `closure` here is identical to `conservation_closure(roles)` by
    construction -- it calls it -- so the two can never disagree.
    """
    sinks = [d for d in roles.values() if d["role"] == "sink"]
    sources = [d for d in roles.values() if d["role"] == "source"]
    return {"closure": conservation_closure(roles),
            "in_at_sinks": float(sum(d["inflow"] for d in sinks)),
            "out_at_sources": float(sum(d["outflow"] for d in sources)),
            "n_sinks": len(sinks), "n_sources": len(sources),
            "n_undetermined": sum(1 for d in roles.values() if d["role"] == "undetermined")}


def ring_conservation_converted(ring, scored_edges: pd.DataFrame, *, edges: str = "included",
                                config: dict | None = None) -> dict:
    """Ring-level conservation under `currency="converted"`, with the totals, in currency 0.

        c = ring_conservation_converted(ring, scored_edges)
        # {"closure": 0.98, "in_at_sinks": 41230.5, "out_at_sources": 42011.0, "currency": 0,
        #  "n_sinks": 2, "n_sources": 1, "n_undetermined": 0, "unconvertible": False, ...}

    The definition is the contract's, unchanged: `1 - |in at sinks - out at sources| / max(...)`,
    clipped to [0, 1], NaN when the ring has no source or no sink. What changes is the flows it
    reads -- each leg booked on its own side's amount and currency, then converted to currency 0
    with `contract/fx_rates.json` -- so the two sums are in **one unit** and can be quoted.

    For narratives: quote `in_at_sinks` and `out_at_sources` as currency-0 totals and say so. They
    are NOT comparable with the contract's `conservation_closure`, which is a raw cross-currency
    ratio and is what `confidence` uses; this is the corrected quantity beside it, and nothing
    shipped was recomputed with it (docs/PITFALLS.md 3c, 3d).

    `unconvertible` is True when any account in the ring touches a currency with no usable rate
    (code 1). The closure is still reported for the accounts that have one, but a narrative should
    say the total is partial rather than present it as the ring's whole flow.
    """
    cfg = config or load_roles_config()
    roles = account_roles(ring, scored_edges, edges=edges, config=cfg, currency="converted")
    out = conservation_totals(roles)
    out["currency"] = load_fx_rates()["hub"]
    out["unconvertible"] = any(d.get("ccy_unconvertible") for d in roles.values())
    out["n_accounts"] = len(roles)
    out["basis"] = "converted to currency 0 via contract/fx_rates.json"
    return out


def conservation_closure(roles: dict[int, dict]) -> float:
    """Ring-level closure (contract): 1 - |sum inflow at sinks - sum outflow at sources| /
    max(sum inflow, sum outflow), clipped to [0, 1]; NaN when the ring has no source or no sink.

    NaN means "this ring has no distinguishable source or sink" -- every account both sends and
    receives, which is what a closed CYCLE looks like. It does NOT mean "nothing is conserved".
    Callers that render a percentage (the XAI narrative's {closure_pct} slot) must branch on NaN
    rather than coerce it: 5-6 rings per detector seed are in this state, and showing 0 % would
    zero the stated confidence of exactly the most ring-like rings. `ring_confidence` drops the
    closure factor for them instead (docs/TYPING.md, "Rings without a closure")."""
    sinks = [d for d in roles.values() if d["role"] == "sink"]
    sources = [d for d in roles.values() if d["role"] == "source"]
    if not sinks or not sources:
        return math.nan
    in_at_sinks = sum(d["inflow"] for d in sinks)
    out_at_sources = sum(d["outflow"] for d in sources)
    hi = max(in_at_sinks, out_at_sources)
    if hi <= 0:
        return math.nan
    return float(min(max(1.0 - abs(in_at_sinks - out_at_sources) / hi, 0.0), 1.0))


def fill_currency_fields(rings, scored_edges: pd.DataFrame, *, edges: str = "included",
                         config: dict | None = None) -> dict:
    """Fill the schema-v2 `*_ccy` fields on every ring, in place. Returns a summary for the log.

    The single place the currency-aware view is computed, so `contract/make_rings_full.py` and the
    validation-rings path cannot drift. The v1 fields (`conservation_closure`, `confidence`,
    `source_accounts`, `sink_accounts`, `mule_accounts`) are **not touched** -- they stay raw-sum by
    design, and `n_roles_changed_ccy` records how far the two assignments disagree so the size of
    that disagreement is visible in the artefact rather than only in a document.

    `scored_edges` already carries `currency_received` (contract column), so no join is needed; if
    the column is absent every ring gets the v1-equivalent empty/NaN values and `n_currencies` 0.
    """
    cfg = config or load_roles_config()
    n_undet = n_changed = n_rings_undet = 0
    closures = []
    for r in rings:
        raw = account_roles(r, scored_edges, edges=edges, config=cfg, currency="raw")
        ccy = account_roles(r, scored_edges, edges=edges, config=cfg, currency="partitioned")
        arrays = role_arrays(ccy, cfg, currency="partitioned")
        r.source_accounts_ccy = arrays["source_accounts_ccy"]
        r.sink_accounts_ccy = arrays["sink_accounts_ccy"]
        r.mule_accounts_ccy = arrays["mule_accounts_ccy"]
        r.undetermined_accounts_ccy = arrays["undetermined_accounts_ccy"]
        r.conservation_closure_ccy = conservation_closure(ccy)
        r.n_accounts_ccy_undefined = int(sum(1 for d in ccy.values() if d.get("ccy_undefined")))
        r.n_roles_changed_ccy = int(sum(1 for a in raw if raw[a]["role"] != ccy.get(a, {}).get("role")))
        r.n_currencies = int(max((d.get("n_currencies", 0) for d in ccy.values()), default=0))
        n_undet += len(r.undetermined_accounts_ccy)
        n_rings_undet += bool(r.undetermined_accounts_ccy)
        n_changed += r.n_roles_changed_ccy
        closures.append(r.conservation_closure_ccy)
    arr = np.array(closures, dtype=float) if closures else np.zeros(0)
    return {"n_rings": len(rings),
            "n_accounts_undetermined_ccy": n_undet,
            "n_rings_with_undetermined": n_rings_undet,
            "n_roles_changed_ccy_total": n_changed,
            "n_rings_roles_unchanged": int(sum(1 for r in rings if r.n_roles_changed_ccy == 0)),
            "conservation_closure_ccy": {
                "n_nan": int(np.isnan(arr).sum()) if len(arr) else 0,
                "mean_non_nan": float(np.nanmean(arr)) if len(arr) and not np.isnan(arr).all() else None},
            "currency_mode": "partitioned (v2 fields only; v1 fields remain raw cross-currency sums)",
            "ccy_min_two_sided_share": CCY_MIN_TWO_SIDED_SHARE}


ROLE_CODES = {"source": 0, "sink": 1, "mule": 2, "holder": 3, "peripheral": 4}


def roles_from_flows(in_sum: np.ndarray, out_sum: np.ndarray, hold: np.ndarray, cfg: dict) -> np.ndarray:
    """Vectorised `role_of` over arrays -> ROLE_CODES values (same rules, same order)."""
    tau, hold_s = float(cfg["tau_role"]), float(cfg["hold_seconds"])
    hi = np.maximum(in_sum, out_sum)
    with np.errstate(divide="ignore", invalid="ignore"):
        closure = np.where(hi > 0, np.minimum(in_sum, out_sum) / np.where(hi > 0, hi, 1.0), 0.0)
        ratio_in = np.where(out_sum > 0, in_sum / np.where(out_sum > 0, out_sum, 1.0), np.inf)
        ratio_out = np.where(in_sum > 0, out_sum / np.where(in_sum > 0, in_sum, 1.0), np.inf)
    code = np.full(len(in_sum), ROLE_CODES["peripheral"], dtype=np.int64)
    balanced = (in_sum > 0) & (out_sum > 0) & (closure >= 1 - tau)
    code[balanced] = np.where(~np.isnan(hold[balanced]) & (hold[balanced] <= hold_s), ROLE_CODES["mule"], ROLE_CODES["holder"])
    rest = ~balanced
    code[rest & (ratio_in < tau)] = ROLE_CODES["source"]
    code[rest & (ratio_out < tau)] = ROLE_CODES["sink"]
    code[in_sum <= 0] = ROLE_CODES["source"]
    code[out_sum <= 0] = ROLE_CODES["sink"]
    return code


def closure_from_positions(idx, pos: np.ndarray, cfg: dict) -> float:
    """Contract conservation closure of the edges at index positions `pos`, without pandas."""
    if len(pos) == 0:
        return math.nan
    f, t, amt, ts = idx.from_dense[pos], idx.to_dense[pos], idx.amount[pos], idx.ts[pos]
    accounts, inv = np.unique(np.concatenate([f, t]), return_inverse=True)
    fi, ti = inv[:len(f)], inv[len(f):]
    n = len(accounts)
    out_sum = np.bincount(fi, weights=amt, minlength=n)
    in_sum = np.bincount(ti, weights=amt, minlength=n)
    gaps = next_outflow_gaps(ti, ts, fi, ts)
    hold = np.full(n, np.nan)
    ok = ~np.isnan(gaps)
    if ok.any():
        by = pd.Series(gaps[ok]).groupby(ti[ok]).median()
        hold[by.index.to_numpy()] = by.to_numpy()
    code = roles_from_flows(in_sum, out_sum, hold, cfg)
    sinks, sources = code == ROLE_CODES["sink"], code == ROLE_CODES["source"]
    if not sinks.any() or not sources.any():
        return math.nan
    a, b = float(in_sum[sinks].sum()), float(out_sum[sources].sum())
    hi = max(a, b)
    return math.nan if hi <= 0 else float(min(max(1.0 - abs(a - b) / hi, 0.0), 1.0))


def ring_confidence(mean_seed_score: float, closure: float) -> float:
    """Contract: mean score_calibrated over the seed edges x conservation_closure. When the closure
    is NaN (no source or no sink) the factor is dropped rather than poisoning the column; those
    rings are counted in the run log (`n_rings_closure_nan`)."""
    if closure is None or (isinstance(closure, float) and math.isnan(closure)):
        return float(mean_seed_score)
    return float(mean_seed_score * closure)


# --------------------------------------------------------------------------------- rerun_ring
class RingRerunner:
    """Re-run the grouping stage of one ring many times (leave-one-out) without rebuilding its index.

        rr = RingRerunner(ring_edges, "full", affinity=aff, cut=0.5, min_size=3, gfp=gfp, emb=emb)
        base = rr.run()                       # the ring as it stands
        loo = {e: rr.without(e) for e in ring_edges["edge_id"]}

    The index, the GFP / embedding context and the amount percentile are built once over the whole
    ring, so every call scores the same feature scaling (the aggregator's) and costs a fraction of
    a standalone `rerun_ring`. Deterministic."""

    def __init__(self, subgraph_edges: pd.DataFrame, aggregator_id: str = "full", *, affinity=None, cut: float = 0.5,
                 min_size: int = 3, threshold: float = 0.5, method: str = "average", gfp: pd.DataFrame | None = None,
                 emb=None):
        from ringshield.expand.features import FeatureContext
        from ringshield.expand.index import SplitIndex
        if aggregator_id not in ("cc", "full"):
            raise ValueError(f"rerun_ring: unknown aggregator {aggregator_id!r} (cc | full)")
        if aggregator_id == "full" and affinity is None:
            raise ValueError("rerun_ring('full') needs the trained affinity")
        df = subgraph_edges.reset_index(drop=True)
        if "score_calibrated" not in df.columns:
            df = df.assign(score_calibrated=df["score_raw"])
        if "is_seed" not in df.columns:
            df = df.assign(is_seed=True)
        df = df.sort_values("edge_id").reset_index(drop=True)
        self.aggregator_id, self.affinity, self.cut, self.min_size = aggregator_id, affinity, float(cut), int(min_size)
        self.threshold, self.method = float(threshold), method
        self.idx = SplitIndex.build(df)
        self.ctx = FeatureContext.build(df, gfp=gfp, emb=emb, index=self.idx)
        self.is_seed = df["is_seed"].to_numpy(bool)
        self.score = df["score_calibrated"].to_numpy(float)
        self.cfg = load_roles_config()
        self.features_degraded = bool(aggregator_id == "full" and (gfp is None or emb is None))

    def run(self, edge_ids=None) -> dict:
        """Group the given edges (default: all of them) and summarise the largest group."""
        pos = (np.arange(self.idx.n_edges) if edge_ids is None else self.idx.pos_of(np.asarray(sorted(edge_ids), dtype=np.int64)))
        return self._group(pos)

    def without(self, edge_id: int) -> dict:
        """Leave-one-out: the ring without `edge_id`."""
        keep = self.idx.edge_id[self.idx.edge_id != int(edge_id)]
        return self.run(keep)

    def _group(self, pos: np.ndarray) -> dict:
        from ringshield.partition.affinity import cluster_average, cluster_pivot, reattach_small
        from ringshield.partition.pairs import components_of, pair_features
        idx = self.idx
        out = {"confidence": math.nan, "n_rings": 0, "largest_ring_edges": [], "features_degraded": self.features_degraded}
        if len(pos) == 0:
            return out
        is_seed = self.is_seed[pos]
        comp = components_of(idx, pos)
        if self.aggregator_id == "cc":
            labels = comp
        else:
            emb_of = None
            if self.ctx.emb is not None:
                def emb_of(pa, pb):
                    return self.ctx.emb.get(idx.edge_id[pa]), self.ctx.emb.get(idx.edge_id[pb])
            P = pair_features(idx, self.ctx.gfp, pos, is_seed, comp, emb_of=emb_of)
            labels = np.full(len(pos), -1, dtype=np.int64)
            local_of = {int(p): i for i, p in enumerate(pos.tolist())}
            p_all = self.affinity.predict(P) if len(P) else np.zeros(0)
            pc = P["component"].to_numpy() if len(P) else np.zeros(0, np.int64)
            ia_all = idx.pos_of(P["edge_a"].to_numpy()) if len(P) else np.zeros(0, np.int64)
            ib_all = idx.pos_of(P["edge_b"].to_numpy()) if len(P) else np.zeros(0, np.int64)
            nxt = 0
            for c in np.unique(comp):
                m = np.flatnonzero(comp == c)
                loc = {int(pos[i]): k for k, i in enumerate(m.tolist())}
                sel = pc == c
                ia = np.array([loc[int(x)] for x in ia_all[sel]], dtype=np.int64)
                ib = np.array([loc[int(x)] for x in ib_all[sel]], dtype=np.int64)
                p = p_all[sel]
                lab = (cluster_pivot(len(m), ia, ib, p, threshold=self.threshold) if self.method == "pivot"
                       else cluster_average(len(m), ia, ib, p, cut=self.cut))
                ends = np.stack([idx.from_dense[pos[m]], idx.to_dense[pos[m]]], axis=1)
                lab = reattach_small(lab, ia, ib, p, ends, self.min_size)
                labels[m] = lab + nxt
                nxt += int(lab.max()) + 1 if len(lab) else 0
        groups = []
        for lab in np.unique(labels[labels >= 0]):
            m = np.flatnonzero(labels == lab)
            gp = pos[m]
            members = np.unique(np.concatenate([idx.from_dense[gp], idx.to_dense[gp]]))
            if len(members) < self.min_size:
                continue
            seeds = gp[is_seed[m]]
            if len(seeds) == 0:
                continue
            groups.append({"n_members": len(members), "edges": sorted(idx.edge_id[gp].tolist()),
                           "confidence": ring_confidence(float(np.nanmean(self.score[seeds])),
                                                         closure_from_positions(idx, gp, self.cfg))})
        if not groups:
            return out
        big = max(groups, key=lambda g: (g["n_members"], -g["edges"][0]))
        out.update({"confidence": float(big["confidence"]), "n_rings": len(groups), "largest_ring_edges": big["edges"]})
        return out


def rerun_ring(subgraph_edges: pd.DataFrame, aggregator_id: str = "full", *, affinity=None, ctx=None,
               cut: float = 0.5, min_size: int = 3, threshold: float = 0.5, method: str = "average",
               gfp: pd.DataFrame | None = None, emb=None) -> dict:
    """One-shot grouping of `subgraph_edges` (see the module docstring). For leave-one-out use
    `RingRerunner`, which keeps the index and the feature context across calls.

    Returns {"confidence", "n_rings", "largest_ring_edges", "features_degraded"}; `confidence` is
    the contract's (mean score_calibrated over the group's seed edges x its conservation closure)
    of the largest group, NaN when no group survives `min_size`."""
    rr = RingRerunner(subgraph_edges, aggregator_id, affinity=affinity, cut=cut, min_size=min_size,
                      threshold=threshold, method=method, gfp=gfp, emb=emb)
    return rr.run()
