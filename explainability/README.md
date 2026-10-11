# L4 Explainability — Week 1 and Week 2 handoff

**Branch:** `explainability-l4` (made from `origin/v2`, commit `003401b`). **Nothing committed or pushed.**
**Status:** Weeks 1 and 2 complete. All 108 tests pass (73 from Week 1, 35 from Week 2), none skipped.
- Week 1 exit criterion — "a fidelity number exists" — met for all five detector seeds and the stub.
- Week 2 exit criterion — "hand-computed fixtures pass" — met; every ring of all five seeds and the stub
  now has an explanation row with edge weights, account weights and roles. **Week 2 starts at section 11.**

This document is written so that someone with only basic technical knowledge can understand what was
built, how every piece works, and how we know it works. Read it top to bottom once; after that, each
section stands on its own.

---

## 1. What this layer is for, in one paragraph

Joan's part of the project (the "research side", layers L0–L3) looks at about 864,000 bank
transactions from the test period and outputs a list of **rings**: small groups of bank accounts that
seem to be laundering money together. Our part (L4, "explainability") has to say, for every ring, *which
transactions in it matter most and why*, in numbers anyone can check. Before we can claim our
explanations are any good, we need a way to **measure** how good an explanation is. Week 1 builds that
measuring stick (called **fidelity**), plus a strict reader for Joan's files, and uses the simplest
possible explanation — "rank the transactions by how suspicious the detector thought they were" — as
the first thing to measure. Later weeks replace that simple ranking with our real one and use the same
measuring stick to prove it is better.

---

## 2. Words you need (glossary)

| Word | Plain meaning |
|---|---|
| **Account** | One bank account. Identified by a number (`account id`). |
| **Transaction / edge** | One payment from one account to another. Called an "edge" because, if you draw accounts as dots and payments as arrows between dots, each payment is an arrow ("edge" in graph language). Each one has an `edge_id`. |
| **Ring** | A group of accounts (and the payments between them) that Joan's system thinks is one laundering attempt. |
| **Detector score** | A number between 0 and 1 that Joan's AI model gives every transaction: how likely it is to be laundering. `score_raw` is the model's direct output; `score_calibrated` is the same score adjusted so that "0.8" really means "about 80 % of transactions with this score are laundering". |
| **Seed edge** | A transaction whose score was in the top 0.1 % — the ones the detector was most sure about. Rings are grown starting from these. |
| **Expanded edge** | A transaction the system *added* to a ring even though its own score was low, because it looked connected to the seeds (timing, amounts, shared accounts). These are the "quiet" members the project is about. |
| **Member edges** | Every transaction between the ring's accounts during the ring's time span. Includes the seeds, the expanded edges, and any other payments between those same accounts. |
| **Truth ring** | A laundering group that really exists in the dataset. The dataset (AMLworld) comes with an answer key listing 370 of them. |
| **Primary window** | The time slice every headline number in this project is measured on: **test days 8 and 9**. (Days 10–17 are measured separately because the dataset's last days are unrealistic — mostly laundering, almost no normal traffic.) |
| **Matching** | Deciding which predicted ring corresponds to which truth ring. Two rings match when their account lists overlap enough (see section 5.2). |
| **Fidelity@k** | Our measuring stick. "Of the k transactions the explanation ranks highest, what share are genuinely part of the true ring?" (exact formula in section 5.4). |
| **Control** | A deliberately dumb comparison. If our explanation can't beat a random ordering, it explains nothing. |
| **Contract files** | The two files Joan hands us: `scored_edges` (one row per transaction) and `rings` (one row per ring). Their exact columns are fixed in Joan's `contract/schema.py`, which is the official rulebook. |
| **Fixture** | A tiny, hand-made fake dataset used only for testing, small enough to check by eye. |

---

## 3. What was built — every file and folder

All paths are relative to the repository root (`Ring-Shield/Ring-Shield/`). Nothing outside these
locations was created or changed.

```
explainability/                 the L4 layer (new)
  __init__.py                   empty; tells Python "this folder is a package you can import"
  config.yaml                   every number this layer uses, in one place            (W1, extended W2)
  contract_io.py                reads Joan's two files and refuses anything that breaks the rules   (W1)
  match.py                      decides which predicted ring is which true ring (using Joan's code) (W1)
  edge_weights.py               W1: detector-score weight + score-only ranking;
                                W2: money-flow weight, leave-one-out weight, bridge flag, the mix
  account_weights.py            W2: roles, money in/out, how busy each account is, account weight
  explain.py                    W2: builds one explanation row per ring; also a command-line tool
  evaluate.py                   computes fidelity and writes the results; also a command-line tool (W1)
  README.md                     this document
  tests/
    __init__.py                 empty; lets the test files import each other
    fixtures.py                 tiny hand-made rings (W1), plus four hand-computed Week 2 cases
    test_contract_io.py         57 tests for the file reader                         (W1)
    test_match.py               8 tests for matching                                 (W1)
    test_fidelity.py            8 tests for the measuring stick and rankings         (W1)
    test_edge_weights.py        21 tests for the edge weights                        (W2)
    test_account_weights.py     10 tests for roles and account weights               (W2)
    test_explain.py             4 tests for the explanation file                     (W2)
results/xai/                    our results (new); kept apart from Joan's results/tables/
  fidelity_week1_seed{1..5}.json, fidelity_week1_stub_cc_seed1.json          Week 1 fidelity
  explanations_week2_seed{1..5}.parquet (+ .log.json)                         Week 2 explanations
  explanations_week2_stub_cc_seed1.parquet (+ .log.json)                      same, on the stub
  roles_disagreement_seed{1..5}.csv, roles_disagreement_stub_cc_seed1.csv     Week 2 role comparison
```

### What Joan's side provides (read only — we never change these)

| File | What we use it for |
|---|---|
| `contract/out/scored_edges_gine_causal_{1..5}.parquet` | every test transaction: who paid whom, when, how much, and the detector scores. One file per detector "seed" (the same model trained 5 times with different random starts). |
| `contract/out/rings_full_gine_causal_{1..5}.parquet` | the predicted rings, one file per seed (108, 112, 113, 120, 107 rings). |
| `contract/out/rings_stub_cc.parquet` | an older, simpler set of rings (98) built only from seeds, no expansion. Used to check our code works on a different kind of ring file. |
| `contract/schema.py` | the official list of columns and their types. |
| `data/processed/amlworld_ring_ground_truth.parquet` | the answer key: which accounts belong to which truth ring. |
| `data/processed/amlworld_test.parquet` | every test transaction with a `ring_id` label (−1 = not in any ring). This is where we get the *true transactions* of each truth ring, because the answer key above lists accounts, not transaction ids. |
| `configs/threshold_rule.yaml`, `configs/eval_window.yaml` | the matching threshold (0.5), the matching rule name (`test_visible`) and the day ranges of each window. We **read** these instead of copying the numbers, so if Joan changes them we follow automatically. |
| Joan's code: `evaluation/ring_metrics.match_rings`, `ringshield/evaluate.restrict_rings`, `ringshield/truth.load_ground_truth`, `ringshield/windows.load_windows`, `ringshield/rings.Ring` | matching and windowing. We call these; we do not rewrite them. |

---

## 4. How to run it

From the repository root, in PowerShell or Git Bash (Python 3.11 with pandas, pyarrow, numpy, pyyaml,
pytest — already installed on this machine):

```bash
# all five seeds, primary window, results into results/xai/
python -m explainability.evaluate

# the old stub file, as a second kind of input
python -m explainability.evaluate --seeds 1 --rings contract/out/rings_stub_cc.parquet --name "fidelity_week1_stub_cc_seed{seed}.json"

# all tests (about 30 seconds)
python -m pytest explainability/tests -q
```

Always use `python -m ...` from the repository root, never `python explainability/evaluate.py`. The
`-m` form makes Python find Joan's packages (`contract`, `ringshield`, `evaluation`) correctly.

Options of the command-line tool: `--scores`, `--rings` (file paths; `{seed}` is replaced by the seed
number), `--truth`, `--split-parquet`, `--window` (default `primary`), `--seeds`, `--out` (folder),
`--name` (file name pattern). Defaults come from `config.yaml`.

---

## 5. How each piece works

### 5.1 `config.yaml` — one home for every number

Instead of numbers being typed inside the code ("magic numbers"), every setting lives here with a
comment. Week 1 actually uses: the window name (`primary`), the k values (3, 5, 10), the number of
random shuffles (20), the random seed (20260921), the input file patterns and the output folder.
Settings for later weeks are already recorded (mixing weights 0.4 / 0.4 / 0.2, grid step 0.1,
λ_split 0.5, leave-one-out over seed + expanded edges, currency policy) so they have one home from day
one. Numbers Joan owns (match threshold, window days, role thresholds) are **not** copied — the file
only points to Joan's config files.

### 5.2 `contract_io.py` — the strict file reader

**Job:** load Joan's two files and stop with a clear error if anything is wrong, instead of quietly
producing wrong numbers later.

**How it works, step by step:**

1. **Check the column list before loading any data.** A parquet file stores its column names and types
   in a small header. We read only that header and compare it with `contract/schema.py`: every
   required column must be there, nothing extra may be there, and each must have the right type
   (whole number, decimal number, true/false, text, or list). If, say, `members` is missing, the error
   says exactly `missing field(s) ['members']`.
2. **Load the data**, and turn the list columns (like `member_edges`) into ordinary Python lists.
3. **Check the transactions file** (`validate_scored_edges`): every `edge_id` appears once; account ids
   and timestamps are never empty; calibrated scores are between 0 and 1; nothing is marked a seed
   without a score; the whole file comes from one model and one seed.
4. **Check every ring** (`validate_rings`), and collect *all* problems before stopping:
   - seed edges and expanded edges must both be part of the ring's member edges, and no edge can be
     both a seed and expanded;
   - there must be exactly one expansion probability per expanded edge;
   - `topology_probs` must be 8 numbers that add up to 1 (one per laundering shape);
   - `topology_type` must be one of the 8 shapes (or `UNKNOWN`);
   - every account listed as a source, sink or mule must be a member of the ring;
   - `conservation_closure` must be between 0 and 1, **or empty (NaN)**. Empty is allowed on purpose:
     it means the ring has no clear start or end (money just goes round), which is legitimate. We keep
     it empty rather than turning it into 0, because 0 would wrongly say "no money was conserved".
   - with the transactions file supplied: every edge the ring mentions must exist there; every member
     edge's two accounts must be ring members; every seed edge must be flagged as a seed there; no
     expanded edge may be flagged as a seed.
5. **Provenance** (`provenance`): the rings file does not say which model or seed produced it, so we take
   that from the transactions file and cross-check it against the ring names, which follow the pattern
   `full-gine_causal-1-0` (aggregator – model – seed – number). Rings from seed 1 paired with seed 2's
   transactions are rejected.

**Why it is called `contract_io.py` and not `io.py`** (as the spec suggests): Python has a built-in
module called `io`. A file of ours with that name can hide the built-in one, which breaks pandas. Joan's
repository already hit exactly this problem with a folder called `typing`.

### 5.3 `match.py` — which predicted ring is which true ring

**Job:** for every predicted ring, find the true ring it corresponds to (if any), using exactly Joan's
rule, so that "matched" means the same thing in her tables and ours.

**The rule (Joan's):** compare the two rings' account lists with the **Jaccard score** = (accounts in
both) ÷ (accounts in either). Example: predicted {A, B, C, D}, true {B, C, D, E} → 3 shared ÷ 5 total
= 0.6. If Jaccard is at least 0.5 it is a match. Pairs are taken best-first, and each ring can be used
only once on each side.

**Step by step:**

1. **Pick the window** (`primary` = test days 8–9), from Joan's `eval_window.yaml`.
2. **Truth rings in the window** — Joan's `load_ground_truth`: a true ring counts if at least one of its
   transactions happens in the window, and its accounts are only the ones seen in the window. For the
   primary window that is **174** true rings.
3. **Predicted rings in the window** — Joan's `restrict_rings`: each ring is cut down to the accounts on
   its transactions that fall inside the window.
4. **Match** — Joan's `match_rings` with threshold 0.5.

**The trap we guard against.** Joan's `restrict_rings` silently throws away rings that have no
transaction in the window and returns a shorter, unnamed list. If ring #1 is thrown away, then "item 1"
of its output is really ring #2. Code that forgot this would credit matches to the wrong ring (Joan's
own repo once published wrong numbers this way — docs/PITFALLS.md §4). So we first remove those rings
ourselves with the same rule, keep their names in a parallel list, and then check that the two lists
have the same length. If they ever differ, the program stops.

**The true transactions of a ring (`truth_edge_sets`).** Fidelity needs the true ring's *transactions*,
but the answer key lists only accounts. `amlworld_test.parquet` labels every transaction with the
`ring_id` it belongs to (−1 if none). So the true edge set T of a ring = all transactions with that
`ring_id` whose time is inside the window. (Some payments appear twice in the dataset as exact
duplicates; both copies are labelled and both are kept.) A test checks that the accounts on these
transactions are exactly the accounts in the answer key, for all 81 matched rings of seed 1.

### 5.4 `edge_weights.py` and `evaluate.py` — the measuring stick

**The explanation being measured in Week 1 (score-only ranking).** For each matched ring, take its
member transactions inside the window and sort them:

1. by calibrated detector score, highest first;
2. if two have the same calibrated score, by raw score, highest first;
3. if still tied, by `edge_id`, lowest first;
4. transactions with no score go last.

Steps 2 and 3 matter more than they look. Calibration squeezes about 800,000 different raw scores into
roughly 100 values, so ties are everywhere. Without fixed tie-breaks the order could change between
runs and the results would not repeat.

**Fidelity@k, the formula:**

> fidelity@k = (number of the top-k ranked transactions that are in the true set T) ÷ min(k, size of T)

Dividing by min(k, |T|) instead of k is fair to small rings: if the true ring has only 2 transactions,
a perfect explanation can only ever get 2 right in its top 3, and it should score 1.0, not 0.67.

**Worked example** (this exact case is a test, `fixtures.five_edge_case`):

| edge | calibrated score | raw score | truly in the ring? |
|---|---|---|---|
| 11 | 0.90 | 0.91 | yes |
| 12 | 0.80 | 0.81 | no |
| 13 | 0.80 | 0.79 | yes |
| 14 | 0.30 | 0.31 | yes |
| 15 | 0.10 | 0.11 | no |

Ranking: 11, then 12 and 13 tie on 0.80 — 12 has the higher raw score so it goes first — then 14, 15.
T = {11, 13, 14}, so |T| = 3.
- fidelity@3: top 3 = {11, 12, 13}; 2 of them are true; 2 ÷ min(3, 3) = **0.667**
- fidelity@5: all 5; 3 true; 3 ÷ min(5, 3) = **1.0**
- fidelity@10: only 5 exist, same as @5 = **1.0**

**The random control.** The same transactions, shuffled into a random order, 20 times; fidelity is
averaged over the 20 shuffles. The shuffles use a fixed random seed built from (config seed, detector
seed, ring position), so every run produces exactly the same "random" numbers. A test checks the
average is correct: for a random order, the expected number of true transactions in the top k is
k × |T| ÷ n (n = transactions in the ring), so expected fidelity = (k × |T| ÷ n) ÷ min(k, |T|).
With 4,000 shuffles our average lands within 0.02 of that formula.

**What the program does for each seed:**
1. reads and validates both files (5.2);
2. matches rings (5.3);
3. gets the true transaction set for each matched ring;
4. for each matched ring: ranks its in-window member transactions by score and computes fidelity@3,
   @5, @10; does the same for the random control;
5. averages each number over all matched rings;
6. writes one JSON file with: what was measured, the input files, model/seed/aggregator, the window
   and matching settings, the counts, the averages, and one row per ring.

The JSON contains no date or time and its keys are sorted, so running twice gives **byte-for-byte
identical files** (a test checks this on the real seed-1 data). Any ranking is just a function "given
the ring's transactions, return their ids in order", so the Week 2–4 ranking plugs into the same
program without changing the measuring stick.

### 5.5 `tests/fixtures.py` — the tiny fake rings

Twelve hand-made rings, each a few accounts and a few payments, all on test day 8, in exactly the
contract format:

- **one per laundering shape:** FAN-OUT (one account pays four), FAN-IN (four pay one),
  GATHER-SCATTER (three pay a hub, the hub pays three), SCATTER-GATHER (one pays three middlemen, they
  pay one), CYCLE (money goes round a loop, with an entry and an exit), RANDOM, BIPARTITE (two accounts
  each pay the same two others), STACK (a chain A→B→C→D→E);
- **four edge cases:** a pure closed loop (no start or end, so its closure is empty/NaN), a ring
  spanning three banks, a ring with mixed currencies, and a ring where two transactions were *expanded*
  (low score, with expansion probabilities 0.85 and 0.72);
- some unrelated background payments, so the file is not "all rings".

Plus two special cases: the five-edge worked example above, and the "window trap" case (a ring entirely
outside the window placed first, then a ring that should match).

---

## 6. Results (primary window, matched rings, mean over rings)

| input | rings | matched | score-only @3 | @5 | @10 | random @3 | @5 | @10 |
|---|---|---|---|---|---|---|---|---|
| seed 1 | 108 | 81 | 0.910 | 0.892 | 0.899 | 0.607 | 0.690 | 0.831 |
| seed 2 | 112 | 81 | 0.926 | 0.933 | 0.935 | 0.632 | 0.725 | 0.862 |
| seed 3 | 113 | 77 | 0.918 | 0.923 | 0.916 | 0.617 | 0.712 | 0.851 |
| seed 4 | 120 | 89 | 0.936 | 0.916 | 0.913 | 0.644 | 0.731 | 0.854 |
| seed 5 | 107 | 73 | 0.906 | 0.898 | 0.899 | 0.603 | 0.685 | 0.829 |
| stub (seed 1) | 98 | 69 | 0.940 | 0.890 | 0.862 | 0.622 | 0.681 | 0.803 |

**How to read this:**

- **The score-only ranking beats random at every k, on every seed and on the stub.** On average about
  91 % of its top-3 transactions are truly part of the ring, against about 62 % for a random order.
- **Random is not near zero, and that is expected.** About 53–56 % of a matched ring's transactions are
  truly ring transactions (the rest are other payments between the same accounts in the same days), and
  rings are small, so even a random top-10 often covers most of the true set. This is exactly why the
  spec requires a random control: a fidelity number alone would look impressive whatever we did.
- **The gap shrinks as k grows** (0.91 vs 0.61 at k = 3; 0.90 vs 0.83 at k = 10), because with k = 10
  most of a small ring is included whichever order you use. k = 3 and 5 are where explanations differ.
- **These are point estimates.** Confidence intervals (1,000 resamples) arrive in Week 4.
- **This is the baseline, not our method.** The spec's second control is exactly this score-only
  ranking. From Week 2 our real ranking (detector score + leave-one-out + money flow) must beat *both*
  this table's score-only column and its random column.
- The matched counts equal Joan's own logs for every seed (seed 1: 94 rings in the window, 174 true
  rings, 81 matched) and her stub metrics file (82 / 174 / 69), so our matching is identical to hers.

---

## 7. The tests — what each one proves (73 passed, 0 skipped)

Run with `python -m pytest explainability/tests -q`.

**`test_contract_io.py` (57 tests) — the reader**
- `test_real_files_load` (×5) and `test_stub_loads`: all five seeds' real files plus the stub load and
  pass every rule; model, seed and aggregator are identified correctly.
- `test_missing_scored_edges_field_is_named` (×17, one per column) and
  `test_missing_rings_field_is_named` (×22, one per column): deleting any single column is caught and the
  error names that column.
- `test_missing_field_in_a_file_on_disk_is_named`: the same, for a real file saved without `members`.
- `test_extra_field_is_rejected`: a spec-style `member_accounts` column is refused (the real name is
  `members`).
- `test_wrong_scalar_type_is_rejected`, `test_wrong_list_element_type_is_rejected`: wrong types caught.
- `test_seed_edges_not_in_member_edges_is_rejected`, `test_expanded_probs_length_mismatch_is_rejected`,
  `test_topology_probs_not_a_distribution_is_rejected`, `test_edge_missing_from_scored_edges_is_rejected`,
  `test_rings_from_another_seed_are_rejected`: each rule in 5.2 fires.
- `test_nan_conservation_closure_is_kept_as_nan`: the 6 seed-1 rings with no start/end keep NaN.
- `test_every_fixture_passes_validation`, `test_broken_fixture_seed_not_in_members_is_rejected`: all 12
  fixtures are valid contract data; a broken one is refused.

**`test_match.py` (8 tests) — matching**
- `test_counts_reproduce_the_research_log` (×5): predicted / truth / matched counts equal Joan's run log
  for each seed (seed 1: 94 / 174 / 81); matches are one-to-one and all at Jaccard ≥ 0.5.
- `test_true_edge_sets_agree_with_the_truth_accounts`: for all 81 matched rings, the accounts on the true
  transactions equal the answer key's accounts.
- `test_a_ring_outside_the_window_does_not_shift_the_ids`: the window trap — the match goes to the right
  ring's name.
- `test_no_matching_code_is_reimplemented_in_the_layer`: scans our code; no function named like a
  matcher exists, and `match.py` imports Joan's `match_rings` (spec rule XR-28).

**`test_fidelity.py` (8 tests) — measuring stick and rankings**
- `test_five_edge_ring_matches_the_hand_computation`: the worked example, to 1e-9.
- `test_w_score_is_the_calibrated_score`, `test_ties_break_on_raw_score_then_edge_id_and_missing_scores_go_last`.
- `test_fidelity_edge_cases`: fewer transactions than k, a one-transaction truth set, an empty truth set
  (refused).
- `test_random_control_is_reproducible_under_its_seed`: same seed → same result, regardless of input order.
- `test_random_control_converges_to_its_expected_value`: matches the formula in 5.4.
- `test_every_fixture_ring_scores_one_when_all_its_edges_are_true`: end-to-end sanity on the fixtures.
- `test_two_runs_write_byte_identical_json`: the full program twice on real seed-1 data → identical files.

---

## 8. Decisions made this week (and why)

1. **True transactions are restricted to the primary window**, the same way Joan restricts rings before
   matching. Measuring inside the window and matching inside the window keeps the two consistent.
2. **Fidelity ranks the ring's member transactions** (all payments between its accounts in the window),
   as the spec says — not only its seed + expanded edges. That is the set an investigator would see.
3. **Results go in `results/xai/` with the experiment id `XAI-W1`**, never `R9`: in this repository R9
   already means Joan's statistics step and R11 her seed-budget runs.
4. **Reader named `contract_io.py`**, not `io.py` (section 5.2).
5. **The stub output gets its own file name** (`fidelity_week1_stub_cc_seed1.json`, via `--name`) so it
   does not overwrite seed 1's result.
6. **Recorded for later weeks** (in `config.yaml`): leave-one-out will use seed + expanded edges (checked:
   this reproduces all 108 shipped seed-1 rings exactly); currency handling is "raw" until agreed with
   Joan.

## 9. Not in Week 1 (planned next)

Leave-one-out and money-flow weights and account roles (Week 2), SHAP on the 17-feature GFP+XGBoost
model and narrative templates (Week 3), tuning the mixing weights and confidence intervals (Week 4),
typology / latency / API schemas (Week 5).

## 10. Open items to send Joan (none block Week 1)

> Hi Joan — L4 Week 1 is done on branch `explainability-l4` (from origin/v2, not pushed). It reads your
> v1 contract files, uses your `match_rings` / `restrict_rings` / `load_ground_truth` unchanged, and
> reproduces your logged counts for all 5 seeds (seed 1: 94 / 174 / 81) and the stub (82 / 174 / 69).
> Four things I'll need from you, none urgent this week:
> 1. **Validation-split rings** (needed by Week 4 to tune the mixing weights on validation, never on
>    test): `contract/make_rings_full.py` only builds the test split.
> 2. **Currency convention** (Week 2, money-flow weights): keep raw cross-currency sums as the shipped
>    roles/closure do, or is a conversion table coming? 78 of 108 seed-1 rings mix currencies.
> 3. **`RingRerunner` hub-degree feature** (Week 2, leave-one-out): inside the rerunner,
>    `acc_log_degree_window` is computed from the ring's own edges, not the full split (differs on 85 % of
>    pairs). Base reruns still reproduce all 108 rings; is that acceptable as a documented caveat, or can
>    the rerunner take the split index?
> 4. **README "L3d explainability" row**: who updates it now that L4 exists? (Its SHAP line refers to the
>    expansion policy; the spec puts SHAP on GFP+XGBoost seed edges.)

*(Week 2 updates this note — see section 19.)*

---
---

# WEEK 2

## 11. What Week 2 adds, in one paragraph

Week 1 built the measuring stick. Week 2 builds the **evidence itself**. For every ring we now compute
three numbers per transaction and combine them into one score, `w_total`:
- **`w_score`**, how suspicious the detector found the transaction;
- **`w_loo`**, how much the ring *depends on* the transaction;
- **`w_flow`**, how much of the ring's money went through it.

We also work out, for every account, what **role** it plays (where money starts, where it ends, who
passes it on) and an **account weight**. The result is written as one *explanation row* per ring, in
the layout the spec asks for, so Week 3 can add the plain-English sentence and the detector-feature
explanation (SHAP) on top. The narrative and SHAP parts are deliberately empty for now.

## 12. New words (glossary, Week 2)

| Word | Plain meaning |
|---|---|
| **Included edges** | The transactions the ring-builder actually *used* to form the ring: its seed edges plus its expanded edges. Other member edges (ordinary payments between the same accounts) were never part of the grouping decision. |
| **Leave-one-out** | Take one transaction away, rebuild the ring without it, and see what changes. If the ring falls apart or loses confidence, that transaction mattered. |
| **Rerun / `RingRerunner`** | Joan's function that rebuilds a ring from a given set of transactions using exactly the same rules (and the same AI "affinity" model) that built it originally. We call it, we never copy it. |
| **Confidence (c₀)** | Joan's score for how sure the system is about a ring: the average detector score of its seed edges × its conservation closure (when that exists). c₀ is the confidence of the full ring; c₋ₑ is the confidence after removing transaction e. |
| **Conservation closure** | How much of the money that enters the ring also leaves it at the other end (1 = all of it). Empty (NaN) when the ring has no clear start or end. |
| **Bridge / `split`** | A transaction whose removal cuts the ring into separate pieces. Think of a rope bridge between two cliffs: remove it and you can no longer cross. `split = 1` for a bridge, `0` otherwise. |
| **Role** | What an account does in the ring: **source** (money starts here), **sink** (money ends here), **mule** (passes money on quickly), **holder** (passes it on, but sits on it more than 72 hours), **peripheral** (involved, but unbalanced — e.g. received 100, sent 50). |
| **Hold time** | How long money sits in an account before moving on. |
| **Background degree** | How many transactions an account made in the *whole* test period, not just inside the ring. |
| **Provenance** | A record, stored with every explanation, of exactly which model, files and settings produced it — so any number can be traced and reproduced. |
| **Deterministic** | Running twice on the same inputs gives exactly the same output. |

## 13. New inputs from Joan's side (all read-only, all already on disk)

| File | Why we need it |
|---|---|
| `data/processed/amlworld_gfp_features_test.parquet` | Ten "graph pattern" counts per transaction. The rerun needs them to rebuild rings *exactly* as they were built. |
| `experiments/R1_gine_causal/embeddings_test_seed{1..5}.parquet` | 198 numbers per transaction learned by the detector (one big file per seed, ~600 MB). Also needed by the rerun. We read only the rows for the rings' transactions. |
| `experiments/R4_partition/affinity/` | The small AI model that decides which transactions belong together. One model, shared by all seeds — exactly what Joan's ring builder used. |
| `experiments/R4_partition/runs/average/seed{1..5}/config.yaml` | The settings the ring builder used for each seed (clustering method `average`, cut 0.5, minimum 3 accounts). Read from the file, never typed in. |
| `contract/out/rings_stub_cc.parquet.log.json` | For the stub file only: its minimum ring size (3). |
| Joan's code: `ringshield.roles` (`RingRerunner`, `account_roles`, `dedup_edges`), `ringshield.expand.features.EmbeddingStore`, `ringshield.partition.affinity.Affinity`, and `configs/roles.yaml` (τ = 0.25, hold limit 72 h) | Rebuilding rings, roles, and their thresholds. |

## 14. How each Week 2 piece works

### 14.1 `config.yaml` additions

- **`research_inputs`**: the four paths above.
- **`edge_weights.loo_nan_policy: full_loss`**: what to do when a ring disappears (14.3).
- **`edge_weights.mixing_sum_tolerance`**: α + β + γ must add up to 1.
- **`account_weights`**: the two halves of the account weight, 0.5 and 0.5.
- **`amounts.flow_amount_column: amount_received`**, with the currency policy still `raw` (marked
  provisional).
- **Output file names**, and `explainer_version` raised to `0.2.0-week2`.
- **`explanations_experiment_id: XAI-W2`.**

### 14.2 `w_flow` — share of the money (`edge_weights.w_flow`)

> w_flow(e) = amount of e ÷ total amount of all the ring's member transactions

**Duplicate rule.** The dataset sometimes lists the very same payment twice: same sender, receiver,
time and amount. The total counts it once, and both copies show the same share.

Example (`fixtures.flow_case`): payments of 100, 100 (a duplicate of the first), 50 and 50. The total is
100 + 50 + 50 = 200, so the shares are 0.5, 0.5, 0.25 and 0.25.

**Currency.** Amounts are summed as they are, even when currencies differ. That matches how Joan's
roles and closure are computed. It is marked *provisional* in every explanation until Joan confirms the
convention: 67–78 rings per seed mix currencies.

### 14.3 `w_loo` — how much the ring depends on a transaction (`edge_weights.w_loo`)

**Step by step, for one ring:**

1. Take the ring's **included** transactions (seed + expanded) and build **one** `RingRerunner` with
   the real GFP features, embeddings and affinity model. If the rerunner reports `features_degraded`
   (an input missing), we stop with an error. A degraded rerun is a different measurement and must
   never be mixed in.
2. **c₀** = the confidence of the ring rebuilt from all its included transactions (1 call).
3. For each included transaction e (1 call each):
   - **c₋ₑ** = the confidence of the largest ring rebuilt *without* e;
   - **drop** = c₀ − c₋ₑ, but never below 0 (if removing e makes the ring *more* confident, e
     simply does not help it);
   - if **no ring is left at all** (c₋ₑ is empty, e.g. a 3-account ring losing a link and falling
     below the 3-account minimum), the transaction was essential: **drop = c₀**, a "full loss";
   - **split(e)** = 1 if e is a bridge (14.4);
   - **raw = drop + 0.5 × split**.
4. **w_loo = raw ÷ the largest raw in the ring**, so the most important transaction gets 1. If every
   raw is 0, every `w_loo` is 0.
5. Member transactions that are **not** included get `w_loo = 0` and `split = 0`. The ring builder
   never used them, so removing one cannot change the ring.

The rerunner is called **exactly (number of included transactions + 1)** times per ring. A test
counts the calls (spec XR-06).

**Worked example** (`fixtures.loo_case`, a real test). Accounts A, B, C, D:

| edge | payment | role in ring | detector score | time |
|---|---|---|---|---|
| e1 | A → B, 100 | seed | 0.9 | 0.0 h |
| e2 | B → C, 90 | seed | 0.8 | 1.0 h |
| e3 | C → D, 80 | seed | 0.6 | 2.0 h |
| e4 | A → C, 30 | expanded | 0.2 | 0.5 h |
| e5 | B → D, 20 | member only | 0.05 | 3.0 h |

For the test we use Joan's simple "connected pieces" rebuild, where confidence = average seed score ×
closure, so everything can be checked on paper:

| without | what is left | closure | avg seed score | confidence | drop |
|---|---|---|---|---|---|
| nothing (c₀) | A source 130 out, D sink 80 in | 1 − 50/130 = 0.615 | 0.767 | **0.4718** | — |
| e1 | sources A 30 + B 90 = 120, sink D 80 | 1 − 40/120 = 0.667 | 0.70 | 0.4667 | **0.0051** |
| e2 | source A 130, sinks B 100 + D 80 = 180 | 1 − 50/180 = 0.722 | 0.75 | 0.5417 | 0 |
| e3 | source A 130, sink C 120 | 1 − 10/130 = 0.923 | 0.85 | 0.7846 | 0 |
| e4 | chain A→B→C→D, source 100, sink 80 | 0.8 | 0.767 | 0.6133 | 0 |

Removing e3 cuts D off, so it is a bridge: split = 1 and raw = 0 + 0.5 = **0.5**, the largest. So
**w_loo(e3) = 1**, **w_loo(e1) = 0.0051 ÷ 0.5 = 0.0103**, e2 and e4 get 0, and e5 gets 0 (not
included). Joan's real rerunner reproduces every one of these numbers to 1e-6.

### 14.4 `split` — bridges (`edge_weights.split_flags`)

Draw the ring's accounts as dots and its transactions as plain lines (direction ignored). Remove one
line. If the dots now fall into **more separate groups** than before, that line was a bridge. The set of
dots stays fixed, so cutting off a single account also counts.

- In a **chain** (STACK) every link is a bridge.
- In a **loop** no link is a bridge, because there is always another way round.
- In a **fan** (one account paying many), every link is a bridge. In fans, split therefore cannot tell
  links apart; the confidence drop, the detector score and the money flow do that work. This is
  expected from the spec's definition and visible in the results: 856 of 7,520 member transactions
  share `w_loo = 1`.

### 14.5 `w_total` — the mix (`edge_weights.edge_weight_table`)

> w_total = α × w_score + β × w_loo + γ × w_flow, with (α, β, γ) = (0.4, 0.4, 0.2) from config

The weights must be ≥ 0 and add up to 1, or the program stops. Every member transaction gets a row,
sorted by `w_total` (highest first), with Week 1's tie-breaks so the order never changes between runs.
For the worked example:

| edge | 0.4 × w_score | 0.4 × w_loo | 0.2 × w_flow (amount ÷ 320) | **w_total** | rank |
|---|---|---|---|---|---|
| e3 | 0.24 | 0.40 | 0.050 | **0.690** | 1 |
| e1 | 0.36 | 0.0041 | 0.0625 | **0.427** | 2 |
| e2 | 0.32 | 0 | 0.0563 | **0.376** | 3 |
| e4 | 0.08 | 0 | 0.0188 | **0.099** | 4 |
| e5 | 0.02 | 0 | 0.0125 | **0.033** | 5 |

The bridge e3 rises to the top even though its detector score (0.6) was only the third highest. That is
exactly the kind of evidence the score alone misses. **These mixing weights are untuned defaults.**
Week 4 chooses them on validation rings, and they are never tuned on test.

### 14.6 Roles (`account_weights.research_roles`, `spec_roles`, `role_disagreements`)

**Authoritative roles** come from Joan's `account_roles`, run on the ring's included transactions.
Joan's rules, with τ = 0.25 and the hold limit of 72 h read from `configs/roles.yaml`:

| role | rule |
|---|---|
| sink | sends nothing |
| source | receives nothing |
| mule | money in and out within 25 % of each other, and passed on within 72 h |
| holder | in and out balanced the same way, but held longer than 72 h (or the hold time can't be measured) |
| source / sink (unbalanced) | receives less than a quarter of what it sends → source; sends less than a quarter of what it receives → sink |
| peripheral | everything else (e.g. in 100, out 50) |

**Joan's hold time:** for each payment *into* the account, the wait until the next payment *out of* it.
The median of those waits.

These roles reproduce the contract's `source_accounts`, `sink_accounts` and `mule_accounts` lists
exactly, for every ring of all five seeds (a test checks all 560 rings).

**The spec's own rule (§4.3)** is also implemented, but only to compare against. Its hold time runs the
other way: for each payment *out*, the time since the latest payment *in* before it. And when no hold
time can be measured, it says "peripheral" where Joan's says "holder". Both are run on the same
transactions (with duplicates removed the same way), so any difference comes from the rule alone. Each
difference becomes a row in `roles_disagreement_seed{S}.csv`, with a likely cause:

- **`hold_time_definition`**: both rules see a balanced account, but the two hold-time rules land on
  opposite sides of 72 h. Example, fixture account X: paid 100 at hour 0, pays out 50 at hour 1 and 50
  at hour 200. Joan's rule gives 1 h (mule); the spec's gives the median of 1 h and 200 h = 100.5 h
  (holder).
- **`undefined_hold_time`**: one rule has no hold time, so they decide differently.
- **`rule_order`**: anything else.

### 14.7 Account weight (`account_weights.account_weight_table`)

For each member account a:

> w_account(a) = 0.5 × (sum of w_total on a's ring transactions ÷ the largest such sum in the ring)
>              + 0.5 × (a's transactions inside the ring ÷ a's transactions in the whole test period)

The second half is high for an account that is **busy inside the ring but quiet outside it**, which is
what an account set up for laundering looks like. A normal business account that happens to touch the
ring scores low there.

Worked example (`fixtures.account_weight_case`): transactions A→B (`w_total` 0.8) and B→C (0.4);
across the whole test period A has 4 transactions, B 2, C 1.

| account | sum w_total ÷ max (1.2) | in ring ÷ whole period | **w_account** |
|---|---|---|---|
| B | 1.2 ÷ 1.2 = 1 | 2 ÷ 2 = 1 | **1.000** |
| C | 0.4 ÷ 1.2 = 0.333 | 1 ÷ 1 = 1 | **0.667** |
| A | 0.8 ÷ 1.2 = 0.667 | 1 ÷ 4 = 0.25 | **0.458** |

Each account row also carries its role, money in, money out and hold time, from Joan's `account_roles`.

### 14.8 `explain.py` — one explanation row per ring

For each ring the program:
1. looks up its member and included transactions;
2. computes `w_loo` (14.3), then the full edge table (14.5);
3. computes roles (14.6) and the account table (14.7);
4. runs the spec role rule and records any disagreement;
5. copies the ring's topology and its probability;
6. writes the provenance;
7. records how long all of that took (`latency_ms`).

**Columns of `explanations_week2_seed{S}.parquet`** (the spec's §3.1 layout):

| column | contents |
|---|---|
| `ring_id`, `tenant_id` | which ring, which bank |
| `edge_weights` | a list, one entry per member transaction: `edge_id, w_total, w_score, w_loo, w_flow`, highest `w_total` first |
| `account_weights` | a list, one entry per member account: `account_id, role, inflow, outflow, hold_time_s, w_account`, highest first |
| `feature_weights` | empty list — SHAP arrives in Week 3 |
| `topology_type`, `topology_prob` | the ring's shape and its probability, copied from the ring |
| `narrative`, `evidence_summary` | empty — Week 3 |
| `latency_ms` | milliseconds this row took |
| `provenance` | text (JSON) listing model, aggregator, seed, explainer version, mixing weights, λ_split, which transactions leave-one-out used, the NaN rule, currency policy (*provisional*), role source, the rerun files and settings, `features_degraded: false`, and **`loo`: c₀, the shipped confidence, and whether the rerun reproduced the shipped ring** |

**Next to each parquet:**
- `….parquet.log.json`: counts, rings that did not reproduce, mixed-currency rings, disagreement counts
  by cause, and latency (p50 / p95 / max, plus any ring over 5 s).
- `roles_disagreement_seed{S}.csv`: the role comparison rows.

**Determinism (spec XR-30).** Running twice gives identical output in every column except `latency_ms`,
because a stopwatch can never give the same reading twice and the spec asks for both in one file. The
test sets `latency_ms` to 0 in both runs, writes each to parquet and requires the **bytes** to be
identical. (A byte comparison is used because Arrow's "equals" treats two empty values (NaN) as
different; NaN is normal here, e.g. a source account has no hold time.)

Commands:

```bash
python -m explainability.explain                                   # all five seeds
python -m explainability.explain --seeds 1 --rings contract/out/rings_stub_cc.parquet --name "explanations_week2_stub_cc_seed{seed}.parquet" --disagreement-name "roles_disagreement_stub_cc_seed{seed}.csv"
```

## 15. Week 2 results

| input | rings | explained | rerun reproduces shipped ring | mixed-currency rings | role disagreements | latency p50 / p95 / max |
|---|---|---|---|---|---|---|
| seed 1 | 108 | 108 | 108 | 78 | 4 | 198 / 683 / 1,770 ms |
| seed 2 | 112 | 112 | 109 | 77 | 4 | 209 / 709 / 1,397 ms |
| seed 3 | 113 | 113 | 112 | 76 | 2 | 205 / 725 / 1,644 ms |
| seed 4 | 120 | 120 | 119 | 77 | 1 | 190 / 510 / 1,180 ms |
| seed 5 | 107 | 107 | 107 | 67 | 2 | 185 / 563 / 1,364 ms |
| stub (seed 1) | 98 | 98 | 48 | 77 | 1 | 46 / 89 / 150 ms |

**How to read it:**

- **Every ring has an explanation.** That is 560 across the five seeds plus 98 for the stub.
- **Speed.** The spec's target is under 2 seconds per explanation (95th percentile); we are at 0.5–0.7 s,
  and the slowest single ring took 1.8 s. The formal latency report (XR-27) is Week 5.
- **5 of 560 rings do not reproduce when rebuilt alone:** `full-gine_causal-2-16`, `-2-47`, `-2-105`,
  `-3-74` and `-4-90`. When Joan's system built the rings, some accounts were shared between several
  rings, and the AI affinity model looked at those accounts' activity across *all* of them. Rebuilt
  alone, the same account only shows this ring's activity, so for these five a grouping decision comes
  out differently. This is the "context" caveat accepted in decision 7.
  - We keep leave-one-out *internally consistent*: c₀ and every c₋ₑ come from the same rebuild.
  - Each of those five explanations says `reproduces_shipped_ring: false` in its provenance.
  - A test pins exactly these five, so any new one is caught.
- **The stub reproduces only 48 of 98.** That is expected and not a fault. The stub file was made before
  Joan's current confidence definition, so its stored confidence is a different number; its rings are
  still rebuilt and explained normally.
- **Role disagreements are rare, not systematic.** We expected (and the Reality Check predicted) many
  differences from the opposite hold-time rules. Measured: **none** came from the hold-time rule; all
  13 across 560 rings are `undefined_hold_time`. These are accounts that **paid money out before any came
  in** (inside the ring), so neither rule can measure a hold time. Joan's rule calls them "holder", the
  spec's "peripheral". **Week 3 consequence:** the narrative must not describe such an account as having
  "held" money.
- **About half of each ring's member transactions get a non-zero `w_loo`** (54 % on average). The rest
  are mostly the ordinary payments between ring accounts that the ring builder never used (`w_loo = 0` by
  definition).
- **No fidelity number for the mix yet, on purpose.** Measuring the untuned mix on test would invite
  choosing weights by looking at test results. The first mix fidelity number will come from Week 4's
  tuning on validation rings.

## 16. Week 2 tests — what each proves (35 new; 108 total pass, 0 skipped)

**`test_edge_weights.py` (21 tests)**
- `test_rerun_is_not_degraded_and_reproduces_the_shipped_rings` (×5 seeds): every rerun has the real
  inputs (never degraded); every ring outside the pinned five rebuilds to exactly itself with exactly the
  shipped confidence; the non-reproducing rings are exactly the pinned five.
- `test_missing_rerun_inputs_are_refused`: take the embeddings away and the program refuses to run.
- `test_week2_contract_fixtures_validate` (×2): the new fixture rings are valid contract data.
- `test_w_flow_counts_a_duplicate_payment_once`, `test_w_flow_matches_the_hand_computation`,
  `test_w_flow_is_zero_when_the_ring_moves_no_money`.
- `test_w_loo_matches_the_hand_computation`: c₀, every c₋ₑ, split and `w_loo` to 1e-6 (the table in
  14.3).
- `test_split_flags_mark_bridges_only`: every chain link is a bridge, no loop link is.
- `test_rerunner_is_called_exactly_edges_plus_one_times` (XR-06).
- `test_a_ring_that_disappears_without_an_edge_counts_as_full_loss`, `test_all_zero_weights_when_nothing_matters`,
  `test_unknown_nan_policy_is_refused`.
- `test_w_total_matches_the_hand_computation_for_all_five_edges` (XR-03): every component, the total and
  the order, to 1e-6.
- `test_changing_the_mixing_weights_changes_the_output` (XR-04), `test_invalid_mixing_weights_are_refused` (×2).

**`test_account_weights.py` (10 tests)**
- `test_research_roles_reproduce_the_contract_role_arrays` (×5 seeds): roles regroup into exactly the
  contract's source / sink / mule lists, for all 560 rings, and every member gets a role (XR-11).
- `test_ring_degree_never_exceeds_background_degree`.
- `test_every_role_is_covered_and_matches_by_hand`: one fixture ring has all five roles (XR-10).
- `test_spec_rule_and_disagreement_log`: the spec rule differs only on account X, cause
  `hold_time_definition` (XR-12).
- `test_role_thresholds_come_from_config`: changing the hold limit changes the roles (XR-10).
- `test_w_account_matches_the_hand_computation` (XR-08 / XR-09): the table in 14.7.

**`test_explain.py` (4 tests)**
- `test_schema_and_coverage_on_the_fixture` (XR-21): exact column layout; every member transaction and
  account explained; sorted; numbers equal the hand computation; Week 3 columns empty.
- `test_provenance_records_every_setting_and_follows_the_config` (XR-32, XR-04): provenance holds every
  setting; a different mix in the config changes both the weights and the provenance.
- `test_role_disagreements_reach_the_output`.
- `test_two_runs_are_identical_except_latency` (XR-30): two full real runs on seed 1 give byte-identical
  data apart from `latency_ms`, and an identical disagreement file; all 108 rings explained.

Run everything: `python -m pytest explainability/tests -q` (about 4 minutes; the real-data tests load the
large embedding files).

## 17. Week 2 decisions, and three things that came up while building

**Approved decisions, as built:**
1. Leave-one-out uses the included (seed + expanded) transactions. Other member transactions get
   `w_loo = 0` and `split = 0`.
2. A ring that disappears without a transaction counts as a full loss (drop = c₀).
3. `w_flow` uses `amount_received`, summed raw across currencies, marked provisional.
4. Roles come from Joan's `account_roles`. The spec rule is used only for the disagreement log.
5. The determinism check covers every column except `latency_ms`.
6. `explain.py` and the explanations file are built now, with the Week 3 columns left empty.
7. The context caveat is accepted and documented.
8. `w_flow` is not rescaled.
9. No untuned mix fidelity on test.

**Came up while building (handled openly, nothing hidden):**
- **The step 1 check was refined, not weakened.** The plan expected every ring of every seed to rebuild
  exactly; that had only been verified on seed 1. On all five seeds, 5 of 560 do not (section 15). The
  test now requires every *other* ring to reproduce exactly and pins those five by name.
- **The determinism test compares bytes.** Arrow's table comparison reported a difference that turned out
  to be only "NaN ≠ NaN"; the data were identical. The byte comparison is stricter and handles NaN
  correctly.
- **`explainer_version` is now `0.2.0-week2`.** The Week 1 fidelity files on disk still say
  `0.1.0-week1`; re-running `evaluate` would write the new version string into those files. Nothing else
  in them would change.

## 18. Not in Week 2 (next)

**Week 3:**
- SHAP on the 17-feature GFP+XGBoost model for each ring's seed transactions (`feature_weights`).
- The phrasing dictionary.
- The eight narrative templates plus a fallback.
- `evidence_summary`, and the regenerate-the-sentence test.

The narrative must handle three things from Week 2's findings: rings with empty closure; accounts
labelled "holder" because they paid out before being paid in; and cross-bank rings as the normal case.

**Week 4:** tuning the mix on validation rings (needs Joan's validation rings), confidence intervals.

**Week 5:** typology accuracy, the formal latency report, the API schemas.

## 19. Note for Joan (Week 2 update — supersedes section 10's list)

> Hi Joan — L4 Week 2 is done on `explainability-l4` (not pushed). Every ring of all 5 seeds + the stub
> now has an explanation row (edge weights via your `RingRerunner`, roles via your `account_roles`).
> Things for you, in order of urgency:
> 1. **Validation-split rings, needed for Week 4.** XR-05 tunes the mixing weights on validation, never
>    on test, and `contract/make_rings_full.py` only builds the test split. This is the one item that
>    will block us.
> 2. **5 of 560 rings don't rebuild identically through `RingRerunner`**: 2-16, 2-47, 2-105, 3-74,
>    4-90. Base reruns are non-degraded. In the component run the affinity features of a shared
>    account see the whole component; in the rerun they see one ring. Is that acceptable as a
>    documented caveat (it's what we do now, flagged per explanation), or can the rerunner take the
>    component or split index?
> 3. **Currency convention**: we sum `amount_received` raw across currencies, like your roles and
>    closure (67–78 rings per seed mix currencies). Keep it, or is a conversion coming?
> 4. **For your information**: your `account_roles` and the spec's §4.3 rule disagree on only 13
>    accounts in 560 rings, all of them accounts that paid out before any inflow (yours says holder,
>    the spec says peripheral). We use yours.
> 5. **README "L3d explainability" row**: who updates it now that L4 exists?
