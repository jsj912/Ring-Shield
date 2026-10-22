# L4 Explainability — Weeks 1 to 9 handoff

**Branch:** `explainability-l4`. It contains Joan's `v2` up to commit `77add7f` (merged by you), your
fixtures-patch commit `c2a37ab`, Weeks 1–2 (`7ad944f`) and the migration + Week 3 (`c5e2dd5`), all pushed.
**Week 4 and the Week 3 caption fix are uncommitted and unpushed.**

**Status:**
- **Weeks 1 and 2** are complete and have been migrated to Joan's rings contract v2, her exchange rates and her
  validation rings. The mixing weights were chosen on the validation split, as the spec requires (XR-05).
- **Week 3** is complete: every ring now also has **feature weights** (SHAP: which detector features drove its
  suspicious transactions) and a **narrative** (a short, plain-English summary built from a fixed template),
  with every value the narrative used stored next to it so the sentence can be rebuilt and checked (XR-31).
  Week 3 is described in **section 14**.
- **Week 4** is complete: `results/xai/fidelity.json` holds fidelity with 95 % confidence intervals, the two
  comparison rankings with paired tests, the expanded-edge measure (XR-23) and two findings. The verdict is
  **negative**: our ranking does not beat either comparison. Week 4 is described in **section 15**.
- **Synced with Joan's `v2` at `b35b233`** (section 16): her feature loader, her code-to-name maps (currency 0 is
  **US Dollar**, the unconvertible currency 1 is **Bitcoin**, payment format 3 is **ACH**, bank names), her roles fix.
- **Week 5** (sections 17–18): typology, latency, the API and its samples, role accuracy, and the whole layer run
  unchanged on all three detectors (Multi-GINe, GFP+XGBoost, MEGA-GNN).
- **Week 6** (section 19): the 30-explanation review is sampled and its packets and answer sheets are ready to send;
  the scoring script (Fleiss' kappa) is built and tested; the review itself is Week 7.
- **Tenant-scoped explanations for the platform** (section 20; Week 9 integration done early): banks 20 and 12, nothing
  the bank cannot see is counted or mentioned; tenant regenerate for partial verdicts. **Typology finding:** the research typing table (0.219) types the wrong ring for 316 of 401
  matches; the narrated shape is right about 60 % of the time on both windows (pending Joan's confirmation).
- **Week 8** (section 23): the review fixes (wording only; weights and fidelity unchanged), `explainer_version`
  `0.5.0-review`, the before/after page for the 30 reviewed narratives, and the report chapter with its Word copy.
- **Week 9** (section 24): the regeneration service the platform calls for partial verdicts
  (`python -m explainability.serve`), built to Kashish's contract, with a real example payload.
- **294 tests pass, 0 skipped, with pandas warnings as errors**: Joan's 116, 30 for the migration, 79 for Week 3,
  10 for Week 4, 3 for the sync, 24 for Week 5, 6 for Week 6, 10 for the tenant run, 6 for Week 7, 4 for Week 8,
  6 for Week 9.
- Every ring of all five detector seeds, plus the old stub file, has an explanation.

This document is written so that someone with basic technical knowledge can understand what was built,
how every piece works and how we know it works. Read sections 1–3 first; after that every section
stands on its own.

---

## 1. What this layer is for, in one paragraph

Joan's part of the project looks at about 864,000 bank transactions from the test period and outputs
**rings**: small groups of bank accounts that seem to be laundering money together. Our part (L4,
"explainability") says, for every ring, **which transactions and accounts matter most and why**, in
numbers anyone can check, and it **measures** how good those explanations are.

- **Week 1** built the reader for Joan's files and the measuring stick (**fidelity**).
- **Week 2** built the evidence itself: a weight for every transaction and account, and a role for every
  account, written as one **explanation row** per ring.
- **The October migration** brought both up to date with Joan's new files and with what we learned about
  currencies.

## 2. What changed in October, in plain words

1. **Joan added 8 columns to the rings file** ("schema v2") about currencies. Nothing else in the rings
   changed: the same rings, the same accounts, the same transactions. The old files ("v1") are kept in
   `contract/out/v1/`. Our reader now looks at a label inside each file saying which version it is, and
   checks it against the right column list.
2. **We found that exchange rates *can* be recovered.** AMLworld records some payments as "sent in one
   currency, received in another", with both amounts. The dataset's generator uses **fixed** exchange rates,
   so those rows reveal them exactly. Joan confirmed this and published the rates in
   `contract/fx_rates.json` (every currency converts to "currency 0", except **currency 1**, whose amounts
   are too small to pin a rate). So we can now put all amounts into **one unit** (spec requirement XR-02,
   which had been "withdrawn", is met).
3. **Currency "conversions" are removed from the evidence.** A **conversion** is a transaction where an
   account changes its *own* money from one currency to another. In the data it looks like a payment from
   the account to itself. **None of the 72,170 conversions in the dataset is laundering**, and no true ring
   contains one, yet they made up **38.7 %** of the transactions listed in rings. Week 2 was ranking them
   as possible evidence; now they are dropped.
4. **Roles are computed with converted amounts.** Joan's `currency="converted"` mode books each side of a
   payment in its own currency and converts both to currency 0. This corrects 285 of 4,280 account roles
   (mostly to "mule"). It adds a sixth role, **`undetermined`**, used only when an account touches currency
   1, whose balance therefore cannot be checked. That happens to 3 accounts in total.
5. **Validation rings arrived**, so the three mixing weights (α, β, γ) could finally be chosen on the
   validation split, never on test.

**Two "policies"** now exist, picked per run with `--policy`:

| policy | used for | what it does |
|---|---|---|
| **`converted`** (default) | everything current | conversions dropped from evidence; money converted to currency 0; converted roles; tuned mixing weights |
| **`raw`** | reproducing Weeks 1–2 only | everything exactly as first built: all member transactions, raw sums across currencies, raw roles, default mixing weights. Tests prove it reproduces Weeks 1–2 byte for byte |

---

## 3. Words you need (glossary)

| Word | Plain meaning |
|---|---|
| **Account** | One bank account, identified by a number (`account id`). |
| **Transaction / edge** | One payment from one account to another. Drawn as an arrow between two dots, so also called an "edge". Each has an `edge_id`. |
| **Ring** | A group of accounts (and payments between them) that Joan's system thinks is one laundering attempt. |
| **Detector score** | A number from 0 to 1 that Joan's AI model gives each transaction: how likely it is laundering. `score_raw` is the direct output; `score_calibrated` is adjusted so "0.8" really means about 80 %. |
| **Seed edge** | A transaction in the top 0.1 % of scores. Rings are grown from these. |
| **Expanded edge** | A transaction added to a ring despite a low score, because it looked connected to the seeds. These "quiet" members are the point of the project. |
| **Included edges** | Seed + expanded edges: what the ring-builder actually used. |
| **Member edges** | Every transaction between the ring's accounts during the ring's time span (included edges plus any other payments between those accounts). |
| **Conversion** | A transaction whose sent currency differs from its received currency: an account changing its own money. Never laundering. |
| **Evidence edges** | The member edges we are allowed to rank: member edges **minus conversions** (policy `converted`). |
| **Currency 0** | The common unit every amount is converted into (`fx_rates.json` "hub"). It is the **US Dollar** (Joan's `contract/currency_map.json`). |
| **Exchange rate (rate_to_ccy0)** | How many units of currency 0 one unit of another currency is worth, e.g. currency 2 → 1.17178. Fixed for the whole dataset. |
| **Partial** | A ring that touches currency 1 — **Bitcoin**, whose rate cannot be recovered (a typical amount like 0.13 BTC is recorded with only two decimals) — so its money total covers only the convertible transactions. |
| **Truth ring** | A laundering group that really exists. The dataset has an answer key of 370. |
| **Primary window** | Test days 8 and 9: where every headline number is measured. The **val window** is days 6–7 of the validation split. |
| **Matching** | Deciding which predicted ring is which truth ring: Jaccard (shared accounts ÷ all accounts) ≥ 0.5, best pairs first, one-to-one. Joan's code. |
| **Fidelity@k** | "Of the k transactions the explanation ranks highest, what share are truly part of the ring?" (section 7.12). |
| **Control** | A deliberately dumb comparison (random order, or detector score only). An explanation must beat it. |
| **Leave-one-out** | Remove one transaction, rebuild the ring with Joan's code, see how much the ring's confidence drops. |
| **Bridge (`split`)** | A transaction whose removal cuts the ring's accounts into separate pieces. |
| **Role** | What an account does: **source** (money starts), **sink** (money ends), **mule** (passes money on within 72 h), **holder** (passes it on but holds > 72 h), **peripheral** (involved but unbalanced), **undetermined** (touches currency 1: cannot be checked). |
| **Schema version** | Which edition of Joan's rings file layout a file uses: v1 = 22 columns, v2 = 30. Stored inside the file. |
| **Provenance** | A record, stored with every explanation, of exactly which files and settings produced it. |
| **Deterministic** | Running twice gives exactly the same output. |

---

## 4. What exists — every file and folder

All paths are relative to the repository root (`Ring-Shield/Ring-Shield/`).

```
explainability/                 the L4 layer
  __init__.py                   empty; tells Python "this folder is a package"
  config.yaml                   every setting this layer uses, in one place
  contract_io.py                reads Joan's files (v1 or v2) and refuses anything that breaks the rules
  match.py                      which predicted ring is which truth ring (calls Joan's code)
  edge_weights.py               conversions filter; w_score, w_flow (raw / converted), w_loo, bridges, w_total
  account_weights.py            roles (raw / converted), money in/out, busyness, account weight, spec-role check
  explain.py                    one explanation row per ring; the Week 3 PILOT review sample; WEEK 5 latency run
  api.py                        WEEK 5: the four functions behind the explanation endpoints, incl. regenerate
  api_schemas.py                WEEK 5: the shapes the endpoints return (pydantic) and the JSON schema export
  schemas/                      WEEK 5: the exported JSON schemas, one file per shape (for the platform)
  schemas/examples/             WEEK 5: real sample responses of the four functions on the stub data
  review/                       WEEK 6: sample.py (the 30 rings, packets, sheets), aggregate.py (scoring, Fleiss' kappa)
                                WEEK 8: before_after.py (the 30 reviewed narratives, before and after the fixes)
  report/                       WEEK 8: make_figures.py, figures/, xai_chapter.md + xai_chapter.docx (report chapter)
  tenant.py                     tenant-scoped explanations for the platform, incl. tenant regenerate (section 20)
  serve.py                      WEEK 9: the local HTTP regeneration service the platform calls (section 24)
  requirements-serve.txt        WEEK 9: the packages serve.py imports directly, pinned
  evaluate.py                   fidelity, the policy comparison report, the XR-05 tuning, WEEK 4 fidelity.json
  stats.py                      WEEK 4: bootstrap confidence intervals and paired tests (mirrors Joan's ring_stats)
  feature_weights.py            WEEK 3: the detector-feature model's inputs, SHAP, the top-10 feature weights
  narrative.py                  WEEK 3: the narrative templates, formatting, evidence_summary, regeneration
  phrasing.yaml                 WEEK 3: plain-English words for the 17 features and the 8 shapes
  README.md                     this document
  tests/
    __init__.py                 empty
    fixtures.py                 tiny hand-made rings and tables used by the tests
    test_contract_io.py         73 tests: the reader, both schema versions
    test_match.py                8 tests: matching
    test_fidelity.py            23 tests: fidelity, policies, the comparison report, XR-05, WEEK 4 fidelity.json
    test_edge_weights.py        26 tests: edge weights, raw and converted
    test_account_weights.py     11 tests: roles and account weights
    test_explain.py             20 tests: the explanation file, both policies, Week 3 on real rings
    test_feature_weights.py     15 tests: WEEK 3, the SHAP model, its inputs and the feature weights
    test_narrative.py           53 tests: WEEK 3, the narrative on hand-made rings of every shape
    test_stats.py                6 tests: WEEK 4, the statistics, checked against Joan's own functions
    test_week5_eval.py          11 tests: WEEK 5, no attention, typology, latency, role accuracy, three detectors
    test_api.py                 12 tests: WEEK 5, the API shapes, every real row, the endpoints, the sample fixtures
    test_review.py              12 tests: WEEKS 6-7, Fleiss' kappa, sampling, packets, scoring, the analysis plan, the summary
    test_tenant.py              10 tests: tenant run: inputs verified, nothing hidden mentioned, tenant-view SHAP, regenerate
results/xai/                    our results (kept apart from Joan's results/tables/)
  fidelity_week1_seed{1..5}.json, fidelity_week1_stub_cc_seed1.json        Week 1 (policy raw, v1 rings)
  explanations_week2_seed{1..5}.parquet (+ .log.json), ..._stub_cc_seed1    Week 2 (policy raw, v1 rings)
  roles_disagreement_seed{1..5}.csv, ..._stub_cc_seed1.csv                  Week 2 role comparison
  explanations_converted_seed{1..5}.parquet (+ .log.json), ..._stub_cc_seed1  CURRENT explanations
  roles_disagreement_converted_seed{1..5}.csv, ..._stub_cc_seed1.csv        current role comparison
  fidelity_converted_seed{1..5}.json, fidelity_converted_stub_cc_seed1.json CURRENT fidelity (incl. w_total)
  migration_report_raw_vs_converted.json      what the migration changed (Joan's item 8)
  xr05_mixing_choice.json                     the validation-only choice of (α, β, γ)
  explanations_week3_seed{1..5}.parquet (+ .log.json), ..._stub_cc_seed1    WEEK 3: CURRENT explanations
                                              (the weights above + feature weights + narrative + evidence_summary)
  roles_disagreement_week3_seed{1..5}.csv, ..._stub_cc_seed1.csv            same content as the converted ones
  narrative_samples_week3.md                  WEEK 3: one narrative per shape -- a PILOT review (7 rings)
  fidelity.json                               WEEK 4: the spec's fidelity file (XR-22/23/24), pooled over seeds
  typology_eval.json                          WEEK 5: shape accuracy (XR-25), incl. the r5_typing reproduction
  latency.json                                WEEK 5: the dedicated timing run (XR-27)
  explanations_{gfpxgb,mega}_seed{1..5}.parquet (+ .log.json), roles_disagreement_{gfpxgb,mega}_*.csv   XR-36
  fidelity_{gfpxgb,mega}.json, typology_eval_{gfpxgb,mega}.json   XR-36 (fidelity.json also holds role_accuracy)
  xr36_detectors.json                         WEEK 5: the three detectors side by side
  review/                                     WEEK 6: packet_R{1,2,3}.md, answers_R{1,2,3}.csv, sample_manifest.json
                                              (+ answer_key.parquet, git-ignored on purpose; review.csv in Week 7)
                                              analysis_plan.md: WEEK 7, how the review is read, written before scoring
                                              review.csv, review_summary.json / .md, fix_proposals.md: WEEK 7, the scored review
                                              item_features.csv (frozen), before_after.md: WEEK 8
  tenant/                                     explanations_{20,12}_1.parquet (+ .log.json); inputs/ = Kashish's files
                                              regenerate_example_12.json: WEEK 9, a real service request + response
```

`.parquet` files are ignored by git in this repository (Joan's convention); the small `.json` / `.csv` /
`.log.json` files are the ones that get committed.

### What Joan's side provides (read only — never changed by us)

| File | What we use it for |
|---|---|
| `contract/out/scored_edges_gine_causal_{1..5}.parquet` (+ `_val`) | every transaction with its scores, test (and validation) split |
| `contract/out/rings_full_gine_causal_{1..5}.parquet` | the rings, **schema v2** |
| `contract/out/v1/rings_full_gine_causal_{1..5}.parquet`, `v1/rings_stub_cc.parquet` | the original v1 rings, only to reproduce Weeks 1–2 |
| `contract/out/rings_stub_cc.parquet` | an older, simpler set of rings, to check the code works on another kind of ring file |
| `experiments_valrings/average/seed{1..5}/rings_val.parquet` | validation rings, for XR-05 |
| `contract/fx_rates.json` | the exchange rates to currency 0 |
| `experiments/R2_b0/gfpxgb_scores/model_seed{1..5}.json` (+ `scores_test_seed{1..5}.parquet`) | Week 3: the 17-feature GFP+XGBoost model SHAP explains, and its shipped scores (used only to prove our inputs are the model's) |
| `data/processed/amlworld_gfp_features_test.parquet` | Week 3: the 10 graph features of every transaction, joined to the split file to rebuild the model's inputs |
| `contract/schema.py` | the official column lists (`RINGS_COLUMNS` for v2, `RINGS_COLUMNS_V1` for v1) |
| `data/processed/amlworld_ring_ground_truth.parquet`, `amlworld_test.parquet`, `amlworld_val.parquet` | the answer key (accounts) and the true transactions of each ring |
| GFP features and embeddings (test and val), the affinity model, the partition settings | needed so leave-one-out rebuilds rings exactly as they were built |
| Joan's code: `match_rings`, `restrict_rings`, `load_ground_truth`, `load_windows`, `RingRerunner`, `account_roles`, `load_fx_rates`, `rings_schema_version` | we call these; we never copy them |

---

## 5. How to run it

From the repository root (PowerShell or Git Bash), Python 3.11:

```bash
# current explanations (Week 3: weights + SHAP + narrative), all five seeds -> results/xai/explanations_week3_seed*.parquet
python -m explainability.explain

# the Week 3 PILOT review sample (one narrative per shape) -> results/xai/narrative_samples_week3.md
python -m explainability.explain --samples

# weights only, as after the migration -> results/xai/explanations_converted_seed*.parquet
python -m explainability.explain --no-narrative

# current fidelity, including the w_total ranking from those explanations
python -m explainability.evaluate --explanations "results/xai/explanations_converted_seed{seed}.parquet"

# XR-05: choose the mixing weights on the VALIDATION split (writes xr05_mixing_choice.json)
python -m explainability.evaluate --tune-mixing

# the migration report (Week 2 raw vs current converted)
python -m explainability.evaluate --compare-policies

# WEEK 4: fidelity with confidence intervals, paired tests and XR-23 -> results/xai/fidelity.json
python -m explainability.evaluate --week4

# reproduce Week 1 / Week 2 exactly (v1 rings, policy raw)
python -m explainability.evaluate --policy raw
python -m explainability.explain --policy raw --rings "contract/out/v1/rings_full_gine_causal_{seed}.parquet"

# all tests (about 12 minutes; the real-data tests load large files)
python -m pytest explainability/tests -q
```

Always run from the repository root with `python -m ...`, never `python explainability/x.py`.

---

## 6. `config.yaml` — every setting in one place

| Section | Contents |
|---|---|
| `inputs` | test-split files: scored edges, v2 rings, v1 rings (for reproduction), truth, test split, seeds 1–5 |
| `val_inputs` | validation-split files and the `val` window — read **only** by the XR-05 tuning |
| `research_inputs` | GFP features and embeddings for test **and** val, the affinity model, the partition settings |
| output names | one file-name pattern per kind of result and policy, so no run overwrites another |
| `evaluation` | window `primary`, k = 3, 5, 10, 20 random shuffles, random seed; WEEK 4: 1,000 bootstrap resamples, 95 %, 10,000 permutations, the statistics seed, verdict at k = 5 |
| `edge_weights` | `mixing_default` (0.4, 0.4, 0.2), **`mixing_tuned` (0.6, 0.0, 0.4)** from XR-05, grid step 0.1, λ_split 0.5, leave-one-out over included edges, the "ring disappears = full loss" rule, XR-05 objective k = 5 |
| `account_weights` | the two halves of the account weight: 0.5 and 0.5 |
| `amounts` | `currency_policy: converted`, the path to `fx_rates.json`, the amount column |
| `feature_weights` | WEEK 3: the SHAP model file pattern (same seed as the detector), its shipped scores (for the input check), top 10 features, "seed edges minus conversions", the additivity tolerance |
| `narrative` | WEEK 3: the phrasing file, 90 words maximum, 3 significant figures, days from 48 h, 3 accounts per list, 3 evidence edges, 3 features, topology source `rings` |

Numbers Joan owns (match threshold 0.5, window days, role thresholds 25 % / 72 h) are **not** copied:
the config only points to her files.

---

## 7. How each piece works

### 7.1 `contract_io.py` — the strict reader

1. **Find the version.** Joan's `rings_schema_version(file)` reads a label stored inside the file: 1 or 2.
2. **Check the column list for that version** before loading any data: v1 must have exactly Joan's 22
   v1 columns, v2 exactly the 30. Missing or extra columns stop the program with a message naming them.
3. **Load**, and turn list columns into ordinary lists.
4. **Check every ring**, collecting all problems before stopping:
   - seed and expanded edges are inside the member edges, and no edge is both;
   - one expansion probability per expanded edge;
   - 8 topology probabilities adding up to 1;
   - every account named in a role list (including v2's `*_ccy` lists) is a member;
   - closure is between 0 and 1 or empty (empty is legitimate and kept empty);
   - every edge exists in the scored-edges file, joins two members, and is (or is not) a seed exactly as
     the scored-edges file says.
5. **Provenance:** model and seed from the scored-edges file, aggregator from the rings, plus the schema
   version. Rings from one seed paired with another seed's transactions are refused.

It is called `contract_io.py`, not `io.py`, because a file named `io.py` can hide Python's own `io`
module and break pandas.

### 7.2 `match.py` — which ring is which (Joan's rule, Joan's code)

1. Take the window (primary for test, val for validation).
2. Truth rings in the window, with only the accounts seen in the window (Joan's `load_ground_truth`):
   174 truth rings on the primary window.
3. Predicted rings cut down to the window (Joan's `restrict_rings`).
4. Match with Joan's `match_rings` at Jaccard ≥ 0.5.

**The trap we guard against:** `restrict_rings` silently drops rings with nothing in the window and returns
an unnamed, shorter list, so "item 1" of its output may really be ring 2. We drop those rings ourselves
first, keep the names alongside, and stop if the lengths ever differ.

**True transactions of a ring:** taken from the split file's `ring_id` column (the answer key lists
accounts, not transactions), inside the window. A test checks that their accounts equal the answer key's.

### 7.3 Conversions and evidence edges (`edge_weights.conversion_mask`, `evidence_edge_ids`)

- **A conversion is any transaction whose sent currency ≠ received currency.** Among ring transactions,
  every one is an account paying itself.
- **Policy `converted`:** the evidence edges are the member edges minus conversions, and each explanation
  records how many were dropped.
- **Policy `raw`:** nothing is dropped.

Measured on the five seeds:
- 2,912 of 7,520 member edges (38.7 %) are conversions, in 489 of 560 rings;
- none is labelled laundering;
- no true ring transaction is a conversion, so dropping them never removes real evidence.

**33 conversions** were among the transactions the ring-builder itself used. They stay in the
leave-one-out rebuild (so rings still rebuild exactly) but are never ranked.

### 7.4 `w_score` and the score ranking (`edge_weights.rank_by_score`)

`w_score` = the calibrated detector score. To rank, sort by calibrated score (highest first), then raw
score, then `edge_id`; a missing score goes last. The tie-breaks matter: calibration squeezes ~800,000
scores into ~100 values, so ties are everywhere and without them the order would change between runs.

### 7.5 `w_flow` — share of the ring's money

**Policy `converted` (current, `w_flow_converted`):**

> value(e) = amount received × exchange rate of its currency to currency 0
> w_flow(e) = value(e) ÷ total value of the ring's evidence edges

- The input must already have conversions removed; if a conversion slips through, the program stops.
- An exact duplicate payment (same sender, receiver, time and amount) is counted once in the total, and
  both copies show the same share.
- A transaction in **currency 1** has no rate. It gets `w_flow = 0`, is left out of the total, and the
  ring is marked **partial**. The shares then add up to 1 over the convertible transactions.

Worked example (`fixtures.converted_flow_case`, rate of currency 2 ≈ 1.17178):

| payment | currency | value in currency 0 | w_flow |
|---|---|---|---|
| A→B 100 | 0 | 100 | 100 ÷ 267.18 = 0.374 |
| A→B 100 (duplicate) | 0 | 100 | 0.374 (counted once in the total) |
| B→C 100 | 2 | 117.18 | 0.439 |
| C→D 50 | 0 | 50 | 0.187 |
| B→B (conversion) | 0→2 | — | not evidence |

The unique payments add up to exactly 1. With a currency-1 payment instead of the currency-2 one, the
ring is partial: 100 ÷ 150 and 50 ÷ 150 for the two convertible payments, 0 for the currency-1 one.

**Policy `raw` (Week 2):** amount ÷ the ring's raw total, summing different currencies as if they were the
same unit. Kept only for reproduction.

### 7.6 `w_loo` and bridges — how much the ring depends on a transaction

For one ring:
1. **Build the rebuilder.** Take the included transactions and build one of Joan's `RingRerunner`s with the
   real GFP features, embeddings and affinity model. If it reports "degraded" (an input missing), stop.
2. **c₀** = the confidence of the ring rebuilt from all its included transactions (1 call).
3. **For each included transaction e** (1 call each):
   - c₋ₑ = the confidence of the largest ring rebuilt without e;
   - drop = c₀ − c₋ₑ, never below 0;
   - if no ring is left at all, drop = c₀ (a "full loss");
   - split(e) = 1 if e is a bridge;
   - raw = drop + 0.5 × split.
4. **Scale to 0–1.** w_loo = raw ÷ the largest raw among the ranked transactions (policy `converted`) or
   among all included transactions (policy `raw`). Transactions the builder never used get 0.

The rebuilder is called exactly (included transactions + 1) times per ring.

**Bridge rule:** draw accounts as dots and transactions as plain lines. Removing a line that leaves more
separate groups means it was a bridge. In a chain every link is a bridge; in a loop none is; in a fan
every link is one.

**Worked example** (`fixtures.loo_case`: A→B 100 seed 0.9, B→C 90 seed 0.8, C→D 80 seed 0.6,
A→C 30 expanded 0.2, B→D 20 member only):

| without | confidence | drop |
|---|---|---|
| nothing (c₀) | 0.767 × (1 − 50/130) = **0.4718** | — |
| A→B | 0.70 × (1 − 40/120) = 0.4667 | **0.0051** |
| B→C | 0.75 × 130/180 = 0.5417 | 0 |
| C→D | 0.85 × 120/130 = 0.7846 | 0 — but it is a bridge (cuts D off): raw 0.5 |
| A→C | 0.767 × 0.8 = 0.6133 | 0 |

So w_loo(C→D) = 1 and w_loo(A→B) = 0.0051 ÷ 0.5 = 0.0103. Joan's real rebuilder reproduces these to 1e-6.

**5 of 560 shipped rings do not rebuild identically** (2-16, 2-47, 2-105, 3-74, 4-90): an account shared
between rings saw all of them when the ring was first built, but only this ring when rebuilt alone. Joan
accepts this. Each of those explanations says `reproduces_shipped_ring: false`, and a test pins exactly
these five.

### 7.7 `w_total` — the mix (`edge_weights.edge_weight_table`)

> w_total = α × w_score + β × w_loo + γ × w_flow

- **Policy `converted` uses the validation-tuned weights (0.6, 0.0, 0.4)** (section 7.13).
- **Policy `raw` uses the untuned default (0.4, 0.4, 0.2).**
- The weights must be ≥ 0 and add up to 1.
- Every evidence transaction gets a row, sorted by `w_total` with the score tie-breaks.

### 7.8 Roles (`account_weights.research_roles`, `spec_roles`, `role_disagreements`)

**Joan's rule, thresholds from her `configs/roles.yaml` (25 %, 72 h):**

| role | rule |
|---|---|
| sink | sends nothing (or sends less than a quarter of what it receives) |
| source | receives nothing (or receives less than a quarter of what it sends) |
| mule | in and out within 25 % of each other, passed on within 72 h |
| holder | balanced, but held longer than 72 h (or hold time unmeasurable) |
| peripheral | everything else, e.g. in 100, out 50 |
| **undetermined** | **policy `converted` only:** touches currency 1, so the balance cannot be checked — never shown as peripheral |

**Policy `converted`** calls Joan's `account_roles(..., currency="converted")`:
- the sender's side is booked at what it **sent**, in its currency;
- the receiver's side at what it **received**;
- both are converted to currency 0 before the rule is applied.

Under the old `raw` booking, an account's outgoing payment was recorded at the receiver's amount and
currency. That's why 285 roles change, mostly to mule.

**Hold time:** for each payment into the account, the wait until the next payment out; take the median.

**The spec's own rule (§4.3)** is run as well, for comparison only. It measures hold time the other way
round, and calls an unmeasurable balanced account peripheral instead of holder. It is always compared
against Joan's **raw** roles, because it is a comparison of two *definitions*, not of two currency
treatments. Differences go to `roles_disagreement_*.csv`, each with a cause: `hold_time_definition`,
`undefined_hold_time` or `rule_order`. Across 560 rings there are 13, all `undefined_hold_time` (accounts
that paid out before receiving anything). The files are byte-identical before and after the migration.

### 7.9 Account weight (`account_weights.account_weight_table`)

> w_account(a) = 0.5 × (sum of w_total on a's ring transactions ÷ the largest such sum in the ring)
>              + 0.5 × (a's transactions inside the ring ÷ a's transactions in the whole test period)

The second half is high for an account busy inside the ring and quiet outside it, which is how a
laundering account behaves. Under policy `converted`, conversions are not counted in either part, so an
account changing its own money does not look busier.

Example (`fixtures.account_weight_case`): A→B (`w_total` 0.8) and B→C (0.4); whole period A 4, B 2, C 1
transactions → B = 1.0, C = 0.667, A = 0.458.

### 7.10 The explanation file (`explain.py`)

For every ring:
1. compute the edge weights (7.3–7.7);
2. compute the roles (7.8) and the account weights (7.9);
3. run the spec-role comparison;
4. copy the ring's topology;
5. record the provenance and the time taken.

| column | contents |
|---|---|
| `ring_id`, `tenant_id` | which ring, which bank |
| `edge_weights` | one entry per evidence transaction: `edge_id, w_total, w_score, w_loo, w_flow`, highest first |
| `account_weights` | one entry per member account: `account_id, role, inflow, outflow, hold_time_s, w_account` (amounts in currency 0 under `converted`) |
| `feature_weights`, `narrative`, `evidence_summary` | empty until Week 3 |
| `topology_type`, `topology_prob` | the ring's shape and probability, copied |
| `latency_ms` | milliseconds this row took |
| `provenance` | the policy, schema version, mixing weights **and where they came from**, the `fx_rates.json` path and SHA-256 fingerprint, conversions dropped, partial flag, money total in currency 0, undetermined accounts, the rebuild settings, and whether the ring rebuilt identically |

**Next to each file:**
- a `.log.json` with counts, role totals, conversions dropped, partial rings and latency;
- a role-disagreement CSV.

**Determinism:** two runs are identical in every column except `latency_ms` (a stopwatch cannot repeat).
The test compares the file **bytes** with `latency_ms` zeroed, because two empty values (NaN) never count
as equal in Arrow's own comparison.

### 7.11 Fidelity (`evaluate.py`)

For each predicted ring that matched a truth ring:

> fidelity@k = (how many of the top-k ranked transactions are truly in the ring) ÷ min(k, number of true transactions)

The transactions ranked are the ring's evidence edges in the window. Three rankings are scored:
- **score-only** (control);
- **random** (control: 20 fixed-seed shuffles, averaged);
- **w_total** (ours, read from the explanation file).

Worked example (`fixtures.five_edge_case`):
- the ranking is 11, 12, 13, 14, 15 and the true set is {11, 13, 14};
- fidelity@3 = 2 ÷ 3 = 0.667;
- fidelity@5 = 3 ÷ 3 = 1.

**The random control is checked against theory:** for a random order, the expected fidelity is
(k × |T| ÷ n) ÷ min(k, |T|), where n is the number of ranked transactions.

### 7.12 XR-05 — choosing α, β, γ on validation (`evaluate.tune_mixing`)

1. For each seed, load the **validation** rings, transactions and true transactions, and match them on the
   validation window (days 6–7).
2. For every matched validation ring, run non-degraded leave-one-out with the **validation** GFP features
   and embeddings.
3. For each of the **66** combinations of (α, β, γ) in steps of 0.1 that add up to 1, rank each ring's
   evidence edges by `w_total` and compute fidelity@5.
4. Average per seed, then across the five seeds.
5. Pick the best combination. Ties go to the one closest to the default (0.4, 0.4, 0.2), then to the
   larger α, then the larger β.
6. Write everything to `xr05_mixing_choice.json`: the whole grid, per-seed details, every file read and the
   latest timestamp read.

Then the choice was copied into `config.yaml` (`mixing_tuned`) **before** any test run used it. A test
proves that no test-split file was read, that every timestamp read is before the test window, that the
choice follows the stated rule, and that the config equals the choice file.

### 7.13 The migration report (`evaluate.compare_policies`)

This compares Week 2 (v1 rings, policy `raw`) with the migrated run (v2 rings, policy `converted`). It
reports:
- role counts and every role change;
- how many top-k evidence edges in Week 2 were conversions;
- how often the top-k set stayed the same;
- fidelity under both policies;
- how many matched rings can tell rankings apart at all.

It was produced **before** tuning, with the default mixing weights on both sides, so it isolates the
effect of the currency change.

---

## 8. Results

### 8.1 Week 1 (policy `raw`, still reproducible exactly)

Mean over 5 seeds, primary window, 401 matched ring-instances. Score-only: **0.919 / 0.912 / 0.912** at
k = 3 / 5 / 10. Random: **0.621 / 0.709 / 0.845**.

### 8.2 The migration (`migration_report_raw_vs_converted.json`)

| | Week 2 (raw) | current (converted) |
|---|---|---|
| roles changed | — | **285 of 4,280** (6.7 %): 111 source→mule, 68 sink→mule, 66 peripheral→mule, … ; 3 → undetermined |
| conversions in the top-3 / top-5 / top-10 evidence slots | 94 / 278 / 779 | 0 (filtered) |
| rings with the same top-3 evidence set | — | 385 of 560 |
| fidelity, score-only @3 / @5 / @10 | 0.919 / 0.912 / 0.912 | 0.924 / 0.918 / 0.915 |
| fidelity, random @3 / @5 / @10 | 0.621 / 0.709 / 0.845 | **0.908 / 0.904 / 0.910** |
| matched rings whose ranked edges are ALL true | 18 of 401 | **343 of 401** |
| matched rings that can tell rankings apart | 377 | **52** |

### 8.3 The most important finding: fidelity is now saturated

**Most of Week 1's gap between "score-only" and "random" came from the conversions.** They are never
laundering, have low scores, and sat in nearly every ring, so any score-based ordering pushed them down
while a random one did not. With them removed, 86 % of matched rings consist entirely of true
transactions, and in those rings **every** ordering scores fidelity 1. Only 52 of 401 ring-instances can
tell one ranking from another.

- **This is a property of the measuring stick, not of the explanations.**
- **It means XR-24** ("beat both controls with non-overlapping confidence intervals") **cannot be passed on
  this metric as defined.**
- **Ways forward are a decision for you and Joan** (section 11).

### 8.4 XR-05 (validation only)

**Chosen weights: (α, β, γ) = (0.6, 0.0, 0.4).**
- **Validation fidelity@5:** 0.9126 for the chosen weights against 0.9017 for the default; the whole
  66-combination grid spans only 0.025.
- **Leave-one-out never helped:** all top-8 combinations give it zero weight.
- **Few rings decided it:** only 89 of 431 matched validation ring-instances could discriminate between
  rankings.
- **It was validation-only:** no test file was read, and the latest timestamp read is 690,970, before the
  test window at 691,210.

### 8.5 Current explanations and fidelity (policy `converted`, tuned weights)

| seed | rings | rebuilt identically | conversions dropped | partial rings | undetermined | latency p95 |
|---|---|---|---|---|---|---|
| 1 | 108 | 108 | 609 | 0 | 0 | 669 ms |
| 2 | 112 | 109 | 601 | 1 | 3 | 710 ms |
| 3 | 113 | 112 | 602 | 0 | 0 | 660 ms |
| 4 | 120 | 119 | 576 | 0 | 0 | 465 ms |
| 5 | 107 | 107 | 524 | 0 | 0 | 585 ms |
| stub | 98 | 48* | 551 | 0 | 0 | ~100 ms |

\* The stub predates Joan's current confidence definition, so its stored confidence differs. This is
expected.

Test fidelity, mean over seeds:

| ranking | @3 | @5 | @10 |
|---|---|---|---|
| score-only | 0.924 | 0.918 | 0.915 |
| **w_total (tuned)** | **0.923** | **0.909** | **0.915** |
| random | 0.908 | 0.904 | 0.910 |

**Honest reading:**
- **The tuned mix does not beat the detector score on test**; it is equal at k = 3 and 10 and slightly
  lower at k = 5.
- **All three rankings are within about 0.02 of each other**: the saturation of section 8.3.
- **This is reported as found**, not hidden.

---

## 9. The tests (294 pass, 0 skipped; Week 3 in 14.6, Week 4 in 15.6, the sync in 16, Week 5 in 17-18, Week 6 in 19.4, tenant in 20.4, Week 7 in 21-22, Week 8 in 23, Week 9 in 24)

**`test_contract_io.py` (73)**
- All real files load and validate: v2 rings for 5 seeds plus the stub, **and** the v1 originals, each
  under its own version.
- v1 and v2 hold the same rings (the 22 shared columns are identical).
- A wrong-version column list is refused, and so is an unknown version.
- Deleting any single column (all 17 transaction and 30 ring columns) is caught and named.
- Wrong types are refused.
- Every ring rule fires: seed not a member, expanded probabilities, topology sum, missing edge, rings
  paired with the wrong seed.
- Empty closure stays empty.
- All fixtures are valid, and Joan's patched "broken fixture" test now fails for its real reason.

**`test_match.py` (8)**
- Matched counts equal Joan's run logs for every seed (seed 1: 94 / 174 / 81).
- The true transactions' accounts equal the answer key.
- The "ring outside the window" trap does not shift names.
- No matching code is rewritten here.

**`test_fidelity.py` (19)**
- The worked example, tie-breaks, edge cases.
- The random control is reproducible and matches theory.
- Fixtures score 1 when every edge is true.
- Two full runs give byte-identical JSON.
- **Policy `raw` on the v2 rings reproduces Week 1 exactly** (5 seeds plus the stub).
- **Policy `converted` drops exactly the conversions and never a true transaction.**
- The evidence-filter unit test.
- The migration report is consistent (285 changes, 3 undetermined, 4,280 accounts).
- The 66-combination grid.
- **XR-05 was chosen on validation only**, follows its tie-break, and equals the config.

**`test_edge_weights.py` (26)**
- Rebuilds are never degraded, and every ring rebuilds exactly except the pinned five.
- Missing inputs are refused.
- The `w_flow` raw duplicate rule.
- `w_loo`, c₀, c₋ₑ and bridges equal the hand computation to 1e-6.
- The rebuilder is called exactly edges + 1 times.
- The full-loss and all-zero cases.
- `w_total` for all five edges to 1e-6, a changed mix changes the output, and bad mixes are refused.
- **Converted `w_flow`**, using Joan's rate table:
  - the shares are correct and sum to 1;
  - conversions are refused;
  - a currency-1 ring is partial and sums to 1 over the convertible transactions;
  - the converted table drops conversions and rescales `w_loo`.
- Currency 1 has no rate.

**`test_account_weights.py` (11)**
- Raw roles reproduce the contract role lists for all 560 rings.
- In-ring activity never exceeds whole-period activity.
- All five roles are covered.
- The spec-rule disagreement and its cause.
- The thresholds come from the config.
- `w_account` matches the hand computation.
- **Converted roles leave exactly 3 undetermined accounts of 4,280, all touching currency 1** (Joan's
  figure, independently confirmed).

**`test_explain.py` (9)**
- The file layout and coverage, with numbers equal to the hand computation under the active mix.
- Provenance follows the config.
- Disagreements reach the output.
- Two real runs are byte-identical apart from timing.
- **`undetermined` appears only under `converted`, never as peripheral.**
- The converted provenance records the currency treatment.
- **Policy `raw` on the v1 rings reproduces Week 2 byte for byte** (seed 1 and the stub: edge weights,
  account weights and the disagreement file).
- **Converted explanations contain no conversion, and `w_flow` sums to 1 per ring.**

Run: `python -m pytest explainability/tests -q` (about 15 minutes).

---

## 10. Decisions, and what came up while building

**Decisions (approved):**
- **Evidence:** the evidence set is member edges minus conversions.
- **Leave-one-out:** the 33 conversions the ring-builder used stay in leave-one-out but are never ranked.
- **Reproduction:** `raw` reproduces Weeks 1–2 fully.
- **XR-05:** one combination pooled over seeds, ties toward the default, recorded before any test use.
- **Timing:** XR-05 was done now rather than in Week 4.

**Came up while building:**
1. **Fidelity is saturated after the conversion filter** (section 8.3). This is the most important result
   of the migration.
2. **XR-05 gave leave-one-out zero weight**, and the tuned mix does not beat the score on test.
3. **(Resolved in v2 `b35b233`: `MIGRATION.md` now has the one rule we implemented.)** **Joan's message and her
   `MIGRATION.md` disagreed** on currency-1 rings: within-currency fallback, or
   convertible-only plus a partial flag. We followed the message (convertible-only plus partial), which
   also matches her requested test.
4. **(Resolved in v2 `b35b233`: Joan replaced `fillna` with `where`; roles byte-identical; our suite now runs with
   pandas warnings as errors.)** **A pandas deprecation warning from Joan's `ringshield/roles.py` (line ~278)**
   appeared in some runs. It
   is harmless, and outside our folders, so it is reported rather than edited.
5. **One Week 1 fixture needed its "true" set to exclude conversions**, because its mixed-currency ring
   used cross-currency payments. Real truth rings never contain conversions (tested).
6. **The migration report was made before tuning**, so it isolates the currency change. Re-generating it
   now would mix in the tuned weights.

---

## 11. Requirements status, and decisions needed

| Req | Status |
|---|---|
| XR-01 reader, 02 one currency, 03–04 weights and mix, 06–07 rerun and bridges, 08–12 accounts and roles, 21 file layout, 28 matching, 30 determinism (except timing), 32 provenance, 37 config | **met** |
| XR-05 mixing tuned on validation | **met** |
| XR-22 fidelity with 1,000-resample bootstrap CIs | **met** (Week 4, section 15) |
| XR-23 fidelity restricted to expanded edges | **met** (Week 4: expanded recall@k as agreed with Joan) |
| XR-24 random and score-only controls | **met as a measurement; the result is negative**: our ranking does not beat either control (spec 6.2 says to report it as negative) |
| XR-13 SHAP on the 17-feature model, XR-14 top-10 per ring, XR-15 phrasing, XR-16 templates, XR-17 evidence_summary, XR-18 cross-bank, XR-19 topology source, XR-31 regeneration | **met** (Week 3, section 14) |
| XR-20 Integrated Gradients (optional, "could") | not done: only if Weeks 1–5 finish early |
| XR-25 typology accuracy and confusion | **met** (Week 5; headline corrected for the research lookup bug, pending Joan) |
| XR-27 latency | **met**: p95 918 ms on this laptop |
| XR-33 functions + schemas, endpoints return 200 on stub data | **met** (Week 5; handoff to Kashish after part 2) |
| XR-34 regenerate after member edits | **met** |
| XR-35 no attention weights | **met** (test) |
| XR-29 thirty-ring internal review, Fleiss' kappa | **met** (Weeks 6-7, sections 19, 21, 22): scored, kappa computed, summary written |
| XR-26 role precision / recall vs ground-truth-derived roles | **met** (Week 5, section 18.1) |
| XR-36 runs unchanged on any detector's files | **met** (Week 5, section 18.2: three detectors, no code difference) |

**Decided with Joan (Week 4):** the spec's definition stays the headline and is reported as negative; the 52
non-saturated rings are a labelled secondary result; "every transaction touching the ring" is not reported as
fidelity; the mixing weights are not re-tuned on test. Details and results in section 15.

## 12. Next weeks

**Week 3:** done (section 14). Open: the 7-ring PILOT review of `narrative_samples_week3.md`; Joan is adding
currency and payment-format name maps (banks keep "Bank <code>": AMLworld has no bank names).

**Week 4:** done (section 15).

**Week 5:** typology, role accuracy with converted roles, latency and the API (role values include
`undetermined`).

## 13. Note for Joan

> Hi Joan — the migration is done on `explainability-l4` (not pushed). Everything you listed:
> - v1/v2 branching on `rings_schema_version` with your `RINGS_COLUMNS_V1`;
> - converted roles, with `undetermined` rendered explicitly;
> - conversions dropped from evidence and `w_flow`;
> - converted `w_flow` with a partial flag for currency 1;
> - XR-02 met;
> - XR-05 tuned on your validation rings with non-degraded reruns;
> - the Week-2 comparison;
> - new tests: 146 pass, and `raw` reproduces Weeks 1–2 byte for byte.
>
> Your figures reproduce independently: 285 of 4,280 role changes, 3 undetermined, 2,912 conversions
> (38.7 %).
>
> Three things for you:
> 1. **Fidelity saturates once conversions are gone.** 343 of 401 matched rings consist entirely of true
>    edges, so any ordering scores 1; only 52 can discriminate. XR-05 chose (0.6, 0.0, 0.4), which gives
>    leave-one-out zero weight, and on test the tuned mix ties the score-only control. We need to agree how
>    fidelity should be defined (README §11).
> 2. **Your message and `MIGRATION.md` §5 disagree on currency-1 rings.** I followed the message:
>    convertible-only share plus a `partial` flag, no within-currency fallback. Please align the doc.
> 3. **`ringshield/roles.py` ~line 278** raises a pandas `FutureWarning` (fillna downcasting). Harmless;
>    yours to change.
>
> Week 3 (SHAP + narratives) is also done, 225 tests pass. Four more things:
> 4. **Your feature loader can't be imported here.** `baselines/gfp_xgboost_aml.py` imports `optuna` at the top,
>    which isn't installed, so I repeated its 10-line join (split + trailing GFP on EdgeID) with the same
>    assertions. A test proves it's the same input: the R2_b0 model's predictions on our rows equal
>    `scores_test_seed*.parquet` exactly on every seed edge of all five seeds.
> 5. **shap 0.50 misreads the R2_b0 model's base value** (XGBoost 3 stores `base_score` as `"[5.42E-1]"`), so
>    `TreeExplainer.expected_value` is off by 2.74 log-odds. The per-feature values are exact (equal to XGBoost's
>    own `pred_contribs`); I take the base value from XGBoost. Worth knowing if anyone else uses SHAP on it.
> 6. **The payment method is the top SHAP feature in 509 of 560 rings.** Is that expected from the refit?
> 7. **Do you have names for the currency, payment-format and bank codes?** Narratives say "currency 0" and list
>    bank codes for now.
>
> Week 4 (your Q1–Q6 decisions) is done: `results/xai/fidelity.json`, 235 tests pass, our bootstrap and paired
> test reproduce your `bootstrap_over_rings` / `paired_permutation` exactly, Holm imported from `ring_stats`.
> - Headline (100 truth rings): fidelity@5 ours 0.881 [0.838, 0.921], score-only 0.891, random 0.874 -> negative
>   against both; only 5 truth rings rank differently from score-only.
> - **XR-23 (b) expanded recall@5: ours 0.724, score-only 0.729, random 0.873** (ours below random, Holm p < 0.001).
>   Quiet edges have low scores by definition, the mix is 0.6 score + 0.4 flow, and LOO got zero weight -- so the
>   explanation under-ranks exactly the edges L3 recovers. Worth a line in the paper.
> - Saturation 343/395 reported as a ring-quality result; XR-05 resting on 89/431 discriminating val rings, grid
>   span 0.025, LOO weight 0 -- stated plainly; nothing re-tuned.
> - Caption changed to "Signals from a reference transaction-level model"; the 7-ring review is labelled a pilot.
>
> Synced with v2 `b35b233` -- thank you, items 2-7 above are resolved: `refit_data` imported (rows byte-identical to
> my copy), roles fix confirmed (suite runs with pandas warnings as errors), narratives now say US Dollar / Bitcoin /
> ACH and bank names (display only, shared names disambiguated by id). Weights and fidelity numbers unchanged.

---

## 14. Week 3 — feature weights (SHAP) and narratives

Week 3 fills the three columns that were empty until now: `feature_weights`, `narrative` and `evidence_summary`.
Nothing from Weeks 1–2 changes: a test proves the edge weights, account weights and topology in the Week 3 files
are byte-identical to the migrated Week 2 files.

### 14.1 What SHAP is, in plain words

Joan's project has a second, simpler detector next to the GNN: **GFP+XGBoost**. It is a set of decision trees
that looks at **17 named numbers** about each transaction (its amount, currency, payment method, hour, day, and
10 "graph" numbers such as how many accounts the sender pays). The GNN's inputs have no names, so the spec
explains rings with this named model instead.

For one transaction, the model gives a score (in "log-odds": higher = more suspicious). **SHAP splits that score
exactly into a starting value plus one contribution per feature.** A positive contribution means "this feature
made the model more suspicious", a negative one "less suspicious". Added together they give the score exactly.

Tiny example: start −3.0; payment method +2.6; scatter-gather paths +1.4; hour of day −1.1 … → score. So the
payment method pushed this transaction most towards "laundering".

### 14.2 `feature_weights.py` — how the feature weights are computed

1. **Pick the model.** `experiments/R2_b0/gfpxgb_scores/model_seed{seed}.json`, same seed as the detector. This is
   the 17-feature refit, not the retired 28-feature model (Reality Check 5.1). **The feature list is read from the
   model file**, never typed in by us; a test checks it equals the refit's own config.
2. **Rebuild the model's inputs.** Join `amlworld_test.parquet` with `amlworld_gfp_features_test.parquet` on
   `EdgeID`, one row each, and take the 17 columns in the model's order. The GFP file must say it is the
   "trailing" version the model was trained on; otherwise the program stops.
3. **Prove the inputs are right.** Predict with the model on our rows and compare with Joan's shipped scores
   (`scores_test_seed*.parquet`): the difference is **exactly 0** on every seed edge of all five seeds (3,400
   edges). Each run checks this again before explaining anything.
4. **SHAP for the ring's seed edges.** `shap.TreeExplainer` (exact for tree models) gives the 17 contributions for
   each **seed edge minus conversions** (conversions are never evidence).
   - The starting value comes from XGBoost itself. shap 0.50 misreads how XGBoost 3 stores it and would be off
     by 2.74; the 17 contributions themselves are exact (tested equal to XGBoost's own `pred_contribs`).
   - Check: starting value + the 17 contributions = the model's output, within 0.00002, for every seed edge.
5. **Average per feature** over the ring's seed edges, sort by size (ignoring the sign; ties keep the model's
   feature order), keep the **top 10**.
6. For each, record the **top edge**: the seed edge with the largest contribution to that feature (ties: the
   smaller edge id).

Stored as `feature_weights = [(feature_name, mean_shap, top_edge_id), …]`.

Worked example (from the tests): two edges, 20 and 10, with feature a = (0.2, 0.4), b = (−1.0, 0.0),
c = (0.3, −0.3). Means: a 0.3, b −0.5, c 0. Order by size: b (0.5), a (0.3), c (0). Top edge of b: edge 20
(|−1.0|). Top edge of a: edge 10 (0.4).

### 14.3 `narrative.py` — how a narrative is built

The narrative is **a filled template, never free text; no language model is used.** Three steps:

**Step 1 — values.** Collect every fact the sentence may state, all from stored weights or ring fields:
- the shape (`topology_type`) and its probability;
- counts of accounts and evidence transactions, and the time span;
- the money total **in currency 0** (the converted `w_flow` total) and whether it is partial (currency 1);
- the share of money conserved, from Joan's `ring_conservation_converted` (currency 0). It's empty when the ring
  has no pure source or no pure sink. The shipped raw closure is kept in the record for audit only;
- the accounts of each role, ordered by account weight;
- the 3 highest-`w_total` transactions with their amounts in currency 0;
- the top 3 SHAP features;
- the banks of the member accounts;
- shape facts measured on the evidence transactions: the account paying (or paid by) the most different
  accounts, an account that both gathers from ≥ 2 and pays ≥ 2, the longest chain, whether there is a loop,
  and the number of separate sender–receiver pairs.

**Step 2 — slots.** Turn each value into the exact text it appears as:
- amounts to 3 significant figures with thousands separators (12,345.6 → 12,300);
- time in hours below 48 h, days from there on (6 h, 47.5 h, 2 days, "under 1 h");
- at most 3 accounts per list, then "+N more";
- a missing value becomes "no slot".

**Step 3 — clauses.** Each shape has an ordered list of clauses (short sentences with slots):
- **A clause is used only if every slot it needs has a value**, so a sentence can never show a blank, "None" or
  "nan".
- **Shape sentences are facts, not guesses.** The shape name comes from Joan's typing model, which is right only
  about 22 % of the time, so it is always written as "most likely shape, p = …". But a sentence like
  "Account X paid 9 different accounts" or "Money travelled in a loop" appears only when the transactions
  actually show it.
- **At most 90 words.** If longer, optional clauses are removed in a fixed order: the role lists, the chain
  hold time, the bank list (first shortened to "The accounts span N banks."), the feature signals, the closure.

| Shape | Its own sentence (when the transactions show it) |
|---|---|
| Fan-out | Account A paid N different accounts. |
| Fan-in | Account A was paid by N different accounts. |
| Gather-scatter | Account A gathered money from N accounts and passed it on to M. |
| Scatter-gather | Money spread out from …, passed through … and came together at …. |
| Cycle | Money travelled in a loop through the accounts. |
| Layered chain (STACK) | Funds moved N hops from … to … through …. Each intermediary passed money on within a median of …. |
| Bipartite | It splits into N separate sender-receiver pairs. |
| Irregular (RANDOM), Unclassified | no shape sentence ("Unclassified" uses the head "Suspected ring: …") |

Common clauses, in order: roles; undetermined accounts ("Account X uses Bitcoin, which has no exchange rate,
so its role cannot be checked."); total moved ("Total moved: 433,000 (US Dollar)", with a "partial" note naming
Bitcoin); closure %, or "Conservation
cannot be measured: no account only sends or only receives."; strongest evidence; feature signals ("that raised
suspicion: …; that lowered it: …"); banks.

A real example (ring `full-gine_causal-1-4`, seed 1):

> Fan-out ring (most likely shape, p = 0.92): 10 accounts, 9 transactions over 2.57 days. Account 513343 paid 9
> different accounts. Total moved: 433,000 (US Dollar). 100% of the money sent by the sources reached the
> sinks. Strongest evidence: 513343→33859 (296,000, weight 0.87); 513343→178251 (59,200, weight 0.65);
> 513343→142719 (18,100, weight 0.62). Signals from a reference transaction-level model that raised suspicion:
> the payment method, two-hop scatter-gather paths; that lowered it: the sender paying many accounts. The accounts span 10 banks (8, 6625,
> 10709 +7 more).

**`evidence_summary`** is JSON with the values (step 1), the slots exactly as substituted (step 2), and the
clauses used (step 3). **`regenerate(evidence_summary)` rebuilds the sentence from the values alone** and must
equal the stored narrative character for character (XR-31). It also refuses a summary whose stored slots or
clauses don't follow from its values, so a hand-edited summary is caught.

### 14.4 `phrasing.yaml`

Plain words for the 17 features (e.g. `scatter_gather` → "two-hop scatter-gather paths", `temporal_cycle` →
"money returns to origin within the window", `Payment Format` → "the payment method") and the 8 shapes (STACK →
"Layered chain", RANDOM → "Irregular"). Change a phrase here and every narrative follows. A test checks it covers
exactly the model's 17 features and every shape, and that no raw feature or shape code ever appears in a
narrative.

### 14.5 Results

| seed | rings | narratives | words (median / max) | latency p95 (incl. SHAP) | max |
|---|---|---|---|---|---|
| 1 | 108 | 108 | 87 / 90 | 1,192 ms | 2,339 ms |
| 2 | 112 | 112 | 86 / 90 | 1,116 ms | 2,229 ms |
| 3 | 113 | 113 | 86 / 90 | 1,183 ms | 2,396 ms |
| 4 | 120 | 120 | 87 / 90 | 796 ms | 1,611 ms |
| 5 | 107 | 107 | 87 / 90 | 893 ms | 2,057 ms |
| stub | 98 | 98 | 84 / 90 | 574 ms | 936 ms |

(Numbers from the regeneration after the Week 4 caption change. That run shared the machine with other jobs, so
latencies are higher than the first Week 3 run (p95 622–927 ms); every seed is still under the 2,000 ms target.)

Over the 560 rings of the five seeds:
- **Latency:** p95 is under the 2,000 ms target in every seed; no ring is over 5,000 ms.
- **Every ring spans at least two banks.** The bank clause is kept in 516 (460 with the bank list, 56 as a
  count); 44 lose it to the word limit. (Before the Week 4 caption change, which adds four words, only 12 did.)
- **Feature clause:** present in 555; 5 lose it to the word limit (1 before the caption change).
- **Closure:** 525 rings state it; 35 take the "cannot be measured" branch.
- **Currency 1:** 1 ring is partial; 1 narrative names undetermined accounts.
- **Shape sentences:** stated only where the transactions show the shape. For example, 9 of the 59 rings typed
  Cycle actually contain a loop, and 65 of 108 typed Gather-scatter have a gathering-and-paying account.
- **Feature dominance:** the payment method is the top SHAP feature in **509 of 560 rings**. The feature model
  leans heavily on it; reported to Joan.

**The PILOT review sample** (`narrative_samples_week3.md`; 7 rings cannot support Fleiss' κ — the spec's
30-ring review comes in Weeks 6–7) holds one matched ring per predicted shape (7; BIPARTITE is
never predicted).
- Each shows the narrative, the top-5 evidence edges, the roles, and the spec's four 0/1 questions.
- The true shapes are only in an answer key at the end.
- Already visible in that key: 2 of the 7 typed shapes are wrong (Irregular and Layered chain are really Cycles).
  This is why the narrative says "most likely shape".

### 14.6 The Week 3 tests (79)

**`test_feature_weights.py` (15)**
- The feature order equals the model file and the refit config (5 seeds).
- Our rows reproduce the shipped scores exactly on every seed edge (5 seeds).
- A missing edge or a non-trailing GFP file is refused.
- SHAP adds up to the model output.
- SHAP equals XGBoost's own contributions.
- The by-hand example.
- A 10-feature snapshot of ring 1-15.

**`test_narrative.py` (53)**
- The phrasing covers exactly the 17 features and every shape (5 seeds).
- Number and time formatting.
- Two full narratives written out by hand (Fan-out, Layered chain).
- Every shape and the fallback give a clean narrative (no blanks / None / raw names, ≤ 90 words).
- Each shape states its own sentence.
- Shape sentences are dropped when the transactions don't show them.
- The no-closure, partial-currency and undetermined branches.
- Bank clause only across banks (XR-18), and the bank list shrinks to a count before being dropped.
- Missing probability or features.
- A large ring is cut in the stated order.
- Regeneration from the stored JSON for every shape (XR-31).
- Every number in a sentence is a stored value.
- A tampered summary is caught.
- Swapping the topology source changes only p (XR-19).

**`test_explain.py` (11 new)**
On real seed-1 rings:
- weights byte-identical to the migrated files;
- every ring has a narrative and 10 feature weights;
- latency p95 < 2 s;
- feature weights come only from non-conversion seed edges;
- every real narrative is clean and regenerates;
- the research rule scorer swapped in for the typing model changes only p where the two agree (XR-19).

Then:
- every narrative in all six Week 3 files regenerates (6 files);
- the review sample matches the files and keeps the truth to the end.

### 14.7 Decisions taken in Week 3

1. **Money and closure** are in currency 0 (Joan's converted closure). The raw one is kept in the record only.
2. **SHAP edges** are the seed edges minus conversions.
3. **The shape** is the shipped typing model's, written as "most likely shape". Shape sentences are stated only
   when true on the transactions.
4. **Feature signals** are split into "raised" and "lowered" suspicion. Since Week 4 (Joan) they are captioned
   **"Signals from a reference transaction-level model"**: they explain the GFP+XGBoost reference model, not
   the GNN that chose the seed edges. Never say they come "from the detector".
5. **Names, not codes** (since the sync, section 16): currency, payment method and bank names from Joan's maps.
6. **Joan's feature loader** (`baselines/refit_data.py`, since the sync). Until then our own 10-line copy, proven
   identical by the exact
   score match.
7. **New output names** (`explanations_week3_*`), so the migrated Week 2 files stay as the comparison reference.

---

## 15. Week 4 — fidelity with confidence intervals, controls and XR-23

Week 4 turns the fidelity numbers into **results with error bars and a verdict**. One file holds everything:
`results/xai/fidelity.json` (`python -m explainability.evaluate --week4`). Nothing was re-tuned: the mixing weights
are still the ones chosen on validation in the migration (0.6, 0.0, 0.4).

### 15.1 What was agreed with Joan

| Topic | Decision |
|---|---|
| Headline | The spec's fidelity on ring member edges, reported honestly, negative if it is |
| Secondary | The same on the 52 ring-instances where order matters (clearly labelled) |
| Not reported as fidelity | "Every transaction touching the ring" — it would measure the detector's ranking, not ours |
| Unit | A **truth ring**. Its value is its mean over the detector seeds in which it was matched |
| Confidence intervals | Mirror Joan's `bootstrap_over_rings`; a test proves our version gives her exact numbers |
| Comparisons | Paired sign-flip test (Joan's `paired_permutation`), Holm over the 6 comparisons, the number of non-zero differences beside every p-value, and the spec's "non-overlapping intervals at k = 5" verdict |
| XR-23 | Headline **(b) expanded recall@k**; also (c) the literal definition with its n, and (a) expanded precision as context |
| Extra findings | (i) the saturation rate as a result in itself; (ii) how weakly XR-05 was determined |

### 15.2 How the numbers are made (`stats.py`, `evaluate.week4_report`)

1. **Per ring-instance fidelity**, as in Weeks 1–3: for every predicted ring matched to a truth ring (5 seeds,
   primary window), rank its member edges (conversions removed) three ways — ours (`w_total`), score-only, random
   — and compute fidelity@3/5/10.
2. **Per truth ring.** The same truth ring is usually matched in several seeds. Its value is the **mean over the
   seeds where it was matched**. 100 truth rings: 61 matched in all 5 seeds, 9 in 4, 9 in 3, 12 in 2, 9 in 1.
3. **Bootstrap 95 % interval.** Draw 100 truth rings with replacement (some twice, some not at all), take the
   mean. Do it 1,000 times with a fixed seed. The middle 95 % of those means is the interval.
4. **Paired test (ours vs a control).** For each truth ring, d = ours − control.
   - If "ours" meant nothing, +d and −d would be equally likely. Flip random signs 10,000 times; the share of
     flips whose mean is at least as far from 0 as the real mean is the p-value.
   - **Rings with d = 0** (every saturated ring) cannot say anything, so the number of non-zero differences is
     printed beside each p.
   - **Holm correction** across the 6 comparisons (2 controls × 3 k) guards against "one of six was lucky".
5. **Verdict (spec 6.2).** "Positive" only if our interval at k = 5 is entirely above the control's; otherwise
   negative.

Why our statistics can be trusted: `test_stats.py` builds Joan's own `RingEvidence` objects, runs her
`bootstrap_over_rings` and `paired_permutation`, and checks that ours give the same point, interval ends and
p-value. Holm is imported from her file, not copied.

### 15.3 Results — headline (spec definition, 100 truth rings, 401 ring-instances)

| ranking | @3 | @5 | @10 |
|---|---|---|---|
| ours (`w_total`) | 0.900 [0.854, 0.940] | 0.881 [0.838, 0.921] | 0.890 [0.846, 0.927] |
| score-only | 0.901 [0.852, 0.941] | 0.891 [0.848, 0.928] | 0.890 [0.846, 0.927] |
| random | 0.879 [0.834, 0.919] | 0.874 [0.830, 0.910] | 0.882 [0.837, 0.919] |

| comparison | mean difference [95 % CI] | p | p after Holm | rings that differ |
|---|---|---|---|---|
| ours − score-only @3 | −0.001 [−0.012, 0.013] | 1.00 | 1.00 | 5 |
| ours − score-only @5 | −0.010 [−0.026, −0.001] | 0.065 | 0.32 | 5 |
| ours − score-only @10 | 0.000 | 1.00 | 1.00 | 0 |
| ours − random @3 | +0.021 [0.002, 0.043] | 0.051 | 0.31 | 26 |
| ours − random @5 | +0.007 [−0.011, 0.025] | 0.47 | 1.00 | 23 |
| ours − random @10 | +0.008 [0.001, 0.017] | 0.066 | 0.32 | 14 |

**Verdict at k = 5: negative against both controls** (the intervals overlap). In plain words: on the spec's
measure our ranking is statistically indistinguishable from simply sorting by the detector score, and only
barely better than random. Only 5 of 100 truth rings rank differently from score-only at all.

**Secondary — the 52 ring-instances where order matters (21 truth rings):** ours 0.840 [0.743, 0.922] at k = 5,
score-only 0.898 [0.824, 0.960], random 0.788 [0.712, 0.863]. Same verdict (negative), with ours numerically
below score-only.

### 15.4 Results — XR-23, the expanded (quiet-member) edges

**(b) Expanded recall@k, the headline (56 truth rings, 159 ring-instances with a true expanded edge in the
window).** It asks: does the ranking put the edges the ring layer recovered — the quiet members, the point of the
project — near the top?

| ranking | @3 | @5 | @10 |
|---|---|---|---|
| ours | 0.428 [0.320, 0.542] | 0.724 [0.616, 0.825] | 0.974 |
| score-only | 0.418 [0.308, 0.534] | 0.729 [0.622, 0.830] | 0.974 |
| random | **0.714** [0.649, 0.778] | **0.873** [0.821, 0.922] | 0.982 |

**This is the most important Week 4 finding: our ranking puts the true quiet-member edges *below* where a random
order would** (ours − random @3 = −0.286, @5 = −0.150, both p < 0.001 after Holm, 40 and 23 rings differ).

The reason is mechanical:
- an expanded edge has a low detector score by definition (that is why it was "quiet");
- our mix is 0.6 × score + 0.4 × money share;
- leave-one-out, the one ingredient that could have lifted a structurally important quiet edge, got weight 0
  in XR-05.

So the explanation hides exactly the edges the ring layer exists to find. It does no worse than score-only;
both are well below random.

**(c) The literal definition** (rank expanded edges alone against the non-seed true edges): 159 ring-instances,
only **11** can tell rankings apart; all three rankings ≈ 0.85. Reported for completeness; it can't separate
rankings.

**(a) Expanded precision** (context, measures the ring layer, not the explanation): **95.8 %** of the expanded
in-window edges are truly in the ring (162 ring-instances).

### 15.5 Findings, in Joan's words where she asked for them

- **The predicted rings are very clean.** After removing currency conversions, 343 of the 395 matched
  ring-instances with any true ranked edge contain **only** true transactions (6 more have none). That is a
  result about the ring layer, not just a reason the metric saturates.
- **XR-05 was weakly determined.**
  - On validation only **89 of 431** matched ring-instances could tell rankings apart.
  - The whole 66-combination grid spanned 0.025 (0.888–0.913).
  - The chosen (0.6, 0.0, 0.4) beat the default by 0.011 there.
  - **Leave-one-out got zero weight.**
  - A weakly determined choice, not a flaw in the method, is the likely reason score-only matches or beats it on
    test.
  - Nothing was re-tuned on test.
- **For the report:** the honest summary is "the explanations are faithful to the detector (≈ 0.88–0.90
  fidelity) but add nothing measurable over the detector's own ordering, and actively under-rank the recovered
  quiet members". The XR-23 result points to what would have to change: a ranking term that rewards structural
  importance (leave-one-out, bridges) independently of score.

### 15.6 The Week 4 tests (10)

**`test_stats.py` (6)**
- Our bootstrap reproduces Joan's `bootstrap_over_rings` exactly on her own evidence objects.
- Our paired test reproduces her `paired_permutation` p-value, difference and interval.
- Per-truth-ring averaging uses only the seeds where a ring was matched.
- Bootstrap basics: identical values give a zero-width interval; same answer twice; empty input.
- Non-zero differences are counted, and ties give p = 1.
- The verdict cases; Holm is Joan's function itself.

**`test_fidelity.py` (4 new)**
- XR-23 (a), (b), (c) on a hand-made chain ring with known answers.
- The per-truth-ring block: seeds-matched counts, six comparisons with Holm, the verdict.
- `fidelity.json` agrees with the per-seed files and the XR-05 file:
  - 401 / 395 / 343 / 52;
  - 89 of 431;
  - β = 0;
  - n = 11;
  - every interval contains its point.
- Recomputing the report reproduces the stored file exactly.

### 15.7 Week 4 changes to Week 3 (asked by Joan)

- **Caption:** feature signals now read "Signals from a reference transaction-level model …" (unchanged by the sync). All Week 3 files
  were regenerated; every narrative still rebuilds exactly and stays ≤ 90 words. The four extra words push the
  bank clause out of 44 rings (was 12) and the feature clause out of 5 (was 1).
- **The 7-ring review file is labelled a PILOT.** The spec's 30-ring review with Fleiss' κ comes in Weeks 6–7.

---

## 16. Sync with Joan's `v2` (`b35b233`, merged into this branch as `b6f28c7`)

Joan answered our open items. Her changes are all in her own folders; ours were only adapted to use them.

| Joan's change | What we did | How we know nothing else moved |
|---|---|---|
| `MIGRATION.md`: one rule for the money share (convertible share + "partial") | nothing: it is what we built | — |
| `ringshield/roles.py`: `fillna` → `where` (the pandas warning) | dropped `-W ignore::FutureWarning`; the suite runs with pandas warnings as **errors** | all 235 earlier tests passed on her merged code before we changed anything; the Week 2 byte-for-byte tests still pass |
| `baselines/refit_data.py`: her feature loader, importable without optuna | `feature_weights.load_feature_rows` now imports it; our copy is gone | feature rows byte-identical (SHA-256) to our copy's on all 5 seeds; predictions still equal the shipped scores exactly |
| `docs/PITFALLS.md` 3f: the shap base value | nothing: we already take it from XGBoost; her note confirms it (gap 2.78–2.84; the true base differs per seed) | — |
| `contract/currency_map.json`, `payment_format_map.json`, `bank_names.json` | narratives use names (below), the pilot review shows currency names | weights, feature weights and every fidelity number unchanged (fingerprints before / after) |
| Payment format explained | the report can say why "the payment method" dominates: **ACH** is 11 % of transactions but 83 % of laundering | — |

**What the narratives say now:**
- **Money:** "Total moved: 433,000 (US Dollar)." The currency name comes from the map; the brackets avoid
  plural rules for 15 currency names.
- **Bitcoin:** "partial: transactions in Bitcoin have no exchange rate"; "(amount in Bitcoin, weight 0.70)";
  "Account X uses Bitcoin, which has no exchange rate, so its role cannot be checked."
- **Code-valued features** name the value of the feature's top edge: "the payment method (ACH)", and likewise
  for the two currency features.
- **Banks:** "The accounts span 3 banks (Arbor Savings Bank, China Bank #14, UK Bank #33)".
  - Names are display only: 30,470 bank ids share 20,053 names, so two banks of one ring with the same name
    get their id in brackets.
  - An id missing from the map would show as "Bank <id>" (none is missing).
  - Names are longer than codes, so the list falls back to "The accounts span N banks." more often. Over the
    560 rings of the five seeds: the bank list is shown in 219, the bank count in 295, and 46 lose the bank clause
    to the 90-word limit (with codes it was 460 / 56 / 44). Every name stays visible in the pilot review file and
    will be in the dashboard.
- **Regeneration:** every name is stored in `evidence_summary`, so a narrative still rebuilds from its summary
  alone. Provenance records the three map files.

**New tests (3, in `test_narrative.py`):**
- the maps are Joan's (US Dollar, Bitcoin, ACH; 15 / 7 / 30,470 entries);
- shared bank names get their id, and an unknown id falls back to "Bank <id>";
- a code-valued feature names its top edge's value.

The clean-narrative check now also refuses any "currency <number>" text.

---

## 17. Week 5 (part 1) — typology, latency, the API

Five of the seven Week 5 steps are built. Role accuracy (XR-26) and "runs on every detector" (XR-36) wait for
Joan's v2 commit (her `roles_for_edges(currency=...)` helper, the `RingRerunner` change, the XGBoost and MEGA-GNN
rings).

### 17.1 No attention anywhere (XR-35)

`test_week5_eval.py` reads every `.py` file of the layer and fails if any mentions attention or imports torch.

### 17.2 Typology: how often the narrated shape is right (XR-25) — and a bug found in the research table

**What it measures.** For every predicted ring matched to a truth ring, is the shape the narrative states (the
ring's `topology_type`, from Joan's typing model) the true pattern type? The research rule scorer is scored on the
same rings. Output: `results/xai/typology_eval.json` (`python -m explainability.evaluate --typology`).

**What we found.** Joan's `evaluation/typing_eval.py`, behind `results/tables/r5_typing.json` and the 0.219 in
`docs/TYPING.md`, types the wrong ring for most matches on the primary window.
- It finds the matched ring as `rings[m.pred_idx]`. But `pred_idx` counts positions in the list `restrict_rings`
  returns, which **leaves out rings with no transaction in the window** (72 rings over the 5 seeds). Every later
  position shifts, so the lookup lands on a different ring.
- Measured: **316 of the 401** matches type a different ring than the one that matched. Check: the members of the
  ring that was looked up equal the matched set in only 85 of 401 cases; with the lookup by ring id, in all 401.
- On the whole test period no ring is left out, so nothing shifts and her number there (0.594) is right.
- This is the same trap our Week 1 code guards against (section 7.2). Her other scripts don't have it:
  `r7_heldout.py` and `ring_stats.py` rebuild the correct mapping.

**Results (by ring id; pending Joan's confirmation):**

| window | matched rings | typing model (narrated type) | rule scorer |
|---|---|---|---|
| primary (test days 8–9) | 401 | **0.599** [0.554, 0.643] | 0.551 |
| whole test period | 433 | 0.594 | 0.547 |

- **The shape the narrative states is right about 60 % of the time**, on both windows. The "typing is
  window-bounded" caveat (0.219 against 0.594) disappears once the lookup is fixed.
- With research's own lookup, our code reproduces `r5_typing.json` exactly: point, interval, macro-F1, per-type
  recall and both confusion matrices. A test pins this, so the lookup is the whole difference.
- **Shape sentences are informative.** When the narrative states a shape sentence (one that holds on the ring's
  transactions; 290 rings), the stated type is right **67 %** of the time. When it can't (111 rings), only **41 %**.
  *(Week 8 update: a shape sentence now also needs its hub's money role to agree, section 23. The split is now
  **0.649** stated (231 rings) against **0.529** not stated (170 rings), `typology_eval.json`.)*
- Joan's other caveat stands: the typing model's role-count features were built on unconverted roles
  (`docs/PITFALLS.md`), while the narrated roles are converted.

### 17.3 Latency (XR-27)

A dedicated run: `python -m explainability.explain --latency`. It ran on this laptop with nothing else running,
single process, over all 560 rings, and writes only `results/xai/latency.json`.

| p50 | p95 | max | over 5 s | target |
|---|---|---|---|---|
| 393 ms | **918 ms** | 2,007 ms | 0 | p95 < 2,000 ms — **met** |

- **Where the time goes:**
  - leave-one-out reruns: 44 %;
  - SHAP: 29 %;
  - roles, accounts and shape: 14 %;
  - the narrative: 10 %;
  - everything else: 3 %.
- **Latency follows the number of leave-one-out reruns** (Spearman ρ = 0.98). The slowest ring has 40 seed +
  expanded transactions.
- **Setup:** loading the files and building the rerunner and SHAP explainer takes about 9–13 s per file. That is
  paid once, not per ring, and is reported separately.
- **Machine:** AMD, 8 cores / 16 threads, 15.4 GB RAM, Windows 11, Python 3.11.9; package versions are in the
  file.
- **The laptop met the target**, so the A5000 rerun Joan offered isn't needed.

How it is measured: `explain_ring` now times its stages (read, leave-one-out, edge weights, roles / accounts /
shape, SHAP, narrative, assemble). The times go into the run log only; the explanation files are unchanged. A test
checks that the stages add up to each ring's latency.

### 17.4 The API for the platform (XR-33, XR-34)

The platform's FastAPI service owns the routes, the login and the tenant isolation. This layer gives it four
functions and the shapes of what they return.

| Endpoint (spec 3.3) | Function in `api.py` | Returns (`api_schemas.py`) |
|---|---|---|
| `GET …/explanation` | `get_explanation(tenant, ring)` | `Explanation`: the explanation row, with a plain-English `display_name` per feature and the explainer version |
| `GET …/evidence/edges` | `get_evidence_edges(tenant, ring)` | `EvidenceEdge` list in w_total order: weights plus the raw transaction fields, the amount in US Dollar, and currency / payment-method / bank names |
| `GET …/evidence/accounts` | `get_evidence_accounts(tenant, ring)` | `EvidenceAccount` list, highest w_account first, with bank id and name |
| `POST …/explanation/regenerate` | `regenerate(tenant, ring, request)` | a new `Explanation` after the analyst removed accounts and/or transactions |

- **Schemas as files:** `explainability/schemas/*.schema.json` (`python -m explainability.api_schemas` writes
  them). A test fails if the files and the code ever differ, so the platform's copy can't drift.
- **Tenants:** an unknown ring and another tenant's ring give the **same** "not found", so a caller can't learn
  that another bank's ring exists.
- **Regenerate:**
  - rebuilds the ring without the removed accounts (and their transactions) and transactions;
  - explains it from scratch: new leave-one-out reruns, weights, roles, SHAP and narrative;
  - records the edit in provenance.
  - The shape stays the typing model's guess for the original ring, and is marked so.
  - It needs the same research files as a normal run, loaded on the first call.
- **Roles include `undetermined`** (an account touching Bitcoin): the dashboard needs a sixth role style.
- **No ground truth** appears in any response (tested on every real ring).

**Tests (`test_api.py`, 11):**
- The exported schema files equal the code.
- All three shapes are built and validated for every ring of all six Week 3 files, with no ground-truth field.
- On the stub data, a test-only FastAPI app with the four routes:
  - the three GETs return 200;
  - unknown and other-tenant rings give an identical 404;
  - **removing a member changes the weights, and the account and its transactions disappear**;
  - regenerate is deterministic;
  - an empty request, an unknown account, or an edit leaving fewer than two accounts gives 422;
  - another tenant gets 404.

---

## 18. Week 5 (part 2) — role accuracy, three detectors, samples for the platform

Built after Joan's `v2` commit `70b997c` (her `roles_for_edges(currency=...)` helper, the detector-aware
`RingRerunner`, the gfpxgb and MEGA rings files). The handoff files were checked before use:
- **The 10 new rings files** match her fingerprints and pass our contract reader.
- **XGBoost seed 1:** our old `scored_edges_gfpxgb_1` (test and validation) had no seeds marked. Joan rebuilt both;
  only `is_seed` changed, and the stale copies are kept outside the repo.
- **The other 16 transactions files and the 2.4 GB of MEGA embeddings** match her list.

### 18.1 Role accuracy (XR-26) — `fidelity.json` → `role_accuracy`

**What it measures:** for every matched ring, does each account get the right role? The "right" role is the one
Joan's same role code gives on the **true** ring's transactions inside the window (converted amounts on both sides,
currency conversions removed on both sides). Precision and recall per role, bootstrap 95 % intervals over truth
rings. There are three versions (Joan, Q2):

| version | what it isolates | shipped detector, 100 truth rings |
|---|---|---|
| **headline** | our roles as narrated (whole ring span) vs truth roles; accounts in only one of the two rings count as errors | source P 0.61 / R 0.87, sink P 0.42 / R 0.66, mule P 0.25 / R 0.70 |
| in-window | our roles recomputed on the ring's in-window transactions only | source P 0.91 / R 0.89, sink P 0.96 / R 0.91, mule P 0.92 / R 0.70 |
| **accounts in both rings** | pure role errors, no membership errors | **82.8 %** of shared accounts get the same role; source 0.95 / 0.94, sink 0.97 / 0.69, mule 0.41 / 0.79 |

**How to read it:**
- Most of the headline "errors" are not role errors. They come from accounts the ring layer added or missed, and
  from the predicted ring spanning more time than the 2-day window: in-window, precision jumps to 0.91–0.96.
- On accounts both rings share, 83 % get the right role. The weak spot is mules: an account we call a mule is
  often a sink in the truth window, because its onward payment falls outside the window.
- Holder and peripheral are rare and unreliable. `undetermined` never occurs on matched rings.
- The recomputed roles differ from the shipped narrated roles for **13 of 3,464** accounts. That's the 33
  conversions the ring-builder used, which the evaluation removes (Joan, Q2).

### 18.2 The same layer on three detectors (XR-36) — `results/xai/xr36_detectors.json`

**No code differs between detectors.** A profile in `config.yaml` (`detectors:`) swaps the input files.
- `contract_io.detector_cfg` applies the profile and tags every output name, e.g. `explanations_gfpxgb_seed1.parquet`.
- The leave-one-out loader takes "no embeddings" and the partition settings from the rings file's own log.
- **Run it with:** `python -m explainability.explain --detector gfpxgb`, then
  `python -m explainability.evaluate --detector gfpxgb --week4` (and `--typology`, `--roles`), then
  `python -m explainability.evaluate --detectors-summary`.
- The mixing weights stay the XR-05 ones for every detector (Joan: not re-tuned).

| | Multi-GINe (shipped) | GFP+XGBoost | MEGA-GNN |
|---|---|---|---|
| rings explained | 560 / 560 | 873 / 873 | 579 / 579 |
| leave-one-out degraded | 0 | 0 (no embeddings, own 19-feature affinity) | 0 (MEGA embeddings, gine-trained affinity) |
| rebuild identical to shipped ring | 555 | 856 | 571 |
| latency p95 (worst seed) / max | 1,240 / 2,987 ms | 1,168 / 4,988 ms | 1,306 / 5,171 ms (1 ring over 5 s) |
| matched ring-instances / truth rings | 401 / 100 | 372 / 87 | 418 / 103 |
| rings whose ranked edges are all true | 343 of 395 | 285 of 357 | 366 of 415 |
| fidelity@5: ours / score-only / random | 0.881 / 0.891 / 0.874 | 0.830 / 0.831 / 0.826 | 0.904 / 0.906 / 0.869 |
| verdict (spec 6.2) | negative | negative | negative |
| expanded recall@5: ours / score / random | 0.724 / 0.729 / 0.873 | 0.794 / 0.794 / 0.890 | 0.730 / 0.728 / 0.860 |
| typing accuracy (narrated) / rule | 0.599 / 0.551 | 0.578 / 0.535 | 0.579 / 0.545 |
| role agreement, accounts in both | 0.828 | 0.769 | 0.824 |

**The findings hold on every detector:**
- fidelity saturates;
- our ranking ties score-only;
- the recovered quiet-member edges rank below random;
- the narrated shape is right about 58–60 % of the time;
- shared accounts get the right role about 77–83 % of the time.

**Latency:** the latencies here come from the explanation runs. The clean, dedicated measurement for the shipped
detector is `latency.json` (p95 918 ms). One MEGA ring (`full-mega-4-35`) took 5.2 s and is logged, as the spec
asks; that is the research side's large-component case.

**Detector caveat (Joan):** MEGA is read through an affinity trained on the GINE embedding space
(`docs/FINDINGS.md`).

### 18.3 Samples for the platform — `explainability/schemas/examples/`

`python -m explainability.api --examples` writes real responses of the four functions on the stub data:
- `explanation.json`, `evidence_edges.json` and `evidence_accounts.json`;
- `regenerate_request.json` and `regenerate_response.json` (one sink removed);
- the two error bodies.

A test validates each against its model and checks that none holds ground truth or a real account number. The
`account_id` values are the dataset's internal integer ids; real account numbers exist only in
`data/processed/account_bank.parquet`, which this layer never reads.

### 18.4 The Week 5 part 2 tests

**`test_week5_eval.py` (+6):**
- role counts by hand;
- the role-accuracy section of `fidelity.json`;
- `detector_cfg` swaps only inputs and output names;
- leave-one-out not degraded for gfpxgb and MEGA (×2);
- the XR-36 summary: all three detectors, every ring explained, same mixing.

**`test_stats.py` (+1):** the ratio bootstrap.

**`test_api.py` (+1):** the sample fixtures validate. The no-ground-truth check now also covers account numbers.

---

## 19. Week 6 — the internal review of thirty explanations (XR-29)

The spec (section 7) asks for a structured check by the three team members (it is not an analyst study, and the
report must say so).
- **What the reviewers do:** each of the three reads 30 explanations and answers four yes/no questions per
  explanation. They see only what the app would show: the narrative, the top-5 evidence transactions and the
  account roles.
- **What we compute afterwards:** how much the three agree (per question, and as Fleiss' κ), then a reveal of the
  true pattern types.

### 19.1 Which 30 rings (`explainability/review/sample.py`)

Matched rings of the shipped detector on the primary window, pooled over the five seeds.
- **One per truth ring:** if a truth ring was matched in several seeds, one of them is drawn at random.
- **Stratified by the true pattern type:** four per type where available, the remainder from the two most frequent
  types in turn.
- **Fixed random seed:** `review.rng_seed`, so the sample is the same on every run.
- **The 7 truth rings in the Week 3 pilot file are left out.** That file and its answer key are already committed
  on the branch the reviewers pull. Three of them (one Fan-out, one Fan-in, one Cycle) were drawn in the first
  sample, and a test now prevents it. The pilot can therefore safely serve as a short calibration round.

| true type | truth rings available | chosen |
|---|---|---|
| Gather-scatter | 29 | 4 + 2 |
| Scatter-gather | 16 | 4 + 2 |
| Fan-out | 14 | 4 |
| Fan-in | 13 | 4 |
| Cycle | 9 | 4 |
| Irregular (RANDOM) | 10 | 4 |
| Stack | 1 | 1 |
| Bipartite | 1 | 1 |
| **total** | 93 (100 matched, minus the 7 in the pilot) | **30** |

### 19.2 What each reviewer gets — `results/xai/review/`

| file | for | contents |
|---|---|---|
| `packet_R1.md`, `packet_R2.md`, `packet_R3.md` | reviewer R1 / R2 / R3 | the four questions, then 30 sections, each: the narrative; the top-5 evidence transactions (amount and currency, ≈ US Dollar, payment method, banks by name, weight); the accounts by role |
| `answers_R1.csv`, … | reviewer R1 / R2 / R3 | blank sheet, one row per item in that reviewer's order: `item_id`, `q1_topology_plausible`, `q2_named_accounts_matter`, `q3_evidence_enough`, `q4_misleading`, `comment` |
| `answer_key.parquet` | **only us, after all sheets are in** | per item: the ring, its seed, the true pattern type, the narrated type |
| `sample_manifest.json` | the record | the rule, what was available and chosen, the SHA-256 of every packet and sheet |

**What stops answers being biased:**
- **Nothing in a packet reveals the truth:** no ring id, no seed, no match score, no true type. A test checks this.
- **Items are numbered R-01 … R-30**, the same for everyone, but **each reviewer reads them in their own shuffled
  order**.
- **The answer key is a `.parquet` file**, which git in this repo always ignores. The reviewers pull this branch,
  so a CSV key would have reached them on GitHub.
- **Who is R1 / R2 / R3** is kept outside the repo, so `review.csv` stays anonymised.

**The four questions** (spec 7, answered 1 = yes, 0 = no):
1. `q1_topology_plausible`: is the stated shape plausible from the evidence shown?
2. `q2_named_accounts_matter`: are the named accounts the ones that matter?
3. `q3_evidence_enough`: would the evidence transactions be enough to start an investigation?
4. `q4_misleading`: is anything in the sentence misleading or unsupported? (1 = yes, something is.)

### 19.3 Scoring (`explainability/review/aggregate.py`, Week 7)

`python -m explainability.review.aggregate` once the three filled sheets are back in `results/xai/review/`.
1. **Each sheet is checked:** the same 30 items as the key, and every answer 0 or 1. A blank or anything else
   stops the run with the item named.
2. **Per question:** the share of "yes", the share of items where all three agree, and **Fleiss' κ**.
   - Fleiss' κ is agreement beyond what three people answering at random with the same yes-rates would reach:
     1 = perfect, 0 = chance level, below 0 = worse than chance.
   - It is computed from the table of how many reviewers said yes / no for each item.
   - A test reproduces the published worked example from Fleiss (1971), κ = 0.210.
3. **The reveal:** for each item, is the narrated shape the true one? Did each reviewer's "plausible" answer match
   that (plausible when right, implausible when wrong)?
4. **Output:** `review.csv` (one row per item and reviewer, with comments) and `review_summary.json`.

### 19.4 Tests (`test_review.py`, 6)

- Fleiss' κ: the published example, plus perfect agreement, one category (undefined) and unequal raters.
- The sampling rule on a made-up pool: four per type, remainder to the two most frequent, one per truth ring, same
  draw every run.
- The real packets and sheets:
  - 30 items with the stated counts;
  - three different orders;
  - blank sheets;
  - no ring id, seed, "truth" or match score in any packet;
  - no truth ring that the committed pilot file reveals;
  - fingerprints match the manifest;
  - **the answer key is git-ignored**.
- Scoring on made-up filled sheets (90 rows, no ring ids in `review.csv`).
- Blank, non-0/1 and missing-row sheets are refused.

### 19.5 Something for the review to judge

A few evidence lists start with a payment from an account to **itself in the same currency** (e.g. 3.77 million
US Dollar). Only currency **conversions** (sent and received currencies differ) are removed from evidence; these
are not conversions. They are almost never laundering (5 of 4,817 in the test split), but not never, so they stay
in. In seed 1 they are 17 of 951 evidence transactions, 3 of them in a top-3 slot. If reviewers find them
misleading (q4), that is a narrative fix for Week 7–8, to be agreed with Joan.

---

## 20. Tenant-scoped explanations for the platform (Kashish's request; Week 9 integration, done early)

**What it is.** In the platform each bank (tenant) may only see its own slice of the data. Kashish's platform rebuilt
rings per bank on the transactions that bank can see. This layer explains those rings **without counting or
mentioning anything the bank can't see**.

- **The rule:** a bank sees a transaction if the sending or receiving bank is that bank. Its own accounts are fully
  visible; another bank's account appears only as the counterparty on those visible transactions.
- **Run it with:** `python -m explainability.tenant --bank 20` (then `--bank 12`).
- **Output:** `results/xai/tenant/explanations_<bank>_1.parquet` + `.log.json`, in the same file layout as the
  shipped explanations.

**Spec note:** the L4 spec puts tenant scoping in the platform layer ("not here"). This is integration work for her
per-tenant inference step, not a new L4 requirement. In the plan it belongs to Week 9; it was done while the review
sheets are out.

### 20.1 Inputs, and how they were checked

| input | from | check |
|---|---|---|
| `tenant_{12,20}_rings.parquet` (+ logs) | Kashish's platform (rings contract v1, 5 rings each) | SHA-256 equals her list; our contract reader accepts them against the bank's visible transactions; no member transaction is hidden from its bank |
| `tenant_{12,20}_edge_ids.parquet` | Kashish | SHA-256 equals her list; the ids are **exactly** the "sending or receiving bank = the bank" set (20,039 and 10,315) |
| shared inputs: transactions, graph features, embeddings, GNN model / affinity / policy | Joan's files, as Kashish's rings used them | SHA-256 equal to her list (the model files once Windows line endings are ignored) |

Copies of her files and fingerprint lists are in `results/xai/tenant/inputs/`.

### 20.2 What is computed on the bank's view, and how

| part | tenant run |
|---|---|
| transactions | the shipped scored-transactions file **filtered** to the visible ones (`scored_edges_visible_<bank>_1.parquet`, same columns and types). Roles, money totals, closure and every count come from these |
| account weight | an account's activity is now counted over visible transactions only (Kashish 4a), so another bank's activity can't inflate or deflate it |
| leave-one-out | the shared graph features and embeddings, restricted to the ring's transactions: exactly what her rings were built with. **All 10 rings rebuild identically** |
| SHAP signals | the reference model's 10 graph features are **recomputed on the bank's visible history** (Kashish 4b), using Joan's own per-transaction functions (`graph/motif_features.py`) over all visible train + val + test transactions. The 7 transaction fields are the transaction's own. Recorded as `feature_scope: "tenant_view"`, with a note that SHAP on a subgraph is less faithful to a model trained on full-graph features. The graph features differ from the full-graph ones for 10 of 11 seed transactions (bank 20) and 19 of 19 (bank 12) |
| shape | Kashish's rings carry no shape (`UNKNOWN`), so narratives open with "Suspected ring: …" |

**Why the recomputed features can be trusted:**
- The fast history index used here equals Joan's `build_adjacency` exactly.
- On the full history, it reproduces the shipped `amlworld_gfp_features_test.parquet` **exactly** for 2,000 random
  test transactions plus every tenant seed transaction.
- Window, hops and look-back are read from the shipped file's own metadata, not retyped.

### 20.3 What goes back to the platform

**The log** records:
- `scope: "tenant"`, `tenant_id`, the visibility rule;
- `input_sha256` (every input file, path and fingerprint);
- `fx_rates_sha256`, `feature_scope`, how many seed transactions had different graph features;
- `n_reproduces_shipped_ring`, `not_reproduced`, latency.

**Every row's provenance** also carries `scope`, `tenant_id`, `feature_scope` and `fx_rates_sha256`.

**`fx_rates_sha256` is now in every run log**, shipped and tenant: `ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6`.
Kashish pins it and rejects explanations whose fingerprint differs.

**Regenerate after a partial verdict:** `TenantExplainer(cfg, bank).regenerate(ring_id, tenant_id,
excluded_members=(), excluded_edges=())`.
- It returns one row with the explanation-file columns, JSON-safe (NaN → null).
- Its provenance adds `regenerated: true`, the excluded ids, the transactions removed with excluded accounts, `scope`,
  `tenant_id` and `fx_rates_sha256`.
- It uses the same editing rules as the API's regenerate (shared `api.edit_ring`).
- Another bank's ring is "not found"; excluding nothing is refused.

### 20.4 Tests (`test_tenant.py`, 10)

- The fast history index equals Joan's.
- The full-history features equal the shipped file (300 random + every tenant seed).
- The inputs match Kashish's fingerprints, and her edge ids are exactly the visibility rule.
- **Nothing hidden is mentioned (×2 banks):** every transaction listed, every feature's top transaction, every
  account, every role list, every account a shape sentence can name and every `A→B` in the narrative is on the
  bank's visible transactions.
- Log and provenance carry scope, tenant, fx and input fingerprints that re-hash correctly (×2).
- Account activity and SHAP inputs come from the visible view only.
- `regenerate`: JSON-safe, the right columns and provenance, deterministic, refuses another tenant and an empty edit.
- The shipped explanations carry no tenant fields, so the reviewed narratives are untouched.

### 20.5 Open with Kashish

- Her ring ids repeat the shipped ones (`full-gine_causal-1-0 …`), and bank 12 and bank 20 share them too. A tenant
  prefix on her side would avoid mix-ups in shared tables.
- No shape on her rings; attaching the typing model in her build would give narratives a shape.
---

## 21. Week 7 (part 1) — the analysis plan, written before scoring

`results/xai/review/analysis_plan.md` fixes, **before** any answer is read, how the review will be read:
- **What is computed:** the yes-rate, the all-agree rate and Fleiss' κ per question, with κ read on the Landis &
  Koch bands; then the reveal.
- **How items are broken down:** by narrative feature (shape sentence stated, a self-payment among the three
  strongest transactions, partial currency, bank names listed, an undetermined account named, narrated shape right)
  and by true pattern type.
- **Exactly when a result triggers a proposed fix:**
  - a q1–q3 yes-rate below 0.5, overall or within a feature that has at least 5 items;
  - or, for q4, at least 3 of a feature's items flagged misleading (or at least 20 % of them, with at least 2
    flagged).

  An item counts as flagged when at least 2 of the 3 reviewers flag it.
- **What a fix may change:** wording and templates (Week 8, with Joan's sign-off). A change to the evidence itself is
  a separate decision with Joan.

The rule numbers live in `config.yaml` (`review.rules`), the plan repeats them, and a test keeps the two identical. The
plan is committed before R2 and R3 return their sheets; R1's sheet was filled but only format-checked.

`aggregate.py` now also writes all of that to `review_summary.json` (`analysis`):
- the flagged items per question;
- the yes-rates by feature and by true type;
- the triggered fixes, with their items;
- the reviewers' comments per item.

**Tests (`test_review.py`, +5):**
- the plan's rules equal the config;
- the κ bands;
- the item features agree with the packets;
- no trigger fires when every answer is ideal;
- the triggers fire by the written rules on made-up sheets.

All review tests use made-up sheets; they never read a reviewer's real answers (a filled sheet is only checked for
being valid, yes / no).

**Still to come (when Joan's and Kashish's sheets are in, about 6 November):** score the review, the human-readable
`review_summary.md`, and the fix list.
---

## 22. Week 7 (part 2) — the review, scored

All three sheets are in. They were scored by `python -m explainability.review.aggregate` with the rules committed in
advance (`analysis_plan.md`, committed before R2's and R3's sheets existed).
- **Outputs:** `review.csv` (90 rows: item × reviewer, anonymised), `review_summary.json` and the plain-language
  `review_summary.md`.
- **Fix list:** `fix_proposals.md`, for sign-off.

| question | yes | all agree | Fleiss' κ |
|---|---|---|---|
| q1 the stated shape is plausible | 0.53 | 70 % | 0.60 (moderate) |
| q2 the named accounts matter | 0.91 | 97 % | 0.86 (almost perfect) |
| q3 enough to start an investigation | 1.00 | 100 % | undefined (unanimous) |
| q4 something is misleading | **0.61** | 80 % | 0.72 (substantial) |

**What the review found:**
- **The evidence works.** Reviewers always found the evidence transactions enough to start an investigation, and
  almost always agreed the named accounts are the ones that matter.
- **The shape claim is the problem.**
  - Four pre-registered triggers fired.
  - Behind them (exploratory, labelled so): **every one of the 13 narratives that names a shape without a shape
    sentence was judged misleading**, whether or not the shape was actually right (6 of the 13 were).
  - With a shape sentence, 6 of 17 were judged misleading.
- **The reveal:** the narrated shape was right for 50 % of these items, and the reviewers' "plausible" matched the
  truth 63 % of the time.

**Proposed fixes** (`fix_proposals.md`; applied in Week 8 after sign-off):
- **A:** without a shape sentence, open with "Suspected ring" and state the typing model's shape as a guess that the
  transactions don't show.
- **B:** ask the reviewers what was misleading on the 6 shape-sentence items before changing them.

The bank list (confounded with A) and the single self-payment item (below the thresholds) are not changed.

XR-29 is **met**: thirty-ring review, Section 7 protocol, Fleiss' κ, `review.csv` and the summary.

**Tests (`test_review.py`, +1):** `review_summary.md` is exactly what the scored JSON renders.

## 23. Week 8 — the review fixes, and the report chapter

Joan signed off Fix A and the reviewers' follow-up comments on the six shape-sentence items (R-02, R-04, R-06,
R-12, R-25, R-30). Every change is **wording only**. Weights, evidence ranking, feature weights and fidelity are
byte-identical before and after (123 file fingerprints compared, 0 differ).

**What the reviewers said, and what changed in `narrative.py`:**

| complaint | cause | fix |
|---|---|---|
| a shape is named but the transactions don't show it (13 of 13 flagged) | the headline used the typing model's guess | **Fix A1:** no shape sentence → the narrative opens "Suspected ring" and says "The typing model's most likely shape is X (p = …), but the ring's transactions do not show that shape." |
| counts and "% reached the sinks" don't match the five transactions shown (R-02, R-06, R-25, R-30) | those numbers cover the whole ring, not the evidence | **Scope words:** "Across the ring's N transactions, …" and "Across the ring, X% of the sources' money reached the sinks." |
| the "gathering" hub is called a source (R-12) | the shape sentence and the role were computed separately | a hub is named only if its money role agrees: fan-out hub sends (source, mule, holder), fan-in hub receives (sink, mule, holder), gather-scatter hub passes money on (mule, holder). Otherwise Fix A1 applies. |
| the scatter-gather / stack sentence mixes in role definitions (R-30) | role lists were folded into the shape sentence | those sentences now use only the transactions' own facts |
| a payment from an account to itself is cited as evidence (R-04) | it ranked high | "Strongest evidence" skips it and says "One stronger-ranked payment from an account to itself is not cited." The ranked edge weights are unchanged. |

R-12's "amounts don't match" is the euro amount shown beside the US-dollar total; both are labelled, so nothing
changed there. The bank list stays (confounded with A1, as the analysis plan said).

**The 90-word limit:** the new sentences are longer, so the drop order was updated (the self-payment note now
outranks the feature clause, and the feature clause has a short form). Every narrative still fits.

**Outputs:**
- `explainer_version` is now **`0.5.0-review`** (`config.yaml`). The platform's cache key uses it, so Kashish's cache
  refreshes on its own.
- Every explanation file was regenerated: five Week 3 seeds and the stub, GFP+XGBoost and MEGA-GNN, and both tenant
  files (`results/xai/tenant/`). Typology and XR-36 summaries were rerun; the API examples in `schemas/examples/`
  were rebuilt.
- `results/xai/review/before_after.md` (`python -m explainability.review.before_after`): each of the 30 reviewed
  narratives exactly as the reviewers read it, then as it reads now. 30 of 30 changed. A1 changed 14 of the 19
  flagged items, the scope words 18 of 19, the self-payment note 1 of 19.
- The shape-sentence split moved (section 17): stated **0.649** (231 rings), not stated **0.529** (170 rings).
  Fewer rings get a shape sentence, mainly because a hub whose role disagrees no longer counts.
- The packets are **not** changed. A second review round on the new wording is future work.
- **The review's item features are now frozen** in `results/xai/review/item_features.csv`. The scoring code used to
  read them (shape sentence stated, bank list, self-payment…) from the current explanation files. After Week 8 those
  files no longer hold the text the reviewers read, so re-scoring would have described the wrong text. The frozen
  file was rebuilt from the stored values with the reviewed code (`0.4.0-narrative`). All 30 rebuilt narratives
  match the packets word for word. Re-scoring with it reproduces `review.csv`, `review_summary.json` and
  `review_summary.md` byte for byte.
- `fidelity.json` was rerun (`evaluate --week4`, then `--roles`): only its `explainer_version` line changed.
  The pilot file `narrative_samples_week3.md` was rerun (`explain --samples`): same 7 rings, new wording.
  `latency.json` keeps `0.4.0-narrative`, because that is the version it timed.

**Report chapter (W8-6), `explainability/report/`:**
- `xai_chapter.md`: the L4 sections in the report's structure (Introduction to Conclusion), with Tables 1–3, the
  test-case table T1–T15 and eight figures. Every number names the `results/xai/` file it comes from. It is for
  Joan's review before it goes into the final report.
- `xai_chapter.docx`: the Word copy (A4, Times New Roman, built-in headings, so Word's table of contents picks it
  up). It was opened in Word and checked page by page: 13 pages.
- `figures/` is drawn by `python -m explainability.report.make_figures` from the results files.

**Tests (`test_narrative.py`, +4):** an unsupported shape is a guess, not a headline; a shape sentence must agree
with its hub's role; shape sentences and the closure state their scope; a self-payment is never cited and the
narrative still regenerates exactly.
`test_review.py`: the item-features test now also checks the frozen features add up to the Week 7 summary.

## 24. Week 9 — the regeneration service for the platform

**Why.** When an analyst records a partial verdict (removes accounts or transactions from a ring), the platform
needs a new explanation of the corrected ring. Kashish's platform never imports research code, so it calls a local
HTTP service. Her contract (her message of 22 October, and her adapter `platform/adapters/xai.py` on `origin/kashish`)
is what `explainability/serve.py` implements. The regeneration itself is the tenant regenerate of section 20,
unchanged.

**Run it** (from the Ring-Shield checkout that holds the data):

```
set RINGSHIELD_XAI_TOKEN=<a long random token, shared with the platform>
python -m explainability.serve --tenants 12,20 --data-root <this checkout> --port 8765
```

| route | answer |
|---|---|
| `GET /health` (no token) | `{"status": "ok", "tenants_ready": [12, 20], "explainer_version": "0.5.0-review"}` |
| `POST /regenerate` with `Authorization: Bearer <token>` and `{"tenant_id", "ring_id", "excluded_members": [...], "excluded_edges": [...]}` | 200: one explanation row as JSON: the explanations parquet columns, `evidence_summary` and `provenance` as JSON strings, NaN as null, plus a top-level `explainer_version` (her validator requires it) |
| wrong or missing token | 401 `{"error": "Unauthorized"}` |
| malformed body | 400 `{"error": "BadRequest", "message"}` |
| unknown ring, or a tenant this service does not serve | 404 `{"error": "RingNotFound"}` |
| nothing excluded, an id not in the ring, fewer than 2 accounts or no seed / expanded transaction left | 422 `{"error": "InvalidEdit", "message"}` |
| anything else | 500 `{"error": "InternalError"}`, no detail |

**Rules built in:**
- Listens on 127.0.0.1 only, and refuses to start without the token.
- Compares the token in constant time.
- Logs one line per request (method, path, status, milliseconds), never the token, a body, a ring id or explanation text.
- Handles requests one at a time, since the tenant explainers are shared.
- Loads every tenant before the port opens, so `/health` answers only when all are ready.
- A regenerated row keeps the running `explainer_version` (`0.5.0-review`), the same as the stored rows; only
  `latency_ms` changes between two identical calls.

**`--data-root` must be this checkout.** Joan's research code (`ringshield/`) finds its data relative to its own
folder, so a separate data folder would be only half used; the service refuses any other path. The files it reads
(traced while starting tenants 12 and 20 and regenerating once; about 0.95 GB in all):
- `contract/`: `fx_rates.json`, `bank_names.json`, `currency_map.json`, `payment_format_map.json`; `configs/roles.yaml`;
- `data/processed/`: `amlworld_train.parquet`, `amlworld_val.parquet`, `amlworld_test.parquet`,
  `amlworld_gfp_features_test.parquet`;
- `experiments/R1_gine_causal/embeddings_test_seed1.parquet` (575 MB);
- `experiments/R2_b0/gfpxgb_scores/model_seed1.json` and `scores_test_seed1.parquet`;
- `experiments/R4_partition/affinity/affinity.json` and `affinity.txt`, and `experiments/R4_partition/runs/average/seed1/config.yaml`;
- `results/xai/tenant/inputs/`: `tenant_{12,20}_rings.parquet` and `scored_edges_visible_{12,20}_1.parquet`. If the
  visible files are missing, they are rebuilt once from `contract/out/scored_edges_gine_causal_1.parquet` and
  `tenant_{12,20}_edge_ids.parquet`.

**Python:** 3.11.9 with `explainability/requirements-serve.txt` (the packages the service's code imports directly).

**Measured here** (one run, tenants 12 and 20, on this laptop):
- start-up: 39 s;
- memory: peak 1.97 GB during start-up, about 1.0 GB once ready;
- a regenerate: 0.35–0.43 s.

**Example:** `results/xai/tenant/regenerate_example_12.json` is a real request (bank 12, ring
`full-gine_causal-1-0`, one member excluded) and the service's full response. A test pins the service to it.

**Tests (`test_serve.py`, +6):**
- health without a token;
- 401 for a missing, wrong or un-prefixed token;
- every 404 / 422 / 400 case;
- a real regenerate passes every rule the platform's validator checks (restated in the test, since research code
  never imports platform code) and equals the pinned example except `latency_ms`;
- the log holds no token, ring id or narrative;
- the command refuses to start without a token, from another folder, or for an unconfigured tenant.

