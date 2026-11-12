# V3.1 — ring observability vs window length on HI-Medium and HI-Large

Measurement only. Nothing is trained, no method is pre-registered, no parameter is chosen. **This
step decides data**: which release, which split, which test-window length, and what ring-recall
ceiling each implies.

Source: `evaluation/v3_observability.py`, `scripts/data_manifest.py --datasets`. Tables:
`results/tables/v3_day_profile_<dataset>.csv`, `v3_ring_spans.csv`, `v3_windows.csv`,
`v3_test_at_end.csv`, `v3_ceiling_decomposition.csv`, `v3_feasibility.csv`, `v3_splits.csv`,
`v3_observability.json`.

**The parser is checked before it is used.** The pattern reader here reproduces the shipped
HI-Small ground truth exactly — 370 rings, 3,209 transactions, per-ring min/max timestamps
identical to `amlworld_ring_ground_truth.parquet` — and the window scoper reproduces the three
documented HI-Small counts (primary 174 in scope / 114 with ≥ 3 members, val 157, whole 183). The
script asserts the first of these and refuses to run otherwise.

## 1. Files

Already present in `data/raw` — nothing was downloaded. Hashed into `docs/data_manifest.json`
under a new `datasets` key, recorded by `python scripts/data_manifest.py --datasets`. A plain
`--check` does **not** re-hash them, so the routine table audit stays cheap (`data manifest OK`
still passes in seconds); pass `--datasets` to verify them too.

| file | bytes | lines | sha256 |
|---|---|---|---|
| `HI-Medium_Trans.csv` | 3,031,783,420 | 31,898,239 | `3126afb8155e7c88…` |
| `HI-Medium_Patterns.txt` | 2,279,574 | 31,011 | `d612cd7ed6f7761c…` |
| `HI-Large_Trans.csv` | 17,052,760,651 | 179,702,230 | `d13635e297c64673…` |
| `HI-Large_Patterns.txt` | 13,807,473 | 187,337 | `bcf815a1931cfdce…` |

HI-Large was never held in memory. The day profile streams it with pyarrow at ~2.1 M rows/s
reading **two columns** (`Timestamp`, `Is Laundering`); the whole 17 GB pass takes about 90 s.
Steps 3 and 4 need no transaction file at all — ring membership, timing and span all come from
the pattern files, which are 2 MB and 14 MB.

## 2. The clean region

Criteria, from `docs/TEST_TAIL.md` and `FINDINGS` C8, applied identically to all three releases:

* **shutdown tail** — the maximal trailing run of days holding < 5 % of the median day's volume
  **and** more than 10× the median day's base rate;
* **warm-up** — leading days above 2× the median of the remaining **non-tail** days. (The tail
  must be removed first. Against a 400-edge day every ordinary day is a "warm-up".)

| dataset | days | rows | warm-up | shutdown tail | **clean region** | edges/day | base rate |
|---|---|---|---|---|---|---|---|
| HI-Small | 0–17 | 5,078,345 | [0] | 10–17 | **1–9** (9 d) | 440,257 | 0.1060 % |
| HI-Medium | 0–27 | 31,898,238 | [0] | 16–27 | **1–15** (15 d) | 1,828,351 | 0.1097 % |
| HI-Large | 0–164 | 179,702,229 | [0] | 97–164 | **1–96** (96 d) | 1,824,945 | 0.1143 % |

Both pathologies are the *same artefact* at three scales, and the numbers say so with almost
comic precision:

* **Warm-up ratio is 2.31× in all three** — day 0 against the interior median is
  1,114,921 / 482,650, 4,465,985 / 1,930,240 and 4,466,821 / 1,929,594.
* **The collapse is total and identical in character**: 208,325 → 396 (526×), 3,021,866 → 2,020
  (1,496×), 831,092 → 2,192 (379×), with the base rate jumping 0.21 % → 58.6 %, 0.08 % → 59.4 %,
  0.28 % → 61.1 %. The generator keeps injecting pattern transactions after the licit background
  stops. This is C1/C8 reproduced at generator level on two more releases.
* **HI-Large's clean region is not denser than HI-Medium's — it is longer.** 1.82 M vs 1.83 M
  edges per day. HI-Large is HI-Medium run for 96 days instead of 15.

One caveat for window placement on HI-Large: days 30, 60 and 90 are month-boundary spikes
(4.29 M, 5.38 M, 3.24 M against a 1.93 M interior median). A window containing day 60 carries
roughly three ordinary days of volume in one.

## 3. Pattern groups

Parsed exactly as `preprocessing/amlworld_loader.parse_patterns` does. Ring counts are close to
uniform across the eight pattern types in every release (HI-Large: 2,001–2,109 per type).

| dataset | rings | pattern transactions | median span | p90 span | max span |
|---|---|---|---|---|---|
| HI-Small | 370 | 3,209 | **74.7 h** | 110.2 h | 202.3 h |
| HI-Medium | 2,756 | 22,743 | **110.5 h** | 144.4 h | 304.7 h |
| HI-Large | 16,467 | 137,936 | **655.0 h** | 891.0 h | 1,690.9 h |

Median span in hours, by pattern:

| pattern | HI-Small | HI-Medium | HI-Large |
|---|---|---|---|
| BIPARTITE | 24.3 | 42.6 | 250.4 |
| RANDOM | 46.0 | 93.5 | 492.6 |
| CYCLE | 71.9 | 121.8 | 700.4 |
| STACK | 73.3 | 102.6 | 636.2 |
| FAN-OUT | 76.7 | 115.6 | 699.0 |
| FAN-IN | 84.9 | 119.2 | 691.4 |
| SCATTER-GATHER | 88.8 | 131.4 | 778.6 |
| GATHER-SCATTER | 150.8 | 227.4 | 1,338.3 |

**This is the finding that decides the dataset.** The generator stretches each pattern over the
run, so a ring on HI-Large lasts a median **27 days** against HI-Small's 3.1. A longer test window
on HI-Large does not buy more of a ring, because the ring grew with the window.

## 4. Observability by window length

`test_visible` scope throughout: a ring is in scope with ≥ 1 transaction in the window, and its
scored members are the accounts of its in-window transactions only. **Ceiling** = share of
in-scope rings with ≥ 3 visible members — **a reference level, not an upper bound; see the
correction in V3.2 below** — i.e. the share of rings reachable under
`min_size` 3.

Windows placed freely in the clean region, each length at two positions:

| dataset | window | position | days | in scope | ≥ 3 members | fully contained | **ceiling** |
|---|---|---|---|---|---|---|---|
| **HI-Small** | **2 d** | **SHIPPED primary** | **8–9** | **174** | **114** | **20** | **0.655** |
| HI-Small | 2 d | early | 1–2 | 99 | 65 | 16 | 0.657 |
| HI-Small | 7 d | early | 1–7 | 281 | 209 | 150 | 0.744 |
| HI-Small | 7 d | late | 3–9 | 337 | 238 | 153 | 0.706 |
| HI-Medium | 2 d | early | 1–2 | 439 | 242 | 50 | 0.551 |
| HI-Medium | 2 d | late | 14–15 | 976 | 601 | 74 | 0.616 |
| HI-Medium | 7 d | early | 1–7 | 1,316 | 917 | 559 | 0.697 |
| HI-Medium | 7 d | late | 9–15 | 1,873 | 1,322 | 575 | 0.706 |
| HI-Medium | 14 d | early | 1–14 | 2,530 | 1,815 | 1,696 | 0.717 |
| HI-Medium | 14 d | late | 2–15 | 2,676 | 1,935 | 1,715 | 0.723 |
| HI-Large | 2 d | early | 1–2 | 309 | 66 | 36 | 0.214 |
| HI-Large | 2 d | late | 95–96 | 2,055 | 603 | 56 | 0.293 |
| HI-Large | 7 d | late | 90–96 | 4,471 | 2,450 | 211 | 0.548 |
| HI-Large | 14 d | late | 83–96 | 6,208 | 3,989 | 505 | 0.643 |
| HI-Large | 21 d | early | 1–21 | 3,474 | 2,050 | 778 | 0.590 |
| HI-Large | 21 d | late | 76–96 | 7,567 | 5,066 | 935 | 0.669 |

Position stability: HI-Medium is stable (7 d: 0.697 vs 0.706; 14 d: 0.717 vs 0.723). HI-Small is
stable at 2 d (0.657 vs 0.655). **HI-Large is not** (2 d: 0.214 vs 0.293; 7 d: 0.387 vs 0.548) —
early windows sit while the ring population is still filling up, so only its late region is
representative.

### The curve that actually decides the split

A test window has to sit at the **end** of the clean region, because training days must precede
it. Selected rows (full curve in `v3_test_at_end.csv`):

| dataset | test days | window | in scope | ≥ 3 members | **ceiling** | **fully contained** | train+val days left |
|---|---|---|---|---|---|---|---|
| HI-Small | 2 | 8–9 | 174 | 114 | 0.655 | **11.5 %** | 7 |
| HI-Small | 7 | 3–9 | 337 | 238 | 0.706 | 45.4 % | 2 |
| HI-Small | 9 | 1–9 | 360 | 263 | 0.731 | 61.9 % | 0 |
| HI-Medium | 5 | 11–15 | 1,562 | 1,063 | 0.681 | 18.8 % | 10 |
| HI-Medium | 7 | 9–15 | 1,873 | 1,322 | 0.706 | 30.7 % | 8 |
| **HI-Medium** | **10** | **6–15** | **2,361** | **1,651** | **0.699** | **44.1 %** | **5** |
| HI-Medium | 12 | 4–15 | 2,569 | 1,839 | 0.716 | 53.0 % | 3 |
| HI-Medium | 15 | 1–15 | 2,704 | 1,948 | 0.720 | 69.0 % | 0 |
| HI-Large | 7 | 90–96 | 4,471 | 2,450 | 0.548 | 4.7 % | 89 |
| HI-Large | 14 | 83–96 | 6,208 | 3,989 | 0.643 | 8.1 % | 82 |
| HI-Large | 21 | 76–96 | 7,567 | 5,066 | 0.669 | 12.4 % | 75 |

### The ≥ 3-member share saturates at ~0.72 everywhere, and here is why

*(First written as a ceiling on ring recall; it is not one. Corrected 2026-09-30 (V3.2b), see
"V3.2 correction" below and FINDINGS B9: 0.72 is the share of rings `ring_recall_ge3` counts.)*

No window on any release pushes the ceiling past **0.72**. HI-Small reaches 0.731 using its entire
clean region; HI-Medium 0.720 using all of its. Decomposing the rings that fall below the bar,
over each dataset's whole clean region:

| dataset | in scope | below the 3-member bar | of those, **the whole ring has < 3 accounts** | median whole-ring accounts | median visible transactions |
|---|---|---|---|---|---|
| HI-Small | 360 | 97 (26.9 %) | 78 — **80.4 %** | 2 | 1 |
| HI-Medium | 2,704 | 756 (28.0 %) | 641 — **84.8 %** | 2 | 1 |
| HI-Large | 16,241 | 4,605 (28.4 %) | 3,906 — **84.8 %** | 2 | 1 |

**Roughly 28 % of every ring population is a two-account object with two transactions.** Those
rings are unmatchable under `min_size` 3 in any window, on any release — it is not a windowing
loss and no amount of data fixes it. The share is 26.9 / 28.0 / 28.4 % across three releases
spanning 36× in size, which makes it a generator property.

(A plausible alternative explanation — that the ~28 % are rings truncated by the shutdown tail —
was tested and is **wrong in the opposite direction**: rings ending in the tail clear the
3-member bar *more* often, 0.78–0.81 against 0.56–0.70 for rings ending inside the clean region,
because they are long rings with more accounts.)

So what a larger release buys is **not a higher ceiling**. It buys two other things: more
matchable rings (statistical power) and a far higher **containment** share — and containment is
the quantity that drives the whole class-(b) / B13 story, since a ring cut by the window boundary
is exactly the ring that arrives in disconnected pieces.

## 5. Feasibility

Cost basis, measured on HI-Small: **25 min** of GFP feature generation for all three splits
(5,078,345 edges, `PROGRESS` 3b-y) and **3.14 h per detector seed** (3,248,921 train edges, mean
255.0 s/epoch × 44.4 epochs, `training_summary.json`). Scaled **linearly in edge count**, which is
the optimistic direction for the GNN — neighbour sampling cost grows with degree, and degree grows
with volume on a roughly fixed account population — so these are lower bounds.

| split | train | val | test | train edges | in scope | ≥ 3 members | ceiling | contained | GFP | GNN h/seed | GNN h × 5 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 | 0–6 | 7–8 | 9–15 | 14,935,512 | 1,873 | 1,322 | 0.706 | 30.7 % | 2.6 h | 14.5 | 72.3 |
| **M2** | **0–3** | **4–5** | **6–15** | **9,146,808** | **2,361** | **1,651** | **0.699** | **44.1 %** | **2.6 h** | **8.9** | **44.3** |
| M3 | 0–1 | 2–3 | 4–15 | 7,487,243 | 2,569 | 1,839 | 0.716 | 53.0 % | 2.6 h | 7.2 | 36.2 |
| M1x (no warm-up in train) | 1–6 | 7–8 | 9–15 | 10,469,527 | 1,873 | 1,322 | 0.706 | 30.7 % | 2.3 h | 10.1 | 50.7 |
| L1 (HI-Large d55–96) | 55–82 | 83–89 | 90–96 | 51,178,235 | 4,471 | 2,450 | 0.548 | 4.7 % | 6.4 h | 49.5 | 247.7 |
| L2 (HI-Large d55–96) | 55–68 | 69–75 | 76–96 | 26,772,503 | 7,567 | 5,066 | 0.669 | 12.4 % | 6.4 h | 25.9 | 129.6 |

Day 0 is kept in **train** in M1–M3, excluded from evaluation — exactly what the shipped HI-Small
split does (train = days 0–5 there). M1x prices the alternative of dropping it.

## Recommendation

**Dataset: HI-Medium. Split: M2 — train days 0–3, val days 4–5, test days 6–15. Test window: 10
days. Implied ring-recall ceiling: 0.699.**

| | shipped HI-Small (primary, 2 d) | **recommended HI-Medium M2 (10 d)** |
|---|---|---|
| in-scope rings | 174 | **2,361** |
| matchable rings (≥ 3 members) | 114 | **1,651** — 14.5× |
| ceiling | 0.655 | **0.699** |
| **fully contained rings** | **11.5 %** | **44.1 %** — 3.8× |
| train edges | 3,248,921 | 9,146,808 |
| GNN cost, 5 seeds | 15.7 h | **44.3 h** |

Why this one:

* **Containment is the lever, and it moves 3.8×.** B13 put 81.5 % of the under-covered class in
  pieces with no in-window path, and `CLASS_B_COMPOSITION` found class (b) rings whose visible
  edges are a scatter of disjoint transactions. Both are consequences of scoring a ring against a
  2-day slice of a 3-day pattern. At 44.1 % containment most in-scope rings are present *as
  objects*, which is the precondition for any of the V3.0/V3.0b questions to be answerable rather
  than structurally foreclosed.
* **14.5× the matchable rings.** V3.0b's linking diagnostic failed partly in a regime of 295
  positive pairs; 1,651 matchable rings is the difference between "no signal" and "no signal, and
  we could have seen one".
* **The ceiling does not suffer.** 0.699 against the shipped 0.655, and the ~0.72 asymptote is a
  generator property nothing can beat.
* **It is affordable.** 44 h of GPU for 5 seeds and 2.6 h of GFP, against 15.7 h today.

**HI-Large is rejected**, and not on cost alone. It has the same edges per day as HI-Medium and 6×
longer rings, so at every affordable window its containment is **4.7–12.4 %** — *at or below the
shipped HI-Small setup* — while costing 2.9–5.6× the GPU time. Buying 96 days of data to measure
rings that take 27 days to complete reproduces the HI-Small pathology at greater expense. The one
thing HI-Large offers that nothing else does is 16,467 rings for a question that needs raw count
rather than containment; no such question is currently open.

**If more training data matters more than containment**, M1 (7-day test, 30.7 % contained, 14.9 M
train edges) is the fallback. **If containment matters most**, M3 reaches 53.0 % at the lowest
cost of all — but its training set is days 0–1, of which the warm-up day is 60 %, and that is a
real risk rather than a free win.

## Limitations

* Ring membership, timing and span come from the pattern files alone. That is exactly how the
  shipped HI-Small ground truth is built and it reproduces it bit-for-bit, but it assumes each
  pattern transaction also exists in the corresponding `_Trans.csv`. On HI-Small all 3,209 do;
  on HI-Medium and HI-Large this was **not** verified, because it needs the account map from a
  full pass over the transaction file. A ring whose transactions are missing from `_Trans.csv`
  would be counted here and be unreachable in practice.
* Cost projections are linear extrapolations from one machine's HI-Small runtimes, and linear is
  the optimistic direction for a GNN. Treat 44.3 h as a floor, not an estimate. No HI-Medium
  training run was made.
* The clean-region rule has two thresholds (2×, 5 % + 10×). They are stated, applied identically
  to all three releases, and each fires with three orders of magnitude of margin here — but they
  were not swept, and a release with a gentler shutdown could need different ones.
* `edges_per_active_minute` is flat at 1,440 active minutes for every body day, so it adds nothing
  beyond volume at day granularity. C8's "ten times day 1's per-minute density" is a finer-grained
  statement than this table can confirm or refute.
* Everything is the HI (high-illicit) family. The LI releases are present in `data/raw` and
  untouched.
* The base rate drifts upward across HI-Large's clean region (0.05 % on day 1 to 0.28 % on day
  96) as the ring population accumulates. Splits on HI-Large are therefore not stationary; this
  does not affect the recommendation, which rejects HI-Large.

---

# V3.2 — closing the gap and choosing the split

## Gap #1 closed: every HI-Medium pattern transaction exists

Source: `preprocessing/verify_patterns.py`, `results/tables/v3_pattern_match_*.json`.

Limitation 1 above said the ring counts in this document assume each pattern line is a real
transaction, and that this was unverified on HI-Medium. It is now verified, and it holds.

A pattern line and a transaction row are the **same 11 comma-separated fields in the same order**,
so the check runs on raw text and needs no account map — in particular none of
`rebuild_account_map`'s `iterrows` pass, which is O(rows) in Python and would take hours on
31.9 M rows. The transaction file is streamed in 64 MiB blocks and never held whole. Three key
levels are counted: **strict** (all 11 fields), **requested** (timestamp, both bank+account, both
amounts — V3.2's key), and **loose** (timestamp + both accounts, which is what
`amlworld_loader` actually merges on).

| | HI-Small (control) | **HI-Medium** |
|---|---|---|
| pattern transaction lines | 3,209 | **22,743** |
| transaction rows read | 5,078,345 | 31,898,238 |
| **strict** — keys unmatched | **0** | **0** |
| **requested** — keys unmatched | **0** | **0** |
| **loose** — keys unmatched | **0** | **0** |
| loose — keys matching > 1 row | 246 | 2,079 |
| loose — transaction rows flagged | **3,455** | **24,822** |

The HI-Small control reproduces the shipped pair exactly — **3,209 lines → 3,455 rows**
(`PROGRESS` Step 3a) — which is what licenses trusting the HI-Medium column. Nothing is
unmatched at any level on either release, so **every ring count in this document stands**.

The gap between 22,743 and 24,822 is the loader's key, not a data defect: 2,079 pattern keys have
a second transaction between the same accounts at the same minute with a *different amount*, and
`(from_id, to_id, Timestamp)` sweeps both in. That is the HI-Small behaviour (246 → +246 rows)
at scale, and it is a property of the loader worth knowing before the ground truth is built.

## Correction: "ceiling" is a reference level, not an upper bound

Found while assembling V3.2's reference numbers, and it changes how every "ceiling" in this
document should be read.

V3.1 §4 called the share of in-scope rings with ≥ 3 visible members "the largest ring recall any
method could reach under `min_size` 3". **That is wrong.** A truth ring with **2** visible members
can be matched: a 3-account prediction containing both scores Jaccard 2/3 = 0.667, over the 0.5
bar. Only a ring with a **single** visible member is structurally unmatchable (best case 1/3).

The evidence is already in the shipped tables. On HI-Small's primary window the `average` run has
ring recall 0.4609 (80.2 of 174 rings matched) while `ring_recall_ge3` is 0.6035 (68.8 of 114) —
so **11.4 matched rings per seed have fewer than 3 visible members**. A quantity that matched
rings routinely sit outside is not a bound on them.

The real structural bound, measured (`results/tables/v3_bound_ge2.csv`):

| window | in scope | ≥ 3 members (the "ceiling") | ≥ 2 members (**the bound**) | unmatchable (1 member) |
|---|---|---|---|---|
| HI-Small primary d8–9 | 174 | 114 — 0.655 | 172 — **0.989** | 2 |
| HI-Small clean d1–9 | 360 | 263 — 0.731 | 360 — **1.000** | 0 |
| HI-Medium C1 test d6–15 | 2,361 | 1,651 — 0.699 | 2,360 — **0.9996** | 1 |
| HI-Medium C1 val d4–5 | 773 | 480 — 0.621 | 773 — **1.000** | 0 |

**Almost nothing is structurally unmatchable — 0 to 2 rings per window.**

**And even that overstates it (refined 2026-09-30, V3.2b).** The "1-member rings cannot match"
argument assumed predictions always have ≥ 3 accounts. They do not: `min_size` constrains the
**unrestricted** prediction, while matching uses the **window-restricted** one, and 13 of 106
restricted predictions per seed fall below 3 members (minimum 1). A 1-member truth ring was in
fact matched at Jaccard 1.0 on seed 4. So there is **no `min_size`-derived bound on ring recall
at all**; 11.4 of the 80.2 matched rings per seed are below the 3-member bar. This retracts
`FINDINGS` B9 and corrects B7 — both now carry dated notes, as do
`docs/paper/evaluation_protocol.md` and `docs/RING_GROUND_TRUTH_DEFINITION.md` §6a.

So the ~0.72 figure is
not a ceiling on recall; it is the share of rings the project's `ring_recall_ge3` metric counts,
and it remains the right *comparator* across datasets because it is the denominator of a
statistic already reported on every shipped run.

What survives unchanged: the ≥ 3-member share is still ~0.70–0.72 on every release and window
(a generator property — 28 % of rings are two-account objects), the containment numbers, the
dataset comparison, and the split choice below, which is made on ≥ 3-member counts exactly as
specified. What does not survive is the word "ceiling" read as a bound. Every table keeps the
column name because it is the defined term used throughout, but it means *share with ≥ 3 visible
members* and nothing stronger.

## The split selection rule — fixed before the train/val counts were taken

**Written before counting.** The test-side numbers for all three candidates already exist in the
V3.1 table above (test-at-end, 8/9/10 days), so they are not new information. The **train and val
ring counts are**, and they are what this rule selects on; neither had been computed when this
section was written.

Candidates, as day ranges in HI-Medium's clean region (day 0 is the warm-up, kept in train and
excluded from evaluation):

| candidate | train | val | test | test length |
|---|---|---|---|---|
| **C1** | 0–3 | 4–5 | 6–15 | **10 d** |
| **C2** | 0–4 | 5–6 | 7–15 | **9 d** |
| **C3** | 0–5 | 6–7 | 8–15 | **8 d** |

Measured per candidate: train-visible rings with ≥ 3 visible members **after dropping day 0**,
val-visible rings with ≥ 3 visible members, primary-test matchable rings, and test containment.

**Selection: take the candidate with the longest test window that satisfies both**

1. train rings (day 0 dropped) **≥ 220**, and
2. val rings **≥ 157**.

**If none satisfies both, all three are reported and nothing is chosen.**

One inconsistency in the bars is recorded here rather than silently resolved. The two thresholds
are given as "HI-Small's counts", but HI-Small's val has **157 in-scope** rings and only **114**
with ≥ 3 visible members. So 157 read against a ≥ 3-member count is a *stricter* bar than
HI-Small itself meets. Both readings are reported below; if they disagree on the choice, nothing
is chosen and the disagreement is what gets reported.

## The counts, and the selection

Reference — HI-Small under its shipped split (train 0–5 / val 6–7 / test 8–17):

| block | in scope | ≥ 3 visible members | fully contained | ceiling |
|---|---|---|---|---|
| train, days 0–5 | **220** | 143 | 124 | 0.650 |
| train, days 1–5 (day 0 dropped) | 217 | 140 | 88 | 0.645 |
| val, days 6–7 | **157** | 114 | 13 | 0.726 |
| test primary, days 8–9 | 174 | 114 | 20 | 0.655 |

This settles the ambiguity flagged above: **220 and 157 are HI-Small's *in-scope* counts** — its
train block with day 0 included, and its val block. Its ≥ 3-member counts are 143 and 114.

HI-Medium candidates (`results/tables/v3_split_candidates.csv`):

| | train days | val days | test days | test length | **train ≥ 3, day 0 dropped** | train in scope, day 0 dropped | **val ≥ 3** | val in scope | test in scope | test ≥ 3 | test contained | test ceiling |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **C1** | 0–3 | 4–5 | 6–15 | **10 d** | **378** | 626 | **480** | 773 | 2,361 | 1,651 | 1,042 (**44.1 %**) | 0.699 |
| C2 | 0–4 | 5–6 | 7–15 | 9 d | 509 | 794 | 527 | 869 | 2,189 | 1,540 | 869 (39.7 %) | 0.704 |
| C3 | 0–5 | 6–7 | 8–15 | 8 d | 640 | 968 | 564 | 914 | 2,024 | 1,427 | 717 (35.4 %) | 0.705 |

Rule check — **all three candidates pass both bars, under both readings of the val bar**:

| | train ≥ 220? | val ≥ 157 on ≥ 3-member count? | val ≥ 157 on in-scope count? |
|---|---|---|---|
| C1 | ✓ 378 | ✓ 480 | ✓ 773 |
| C2 | ✓ 509 | ✓ 527 | ✓ 869 |
| C3 | ✓ 640 | ✓ 564 | ✓ 914 |

The two readings agree, so the ambiguity never bites and nothing has to be referred back.

### Selected: **C1 — train days 0–3, val days 4–5, test days 6–15**

The rule takes the longest test window among the passers, and that is C1's **10 days**. It is
also the candidate the V3.1 recommendation reached independently (split M2), by a different
argument — containment — which is worth noting only because the two did not have to agree.

What C1 costs against C3, and what it buys: the train block loses two days (378 vs 640 rings with
≥ 3 members, still **2.7×** HI-Small's day-0-dropped 140), and the test block gains **10.9 points
of containment** (44.1 % vs 35.4 %) and 224 matchable rings. The ceiling is flat across all three
(0.699–0.705), as V3.1 predicted it would be — the ~0.72 asymptote is a generator property, not
something a window choice moves.

Against the shipped HI-Small setup: **1,651 matchable test rings against 114** (14.5×) and
**44.1 % containment against 11.5 %** (3.8×).

## Preprocessing under isolation

Run with `RINGSHIELD_PATHS=configs/paths_hi_medium.yaml`, reusing the LI-Small isolation path
exactly: a separate `raw_dir`, `processed_dir` and `experiments_dir`, so no command can overwrite
an HI-Small artefact. `raw_dir` has to be separate because `amlworld_loader` reads a **fixed**
`formatted_transactions.csv` name out of it; the three HI-Medium raw files are **hardlinked**
into `data/raw_hi_medium/` rather than copied, so the 3.0 GB is not duplicated.

New files: `configs/paths_hi_medium.yaml`, `configs/eval_window_hi_medium.yaml` (primary = the
chosen test days 6–15, tail = 16–27, val = 4–5).

### Three `iterrows` loops had to be vectorised first

None of these is an optimisation; each is the difference between "runs" and "does not finish".
Every one is validated against a shipped HI-Small artefact, because a rewrite that silently
changes the numbering would corrupt the ground truth rather than fail loudly.

* **`scripts/format_kaggle_files.py`** walks the raw CSV row by row and builds a 31.9 M-element
  list of Python lists. Replaced by `scripts/format_kaggle_files_fast.py`, which reproduces the
  same first-appearance id numbering with Arrow dictionary encoding (the two account columns
  interleaved per row, so `from` is numbered before `to`, as the original does).
  **Validated by sha256**: run on HI-Small it reproduces the shipped `formatted_transactions.csv`
  **byte for byte** — `3b9678458eeece7e…`, the manifest value — with the same 515,088 accounts.
* **`amlworld_loader.rebuild_account_map`** does the same row-by-row walk purely to rebuild the
  account map for pattern matching. Vectorised the same way, with the old path kept behind
  `legacy=True`. **Validated against the shipped ground truth**: the HI-Medium-style vectorised
  map, run on HI-Small, reproduces `amlworld_ring_ground_truth.parquet` exactly — 370 rings,
  3,209 rows, identical `from_id`/`to_id`/`timestamp_int`.

* **`graph/motif_features.build_adjacency`** walks *all* 31.9 M edges row by row to build the
  temporal adjacency, then sorts each node's list of `(ts, other)` tuples. Replaced by a single
  `lexsort` keyed (node, ts, other), whose per-node slices are already in exactly that order.
  **Validated twice**: the two implementations produce byte-equal dicts on a 300,000-edge slice
  (227,783 out-nodes, 221,385 in-nodes, zero mismatches), and — the decisive check — regenerating
  HI-Small's GFP features end to end with the vectorised path reproduces the **shipped parquets
  value for value**, `amlworld_gfp_features_train.parquet` (3,248,921 × 11) and
  `_val.parquet` (965,524 × 11) both identical. The adjacency build itself went from ~14 minutes
  to **8.3 s**.

`preprocessing/amlworld_loader.py` also gained `--split-days I J`, because HI-Medium's split is
chosen by ring observability, not by edge proportion: the chosen days give **28.7 / 12.1 / 59.2 %**
of edges, and the automatic 60/20/20 day search would have picked something else.

### What was produced

| | edges | laundering | base rate | in-scope rings |
|---|---|---|---|---|
| train, days 0–3 | 9,146,808 | 5,309 | 0.06 % | 657 |
| val, days 4–5 | 3,857,689 | 3,904 | 0.10 % | 773 |
| test, days 6–27 | 18,893,741 | 26,017 | 0.14 % | 2,396 |
| **total** | **31,898,238** | 35,230 | 0.11 % | 2,756 |

2,077,023 accounts, 122,330 sending banks. Pattern match rate **24,822 / 22,743 = 109.1 %** —
which is not a defect but the loose `(from_id, to_id, Timestamp)` key predicted exactly by the
verification above, and the HI-Small behaviour (3,455 / 3,209 = 107.7 %) at scale.

**HI-Small is untouched.** `python scripts/data_manifest.py --check` still prints
`data manifest OK` after the whole run, and `data/processed/` and
`data/raw/formatted_transactions.csv` keep their original timestamps.

## Scope and ceiling on the chosen split

Computed through the real evaluation path — `load_ground_truth` on
`data/processed_hi_medium/amlworld_ring_ground_truth.parquet` with
`configs/eval_window_hi_medium.yaml` — and **independently reproducing** the pattern-file
measurements above (primary 2,361 / 1,651 / 1,042 from both paths).
Tables: `docs/ring_scope_hi_medium.json`, `results/tables/v3_himedium_scope.csv`.

| window | days | in scope | ≥ 3 members | ≥ 2 (bound) | < 3 | share ≥ 3 | fully contained | median members |
|---|---|---|---|---|---|---|---|---|
| val | 4–5 | 773 | 480 | 773 | 293 | 0.621 | 62 (8.0 %) | 3 |
| **primary** | **6–15** | **2,361** | **1,651** | 2,360 | 710 | **0.699** | **1,042 (44.1 %)** | 5 |
| tail | 16–27 | 738 | 551 | 734 | 187 | 0.747 | 35 (4.7 %) | 5 |
| whole | 6–27 | 2,396 | 1,773 | 2,395 | 623 | 0.740 | 1,771 (73.9 %) | 6 |

Rings below the 3-member bar on the primary window, by pattern:

| pattern | rings | < 3 members | share ≥ 3 |
|---|---|---|---|
| GATHER-SCATTER | 297 | 61 | 0.795 |
| FAN-IN | 297 | 76 | 0.744 |
| SCATTER-GATHER | 302 | 80 | 0.735 |
| STACK | 288 | 77 | 0.733 |
| FAN-OUT | 296 | 96 | 0.676 |
| RANDOM | 280 | 94 | 0.664 |
| CYCLE | 330 | 122 | 0.630 |
| BIPARTITE | 271 | 104 | 0.616 |

Split-level scope (`docs/ring_scope_hi_medium.json`, split boundaries not eval windows): test
`test_visible` 2,396 (< 3: 623), `strict` 1,771, `majority` 2,049, straddling 625; val
`test_visible` 773 (< 3: 293), straddling 711. Cross-bank rings 2,748/2,756 = 99.7 %. Ceiling
inputs: 26,017 test laundering transactions, 18,039 of them in in-scope rings, and
377/20,815 = 1.8 % of in-scope-ring members have no test-period transaction.

**Tail check — the test window ends before the collapse.** Day 15 carries 3,021,866 edges at a
0.0800 % base rate; day 16 carries **2,020** at **59.36 %**. The primary window stops at day 15,
one day short of the cliff, and the tail is reported separately and never merged in.

## Status and cost, honestly

Complete: pattern verification, split selection, formatting, account-bank map, loader, ring
ground truth, ring scope and ceiling tables, both config files, and the three vectorisations with
their validations.

**GFP feature generation was blocked, and V3.2b fixed it.** The blocker is recorded because it
will hit anyone running this pipeline on a release above HI-Small's size.

`compute_features_parallel` handed the adjacency to each worker through `Pool(initargs=…)`. On
Windows that is `spawn`, so **every worker got its own pickled copy** of a dict of per-node lists
of `(ts, other)` tuples — for HI-Medium, 63.8 M Python tuples over 2.08 M nodes, **~8.5 GB per
worker**. Measured twice before the rewrite:

| workers | what happened |
|---|---|
| 36 (all cores) | RAM 87 GB, **CPU 2 %**, no split finished in 47 min — stuck in worker spawn |
| 12 | RAM climbed **+8.5 GB per worker** (50 → 67 → 84 → 102 GB), **CPU 0 %** throughout |

### The CSR rewrite (V3.2b)

The adjacency is now stored as CSR: per direction an `indptr` offset array plus flat `ts` and
counterparty arrays, grouped by node and sorted within a node by `(ts, counterparty)` — the same
order `list.sort()` gave the dict form. They are written once as `.npy` beside the split, and
**workers receive only the file paths** and open them with `np.load(..., mmap_mode="r")`, so the
OS page cache holds **one** physical copy that every worker shares. Nothing large is pickled.

Every feature definition is unchanged, including the trailing `closes_cycle` backward BFS with
its 5-hop and 14-day bounds. One implementation of each kernel serves both modes (the legacy dict
path is kept behind `--legacy-adjacency` and is what `tests/test_gfp_causality.py` drives), so
the two cannot drift.

**Validation, in three steps:**

1. Dict and CSR modes produce **identical** values for all ten features on a dense synthetic
   graph (4,000 edges, 300 nodes, 1,794 cycle positives).
2. `tests/test_gfp_causality.py` — **3 passed**, unchanged.
3. HI-Small regenerated end to end and compared with the shipped parquets: **train
   (3,248,921 × 11), val (965,524 × 11) and test (863,900 × 11) all value-identical**, at both
   12 and 36 workers.

**HI-Small cost** (`--data-dir data/processed`, shipped parameters):

| workers | wall | peak RSS | output |
|---|---|---|---|
| 12 | **283.5 s** | **5.4 GB** | identical |
| 36 | **222.3 s** | **11.5 GB** | identical |

Adjacency: 515,088 nodes, 5,078,345 edges, **0.17 GB** on disk, built in 3.9 s (the dict build
took ~14 min before the earlier V3.2 vectorisation, and ~8 s after it). Peak RSS is measured by
summing per-process RSS every 2 s, which **double-counts shared memory-mapped pages**, so it is
an upper bound — the OS-level figure is lower.

**HI-Medium** (36 workers), complete:

| | rows | wall | rate |
|---|---|---|---|
| CSR adjacency | 2,077,023 nodes / 31,898,238 edges, **1.05 GB** on disk | **33.3 s** | — |
| train | 9,146,808 | 687.8 s | 13,299 txn/s |
| val | 3,857,689 | 939.0 s | 4,108 txn/s |
| test | 18,893,741 | 9,379.7 s | 2,014 txn/s |
| **total** | **31,898,238** | **11,057 s (3 h 04)** | **peak RSS 55.2 GB** |

All three parquets have the expected row counts, 11 columns, **zero nulls**, `EdgeID` aligned
row-for-row with their split parquet, and the shipped GFP metadata (`window_s` 86400,
`max_cycle_hops` 5, `cycle_lookback_days` 14, `trailing` true). Hashes are in
`docs/data_manifest.json`; `scripts/data_manifest.py --check` still prints `data manifest OK`
for HI-Small.

Throughput falls across the splits — 13,299 → 4,108 → 2,014 txn/s — because the 14-day
`closes_cycle` lookback covers an ever-denser accumulated graph as the window advances. Within
the test split the rate recovers at the end (the day 16–27 tail holds only 6,987 edges, `v3_day_profile_HI-Medium.csv`; corrected from 8,047 on 2026-11-12), which is
why the running ETA swung between 30 h and 3 min; the honest figure is the 9,379.7 s total. The
55.2 GB peak is the sum of per-process RSS sampled every 2 s and **double-counts shared
memory-mapped pages**; the OS-level total observed during the run was **32 GB**, against 102 GB
and 0 % CPU for the old path at a third of the workers.

## V3.3 — three pipeline fixes made before the detector run

### 1. `--split-days` had to reach the trainer, and the scorer

`models/tgn.py::load_data` ran its **own** 60/20/20 day search, independent of the boundaries
`preprocessing/amlworld_loader.py` used to write the split parquets. On HI-Small the two agree
(same rule, same data); on HI-Medium the search picks **train [0,9) val [9,13) test [13,28)**
against the chosen **[0,4) / [4,6) / [6,28)**. The first training attempt died in seconds on
`GFP rows missing for some EdgeIDs of the train split` — the GFP features are keyed by split, so
the reindex caught it. **Without GFP enabled it would have trained on one edge set, scored
against another, and produced plausible wrong numbers.**

`--split-days I J` is now on the trainer too (default `None` → the search, so HI-Small is
untouched), and three further holes are closed:

* the run's `config.yaml` now records `split_days`, and the **real** dataset and split
  description — it previously hardcoded `"AMLworld HI-Small"` and `"60/20/20 day-based"` for
  every run, including this one;
* `models/score.py::args_from_run_config` reads `split_days` back out, so `score.py` and
  `ringshield/expand/cross_score.py` (which shares it) rebuild the split the model trained on
  rather than re-running the search;
* `tests/test_split_days_roundtrip.py` asserts the contract directly — **the edge ids
  `load_data` assigns to a split equal the `EdgeID`s of `amlworld_<split>.parquet`** — for
  train, val and test, plus the config round-trip and the pre-V3.3 "no key means search"
  default. **6 passed on HI-Small and 6 on HI-Medium**, and the test is not vacuous on
  HI-Medium: the search there disagrees with the parquets, which is the case it exists for.

`score.py` also gained `--batch-size`, an inference-only override for the 18.9 M-edge test
split; training already sits at 24.1 of 24.5 GB of VRAM.

### 2. Preprocessing cache for the ports / time-delta columns

`load_data` is called inside `run_single_seed`, so the 82-minute ports/time-delta build is paid
**per seed**. It is three pure-Python loops over up to 31.9 M edges and depends only on the data
and the split — never on the seed.

`--feature-cache DIR` stores the four columns as `.npy` with a key covering the source file's
**sha256**, the split boundaries, the node count, the ports/tds flags and the dry-run sampling,
so a stale or foreign cache cannot be read by mistake. A JSON sidecar records the key's inputs.

**Validated on HI-Small, three ways:**

| check | result |
|---|---|
| full pipeline, all three splits: final `edge_attr` computed vs read from cache | **identical** (train 3,248,921 × 9; val 4,214,445 × 9; test 5,078,345 × 9) |
| cache I/O byte level: written `.npy` vs `compute_ports_tds` output | **byte-identical** |
| model inputs on the full adaptation stack (HeteroData, GFP, ego) | **bit-identical**, and `tr/val/te_inds` identical |
| RNG state after `load_data`, cached vs not | **identical** (torch, numpy and python) |

Pass 1 (cold) 1,311 s, pass 2 (warm) 10 s — a **126× speedup**.

**The pre-registered "identical loss on one dry-run epoch" check could not be run as written,
because the baseline is not reproducible.** Two no-cache runs of the same configuration give
different losses (0.1450 and 0.1387): training is nondeterministic run to run. Measured over
one-epoch dry runs: no-cache *n* = 6, mean 0.1316, sd 0.0119, range [0.1117, 0.1450]; cached
*n* = 11, mean 0.1374, sd 0.0153, range [0.1120, 0.1661]; **Mann-Whitney p = 0.462**. (The first
five cached draws all landed above the no-cache mean and gave p = 0.052; widening the sample
removed it. The interim figure is recorded because it was seen before the larger sample, not
after.) Since the model inputs and the RNG state are bit-identical, there is no mechanism by
which the cache could shift the loss, and the input-identity check above is the stronger
substitute.

The cache is **off by default** and is enabled from **seed 2** onward, as instructed; seed 1 ran
without it and will have populated nothing.

## V3.2 — anything else, listed and not started

1. ~~**The GFP adjacency needs a CSR representation.**~~ **Done in V3.2b** — see above. The
   HI-Medium test split is still computing; nothing else is outstanding.
2. **HI-Large's pattern transactions are still unverified.** `preprocessing/verify_patterns.py`
   takes a `--dataset` argument and would settle it in one 17 GB pass, but HI-Large is rejected
   as a candidate, so it was not spent.
3. **The 109.1 % pattern match rate deserves a decision, not just a measurement.** 2,079 HI-Medium
   pattern keys (246 on HI-Small) have a second transaction between the same accounts in the same
   minute at a different amount, and the loader's `(from_id, to_id, Timestamp)` key labels both as
   ring edges. Whether that is wanted is a ground-truth convention question of the same kind as
   C9; V3.2 reproduces the HI-Small behaviour rather than changing it.
4. **`min_size` and the two-account rings.** 28 % of every ring population has two accounts, and
   the correction above shows two-member rings *are* matchable. Whether the protocol should keep
   a 3-account bar is now a quantified question on three releases, and any change has to be
   applied to the HI-Small re-analysis too.
5. **Seed budget on HI-Medium.** 0.1 % of 18.9 M test edges is 18,894 seeds against HI-Small's
   864. The budget is re-chosen on validation per the pre-registration, but nothing here has
   checked that 0.1 % is even the right *order* at this scale.
6. **A dry-run path for the isolated release.** `--dry-run` exists on the loader and
   `ring_scope.py` but was not exercised for HI-Medium; a 1 % smoke test would make the full
   pipeline cheap to re-verify after any change.
7. **The legacy `iterrows` paths are now dead weight** in three files, kept behind flags for
   comparison. They should be deleted once someone is satisfied the vectorised versions are the
   only ones anyone will run.
8. **LI-Medium as a prevalence control** — unchanged from V3.1.

## Anything else — listed, not started

1. **Verify pattern transactions against `_Trans.csv`** for HI-Medium, by rebuilding the account
   map in one streaming pass. This is the one gap that could change the ring counts above, and it
   should be closed before any split is built.
2. **Build the HI-Medium M2 split end to end** — loader, GFP features, ground truth — reusing
   `preprocessing/amlworld_loader.py` with `--dataset HI-Medium`. Step 11 already added the
   `--dataset` argument and an explicit output path for exactly this.
3. **Re-measure the V3.0 diagnostics on HI-Medium** once a detector exists: class (b) share, the
   B13 disconnection rate, and the part (a) oracle. The prediction implied by 44.1 % containment
   is that the disconnection rate falls sharply; that is a falsifiable claim and should be
   pre-registered before the split is built, not after.
4. **Decide `min_size`.** 28 % of every ring population has two accounts. Whether the protocol
   should report a 2-account bar alongside the 3-account one is an evaluation-convention question
   of the same kind as C9, and it is now quantified on three releases.
5. **LI-Medium as a prevalence control.** Same structure, ~10× lower base rate; the only way to
   separate "what the base rate does" from "what the pattern length does".
6. **Month-boundary spikes on HI-Large** (days 30, 60, 90) are unexplained and were only noted.

Nothing in this list is started. No commit.
