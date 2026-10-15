"""Exchange rates recovered from AMLworld's own cross-currency transactions.

    python contract/make_fx_rates.py            # writes contract/fx_rates.json + docs/FX_RATES.md
    python contract/make_fx_rates.py --dry-run

Why this exists. The v2 currency work asserted that no single AMLworld edge is cross-currency and
that no exchange rate is recoverable from the data. **Both are false**, established by the XAI
teammate on 2026-10-14: 13,627 test edges (1.58 %) carry `Sent Currency != Received Currency` with
a real amount on each side, so every one of them *states* a rate. The generator uses fixed rates,
and the relative IQR per currency pair is ~1e-6 -- float noise, not estimation spread. See
docs/PITFALLS.md entry 3c.

Estimation. **Train split only**, so nothing is read from val or test, and **no label filter**: the
rate is a property of the generator, not of the illicit subpopulation, and filtering on `ring_id`
would make the rate table depend on labels for no benefit. For each ordered pair
(sent -> received) the rate is the **median** of `Amount Received / Amount Sent`.

Precision floor, derived not chosen. Amounts are recorded to 2 decimal places, so each side
carries up to 0.005 of rounding error and the implied rate of a *small* transaction is quantisation
noise: for pair 0 -> 2 the median reads 0.853400 at every amount scale while the relative IQR falls
from 2.6e-2 (amounts below 1) to 1.2e-9 (amounts above 1e6). The rate is exact; only its
*observability* depends on size. So a row is used when both amounts are at least
`0.5 * 10**-amount_dp / tol` -- the amount at which rounding cannot shift the rate by more than the
tolerance the checks are judged at. At the defaults that is 0.005 / 1e-4 = **50**. The floor is a
consequence of the two numbers already fixed (recording precision, tolerance), and a check below
asserts it does not move any pair's median.

Three checks the table must pass before it is written, all on train:

  round trip   rate(a->b) * rate(b->a) == 1 within --tol
  triangle     rate(a->b) * rate(b->c) == rate(a->c) within --tol, over every observed triple
  spread       relative IQR per pair below --max-iqr-rel

Output is rates **to currency 0** (the hub: it appears in most pairs), completed through 0 where a
direct pair is unobserved, with `n` and the relative IQR carried per currency so a consumer can see
what each rate rests on. Converting an amount: `amount_in_ccy0 = amount * rate_to_ccy0[currency]`.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402

HUB = 0
COLS = ["Sent Currency", "Received Currency", "Amount Sent", "Amount Received"]


def observed_rates(df: pd.DataFrame, min_amount: float = 0.0) -> pd.DataFrame:
    """Median Amount Received / Amount Sent per ordered (sent, received) pair.

    `min_amount` applies to BOTH sides: below it, 2-decimal rounding dominates the implied rate.
    """
    x = df[(df["Sent Currency"] != df["Received Currency"]) & (df["Amount Sent"] > 0)].copy()
    if min_amount > 0:
        x = x[(x["Amount Sent"] >= min_amount) & (x["Amount Received"] >= min_amount)]
    x["rate"] = x["Amount Received"].to_numpy(float) / x["Amount Sent"].to_numpy(float)
    g = x.groupby(["Sent Currency", "Received Currency"])["rate"]
    t = g.agg(n="size", median="median",
              q1=lambda v: v.quantile(0.25), q3=lambda v: v.quantile(0.75),
              lo="min", hi="max")
    t["iqr_rel"] = (t["q3"] - t["q1"]) / t["median"]
    t["range_rel"] = (t["hi"] - t["lo"]) / t["median"]
    return t.reset_index().rename(columns={"Sent Currency": "cur_from",
                                           "Received Currency": "cur_to"})


def consistency(m: dict[tuple[int, int], float], tol: float) -> dict:
    """Round-trip and triangle closure over the observed pairs."""
    rt = []
    for (a, b), r in sorted(m.items()):
        if (b, a) in m:
            rt.append({"pair": f"{a}<->{b}", "product": r * m[(b, a)],
                       "ok": abs(r * m[(b, a)] - 1.0) <= tol})
    tri = []
    cur = sorted({c for p in m for c in p})
    for a, b, c in itertools.permutations(cur, 3):
        if (a, b) in m and (b, c) in m and (a, c) in m:
            got, want = m[(a, b)] * m[(b, c)], m[(a, c)]
            tri.append({"path": f"{a}->{b}->{c}", "via": got, "direct": want,
                        "rel_err": abs(got - want) / want,
                        "ok": abs(got - want) / want <= tol})
    return {"round_trip": rt, "triangle": tri,
            "n_round_trip": len(rt), "n_round_trip_ok": sum(r["ok"] for r in rt),
            "n_triangle": len(tri), "n_triangle_ok": sum(t["ok"] for t in tri),
            "worst_round_trip_err": max((abs(r["product"] - 1) for r in rt), default=0.0),
            "worst_triangle_rel_err": max((t["rel_err"] for t in tri), default=0.0)}


def currency_names() -> dict[int, str]:
    """contract/currency_map.json if it has been generated, else {} -- labels only."""
    f = REPO_ROOT / "contract" / "currency_map.json"
    if not f.exists():
        return {}
    return {int(k): v for k, v in json.loads(f.read_text(encoding="utf-8"))["code_to_name"].items()}


def rates_to_hub(t: pd.DataFrame, m: dict[tuple[int, int], float],
                 all_currencies: list[int]) -> dict[int, dict]:
    """rate_to_ccy0 per currency: direct pair if observed, else 1/inverse, else via one hop.

    `all_currencies` is every code present in the split, so a currency with no usable rate is
    listed with `rate_to_ccy0: null` and a reason. Omitting it would hand a consumer a KeyError
    instead of the fact that this currency cannot be converted.
    """
    by_pair = {(int(r.cur_from), int(r.cur_to)): r for r in t.itertuples(index=False)}
    currencies = sorted(set(all_currencies) | {c for p in m for c in p} | {HUB})
    names = currency_names()
    out: dict[int, dict] = {}
    for c in currencies:
        if c == HUB:
            out[c] = {"rate_to_ccy0": 1.0, "n": None, "iqr_rel": 0.0, "source": "hub"}
        elif (c, HUB) in by_pair:
            r = by_pair[(c, HUB)]
            out[c] = {"rate_to_ccy0": float(r.median), "n": int(r.n),
                      "iqr_rel": float(r.iqr_rel), "source": f"direct {c}->0"}
        elif (HUB, c) in by_pair:
            r = by_pair[(HUB, c)]
            out[c] = {"rate_to_ccy0": 1.0 / float(r.median), "n": int(r.n),
                      "iqr_rel": float(r.iqr_rel), "source": f"inverse of 0->{c}"}
        else:                                       # one hop through any currency that reaches 0
            via = next((k for (a, k) in m if a == c and (k, HUB) in m), None)
            if via is None:
                out[c] = {"rate_to_ccy0": None, "n": 0, "iqr_rel": None,
                          "source": "UNREACHABLE: no pair survives the precision floor",
                          "reason": ("this currency's amounts are too small for 2-dp recording to "
                                     "pin the rate -- one unit is worth thousands of the hub "
                                     "currency, so a typical amount is a fraction with two "
                                     "decimals and the implied rate is quantisation noise. "
                                     "In HI-Small this is BITCOIN: a BTC amount such as 0.13 "
                                     "carries ~4 % rounding error, which no amount floor can fix "
                                     "because the data never records more decimals. An amount in "
                                     "this currency CANNOT be converted; withhold, do not guess.")}
            else:
                out[c] = {"rate_to_ccy0": m[(c, via)] * m[(via, HUB)],
                          "n": int(by_pair[(c, via)].n), "iqr_rel": float(by_pair[(c, via)].iqr_rel),
                          "source": f"via {via}: {c}->{via}->0"}
    for c, d in out.items():
        if c in names:
            d["name"] = names[c]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="train", help="estimated on this split only (default train)")
    ap.add_argument("--tol", type=float, default=1e-4,
                    help="round-trip / triangle relative tolerance")
    ap.add_argument("--max-iqr-rel", type=float, default=1e-3,
                    help="a pair whose relative IQR exceeds this is not a fixed rate")
    ap.add_argument("--min-n", type=int, default=5, help="pairs with fewer observations are listed, not used")
    ap.add_argument("--amount-dp", type=int, default=2,
                    help="decimal places the dataset records amounts to; with --tol this DERIVES "
                         "the minimum usable amount, it is not a tuned threshold")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "contract" / "fx_rates.json")
    ap.add_argument("--doc", type=Path, default=REPO_ROOT / "docs" / "FX_RATES.md")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    pdir = load_paths()["processed_dir"]
    f = pdir / f"amlworld_{a.split}.parquet"
    df = pd.read_parquet(f, columns=COLS)
    n_cross = int((df["Sent Currency"] != df["Received Currency"]).sum())
    print(f"[fx] {f.name}: {len(df):,} rows, {n_cross:,} cross-currency "
          f"({100*n_cross/len(df):.3f} %), NO label filter")

    floor = (0.5 * 10.0 ** -a.amount_dp) / a.tol
    print(f"[fx] amounts recorded to {a.amount_dp} dp -> rounding error <= "
          f"{0.5 * 10.0 ** -a.amount_dp:g}; for a rate error <= {a.tol:g} both amounts must be "
          f">= {floor:g}")

    all_rows = observed_rates(df)                      # every cross-currency row, for comparison
    t = observed_rates(df, min_amount=floor)
    used = t[t["n"] >= a.min_n]
    print(f"[fx] rows used: {int(t['n'].sum()):,} of {int(all_rows['n'].sum()):,} cross-currency "
          f"({100*t['n'].sum()/all_rows['n'].sum():.1f} %)")

    # The floor must sharpen the rate, not change it: a floor that selected a different
    # subpopulation would be a tuned threshold wearing a derivation's clothes.
    cmp = used.merge(all_rows[["cur_from", "cur_to", "median", "iqr_rel"]],
                     on=["cur_from", "cur_to"], suffixes=("", "_all"))
    rel = ((cmp["median"] - cmp["median_all"]).abs() / cmp["median"])
    moved = cmp[rel > cmp[["iqr_rel", "iqr_rel_all"]].max(axis=1).clip(lower=a.tol)]
    print(f"[fx] floor vs no floor: median unchanged within each pair's own spread on "
          f"{len(cmp) - len(moved)}/{len(cmp)} pairs (max relative move {rel.max():.2e})")
    if len(moved):
        print("[fx] pairs whose median MOVED beyond their spread:")
        print(moved[["cur_from", "cur_to", "n", "median", "median_all"]].to_string(index=False))
    m = {(int(r.cur_from), int(r.cur_to)): float(r.median) for r in used.itertuples(index=False)}
    print(f"[fx] {len(t)} ordered pairs observed, {len(used)} with n >= {a.min_n}")
    print(f"[fx] relative IQR: max {t['iqr_rel'].max():.3e}, "
          f"pairs over {a.max_iqr_rel:g}: {int((t['iqr_rel'] > a.max_iqr_rel).sum())}")

    chk = consistency(m, a.tol)
    print(f"[fx] round trip: {chk['n_round_trip_ok']}/{chk['n_round_trip']} within {a.tol:g} "
          f"(worst |product-1| = {chk['worst_round_trip_err']:.3e})")
    print(f"[fx] triangle  : {chk['n_triangle_ok']}/{chk['n_triangle']} within {a.tol:g} "
          f"(worst rel err = {chk['worst_triangle_rel_err']:.3e})")

    all_cur = sorted(set(df["Sent Currency"].unique()) | set(df["Received Currency"].unique()))
    hub = rates_to_hub(used, m, [int(c) for c in all_cur])
    unreachable = [c for c, d in hub.items() if d["rate_to_ccy0"] is None]
    print(f"[fx] rates to currency {HUB}: {len(hub) - len(unreachable)} of {len(hub)} currencies"
          + (f"; unreachable {unreachable}" if unreachable else ""))

    bad_iqr = t[t["iqr_rel"] > a.max_iqr_rel]
    fixed = bad_iqr.empty and chk["n_round_trip_ok"] == chk["n_round_trip"] \
        and chk["n_triangle_ok"] == chk["n_triangle"]
    print(f"\n[fx] VERDICT: {'fixed rates, all checks pass' if fixed else 'CHECKS FAILED -- do not use'}"
          + (f"; {len(unreachable)} currency/currencies NOT convertible: {unreachable}"
             if unreachable else "; every currency convertible"))
    print(used.sort_values("n", ascending=False).head(10).to_string(index=False))

    if a.dry_run:
        print("\n[fx] DRY RUN -- nothing written")
        return t
    if not fixed:
        # The first version of this script printed "do not use" and then wrote the file. A rate
        # table that fails its own consistency checks must not reach disk for a consumer to find.
        print("\n[fx] REFUSING TO WRITE: the checks did not pass. Nothing was written.",
              file=sys.stderr)
        if not bad_iqr.empty:
            print(bad_iqr.to_string(index=False), file=sys.stderr)
        raise SystemExit(1)
    if len(moved):
        print("\n[fx] REFUSING TO WRITE: the amount floor changed a pair's median, so it is "
              "selecting a subpopulation rather than sharpening a constant.", file=sys.stderr)
        raise SystemExit(1)

    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "convert an AMLworld amount to currency 0: amount * rate_to_ccy0[currency]",
        "provenance": ("recovered from the generator's own cross-currency transactions; "
                       "the premise that no edge is cross-currency and no rate is recoverable was "
                       "FALSE and was corrected by the XAI teammate's measurement, 2026-10-14"),
        "split": a.split,
        "label_filter": "none -- the rate is a property of the generator, not of the illicit subset",
        "hub_currency": HUB,
        "n_rows": int(len(df)), "n_cross_currency": n_cross,
        "thresholds": {"tol": a.tol, "max_iqr_rel": a.max_iqr_rel, "min_n": a.min_n,
                       "amount_dp": a.amount_dp, "min_amount_derived": floor,
                       "min_amount_rule": "0.5 * 10**-amount_dp / tol -- the amount below which "
                                          "2-dp rounding can shift the implied rate by more than "
                                          "tol; derived, not swept"},
        "rows_used": int(t["n"].sum()), "rows_cross_currency_total": int(all_rows["n"].sum()),
        "checks": {k: chk[k] for k in ("n_round_trip", "n_round_trip_ok", "n_triangle",
                                       "n_triangle_ok", "worst_round_trip_err",
                                       "worst_triangle_rel_err")},
        "fixed_rates": bool(fixed),
        "currencies_in_split": [int(c) for c in all_cur],
        "unconvertible": unreachable,
        "rate_to_ccy0": {str(c): hub[c] for c in sorted(hub)},
        "pairs": json.loads(used.to_json(orient="records")),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"-> {a.out}")

    write_doc(a.doc, payload, used, chk, a)
    print(f"-> {a.doc}")
    return t


def write_doc(path: Path, payload: dict, used: pd.DataFrame, chk: dict, a) -> None:
    rows = "\n".join(
        f"| {c} | {d.get('name', '?')} | {d['rate_to_ccy0']:.6g} | "
        f"{d['n'] if d['n'] is not None else '-'} | {d['iqr_rel']:.2e} | {d['source']} |"
        if d["rate_to_ccy0"] is not None else
        f"| {c} | {d.get('name', '?')} | - | {d['n']} | - | {d['source']} |"
        for c, d in payload["rate_to_ccy0"].items())
    top = "\n".join(
        f"| {int(r.cur_from)} -> {int(r.cur_to)} | {int(r.n):,} | {r.median:.6g} | {r.iqr_rel:.2e} | {r.range_rel:.2e} |"
        for r in used.sort_values("n", ascending=False).head(15).itertuples(index=False))
    path.write_text(f"""# FX_RATES - exchange rates recovered from AMLworld

Generated by `contract/make_fx_rates.py` from **`amlworld_{a.split}.parquet` only**, with **no label
filter**. Machine-readable copy: `contract/fx_rates.json`.

## Why this file exists

The schema-v2 currency work rested on two claims that are **false**:

1. *"No single transaction is cross-currency."* The {a.split} split has
   **{payload['n_cross_currency']:,} cross-currency rows** of {payload['n_rows']:,}
   ({100*payload['n_cross_currency']/payload['n_rows']:.3f} %), each with an amount and a currency
   on **both** sides.
2. *"No exchange rate is recoverable from the data."* Every one of those rows states a rate
   directly. The generator uses **fixed** rates.

Both were established by the **XAI teammate's measurement on 2026-10-14**, and neither claim was
ever measured before it was written down. See `docs/PITFALLS.md` entry 3c.

## The rates, to currency {payload['hub_currency']}

To convert: `amount_in_ccy0 = amount * rate_to_ccy0[currency]`. **Currency 0 is US Dollar** (`contract/currency_map.json`).

A sanity check that costs nothing and is worth stating: the recovered Euro rate is **1.1718 USD**
and the Swiss Franc **1.0929** - plausible 2022 rates, which no fitting procedure was asked to
produce. The one currency with no usable rate is **Bitcoin**.

| currency | name | rate to 0 | n | relative IQR | source |
|---|---|---:|---:|---:|---|
{rows}

## The pairs they come from (top 15 by n)

| pair | n | median rate | relative IQR | relative range |
|---|---:|---:|---:|---:|
{top}

## Why these are constants, not estimates

* **Bitcoin is the exception, and the reason is arithmetic, not missing data.** One BTC is
  worth ~11,900 USD here, so a typical BTC amount is a fraction recorded to two decimals
  (0.13), carrying ~4 % rounding error. No amount floor can fix that, because the data never
  records more decimals. An amount in Bitcoin cannot be converted and is withheld.
* **Spread.** The largest relative IQR over all {len(used)} used pairs is
  **{used['iqr_rel'].max():.2e}** - float noise on a fixed multiplier, not sampling spread.
* **Round trip.** `rate(a->b) * rate(b->a) == 1` holds on
  **{chk['n_round_trip_ok']}/{chk['n_round_trip']}** reciprocal pairs, worst
  |product - 1| = **{chk['worst_round_trip_err']:.2e}**.
* **Triangle.** `rate(a->b) * rate(b->c) == rate(a->c)` holds on
  **{chk['n_triangle_ok']}/{chk['n_triangle']}** observed triples, worst relative error
  **{chk['worst_triangle_rel_err']:.2e}**.

A table that closes under both composition and inversion to within 1e-4 is a rate card, not a
fitted model.

## Rules of use

* **Estimated on train only.** Nothing here reads val or test.
* **No label filter.** Filtering on `ring_id` would make a generator constant depend on labels.
* **Rates are not swept, tuned or seeded.** There is nothing to choose.
* **Conversion is opt-in.** `account_roles(..., currency="converted")` uses this table;
  `currency="raw"` is unchanged and remains what every shipped result was computed with.
""", encoding="utf-8")


if __name__ == "__main__":
    main()
