# Review of 30 explanations — summary

A structured check by the three team members (spec section 7), **not an analyst study**. Reviewer R1 also built the explanations. The rules for reading the answers were written and committed before two of the three sheets came back (`results/xai/review/analysis_plan.md`).

30 items, reviewers R1, R2, R3, four yes/no questions each.

## 1. Answers and agreement

| question | yes-rate | all three agree | Fleiss' κ |
|---|---|---|---|
| q1  the stated shape is plausible | 0.53 | 70% | 0.598 (moderate) |
| q2  the named accounts are the ones that matter | 0.91 | 97% | 0.863 (almost perfect) |
| q3  the evidence is enough to start an investigation | 1.00 | 100% | n/a (every answer the same) |
| q4  something in the sentence is misleading (1 = a problem) | 0.61 | 80% | 0.719 (substantial) |

Fleiss' κ is agreement beyond chance (Landis & Koch bands). Where every reviewer gave the same answer to every item, κ is undefined.

## 2. What triggered a fix (rules from the analysis plan)

- **q1-q3 within a feature** — q1_topology_plausible, feature `bank_list`: yes-rate 0.35; items R-03, R-07, R-08, R-09, R-10, R-11, R-13, R-14, R-16, R-19, R-22, R-29
- **q4 within a feature** — q4_misleading, feature `shape_sentence`: 6 of 17 items flagged; items R-02, R-04, R-06, R-12, R-25, R-30
- **q4 within a feature** — q4_misleading, feature `bank_list`: 13 of 16 items flagged; items R-03, R-07, R-08, R-09, R-10, R-11, R-13, R-14, R-16, R-19, R-22, R-27, R-29
- **q4 within a feature** — q4_misleading, feature `narrated_shape_correct`: 9 of 15 items flagged; items R-09, R-11, R-12, R-13, R-19, R-22, R-25, R-27, R-30

## 3. Breakdown by narrative feature

| feature | items | q1 yes | q2 yes | q3 yes | q4 yes (misleading) | q4 flagged |
|---|---|---|---|---|---|---|
| `bank_list` | 16 | 0.35 | 0.94 | 1.00 | 0.77 | 13 |
| `narrated_shape_correct` | 15 | 0.67 | 1.00 | 1.00 | 0.58 | 9 |
| `self_payment_top3` | 1 | 0.00 | 0.33 | 1.00 | 1.00 | 1 |
| `shape_sentence` | 17 | 0.78 | 0.90 | 1.00 | 0.37 | 6 |

## 4. Exploratory (not in the analysis plan): shape sentence × bank list

| shape sentence | bank list | items | flagged misleading (q4) | flagged implausible (q1) | narrated shape correct |
|---|---|---|---|---|---|
| no | yes | 13 | 13 | 12 | 6 |
| yes | no | 14 | 6 | 3 | 7 |
| yes | yes | 3 | 0 | 0 | 2 |

## 5. The reveal

- The narrated shape was the true pattern type for **50%** of the 30 items.
- Reviewers' "plausible" answer matched that (plausible when right, implausible when wrong) **63%** of the time; the majority answer **67%**.

| true type | items | narrated shape correct |
|---|---|---|
| BIPARTITE | 1 | 0% |
| CYCLE | 4 | 50% |
| FAN-IN | 4 | 25% |
| FAN-OUT | 4 | 75% |
| GATHER-SCATTER | 6 | 50% |
| RANDOM | 4 | 0% |
| SCATTER-GATHER | 6 | 83% |
| STACK | 1 | 100% |

Reviewer comments: 0.
