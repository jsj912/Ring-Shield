# Chapter 6 System Testing

## 6.1 Overview

RingShield was tested at four levels, from single functions up to the whole system running on real
data. Every level ran on branch `jsj-testing1` (v2 with the platform `regen-api` and explanation
`explainability-l4` branches merged) on 24 October 2026.

| Level | What it checks | Tool | Result |
|---|---|---|---|
| Unit | functions in isolation, with fake databases and fake research CLIs | pytest, `platform/tests` (excluding `isolation/`) | 373 passed, 0 failed |
| Integration | the platform against a real PostgreSQL 16: migrations, row-level security, loaders, API | `scripts/test-db.ps1` (disposable Docker database) and GitHub Actions CI | 412 passed, 0 failed locally; CI green |
| End-to-end | rings → explanations → database → API → dashboard for one bank, by one command | `scripts/e2e_demo.ps1` | pass |
| Experiments | the platform's own experiments on real files: R10, R11, R12 | `evaluation/r10_registered.py`, `scripts/run-r11.ps1`, `experiments.r12_injected_shift` | R10 and R11 completed; R12 stopped at its positive control |

The research layer (ring recovery, scoring, typing, evaluation) has its own suite, `tests/`, which
passed 204 of 204 on the merged `final` branch. The explanation layer's suite
(`explainability/tests`) passed 192 tests; 86 failed because that branch still expects the old
22-column (v1) rings, and about 15 of those need generated files that are not in git.

**Environment.** Windows 11, Python 3.12 in three virtual environments (research, explanation,
platform), Docker Desktop on WSL 2 running PostgreSQL 16. Data: AMLworld HI-Small, detector seed 1
unless stated, evaluation on the primary window (test days 8–9).

**Approach.** Each experiment's design was written down and committed before it was run (R10 in
`docs/TENANT_SIZES.md`, R11 in `docs/R11.md`, R12 in `docs/R12.md`). A test that failed was traced to
its cause; a defect in the code was fixed with a regression test, and a limit of the data or the
design was reported as a result rather than worked around.

**Defects found.** Running the system for real found ten defects that the unit tests had missed,
because those tests used fake databases or fake research tools. All were fixed except one (the drift
monitor, 6.2 T-21), which is recorded as future work.

## 6.2 Test Cases

### Unit and integration

| ID | Objective | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| T-01 | Platform unit suite passes | `pytest platform/tests --ignore=platform/tests/isolation` | all pass | 373 passed | Pass |
| T-02 | Database suite passes on real PostgreSQL | `scripts/test-db.ps1` | all pass | 412 passed | Pass |
| T-03 | Two banks cannot read each other's rows | RLS isolation tests (22 run against PostgreSQL in CI) | cross-tenant query returns nothing | 0 rows across tenants | Pass |
| T-04 | Rings in the current (v2, 30-column) format load | load bank 12's v2 rings and explanations | loaded | refused as "v1" until fixed (D-1) | Pass after fix |
| T-05 | Simulator can record a verdict | simulated partial verdict on a real database | verdict saved | "permission denied for table verdicts" until fixed (D-3) | Pass after fix |
| T-06 | Wrong verdicts cannot get a worse model promoted | unit test: flipped verdicts make the candidate worse on the holdout | gate refuses | refused; honest verdicts promoted | Pass |
| T-07 | Test database builds on a restricted network | build the test image on the college network | image builds | plain-HTTP Debian downloads timed out (D-4) | Pass after fix |

### End-to-end

| ID | Objective | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| T-08 | Build a bank's rings from its visible edges | `build_tenant_rings.py --tenant-id 12` | 5 rings from 20,039 edges | 5 rings from 20,039 edges | Pass |
| T-09 | Explain every ring | `python -m explainability.tenant --bank 12` | all rings explained and reproduced | 5/5 explained, 5/5 reproduced | Pass |
| T-10 | One command runs the whole system | `scripts/e2e_demo.ps1 -Tenant 12` | API healthy, dashboard up | `/health` ok (database, file store); dashboard HTTP 200 | Pass |
| T-11 | Analyst sees a ring with its explanation | log in as bank 12 analyst, open a ring | accounts, transactions, L4 explanation, verdict form | all shown | Pass |
| T-12 | Dashboard starts unattended | start Streamlit in the background | dashboard up | blocked on Streamlit's first-run email prompt until fixed (D-5) | Pass after fix |

### Experiments

| ID | Objective | Steps | Expected | Actual | Status |
|---|---|---|---|---|---|
| T-13 | R10: ring recall a bank loses by seeing only its own edges | `evaluation/r10_registered.py`, 5 tenants, 5 seeds | table with 95 % CIs | tenant 0.088 [0.031, 0.161] vs pooled 0.359 [0.239, 0.500]; 172 of 174 rings span banks | Pass |
| T-14 | R11: tenant selection rule | most seed-1 tenant rings in days 8–9 among banks 1, 20, 11, 118, 12 | one bank chosen | bank 1 (7 rings) | Pass |
| T-15 | R11: verdicts recorded each cycle | 12 four-hour cycles, 100 % review | verdicts in the database | 6 on day 8, 1 on day 9 | Pass after fix (D-6) |
| T-16 | R11: retrain uses the verdicts | one retrain after cycle 6 | trains on day 8's verdicts | skipped with "0 new labels" until fixed (D-7) | Pass after fix |
| T-17 | R11: real trainer runs from the platform | `ringshield train` through the platform adapter | candidate model written | refused for missing inputs until fixed (D-8) | Pass after fix |
| T-18 | R11: platform reads what the model trained on | read `training_labels.rings` | ring ids read | rejected the trainer's records until fixed (D-9) | Pass after fix |
| T-19 | R11: gate decides on the frozen holdout | evaluate candidate vs base (0.6883), ε = 0.005 | promote or refuse with a reason | all four candidates refused (0.6612, 0.6556 at a = 0.90; 0.6531, 0.6639 at a = 0.70); base model kept | Pass |
| T-20 | R11 is reproducible | run a = 0.90 twice | same numbers | identical | Pass |
| T-21 | R12: drift monitor fires on a synthetic step | +3 SD step from hour 12 of day 9, 48 hourly steps | detected | not detected (D-10) | **Fail** — monitor broken; R12 stopped as registered |

### Defects found and fixed

| ID | Defect | Effect | Fix |
|---|---|---|---|
| D-1 | Ring-format check compared columns with the new list for both versions | every current ring file was refused | compare with the v1 and v2 column lists |
| D-2 | Demo runner required exactly 5 rings for every bank | only banks 12 and 20 could be loaded | apply the count to those two only |
| D-3 | Simulator had insert but not read permission on verdicts | simulated verdicts failed on a real database | migration 0010 grants read on the two returned columns |
| D-4 | Test image fetched Debian packages over plain HTTP | build failed on restricted networks | HTTPS sources, pip retries |
| D-5 | Streamlit waits for an email on first run | background dashboard never started | write an empty credentials file before start |
| D-6 | Verdicts saved the verb ("confirm") as the ring status | every confirm or reject failed, including the dashboard buttons | map to "confirmed" / "rejected" |
| D-7 | First retrain stamped the base model with the current time | no earlier verdict ever counted as new | use the base model file's time |
| D-8 | Platform called the trainer without its required inputs | every real retrain failed | pass scores, rings, features and embeddings |
| D-9 | Platform expected plain ring ids from the trainer | every real retrain failed | read the trainer's ring records |
| D-10 | Drift monitor checks only every 32 updates, and the calibrated p99 is flat | it cannot fire within the test period | **open** — future work F8 (`docs/FUTURE_IMPLEMENTATIONS.md`) |
