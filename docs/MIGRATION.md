# MIGRATION — rings contract v1 → v2 (currency-aware fields, validation rings)

For the XAI teammate on `explainability-l4`. Read the five **Action required** boxes; the rest is
background.

Branch: `contract-ccy-valrings`, cut from `v2`. Nothing on `jsj-v3` or `explainability-l4` was
touched.

---

## 1. What changed, in one paragraph

AMLworld amounts carry a currency code. **55.2 % of test rings span more than one currency** and
median amounts differ by **~140×** between codes. The shipped roles and closure sum amounts
**across** currencies, so for a meaningful share of accounts they compare mismatched units. Schema
**v2** adds a currency-partitioned view **beside** the existing fields. **No v1 field changed
meaning or value.**

> ### Correction, 2026-10-14 — thank you
>
> This section used to say *"No single transaction is cross-currency"*, and section 5 used to say
> there is no exchange table and no recoverable rate. **Both were wrong, and your measurement is
> what caught them.** 13,627 test edges (1.58 %) have `Sent Currency != Received Currency` with a
> real amount on each side; the generator's rates are fixed and recoverable directly from those
> rows. Neither claim had ever been measured before it was written down — it went into a docstring
> and was copied from there into four files and two commit messages. The record is
> `docs/PITFALLS.md` entry 3c.
>
> What follows from it:
>
> * The rates are now in **`contract/fx_rates.json`** with **`docs/FX_RATES.md`** — train split
>   only, no label filter, round trip and triangle closing to 3e-5.
> * **`currency="partitioned"` is superseded by `currency="converted"`** (section 3). The v2
>   `*_ccy` columns are kept exactly as published and nothing was regenerated, but prefer the
>   converted roles.
> * **XR-02 is reinstated** (section 5), met through `fx_rates.json` rather than a table the
>   dataset never shipped.
> * Everything published still stands: `currency="raw"` is byte-identical, and the HI-Small
>   results and the pinned HI-Medium v3 run are untouched.

## 2. Action required — your validator will reject v1 files

`explainability/contract_io.py::check_columns` requires *"the exact column set: every field
present, nothing extra"*. Because you import `RINGS_COLUMNS` from `contract.schema`, merging `v2`
updates your spec to 30 columns, and **every rings parquet written before this change becomes
invalid** against it:

```
ContractError: ...: missing field(s) ['conservation_closure_ccy', 'n_accounts_ccy_undefined',
  'source_accounts_ccy', 'sink_accounts_ccy', 'mule_accounts_ccy',
  'undetermined_accounts_ccy', 'n_roles_changed_ccy', 'n_currencies']
```

Two things to do:

1. **Re-point to the regenerated files.** `contract/out/rings_full_gine_causal_{1..5}.parquet` have
   been rebuilt at v2, and so have **both stubs** - `rings_stub_cc.parquet` (the one
   `test_stub_loads` reads) and `rings_stub_cc_step1_legacy.parquet`. Every rings file on disk is
   now v2; the regenerations reproduce all 22 v1 columns row-for-row and add 8, with the currency
   fields computed rather than left at their defaults (a v2-stamped file with empty `_ccy` columns
   would be worse than a v1 file, because a reader could not tell "no currency effect" from "never
   computed"). The `full` rebuild The run asserts the primary-window precision / recall / F1 / Jaccard /
   coverage are **identical to the R4 `average` run to 1e-9**, so membership did not move — only
   columns were added. Primary ring-F1 0.5895 ± 0.0371, unchanged.
2. **Your Week-2 outputs stay reproducible.** The v1 files are preserved verbatim at
   **`contract/out/v1/`**, the two stubs among them, so
   `fidelity_week1_stub_cc_seed1.json` and `explanations_week2_stub_cc_seed1.parquet` can still be
   re-derived from the file they were produced from. Point there if you need to re-derive anything from before the merge.
   `ringshield.rings.rings_schema_version(path)` returns 1 for those and 2 for the new ones — the
   version is in the parquet key-value metadata, so you can branch on it instead of sniffing
   columns.

If you would rather not take the column change yet, pin `contract/schema.py` to the merge-base and
merge the rest; nothing else in this branch depends on the new columns.

## 3. Action required — use the currency-aware roles (`converted`), and render `undetermined` explicitly

`account_roles` is unchanged by default. `currency="raw"` is byte-identical to today, verified
across all 108 rings of seed 1, so **`research_roles`, your `roles_disagreement_*.csv` and
`currency_policy: raw` all stay valid**.

For narratives, switch to the currency-aware assignment. **Use `converted`, not `partitioned`:**

```python
roles  = account_roles(ring, scored_edges, edges="included", currency="converted")
arrays = role_arrays(roles)          # the v1 array names: converted is the corrected same quantity
```

`converted` books the sender's leg from `amount_sent` / `currency_sent` and the receiver's from
`amount_received` / `currency_received`, converts both to currency 0 with `contract/fx_rates.json`,
then applies the ordinary role rule. It needs no new columns and there is **no schema bump**.

**`partitioned` is superseded** and kept only because the published v2 columns were computed with
it. It withholds a verdict wherever it cannot compare within one currency, which is the right
instinct under the false premise that no rate exists — and far too often now that one does:

| | `partitioned` | `converted` |
|---|---:|---:|
| ring-accounts whose role changes vs `raw` | 575 (13.4 %) | **285 (6.7 %)** |
| left `undetermined` | 571 (13.3 %) | **3 (0.07 %)** |

Of `partitioned`'s 571 withholdings, **568 resolve under `converted` — 492 of them (86 %) to
`mule`**, 41 to peripheral, 17 to source, 14 to holder, 7 to sink.

**There is a sixth role: `undetermined`.** Under `converted` an account gets it only when it
touches a currency with **no usable rate** — in practice **Bitcoin** (code 1), whose amounts are
so small that 2-decimal recording cannot pin its rate: one BTC is ~11,900 USD here, so a typical
amount is a fraction like 0.13 carrying ~4 % rounding error. That is **3 accounts of 4,280**, in one ring.

**Still render it explicitly** where it does occur: *"this account converts into a currency whose
rate cannot be recovered; the balance cannot be checked"*. Never collapse it into `peripheral`,
`source` or `sink` — each asserts a flow imbalance the evidence does not establish. But it is now
a rare edge case rather than a label on 13 % of accounts.

Under the superseded `partitioned` mode the same role fired whenever in and out currencies did not
overlap, on the reasoning that *"whether it is a mule depends on the exchange rate"*. The rate is
now known, so that sentence is no longer a reason to withhold — it is a reason to convert.

Measured across 4,280 ring-accounts, 5 seeds (shipped `full` runs):

| raw → currency-aware | accounts |
|---|---|
| mule → **undetermined** | **253** |
| source → **undetermined** | 149 |
| sink → **undetermined** | 84 |
| peripheral → **undetermined** | 81 |
| holder → **undetermined** | 4 |
| mule → peripheral | 4 |

**575 of 4,280 (13.4 %) change, and 571 of those become `undetermined`** — under the superseded
`partitioned` mode. The statement that went with that table was *"253 mule labels are not supported
by same-currency evidence"*.

**That is now resolved rather than hedged.** With the rate applied, those mule labels **are**
supported: 86 % of `partitioned`'s withheld accounts come back `mule` under `converted`. The
table above is kept because it describes the published v2 columns, not because it is the best
available answer.

Per ring, `n_roles_changed_ccy` gives the size of the disagreement directly: **median 0, max 15,
and 317 of 560 ring-instances are entirely unaffected**. The disagreement is concentrated, not
spread thin — useful if you want to flag only the rings where it matters.

## 4. `currency_policy: raw` is now a real choice

Your `explainability/config.yaml` line reads:

```yaml
currency_policy: raw   # PROVISIONAL: raw sums across currencies, as the shipped roles/closure do
```

It is no longer provisional — it now selects between two *shipped* conventions:

| | `raw` (v1) | `partitioned` (v2, superseded) |
|---|---|---|
| fields | `source/sink/mule_accounts`, `conservation_closure`, `confidence` | `*_accounts_ccy`, `undetermined_accounts_ccy`, `conservation_closure_ccy` |
| sums amounts across currencies | yes | no |
| withholds a role when it cannot judge | no | yes (`undetermined`) |
| recommended for narratives | no | **yes** |

Ring-level `conservation_closure` is **essentially unaffected** by the `raw` / `partitioned`
choice — median |Δ| 0.0000, only **2 of 102** rings differ by more than 0.1 — because it reads
sources and sinks, which are one-sided by definition.

**It is not unaffected by `converted`.** Median |Δ| is still 0.0000, but **87 of 525 rings differ
by more than 0.1, worst 0.97**, because `converted` also repairs the leg-booking defect
(`PITFALLS.md` 3d) and not just the units. The shipped `conservation_closure` and `confidence` are
left as published; this is the note that they would move. So: if you only use closure, `raw` is
what every published number uses; if you use **roles**, use **`converted`**.

## 5. Action required — `w_flow` is the share of the ring's convertible total (XR-02 reinstated)

`edge_weights.py::w_flow` divides each edge's amount by the total over the ring's member edges,
summed **raw across currencies**:

```python
total = float(amt[~dup].sum())       # mixes currency codes
share = amt / total
```

With median amounts differing by **~140x** between codes (7,918 for code 11 against 1,100,155 for
code 6), one edge in a high-magnitude currency takes almost the whole share of a mixed-currency
ring, and the other members round towards zero. That is not a flow share; it is a currency
artefact. **55.2 % of test rings span more than one currency**, so it is not a corner case.

**The rule: `w_flow` is the share of the ring's convertible total.** Convert each member edge to
currency 0 with `contract/fx_rates.json`, over the **convertible, non-conversion** member edges,
and take the ordinary share of that total. One rule, no second mode:

* **Exclude currency conversions** (`currency_sent != currency_received`) from both the numerator
  and the denominator - section 7. A self-loop conversion moves no money between accounts.
* **Exclude edges whose currency has no rate** (Bitcoin, code 1) from the total as well, and **flag the
  ring partial**. `ring_conservation_converted(...)["unconvertible"]` is already True for such a
  ring, so the flag is available without extra work.
* The existing duplicate-payment rule is unchanged: same from, to, timestamp, amount counted once
  in the total, every copy keeping the same share.

A single-currency ring with no conversions is unaffected, so nothing in your hand-computed tests
moves.

**Why there is no within-currency fallback.** An earlier draft of this section said a ring touching
Bitcoin should fall back to a per-currency share. That is withdrawn: it made `w_flow` mean two
different things depending on the ring, so two explanations could not be compared, and it reported
a confident-looking share computed on a subset without saying so. Excluding the unconvertible edges
and marking the ring partial keeps one definition and states the gap.

**`w_flow` sums to 1 over the edges it covers**, as it did before - the convertible,
non-conversion member edges. On a ring flagged partial those are a subset of `member_edges`, so say
so ("X % of the ring's traceable flow") rather than implying it is the whole ring. `w_total = alpha*w_score + beta*w_loo + gamma*w_flow` stays
well defined per edge, but any assertion that `w_flow` sums to 1 over the ring, or any narrative
sentence of the form "this edge carries X % of the ring's money", needs the currency named: *"X %
of the ring's money in currency C"*.

### XR-02 is REINSTATED, via `contract/fx_rates.json`

> **Corrected 2026-10-14.** This section said XR-02 was withdrawn because *"there is no exchange
> table in AMLworld"* and no rate was recoverable. **Both were wrong**, and your measurement caught
> it. The rate is recorded on each cross-currency transaction, and the generator's rates are fixed.
> The earlier reasoning rested on `evaluation/fx_stability.py`, which asked an *account*-level
> question (how many accounts convert) and got the right answer to it — then had that answer
> generalised into a claim about *edges*, which does not follow. `PITFALLS.md` 3c.

**XR-02 stands, and can be met.** Normalise with `contract/fx_rates.json`:

```python
from ringshield.roles import load_fx_rates
fx = load_fx_rates()["rate_to_ccy0"]           # {currency: rate to currency 0}
value = amount * fx[currency]                  # None for Bitcoin (1): withhold, do not guess
```

Rates come from the train split only, with no label filter, and close under inversion and
composition to 3e-5 (`docs/FX_RATES.md`). **Bitcoin (code 1) has no usable rate** — its amounts are too
small for 2-decimal recording to pin one — so an amount in Bitcoin cannot be normalised and the
edge must be reported as unconvertible rather than converted at a guess.

**So `w_flow` has one correct form:** normalise every convertible, non-conversion member edge to
currency 0 and take the ordinary share of that total. *"This edge carries X % of the ring's
money"* is then true without qualification on a fully convertible ring, and *"X % of the ring's
traceable flow"* on one flagged partial.

## 6. Action required - apply `docs/xai_fixtures.patch`

```bash
git apply docs/xai_fixtures.patch
```

That is the whole instruction. One file, two hunks, `explainability/tests/fixtures.py`: the import
line and the `self.rings.append({...})` call, which becomes
`self.rings.append(ring_record(**{...}))`. Nothing was committed on `explainability-l4`; the patch
is yours to apply, read or reject.

**Why it is needed.** Your builder ends with `pd.DataFrame(self.rings, columns=RINGS_ORDER)`.
`RINGS_ORDER` is 30 entries after this merge while the row dicts set 22, so pandas materialises the
eight new columns as **all-NaN `float64`**. The column *names* are then all present, so
`check_columns` passes and `check_frame_types` is what rejects them:

```
fixture rings: wrong type(s): n_accounts_ccy_undefined: expected int64, got float64;
  source_accounts_ccy: expected list<int64>, got float64; ... (7 fields)
```

`contract.schema.ring_record(**overrides)` returns one rings row with every contract column at a
correctly-typed default - `0` for counts, `[]` for the list columns, NaN only for
`conservation_closure` and `conservation_closure_ccy` (the two the contract permits), uniform
`topology_probs` with `topology_type` `"UNKNOWN"` so a bare record is already a valid distribution.
An override key that is not a contract column is refused, so a typo cannot silently leave a column
at its default. The next schema version then reaches your fixtures without touching them.

**What this fixed, measured.** Before the patch your suite was 111 passed / 5 failed on the merge;
after it, **116 passed / 0 failed**. Four of the five failures were this dtype problem. The fifth
was the stub, handled in section 2.

**One of the four deserves a second look.** `test_broken_fixture_seed_not_in_members_is_rejected`
expects `ContractError: seed_edges not a subset of member_edges`, and before the patch it received
the dtype error instead - so it failed, but the subset check it guards was **not being exercised**.
It now raises for its original reason:

```
rings: 2 violation(s):
  full-fixture-0-fan_out: seed_edges not a subset of member_edges ([1053])
  full-fixture-0-fan_out: a seed_edge is not is_seed in scored_edges
```

Any other repair that silences the dtype errors would have turned this test green without that
check ever running. Worth knowing if you decide to fix it differently.

## 7. Action required - drop currency conversions from evidence edges and `w_flow`

`member_edges` is **every** edge among the ring's member accounts inside its span, not only the
edges the aggregator used. The biggest category of extra traffic is currency conversion, and
AMLworld records a conversion as a **self-loop**: one account, `from_id == to_id`,
`currency_sent != currency_received`, a real amount on each side.

| edge set | edges | cross-currency |
|---|---:|---:|
| `member_edges` | 7,520 | **2,912 (38.7 %)**, in 489 of 560 rings |
| `seed_edges` + `expanded_edges` | 4,316 | 33 (0.76 %) |

**Not one of them is laundering: 0 of 72,170 across all three splits**, and 0 of the 1,611
laundering test edges is a conversion. Truth rings contain none at all.

So in any ring you render, roughly two edges in five are a conversion that is provably not
laundering. The filter needs no labels and no schema change:

```python
conv = se["currency_sent"] != se["currency_received"]      # 96.95 % also have from_id == to_id
evidence = [e for e in ring.member_edges if not conv_by_edge_id[e]]
```

**Two places to apply it:**

* **Evidence edges.** A conversion is an artefact of how the dataset represents an exchange rather
  than a transfer between parties. Ranking it as evidence spends an explanation slot on an edge
  that cannot be laundering.
* **`w_flow`.** A self-loop moves no money *between* accounts, so including it in the ring's total
  dilutes every real edge's share. Drop conversions from the denominator and from the ranking.

This also simplifies section 5: with conversions excluded, far fewer rings are mixed-currency in
the edges you actually use, and almost none are flagged partial - so `w_flow` is the plain share of
the ring's converted total in nearly every case.

For the ring-level statement, use the new helper rather than recomputing:

```python
from ringshield.roles import ring_conservation_converted
c = ring_conservation_converted(ring, scored_edges)
# c["closure"], c["in_at_sinks"], c["out_at_sources"] -- all in currency 0, c["currency"] == 0
# c["unconvertible"] is True if the ring touches Bitcoin: say the total is partial
```

It uses the contract's closure definition unchanged, on converted flows, and returns the two totals
so a narrative can quote them. They are **not** comparable with the contract's
`conservation_closure`, which stays the raw cross-currency ratio and is what `confidence` uses.

## 8. New: the integer codes can be decoded

`currency_sent`, `currency_received` and `payment_format` are first-appearance integers from
`scripts/format_kaggle_files.py`, which kept no record of the mapping.
`contract/make_code_maps.py` reproduces the encoding and verifies it row-for-row against the
processed parquets (5,078,345 rows, 0 mismatches) before writing:

| file | contents |
|---|---|
| `contract/currency_map.json` | 15 currencies, both directions |
| `contract/payment_format_map.json` | 7 payment formats, both directions |
| `contract/bank_names.json` | 30,470 bank ids to names |

**Currency 0 is `US Dollar`** - the first raw row's *receiving* currency, because the formatter
assigns the receiving side before the payment side within each row. `rate_to_ccy0` in
`contract/fx_rates.json` therefore converts to US Dollar, which is worth saying explicitly in a
narrative rather than leaving as "currency 0".

Payment formats, which you will want for the narrative text:

| code | name |
|---|---|
| 0 | Reinvestment |
| 1 | Cheque |
| 2 | Credit Card |
| 3 | ACH |
| 4 | Cash |
| 5 | Wire |
| 6 | Bitcoin |

**Bank names exist after all.** We previously said they did not. `<dataset>_accounts.csv` has
`Bank Name` beside `Bank ID`, and `from_bank` / `to_bank` **are** that `Bank ID` -
30,470 of 30,470 codes used in the splits resolve. So
"Arbor Savings Bank" is available where a narrative currently prints a number. **A name is not a
unique key** (30,470 ids, 20,053 distinct names): display only.

## 9. New: validation rings

`run_partition.py --save-val-rings` writes `rings_val.parquet` (+ `.log.json`) for the **chosen
cell only**, with every contract field filled at v2. Validation rings were previously built during
the grid search and discarded, which is why XR-05 had no interval to bootstrap.

Produced for `gine_causal`, 5 seeds, under `experiments_valrings/average/seed{1..5}/`. Each run
asserts the written rings' member sets are **identical to the rings the validation metrics came
from**, so the file is the same object the grid chose on, not a re-derivation.

## 10. Merge expectations

**No file of yours conflicts.** `explainability-l4` vs `v2` is 35 files, 10,777 insertions, 0
deletions — purely additive, and it touches none of the files changed here (`contract/schema.py`,
`contract/README.md`, `contract/make_rings_full.py`, `ringshield/rings.py`, `ringshield/roles.py`,
`ringshield/partition/run_partition.py`, `configs/roles.yaml`, `evaluation/step9_tables.py`,
`README.md`). The textual merge is clean; the two items above are semantic, not textual.

Files to look at after merging:

| file | why |
|---|---|
| `explainability/tests/test_contract_io.py` | exact-column-set check against the new 30-column spec |
| any re-validation of your Week-2 parquets | v1 files now fail the v2 spec — use `contract/out/v1/` |
| `explainability/config.yaml` | `currency_policy` is a real choice; `partitioned` recommended for roles |
| your narrative templates | need an `undetermined` branch |

## 11. What converts, and what still does not

**Corrected 2026-10-14.** This section used to say FX rates were report-only and that nothing
converts amounts. The rates are now recovered, checked and shipped:

* `contract/fx_rates.json` + `docs/FX_RATES.md` — the generator's fixed rates to currency 0, from
  the train split with no label filter, closing under inversion and composition to 3e-5.
* `account_roles(..., currency="converted")` applies them. It is **opt-in**: `raw` remains the
  default and every published number still comes from `raw`.
* `results/tables/fx_stability.*` is **superseded** and carries a `SUPERSEDED` block saying why.

**What still does not convert:** **Bitcoin** (code 1). Its amounts are too small for 2-decimal recording
to pin a rate, so it is listed in `fx_rates.json` under `unconvertible` with
`rate_to_ccy0: null`. An account touching it is reported `undetermined` — 3 of 4,280 across the
five shipped seeds. A consumer must withhold there, never guess.

**Nothing was regenerated.** The v2 `*_ccy` columns, the rings files, the HI-Small results and the
pinned HI-Medium v3 run are all exactly as published.
