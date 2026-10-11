# MIGRATION — rings contract v1 → v2 (currency-aware fields, validation rings)

For the XAI teammate on `explainability-l4`. Read the two **Action required** boxes; the rest is
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
   been rebuilt at v2. The run asserts the primary-window precision / recall / F1 / Jaccard /
   coverage are **identical to the R4 `average` run to 1e-9**, so membership did not move — only
   columns were added. Primary ring-F1 0.5895 ± 0.0371, unchanged.
2. **Your Week-2 outputs stay reproducible.** The v1 files are preserved verbatim at
   **`contract/out/v1/`**. Point there if you need to re-derive anything from before the merge.
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

## 5. New: validation rings

`run_partition.py --save-val-rings` writes `rings_val.parquet` (+ `.log.json`) for the **chosen
cell only**, with every contract field filled at v2. Validation rings were previously built during
the grid search and discarded, which is why XR-05 had no interval to bootstrap.

Produced for `gine_causal`, 5 seeds, under `experiments_valrings/average/seed{1..5}/`. Each run
asserts the written rings' member sets are **identical to the rings the validation metrics came
from**, so the file is the same object the grid chose on, not a re-derivation.

## 6. Merge expectations

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

## 7. Not in this branch

Implied FX rates are **estimated and reported only** (`results/tables/fx_stability.*`), never
applied. Until they are shown stable across days and across releases, an `undetermined` account
stays undetermined; nothing converts amounts.
