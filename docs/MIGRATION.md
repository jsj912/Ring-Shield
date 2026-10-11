# MIGRATION — rings contract v1 → v2 (currency-aware fields, validation rings)

For the XAI teammate on `explainability-l4`. Read the four **Action required** boxes; the rest is
background.

Branch: `contract-ccy-valrings`, cut from `v2`. Nothing on `jsj-v3` or `explainability-l4` was
touched.

---

## 1. What changed, in one paragraph

AMLworld amounts carry a currency code. No single transaction is cross-currency, but **55.2 % of
test rings span more than one currency** and median amounts differ by **~140×** between codes. The
shipped roles and closure sum amounts **across** currencies, so for a meaningful share of accounts
they compare mismatched units. Schema **v2** adds a currency-partitioned view **beside** the
existing fields. **No v1 field changed meaning or value.**

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

## 3. Action required — use the `_ccy` roles, and render `undetermined` explicitly

`account_roles` is unchanged by default. `currency="raw"` is byte-identical to today, verified
across all 108 rings of seed 1, so **`research_roles`, your `roles_disagreement_*.csv` and
`currency_policy: raw` all stay valid**.

For narratives, switch to the currency-aware assignment:

```python
roles = account_roles(ring, scored_edges, edges="included", currency="partitioned")
arrays = role_arrays(roles, currency="partitioned")   # includes undetermined_accounts_ccy
```

**There is a sixth role: `undetermined`.** An account gets it when its inflow and outflow
currencies do not overlap, or when the currencies on both sides carry less than
`ccy_min_two_sided_share` (0.5) of each side's flow. It is **not** `peripheral`, and the
distinction is the whole point:

> Partitioned flows cannot show that such an account is *not* a mule — only that same-currency
> evidence does not support the label. Whether it is a mule depends on the exchange rate.

**Render it explicitly.** Something like *"currency changes inside this account; balance cannot be
checked"*. Never collapse it into `peripheral`, `source` or `sink` — each of those asserts a flow
imbalance the evidence does not establish.

Measured across 4,280 ring-accounts, 5 seeds (shipped `full` runs):

| raw → currency-aware | accounts |
|---|---|
| mule → **undetermined** | **253** |
| source → **undetermined** | 149 |
| sink → **undetermined** | 84 |
| peripheral → **undetermined** | 81 |
| holder → **undetermined** | 4 |
| mule → peripheral | 4 |

**575 of 4,280 (13.4 %) change, and 571 of those become `undetermined`.** Only 4 accounts are
actually contradicted by same-currency evidence. So the honest statement is *"253 mule labels are
not supported by same-currency evidence"*, not *"253 accounts are not mules"*.

Per ring, `n_roles_changed_ccy` gives the size of the disagreement directly: **median 0, max 15,
and 317 of 560 ring-instances are entirely unaffected**. The disagreement is concentrated, not
spread thin — useful if you want to flag only the rings where it matters.

## 4. `currency_policy: raw` is now a real choice

Your `explainability/config.yaml` line reads:

```yaml
currency_policy: raw   # PROVISIONAL: raw sums across currencies, as the shipped roles/closure do
```

It is no longer provisional — it now selects between two *shipped* conventions:

| | `raw` (v1) | `partitioned` (v2) |
|---|---|---|
| fields | `source/sink/mule_accounts`, `conservation_closure`, `confidence` | `*_accounts_ccy`, `undetermined_accounts_ccy`, `conservation_closure_ccy` |
| sums amounts across currencies | yes | no |
| withholds a role when it cannot judge | no | yes (`undetermined`) |
| recommended for narratives | no | **yes** |

The ring-level `conservation_closure` is **essentially unaffected** by the choice — median |Δ|
0.0000, and only **2 of 102** rings differ by more than 0.1 — because it reads sources and sinks,
which are one-sided by definition. It is the **per-account roles** that move. So if you only use
closure, `raw` is fine; if you use roles, use `partitioned`.

## 5. Action required — `w_flow` must be a within-currency share

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

**The rule: `w_flow` is a within-currency share.** Each edge's amount divided by the total of the
**same-currency** member edges of that ring, with the existing duplicate-payment rule unchanged
(same from, to, timestamp, amount counted once in the total; every copy keeps the same share). A
single-currency ring is unaffected, so nothing in your hand-computed tests moves.

**`w_flow` therefore no longer sums to 1 over a ring — it sums to 1 per currency**, so a ring with
three currencies has three unit totals. `w_total = alpha*w_score + beta*w_loo + gamma*w_flow` stays
well defined per edge, but any assertion that `w_flow` sums to 1 over the ring, or any narrative
sentence of the form "this edge carries X % of the ring's money", needs the currency named: *"X %
of the ring's money in currency C"*.

### XR-02's exchange-table normalisation is withdrawn

XR-02 said to normalise amounts with the dataset's exchange table. **There is no exchange table in
AMLworld.** It is not merely unpublished — it is not recoverable from the data either: of 393,544
unlabelled accounts with exactly one currency on each side, **99.99 % use the same currency on
both**, leaving 50 cross-currency pass-throughs and just 1 with >= 3 edges per side
(`results/tables/fx_stability.json`). There is no background population to estimate a rate from.

So the requirement cannot be met as written and is **withdrawn**, not deferred. The within-currency
share is the replacement, and it is the same discipline as the `undetermined` role in section 3:
where no rate exists, compare only within a currency and say so, rather than converting with a
number nobody has.

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

## 7. New: validation rings

`run_partition.py --save-val-rings` writes `rings_val.parquet` (+ `.log.json`) for the **chosen
cell only**, with every contract field filled at v2. Validation rings were previously built during
the grid search and discarded, which is why XR-05 had no interval to bootstrap.

Produced for `gine_causal`, 5 seeds, under `experiments_valrings/average/seed{1..5}/`. Each run
asserts the written rings' member sets are **identical to the rings the validation metrics came
from**, so the file is the same object the grid chose on, not a re-derivation.

## 8. Merge expectations

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

## 9. Not in this branch

Implied FX rates are **estimated and reported only** (`results/tables/fx_stability.*`), never
applied. Until they are shown stable across days and across releases, an `undetermined` account
stays undetermined; nothing converts amounts.
