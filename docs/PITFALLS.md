# Pitfalls — traps this repository has actually fallen into

Every entry below cost real time or produced a wrong number that had to be retracted. This is not
a style guide; it is the list of things that look fine and are not. `docs/RINGSHIELD_IMPLEMENTATION_LOG_v2.md`
§10 holds the *accepted trade-offs*; this file holds the *mistakes*.

---

## Data integrity

### 1. `format_kaggle_files.py` used to write next to its input — and `edge_id` is defined by that file

**The trap.** The script wrote `formatted_transactions.csv` into the directory of its input, with
no way to redirect it. Running it on a second AMLworld release (`data/raw/LI-Small_Trans.csv`)
would have silently overwritten HI-Small's formatted CSV.

**Why it is worse than it looks.** Every `edge_id` in this project is a row position in that file
after a mergesort on `Timestamp`. Overwriting it does not corrupt anything visibly — it silently
re-keys the entire project. Every score parquet, embedding, calibrator, rings artefact and contract
file would still load, still join, and be **wrong**, because they would be indexed against a file
that no longer exists. `docs/data_manifest.json` would have caught it on the next `--check`, but
only after a confusing day of results that almost made sense.

**Now.** The script takes an explicit output path (the default is unchanged for HI-Small), and a
second dataset lives under its own paths file — see §3. **Before reporting any number after
touching preprocessing, run `python scripts/data_manifest.py --check` and require `data manifest
OK`.** Checking the file *size* is not sufficient; a re-keyed file of the same length is exactly
the failure mode. (2026-09-27)

### 2. Feature look-ahead hides in features that look local

`temporal_cycle` did a forward BFS over *all later edges of the whole dataset*, 5 hops, no upper
time bound. It read as a local motif count and inflated the detector by 12–16× lift over base rate.
Any feature computed from an adjacency built over the full dataset needs an explicit time bound and
a test that the graph cut at `t_e` changes nothing. See `docs/FEATURE_CAUSALITY.md`.

### 3. A second dataset must not share a paths file

`configs/paths.yaml` names `raw_dir`, `processed_dir`, `experiments_dir` and the account-bank map.
A second release run against it overwrites all four. Use `$RINGSHIELD_PATHS` to select a per-dataset
paths file (`configs/paths_li_small.yaml`), which every script inherits through `load_paths()`.

Related: `load_paths()` resolves **string** values against the repo root, so a non-path key added to
a paths file becomes a `Path`. `dataset: LI-Small` silently became
`E:\JSJ\Ring-Shield\LI-Small`. Non-path keys must be listed in `NON_PATH_KEYS`. (2026-09-27)

---

### 3b. Raw cross-currency sums reached the per-account roles, and everything downstream of them

AMLworld amounts carry a currency code. No single transaction is cross-currency, but **55.2 % of
test rings span more than one currency** (up to 8) and median amounts differ by **~140x** between
codes (7,918 for code 11 against 1,100,155 for code 6). `ringshield/roles.py` summed amounts
**across** currencies, so `closure = min(in, out) / max(in, out)` compared mismatched units
wherever an account's inflow and outflow currencies differed.

**What it reached.** Every consumer of the per-account roles:

* the **typing head's role-count features** (`ringshield/typing/features.py`),
* the **XAI layer's account roles** (`explainability/` calls `account_roles` as authoritative),
* the **expansion policy's conservation feature group** (`closure_before`, `closure_after`,
  `delta_closure`),
* the rings contract's `source_accounts` / `sink_accounts` / `mule_accounts`.

**On both v2 and v3.** The HI-Medium work on `jsj-v3` uses the same `roles.py`, so its
`R3_expansion` runs and anything derived from them carry the same raw-sum convention. A v3 run that
adopts schema v2 gets the corrected fields; one that does not should pin the raw convention
explicitly rather than leave it implicit.

**What it did NOT reach.** The ring-level `conservation_closure` in the contract is essentially
unaffected — median absolute difference **0.0000**, and only **2 of 102** rings differ by more than
0.1 — because it sums inflow at *sinks* and outflow at *sources*, which are one-sided by definition.
`confidence`, which multiplies by that closure, is likewise unaffected. The initial framing of this
defect as "closure is broken for half its inputs" was wrong and is corrected here.

**Scale of the role effect**, 4,280 ring-accounts over 5 shipped `full` seeds: **575 (13.4 %)**
change role under currency partitioning, of which **571 become `undetermined`** and only **4** are
genuine reclassifications. Per ring, `n_roles_changed_ccy` is median 0, max 15, and 317 of 560
ring-instances are unaffected.

**The trap inside the fix.** Partitioned flows cannot show that an account with disjoint in/out
currencies is *not* a mule — only that same-currency evidence does not support the label. An
implementation that lets a NaN closure fall through `role_of` lands those accounts on `peripheral`,
which asserts an imbalance the evidence does not establish. The first version of this fix did
exactly that and reported "257 accounts are not mules"; the correct statement is **"253 mule labels
are not supported by same-currency evidence; whether they are mules depends on the exchange rate"**.
Hence the sixth role, `undetermined`, and `undetermined_accounts_ccy` in schema v2.

**And the rate cannot be recovered from the data.** Of 393,544 unlabelled accounts with exactly one
currency on each side, **99.99 % use the same currency on both** — only 50 are cross-currency
pass-throughs and just 1 has >= 3 edges per side. There is no background population to estimate an
FX rate from (`results/tables/fx_stability.json`), so an `undetermined` account stays undetermined.
(2026-10-11)

## Evaluation correctness

### 4. `restrict_rings` drops predictions, so its indices are not the caller's indices

`ringshield.evaluate.restrict_rings` removes predictions with no member edge inside the evaluation
window — 108 → 94 on a typical seed. `evaluation/unmatched_rings.py::classify` built its
`touch` list over the **full** ring list and then indexed the **restricted** list with those
positions, reading a different prediction than the ring it was classifying.

It did not affect `matched`, `a_lt3_members` or `b_untouched` (computed without that lookup), but it
corrupted the over-merged / under-covered split, which had been published: "9.6 → 14.4 over-merged,
2.4 → 0.4 under-covered" was really "5.2 → 8.2 and 6.8 → 6.6", reversing the claim that
under-coverage nearly vanishes. Regression test:
`tests/test_partition.py::test_classify_maps_restricted_prediction_indices`. (2026-09-27)

### 5. Never read a result off one seed, or one batch

Two claims in Step 10 had to be retracted for this. MEGA-GNN's paper comparison was judged on seed
1 (64.35, the worst of five) and declared outside the ±5-point band; over five seeds it is
68.93 ± 3.96 and inside. Separately, a parallel-edge diagnostic read the first batch of the
earliest 200k train edges — the opening of day 0, where no history exists by construction — and
reported 1.5 % parallel edges; across the epoch it is 85.3 %.

**Rule.** A number from a single seed, a single batch, or the first/last slice of a time-ordered
split is a smoke test, not a result.

### 6. Derived quantities: verify the decomposition, do not infer it

B11's "about a third of newly reached rings convert" came from the *net* matched delta
(80.2 → 83.6), which nets off an opposite movement — MEGA loses ~3.0 matches among rings below
`min_size`, which the class counts hide because a matched small ring is never counted as
below-`min_size`. The real conversion is 6.4 of 9.2, **70 %**. Compute the full partition and check
it sums, rather than subtracting two totals. (2026-09-26)

### 7. The paired significance test is blind to precision

The project's standard test is a paired sign-flip permutation on per-ring **matched indicators**. A
method that produces far more rings and matches about as many tests as indistinguishable:
GFP-XGBoost's full pipeline is 13.9 ring-F1 points below ours at `p_holm` 0.807. Precision-side
differences come from the CIs on ring precision, ring-F1 and added-member precision. See
`docs/FINDINGS.md` section B's standing caveat.

### 8. Overlapping confidence intervals are not a test

Compare two methods with a **paired** bootstrap on the difference, resampling the shared unit
(truth rings) and averaging seeds inside each resample. Two intervals that overlap can still have a
difference interval excluding zero, and vice versa.

---

## Data alignment and identity (from the roadmap's running list)

### 13. `edge_id` is only meaningful against the hashed `formatted_transactions.csv`

If the manifest hash changes, every score and embedding file is stale — see §1 for the way this
nearly happened. `python scripts/data_manifest.py --check` is the gate.

### 14. The 10-second timestamp offset between the legacy CSV basis and the loader basis

It cost one ring (346) in the old E7 count. Dead since Step 3b: `models/score.py` writes the loader
basis directly. Any script that still reads a CSV-basis time must **fail loudly**, not silently
convert.

### 15. Align by `edge_id`, never by position

GFP features are keyed by `edge_id`; anything reading them positionally is a bug. Window batching
also changes the order in which edges are scored, so every consumer re-aligns by id — `evaluate()`
and `_align_to_inds` already do. A positional join will look correct and be wrong.

### 16. Deduplicate amounts before any sum

Duplicate payments in the synthetic data give **3,455 matched rows for 3,209 pattern lines** (a
107.7 % match rate). Any per-ring amount total must deduplicate first, or it double-counts.

### 17. `rebuild_account_map` is a 5M-row `iterrows` loop (~10 min; ~15 min on LI-Small's 6.9M)

Build from `account_bank.parquet` where possible and keep the equality test. Budget for it when it
is unavoidable — it is the slow step in a fresh dataset's loader run, and it looks like a hang.

### 18. Windows multiprocessing: share large structures via initializer globals

Otherwise every task pickles the adjacency, and the parallel version is slower than the serial one.

---

## Expected behaviour that is not a bug

### 19. Validation under-flags relative to test, and that is not to be "fixed"

The validation split's illicit ratio is **0.11 %** against test's **0.19 %**, so validation-chosen
thresholds under-flag on test. This is a property of the day split, it is expected, and correcting
it by looking at test would be tuning on test. Report it; do not repair it.

## Environment and imports

### 8b. A test that skips is not a test that passes — and a duplicated config loader is a silent isolation failure

After adding per-dataset paths, the suite reported **133 passed → 115 passed, 18 skipped**. The
totals matched, the run was green, and the skip reason ("dry-run inputs not on disk") looked like a
missing artefact rather than a defect.

It was neither. `contract/make_scored_edges.py` carried a **second copy of `load_paths`**, imported
by ten modules — `evaluation/step9_tables.py`, `unmatched_rings.py`, `r9_robustness.py`,
`csgm_baseline.py`, `typing_eval.py`, `quiet_precision_figure.py` and the contract builders and
tests. That copy resolved every string value against the repo root, so a newly added non-path key
became a `Path` and the input checks failed.

The skip was the *visible* symptom. The invisible one was far worse: those ten modules — which
produce most of the project's reported tables — **did not honour `$RINGSHIELD_PATHS`**, so a second
dataset's run would have silently read the first dataset's paths and produced a cross-contaminated
result that looked entirely plausible.

**Two rules.** Investigate a change in the *skip* count with the same seriousness as a failure; a
suite that goes green-with-skips has told you something. And a configuration loader must have
exactly one definition — a second copy does not drift loudly, it drifts silently. (2026-09-27)

### 9. `ringshield/typing/` shadows the standard library

Running a module *as a script* from inside the package (`python ringshield/run_rings.py`) puts
`ringshield/` on `sys.path[0]`, where `typing/` shadows stdlib `typing` and numpy fails to import
with `cannot import name 'Any'`. Always invoke as a module: `python -m ringshield.run_rings`.

### 10. Third-party top-level modules can shadow ours

`third_party/mega_gnn/models.py` collides with our `models/` package. Because `models/` is a
*namespace* package (no `__init__.py`), a regular module of the same name found later on
`sys.path` **wins**. Their directories go at the END of `sys.path`, and their model module is loaded
from its file and registered under a temporary name — see `models/mega_adapter.py::upstream`.

### 11. Write patch scripts with the Write tool, not shell heredocs

Non-ASCII (—, ±, →) and nested quotes in heredocs corrupt silently on this Windows/Git-Bash setup.
Every doc edit in this project goes through a Python file written with the Write tool and run with
`PYTHONIOENCODING=utf-8`, then verified with an explicit `U+FFFD` check.

### 12. A background command piped to `tail` shows nothing until it exits

`cmd | tail -50 &` buffers the whole pipeline. Redirect to a log file and `tail` the file instead,
and pass `-u` to Python for unbuffered output.
