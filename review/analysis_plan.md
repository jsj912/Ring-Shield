# External analyst study for L4: analysis plan (DRAFT)

**Status:** draft, written 2026-11-12 (deep-analysis #14). This is **not registered yet**. It becomes
the registration when it is committed, before the first reviewer sees a case. After that, any
change is a dated amendment at the bottom of this file. Nothing below has been run.

## 1. Question

Does the L4 narrative change an outside analyst's **decision accuracy** or **time** on a suspected
ring, compared with the same evidence without the narrative?

This study is what the README's "a delivered capability, not a validated explanation" is waiting
for. The 30-ring review on `explainability-l4` was internal: three team members, and one of them
built the explanations. Every R11 verdict is simulated.

## 2. Design

- **Within-subject, two conditions, crossover.**
  - **N (narrative + evidence):** the revised narrative sentence, the top-5 evidence table and the
    account roles, exactly as the dashboard shows them.
  - **E (evidence only):** the same evidence table and account roles. The narrative sentence is
    removed, along with anything derived from it (stated shape, shape probability, money-conserved
    share, model signals).
- **Reviewers:** at least 3 from outside the team. The target is **6**, so the two counterbalancing
  orders are equally filled. None may have built, reviewed or read the L4 code, the narratives or
  the internal review.
- **Cases:** **40**, each a ring the shipped pipeline output on the HI-Small primary window. Every
  reviewer sees every case once. Half the cases are in N and half in E. Which half is which is set
  by reviewer group (§4), so across reviewers each case appears in both conditions.
- **Ground truth is hidden** from reviewers and from the session facilitator. Only the person who
  scores (§7) holds the answer key, and only after all sheets are in.

## 3. Case sample (fixed by rule, drawn once, seed 20261112)

The internal review showed only true rings, so "start an investigation" was 100 % yes and could not
measure accuracy. This sample includes rings that should be **rejected**.

| Stratum | n | Definition |
|---|---|---|
| T: true rings | 28 | `full` rings of detector seed 1 on the primary window, matched to a truth ring at Jaccard ≥ 0.5 (`test_visible`). One per truth ring. Stratified by true pattern as in `explainability/review/sample.py` (4 per type where available, the rest from the two most frequent types). |
| F: false rings | 12 | `full` rings of seed 1 on the primary window that match no truth ring at Jaccard > 0 (no member account is in any truth ring). Drawn uniformly, with size ≥ 3 enforced. |

**Excluded:** every truth ring in the Week 3 pilot file, and every truth ring in the internal
30-ring review (its packets were seen by team members who might brief reviewers).

**Fallback:** if fewer than 12 F rings exist, take all of them and top up T to 40. Record the
actual counts. The prevalence (T share) is **not** told to reviewers.

**Partial rings.** A T ring may carry extra or missing members (Jaccard 0.5–1). The case's
**correct member set** is the matched truth ring's accounts restricted to the ring shown. It is
recorded in the answer key and used only for the secondary partial-correction score.

## 4. Counterbalancing

- Cases are split once (seed 20261112, stratified by T/F and pattern) into halves H1 and H2.
- **Group A** reviewers see H1 in N and H2 in E. **Group B** reviewers see the reverse.
- Each reviewer's case order is shuffled individually (seed 20261112 + reviewer index), so N and E
  cases are interleaved, not blocked.
- Reviewers are assigned alternately to A and B in recruitment order.

## 5. What a reviewer records per case (the dashboard verdict form)

| Field | Values | Source |
|---|---|---|
| verdict | confirm / reject / partial | dashboard verdict form (`VerdictKind`) |
| corrected_members | account ids kept (partial only) | verdict form |
| shape | one of the 8 AMLworld pattern names, or "can't tell" | answer sheet (the form has no shape field) |
| confidence | 1–5 | answer sheet |
| misleading (N cases only) | 0/1: is anything in the sentence unsupported by the evidence shown? | answer sheet |
| time | seconds from the case opening to the verdict being submitted | dashboard timestamps (§8) |

Verdicts go into the study tenant with `simulated = false`. That is what gives R11 a
non-simulated arm.

## 6. Endpoints

**Primary (two, Holm-corrected at family-wise α = 0.05, two-sided):**
1. **Decision accuracy.** A verdict is correct when it is confirm or partial on a T case, or reject
   on an F case. Effect = accuracy(N) − accuracy(E).
2. **Time per case.** Effect = mean of log(seconds), N − E (reported back-transformed as a ratio).

**Secondary (reported with CIs, no correction, not used for any claim of effect):**
- shape accuracy (the stated shape equals the true pattern; "can't tell" counts as wrong);
- on F cases, the false-confirm rate (the error that matters most in practice);
- partial-correction quality on T cases: Jaccard between the kept members and the correct member
  set;
- confidence calibration: accuracy by confidence level;
- the share of N cases flagged misleading, by stratum;
- inter-reviewer agreement on verdict: Fleiss' κ per condition (`explainability/review/aggregate.py`'s
  `fleiss_kappa`).

## 7. Analysis

- **Primary model:** a mixed-effects logistic regression,
  `correct ~ condition + group + (1 | reviewer) + (1 | case)`. For time, the same structure as a
  linear model on log seconds. The condition coefficient is the effect.
- **With fewer than 6 reviewers**, random-effect variances are poorly estimated. Then the primary
  inference is a **case-clustered paired bootstrap** instead. The unit is the case, 10,000
  resamples, and the effect is the mean over reviewers of the per-reviewer N − E difference. The
  mixed model is reported beside it.
- This choice is fixed now by the number of reviewers who complete, not by the results.
- **Order and learning:** report accuracy by position tercile. Test the `condition × position`
  interaction as a check, not a gate.
- **Missing data:** a skipped case is missing, not wrong. If more than 10 % of a reviewer's cases
  are missing, that reviewer is excluded from the primary analysis and reported separately.
- **Outliers in time:** times over 20 minutes are winsorised at 20 minutes (the reviewer has left
  the case). The count is reported.
- **Scoring is blind to condition.** The scorer runs `aggregate` on sheets keyed by case id. The
  condition key is joined only after accuracy is computed.

## 8. Precision, stated before data

- With 6 reviewers × 40 cases, 120 verdicts fall in each arm. If baseline accuracy is around 0.8, a
  95 % CI on the N − E difference has a half-width of roughly ±0.08–0.10 once clustering is
  accounted for.
- With 3 reviewers it is roughly ±0.13.
- **An effect smaller than about 0.10 in accuracy cannot be distinguished from zero with this
  study.** A null result is reported as "no effect large enough to detect", never as "no effect".
- **Timing depends on the dashboard.** It needs the case-open time. Today the platform records
  verdict submission (`Verdict.created_at`, audit events) but not when a case was opened. **A
  case-opened audit event must be added before the study** (see `protocol.md` §6), or time is
  recorded on the answer sheet by the facilitator. Whichever is used is fixed before the first
  session.

## 9. Decisions this study can and cannot support

| Result | What may be written |
|---|---|
| Accuracy N > E (Holm p < 0.05, CI excludes 0) | L4 enters FINDINGS: "the narrative improved outside analysts' decision accuracy on synthetic rings by X [CI]." |
| Time N < E with accuracy not worse (CI lower bound > −0.10) | L4 enters FINDINGS as a time saving at no measurable accuracy cost. |
| Accuracy N < E (CI excludes 0) | L4 enters FINDINGS as **harmful** on this measure. The narrative is not shown by default until revised. |
| Neither primary resolved | L4 stays "a delivered capability, not a validated explanation", now with a measured interval. |

In every row, the claim is limited to **synthetic AMLworld rings, the HI-Small primary window and
these reviewers**. It is not a claim about real cases.

## 10. Known limits, stated now

- Synthetic rings may not look like real cases to practitioners. The briefing says so, and the
  debrief asks about it (protocol §7).
- Forty cases and three to six reviewers give wide intervals (§8).
- F rings are chosen as rings matching no truth ring. Some may be real laundering that AMLworld
  does not label. A confirm on an F case is scored as wrong; the scorer records how many F rings
  contain any illicit-labelled edge.
- The narrative generator is the revised one (the four wording fixes from the internal review). Its
  git commit is recorded in the packet manifest.

## Amendments

_None yet._
