# External analyst study for L4: protocol (DRAFT)

**Status:** draft, written 2026-11-12 (deep-analysis #14). This file goes with
`review/analysis_plan.md`. Items marked **TODO** need a person or a code change before the first
session.

## 1. Roles

| Role | Who | Sees ground truth? |
|---|---|---|
| Study owner | the project lead | yes, after scoring only |
| Facilitator | one team member, **not** the narrative author | no |
| Scorer | one team member, ideally not the facilitator | yes, after every sheet is in |
| Reviewers | ≥ 3, target 6, outside the team | never during the study |

## 2. Recruiting reviewers (TODO: people)

- **Who qualifies:** someone who has done transaction-monitoring, AML or fraud investigation work,
  or a graduate student or researcher in financial crime analytics. Record years of experience and
  background in a short intake form. This is reported in aggregate only.
- **Excluded:** anyone who has worked on this repository, seen the internal review packets, or read
  `docs/` about L4.
- **Commitment:** one remote session of about 2 hours (40 cases at about 2–3 minutes each, plus
  briefing and debrief), or two sessions of 1 hour.
- **Compensation and ethics:** follow the host institution's rules. If the institution requires
  ethics or IRB review for a study with human participants, get it **before** recruiting.
  **TODO:** check with the institution.

## 3. Materials to produce (code and data steps, no GPU)

1. **Case sample.** A new script, `explainability/review/sample_external.py`, implementing
   `analysis_plan.md` §3–4. It reuses `sample.py`'s exclusion and stratification code.
   - Writes: `results/xai/review_external/manifest.json` (rule, seed, counts, generator commit,
     per-file hashes), `case_key.parquet` (git-ignored: case id → ring id, T/F, true pattern,
     correct member set, condition per group), and per-reviewer packets.
2. **Two renderings per case**, through the same renderer as the dashboard.
   - N: the narrative, evidence and roles.
   - E: evidence and roles only.
   - A test asserts the E rendering contains no word from the narrative's shape vocabulary and no
     probability.
3. **Study tenant.** Load the 40 cases into a separate platform tenant, `study-l4-ext`, with one
   analyst account per reviewer (pseudonymous: `ext-01` … `ext-06`). Hide ring ids, seeds and
   match scores in that tenant. **TODO:** check that the dashboard can hide the narrative per case
   per user, or serve two case lists, one per group.
4. **Case-opened timing.** **TODO (code):** add an audit event `case_opened(ring_id, user_id, ts)`
   when a reviewer opens a ring, so time = verdict `created_at` − first `case_opened`. If this is
   not ready, the facilitator records start and stop times on a sheet. The analysis plan fixes
   which one before the first session.
5. **Answer sheet** (`answer_sheet_template.csv`) for the fields the verdict form lacks: shape,
   confidence, and misleading.

## 4. Pilot (before any counted session)

- One pilot with a person who is **not** a reviewer, using 4 cases **not** in the sample.
- Checks: instructions understood, timing captured, E rendering leaks nothing, the session fits the
  time.
- Pilot data are not analysed. Any change to materials after the pilot is made before the plan is
  committed. If the plan is already committed, it is a dated amendment.

## 5. Session script

1. **Consent and briefing (10 min).** Read `reviewer_instructions.md` with the reviewer. Say that
   the data are synthetic, and that some cases are not laundering. Do not give the share. Do not
   say which cases have narratives "for a reason". Say only that the presentation varies.
2. **Two practice cases** from outside the sample, one N and one E. They are not scored.
3. **40 cases** in the reviewer's own order. Reviewers may take a break after any case. The
   facilitator does not answer questions about a specific case, only about the interface.
4. **Debrief (10 min, recorded as notes).**
   - Did the cases look like real alerts?
   - Did the narrative help, mislead, or not get read?
   - Was anything unclear?
   - Nothing in the debrief changes a recorded verdict.

## 6. Data handling

- Verdicts live in the study tenant's database and are exported to
  `results/xai/review_external/verdicts.csv` with reviewer ids pseudonymous. Answer sheets go to
  `answers_ext-XX.csv`.
- No reviewer name, email or employer goes into the repository. The id-to-name mapping stays with
  the study owner, outside the repository.
- `case_key.parquet` is git-ignored until scoring is complete. Its sha256 is recorded in the
  manifest before the first session, so it is fixed.

## 7. Scoring and reporting

1. Run the scorer: a new `explainability/review/aggregate_external.py`, implementing
   `analysis_plan.md` §6–7. It reuses `fleiss_kappa`.
2. Write `results/xai/review_external/summary.json` and a report section in `docs/` with:
   - every endpoint and its CI;
   - the reviewer intake (aggregate);
   - the debrief themes;
   - the limits listed in plan §10.
3. Add a dated note to FINDINGS (L4) and to `deep-analysis.md` §14. Update the R11 verdict counts
   with the non-simulated arm.

## 8. Timeline

| Step | Depends on |
|---|---|
| Ethics check, recruiting | the institution |
| `sample_external.py`, renderings, leak test | the code (about 1 day) |
| Study tenant, case-opened event | the platform (about 1 day) |
| Pilot | the materials |
| Commit the analysis plan (registration) | the pilot |
| Sessions | the reviewers' calendars |
| Scoring and report | all sessions |
