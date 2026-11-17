# RUNBOOK_PROGRESS

Runbook: paper/RUNBOOK_OPUS.md (sha256: 1307cedceb2a1a0a29f052eec3ce552a386f5dedbb68990be102e01e5670c7cc)   Repo HEAD at start: aeab2be6fd52cc763c7095954146de2e89c40c93
PREREG file: paper/PREREG_2026-11-14.md (sha256: 568a296fd095abe8b07849f0dcfb71abce095de2a8143a9c7bae3831372110a6, frozen at 2026-11-14T06:02:48Z)

## Status
| Task | Status | Started | Finished | Gate result | Notes |
|---|---|---|---|---|---|
| Phase 0 | DONE | 2026-11-14 | 2026-11-14 | PASS | 0.7 passed on the third run after author-approved env repairs 1–3; 0.12 LaTeX absent |
| PREREG amendment addendum A | DONE | 2026-11-14 | 2026-11-14T17:36:04Z | | ring-folded full; amendment file sha256 now 705e2cccd478a0c21c6333866a58d2c555cbafce4811d3acd6be1ae30c1a8fc1 |
| PREREG amendment | DONE | 2026-11-14 | 2026-11-14T14:19:31Z | frozen | paper/PREREG_AMENDMENT_2026-11-14.md sha256 4f10b6e26d5beffadea458a5166ec2f8bfd62649d1253173bc7faa16a7e396da |
| PREREG | DONE | 2026-11-14 | 2026-11-14T06:02:48Z | frozen | sha256 568a296f… |
| T-P6 related work | DONE | 2026-11-14 | 2026-11-14 | PASS | no prior claim; 0 scope rules stated; 1/17 partly inaccessible (Chai). See results/notes/p6_related_work.md |
| T-P1 scorer | DONE | 2026-11-14 | 2026-11-14 | PASS | 90 cells vs r14/v36, max abs dev 0.0; suite 273/44/1 |
| T-P7a GenAgg seed 1 | DONE | 2026-11-14T09:28:13Z | 2026-11-14T19:34:43Z | **PASS** (test edge F1 0.7558 ≥ 0.70) | trained at batch 4096 (stopped by watchdog during first test scoring, 24,048 MiB); test scored from the saved model at batch 2048 (deviation D-7a-1); gate_seed1.json |
| T-P2 ring-fold report | DONE | 2026-11-14 | 2026-11-14 | INCONCLUSIVE (amendment) | ring-F1 +0.0028 [−0.0137, +0.0211]; B17 not closed; precision follow-ups post hoc (deep-analysis §15) |
| T-P3 classical baselines | DONE | 2026-11-14 | 2026-11-14 | METHOD_SUPERIORITY=ON; bar A met narrowly; bar B not competitive | v40 bd63558b…; Leiden skipped (install refused); identity checks exact on 5 seeds |
| T-P4 HI-Medium audit | DONE | 2026-11-14 | 2026-11-14 | HM_AUDIT=NOT_REPRODUCED (scope size); observability within band; threshold reproduced | close-out reproduced byte-exact; HS cross-check 77/174, −0.3467; step 7 not done |
| T-P7b GenAgg seeds 2-5 | WAITING (author go-ahead) | | | | gate passed; author asked to be consulted before seeds 2-5 |
| CHECKPOINT A | DONE | 2026-11-14 | 2026-11-14 | author replied | paper/CHECKPOINT_A.md; suite 282/44/1 |
| T-P5 paper sync (pass 1) | DONE | 2026-11-14 | 2026-11-14 | static checks 0 problems; stale grep: one documented false positive (0.219 = a CI bound) | §6.1–6.3 applied; CLAIMS_CHECK dated section; figures deferred to pass 2; not compiled (no LaTeX toolchain; author compiles on Overleaf) |
| T-P7c GenAgg downstream | TODO | | | | |
| T-P8 budget sweep | RUNNING | | | | |
| T-P9 TAML | TODO | | | | |
| CHECKPOINT B | TODO | | | | |
| T-P5 paper update (pass 2) | TODO | | | | |
| T-P10 packaging | TODO | | | | |
| T-P11 anonymised snapshot | TODO | | | | |
| Final verification | TODO | | | | |

Status values: TODO / RUNNING / DONE / FAILED / BLOCKED.

## Phase 0 checks (PASS/FAIL, one line each)
- 0.1 PASS: branch integrate/main; HEAD aeab2be6 (= aeab2be). Untracked: experiments/R10_consortium/, experiments/R1_gine_causal_c10/, experiments/R3_ringfold/{cross_scores,expansion}/, experiments/R3_ringfold/runs/proposed/seed{1..5}/environment.txt, experiments_hi_medium/{closeout,closeout_smoke}/, paper/. Nothing deleted.
- 0.2 PASS: paper_draft/latex/* copied into paper/ (main.tex, sections/ 11, tables/ 14, figures/ 9); references.bib → refs.bib; `\bibliography{refs}`; README_LATEX.md; CLAIMS_CHECK.md, OPEN_QUESTIONS.md, REVIEW.md, ACTION_PLAN.md, make_figs.py copied (cp -n; RUNBOOK_OPUS.md untouched, sha unchanged). §6.6 static check: 26 files, 44 labels, 62 refs, 20 cites, 20 bib keys — all resolved, no uncited entry, environments and braces balanced.
- 0.3 PASS: torch 2.5.1+cu121, PyG 2.8.0.post1 (post-release of 2.8.0), CUDA True, NVIDIA RTX A5000.
- 0.4 PASS: `data manifest OK`.
- 0.5 PASS: ../RS-e2e/experiments has R1_gine_causal, R2_b0, R3_expansion, R4_partition, R6_mega, R6_full; ../RS-ccy-valrings/contract/out and experiments_valrings exist.
- 0.6 PASS: (a) tests/test_frozen.py 47 passed. (b) scores_test_seed1 bb4edddbdde63064…, embeddings_test_seed1 f32be717c132b7b3…, R4 average seed1 rings b3a981bc51931ba2… — identical in both roots. (c) rings_full_gine_causal_1.parquet sha256 9d1e0b9e692a…5328.
- 0.7 **FAIL**: 2 failed, 259 passed, 44 skipped, 1 xfailed (613.9 s). Previous record: 258 passed, 47 skipped, 1 xfailed.
  - tests/test_partition.py::test_cli_export_and_run_full — `export-model` reads `policy_json` from the frozen experiments/R4_partition/config.yaml, which holds an absolute path to the old checkout, `E:\JSJ\Ring-Shield\experiments\R3_expansion\policy_proposed\policy.json`; that file does not exist there.
  - tests/test_run_typing.py::test_the_head_is_recorded_in_version_json — `models/artifacts/full_gine_causal_seed1/version.json` is missing (the directory exists, git-ignored).
  - Both look environmental (artefacts missing or stale absolute paths), not code regressions; 3 tests that skipped before now run (47→44 skips), which matches that. Not fixed: config.yaml is frozen and the rule says STOP.
- 0.8 PASS: scripts/test-db.ps1 → 567 passed, 0 skipped, 1 warning; RLS tests executed against PostgreSQL = 22. (Previous: 563 passed, 2 skipped.) Deviation: the script is written for pwsh 7, which is not installed; under Windows PowerShell 5.1 an in-shell `*>` redirect turned docker's stderr into a terminating error. Re-run by launching powershell.exe from Git Bash with the redirect at process level; the script was not edited.
- 0.9 PASS: `traceable: 18 | mismatched: 0 | not checked: 0`.
- 0.10 PASS: B0 0.5213 (r9_ring_ci b0 primary 0.52132), proposed 0.5819 (0.58193), full 0.5894 (0.58945), MEGA B0 0.5208 (r6_detector_swap 0.52085), CSGM 0.1224 (r4_partition b5 / r9 0.12245).
- 0.11 PASS (with two flags): genagg/genagg dry run completed 1 train+val epoch, exit 0; 1078 s per epoch (data load 115 s); valF1 0.0000, valAP 0.0302 after epoch 1; 128,420 params; loader route = fallback (native rejected: pyg-lib too old for edge-level temporal sampling), window 1800 s. Peak VRAM, whole card via nvidia-smi: 24,173 MiB (23.6 GiB) — under 24 GiB but at the card's limit. Warning: NumPy non-writable-array UserWarning in third_party/mega_gnn/data_loading.py:25. `--dry-run` writes nothing (confirmed from source and output); experiments/_smoke_megagenagg was never created, so nothing to delete. Fallback variants not run. GenAgg caveat (adapter ~line 472): "GenAgg as published: MLPAutoencoder's inverse-objective forward hook never fires … the node-stage GenAgg is one instance shared by every GINE layer". **Flag for T-P7:** 1078 s/epoch is 4.5× MEGA's 238 s, beyond the T-P7 stop-and-ask threshold (> 2×); 80 epochs ≈ 24 h per seed.
- 0.12 ABSENT: no pdflatex, bibtex, latexmk or tectonic on PATH. The paper will be statically checked only; the author compiles on Overleaf.
- 0.13 PASS: arxiv.org/abs/2502.19952 readable ("Towards Collaborative Anti-Money Laundering Among Financial Institutions"; 7 authors Tian, Ding, Qu, Yu, Gong, Liu, Ren; WWW 2025; DOI 10.1145/3696410.3714576).

- 0.7 RE-RUN (after env repairs 1–2) **FAIL**: 1 failed, 260 passed, 44 skipped, 1 xfailed (611 s). test_run_typing now passes. test_partition::test_cli_export_and_run_full now fails on `E:\JSJ\Ring-Shield\experiments\R3_expansion\policy_proposed\policy.txt` (missing). export-model resolves the frozen R4 config's absolute policy_dir and affinity_dir; the old checkout also lacks `experiments\R4_partition\affinity\` (RS-react has affinity.json 86a3a4ae…, affinity.txt 61b53edd…; policy.txt a1768ee8…). Further copies not made: beyond the authorised repair. STOPPED.
- GenAgg probe (author decision 4): genagg/genagg, --batch-size 4096, --num-neighs 100 100, --epochs 1 --dry-run → 571 s/epoch, peak 20,675 MiB on the card (idle 387 MiB), valAP 0.1526, valF1 0.0000, loader fallback; nothing written. Both limits missed (571 > 500 s; 20,675 MiB = 20.2 GiB / 21.7 GB > 20 GB) → the "otherwise" branch applies: T-P7 = seed 1 only at 8192, background, 30 h cap, as the 0.70 gate; ask before seeds 2–5. To be written into the PREREG once 0.7 passes.

- 0.7 RE-RUN 2 **PASS**: 261 passed, 0 failed, 44 skipped, 1 xfailed (564.5 s), after env repair 3. The single test passed first on its own (15.8 s); the standing rule for further copies was not needed.

## Baselines recorded (test counts, audit rows)
- **Research suite no-regression baseline: 261 passed, 44 skipped, 1 xfailed, 0 failed.**
- Platform suite: 567 passed, 0 skipped, 22 RLS.
- audit_tables: 18 traceable, 0 mismatched.

## Task log (one subsection per task: commands, outputs, numbers, runtime)
### Phase 0
Commands as in runbook §2, run from /e/JSJ/RS-react with PY=.venv312/Scripts/python.exe, PYTHONIOENCODING=utf-8. Logs kept in the session scratchpad (pytest_baseline.log, platform_tests2.log, smoke_genagg.log, vram.log).

### T-P6 related work (2026-11-14) — PASS
Full texts read through arXiv HTML, publisher HTML, the in-app browser (AAAI abstract page), and local `pdftotext` on fetched PDFs (no packages installed). Outputs: paper/sections/related.tex (rewritten, four paragraphs + table), paper/tables/related_comparison.tex (new), paper/refs.bib (22 entries, all cited, no "and others"; weber2019 removed as uncited), paper/RELATED_WORK_AUDIT.md (new), results/notes/p6_related_work.md (new). §6.6 static check: STATIC OK (27 files, 22 cites, 22 keys); stale-phrase/code grep on the touched files: empty. Not compiled (no LaTeX toolchain).
Key facts: MEGA-GenAgg published HI-Small F1 = 74.48 ± 0.84 (not 74.88 ± 0.38); MEGA paper now two authors, TMLR 2026. Closest prior work to the edge-vs-group claim: Malik, arXiv 2604.23494 (Elliptic++ queues), not yet cited.

### T-P1 scorer (2026-11-14) — PASS
Modules reused (no rewrite): truth/scope `ringshield.truth.load_ground_truth`; pieces `evaluation.component_scope.component_truth` (uses `v3_diagnostics.edge_components`); window restriction `ringshield.evaluate.restrict_rings` via `ring_stats.ring_evidence`; matching `ring_metrics.match_rings`; metrics `ring_stats.metrics_from_evidence`; CI `scope_sensitivity.boot` (seed 0, the r14/v36 procedure); paired test `ring_stats.paired_unit_bootstrap`. Disagreement noted: r9/r4 CIs use `ring_stats.bootstrap_over_rings` (different RNG draw order) while r14/v36 use `scope_sensitivity.boot`, so the same point estimate carries slightly different intervals in the two table families (e.g. full 0.5894 [0.502, 0.675] in r9 vs [0.5234, 0.6529] in r14). The scorer follows r14/v36, as the T-P1 bar requires.
Commands: `$PY evaluation/score_external.py --rings experiments/R4_partition/runs/average/seed{1..5}/rings.parquet --out <scratch>/p1_full`; same with `../RS-e2e/experiments/R2_b0/gine_causal/seed{1..5}/rings.parquet --out <scratch>/p1_b0` (B0 rings are git-ignored and absent from experiments/ here). Comparison: 90 cells, max abs deviation 0.0 → results/notes/p1_reproduction_cells.csv. Outputs: evaluation/score_external.py, tests/test_score_external.py (12 passed), docs/PROTOCOL.md, results/notes/p1_scorer.md, results/notes/p1_reproduction_cells.csv. Research suite after: 273 passed, 44 skipped, 1 xfailed (baseline 261 + 12 new; skips unchanged).

### T-P7a step 3 — detector-swap table reproduction (2026-11-14) — reproduced; STOP on frozen-file incident
Command: scratchpad wrapper `r6_repro.py` imports `evaluation/r6_detector_swap.py` unmodified and repoints `DETECTORS[gine_causal|mega]` scores/runs to `../RS-e2e/experiments` (B0 rings and MEGA scores are absent from experiments/ here); `--detectors gine_causal mega --methods b0 full --labels-dir ../RS-e2e/contract/out --out <scratch>/r6_repro/r6_detector_swap.csv` (484 s). Result: the 4 Multi-GINe and MEGA rows equal `results/tables/r6_detector_swap.csv` on all 29 numeric columns (max abs dev 0.0) and on edge_f1_per_seed.
**Incident:** the builder writes `results/tables/r6_pvalues.csv` unconditionally (line 306: `TABLES / "r6_pvalues.csv"`), ignoring `--out`. With two detectors it wrote 2 of 4 rows and a different Holm p (0.6135 vs 0.8072). Detected at once from `git status`; restored with `git checkout -- results/tables/r6_pvalues.csv`; verified identical to HEAD (`git diff --quiet`), `git status --short results/tables/` empty, audit_tables 18/0, test_frozen 47 passed. No other file was written outside the scratchpad. Under runbook §0.4 rule 6 any touch of a frozen file is a STOP: training not launched.
Proposed fix for the T-P7c extension (needs approval): give r6_detector_swap.py a `--pvalues-out` argument defaulting to the current path, and always pass a new path (e.g. `results/tables/r6_pvalues_v2.csv`) from new runs.

### T-P2 ring-fold report (2026-11-14) — STOP, bar ill-defined
Step 1 reproduced (10/10 values to 4 dp). Grep before running: the new script writes only --out and its json. Run: `evaluation/ringfold_report.py --shipped-root ../RS-e2e/experiments --out <scratch>/p2/v39_ringfold_report.csv`, then copied (no overwrite) to results/tables/v39_ringfold_report.{csv,json} (a7b659fa…, 11442a20…). `git status results/ docs/` afterwards: no tracked file changed. Tests: tests/test_ringfold_report.py, 3 passed. Leak assertion 0 violations. Numbers and amendment proposal: results/notes/p2_ringfold.md. deep-analysis §8 and FINDINGS are not edited, pending the author.

## Background jobs (PID, log path, watch command, state)
- T-P3 CSGM bank seeds 0–4 → experiments/R13_baselines/csgm/seed1–5 (logs bank*.log); run with PYTHONPATH=E:\JSJ\Ring-Shield\external\Collaborative-AML (upstream 2db6537; not present in RS-react). Done.
- T-P3 community baselines → experiments/R13_baselines/<method>/seed* (community.log).
- T-P4 close-out reproduction → scratch p4/closeout_repro, with a scratch paths file pointing processed_dir at E:/JSJ/RS-e2e/data/processed_hi_medium (absent in RS-react; ground truth and test split sha256 identical to Ring-Shield's) and --exp-dir E:/JSJ/Ring-Shield/experiments_hi_medium (HI-Medium test scores exist only there; read-only).
- T-P7a seed 1: python PID 32272 (venv launcher 19172), started 2026-11-14T09:28:13Z under `timeout 15h`. Command: `models/mega_adapter.py --seeds 1 --edge-agg-type genagg --node-agg-type genagg --batch-size 4096 --num-neighs 100 100 --out-dir experiments/R6_megagenagg`. Log `experiments/R6_megagenagg/train_seed1.log`. Watchdog (scratchpad genagg_watch.sh) polls every 30 s, logs peak VRAM to `experiments/R6_megagenagg/watchdog.log`, kills the run if VRAM > 23,000 MiB or an epoch > 900 s. Pre-launch grep: every write in mega_adapter.py goes under --out-dir.

## Deviations (what, why, when; approved by author? y/n)
| What | Why | When | Approved |
|---|---|---|---|
| 0.8 run through `powershell.exe -Command` from Git Bash instead of an in-shell redirect | pwsh 7 absent; PS 5.1 in-shell redirect makes docker stderr fatal | 2026-11-14 | y |
| ENV REPAIR 1: copied RS-react/experiments/R3_expansion/policy_proposed/policy.json → E:\JSJ\Ring-Shield\experiments\R3_expansion\policy_proposed\policy.json (folder created); sha256 104ebeb19e69b647fa55… before and after | frozen R4 config points there; config not edited | 2026-11-14 | y (author decision 1) |
| ENV REPAIR 3: copied from RS-react/experiments into E:\JSJ\Ring-Shield\experiments (no overwrite): R3_expansion/policy_proposed/policy.txt a1768ee8ea11a147…, R4_partition/affinity/affinity.json 86a3a4aeb478bf79…, R4_partition/affinity/affinity.txt 61b53eddcb0b94da…; each sha256 equal before and after | test_cli_export_and_run_full reads them via the frozen config's paths | 2026-11-14 | y (author, round 2) |
| T-P7 batch size 4096 (not 8192), seed-1 cap 15 h, stop at > 23,000 MiB or > 900 s/epoch; written into the PREREG | author decision replacing the round-1 rule | 2026-11-14 | y |
| ENV REPAIR 2: in RS-react/models/artifacts/full_gine_causal_seed1, backed up typing/head.{json,txt} to typing/lf_backup/ (b01c3aa9…, eb33438c… = version.json lf_copy_sha256); copied version.json and typing/head.{json,txt} from RS-e2e (58055aa0…, ac147037… = version.json typing_head.files) | version.json missing | 2026-11-14 | y (author decision 2) |

## Author decisions (2026-11-14, after Phase 0 stop)
1–3. The two environment repairs above; re-run the research suite; 0.7 passes only with zero failures. Platform baseline = 567 passed.
4. GenAgg: no pyg-lib install/upgrade. One-epoch probe at --batch-size 4096, --num-neighs 100 100 before the PREREG. Rule written into the PREREG: probe ≤ 500 s and peak ≤ 20 GB → all seeds at 4096 (footnote: the GIN-aggregation MEGA row used 8192); otherwise seed 1 only at 8192 in background, capped at 30 h, as the 0.70 gate, while T-P2–T-P4 proceed; stop and ask before seeds 2–5.
5. PS 5.1 deviation accepted.

## Author decisions, round 3 (2026-11-14, after the T-P7a stop)
1. Incident accepted as resolved (author confirmed r6_pvalues.csv equals the committed version).
2. `--pvalues-out` added to evaluation/r6_detector_swap.py (default results/tables/r6_pvalues.csv, behaviour unchanged) plus tests/test_r6_pvalues_out.py (temp --out/--pvalues-out → results/tables/ unchanged by sha256 and mtime). Passed (110 s).
3. **Standing rule:** before running any existing builder/script for the first time, grep it for hard-coded writes (to_csv, to_parquet, write_text, json.dump) outside the path passed in; after every builder run, `git status` on results/ and docs/, and STOP if a tracked file changed.
4. MEGA-GenAgg: paper uses 74.48 ± 0.84 (TMLR 2026, Bilgi and Atasu). docs/FUTURE_IMPLEMENTATIONS.md F4 got a dated correction note beside the old value (old value kept).
5. Cite arXiv 2604.23494 in related work as closest prior work: blockchain dataset, account level, not rings on AMLworld; characterise only what was read.
6. TAML code findings recorded in results/notes/p9_taml.md now; act on them only at the T-P9 day-1 go/no-go.
7. Chai et al.: say nothing about its metrics beyond the abstract and article page.
8. The two typing head files show modified (line endings only): leave as is; do not stage or revert.

## Author decisions, round 4 (2026-11-14, T-P2)
1. Amendment written: paper/PREREG_AMENDMENT_2026-11-14.md, sha256 4f10b6e26d5beffadea458a5166ec2f8bfd62649d1253173bc7faa16a7e396da, 2026-11-14T14:19:31Z. Ring-F1 INCONCLUSIVE; no equivalence claim; follow-ups post hoc.
2. B17 not closed. Ring-folded policy run through step9_tables and precision_paired, unmodified (wrapper evaluation/ringfold_followup.py; both builders grepped first: all writes under --out-dir/--out). Output to scratch, then copied (no overwrite) to results/tables/v39_ringfold_*. git status results/ docs/: no tracked file changed.
3. T-P5 required change R1 recorded in results/notes/p5_required_changes.md.
4. deep-analysis §15 added; FINDINGS untouched; proposed B17/A5 notes in results/notes/p2_ringfold.md.
5. Fold-2 denominator stated (485 vs 687 ring edges; 372 common; pooled 1,406).

## Author decisions, Checkpoint A (2026-11-14)
1. HI-Medium wording: the direction of the scope effect reproduces, its size does not; observability and threshold dependence reproduce on both releases. The window-length explanation is a hypothesis (word it as one, or test it). No venue wording anywhere; venue is decided at Checkpoint B.
2. Bar (A) wording approved: "conventions re-rank methods that are close; the partition step's sign flips under component_ge3 on both releases". The paper states that the new swaps are between near-ties, with the differences.
3. T-P9 yes, with the day-1 go/no-go, in runbook position; not while GenAgg holds the GPU unless it runs on CPU.
4. FINDINGS: B17 and A5 notes added as dated notes (no row changed). HI-Medium note added after fixing the range (global −0.038 to −0.059; all eight cells −0.038 to −0.073).
5. Ring-folded full run approved: post hoc, new files only, reported beside shipped full with intervals; amendment addendum with a new sha256.
6. Deviations accepted. Leiden skip logged as "install not permitted in this session". FlowScope not attempted (optional).
7. Interval consistency: investigated → results/notes/interval_consistency.md. scope_sensitivity.boot drops resample multiplicities (a subsample, about 25 % too narrow); r9 is the correct bootstrap. The paper headline uses r9; any table using the r14-style interval says so in its caption; no table mixes them. Fix of the scorer proposed, awaiting decision.
8. Next: ring-folded full → T-P5 pass 1 → GenAgg seed-1 gate report; stop before seeds 2–5 and at Checkpoint B.

## Incident log
| When | What | Cause | Fix | Verified |
|---|---|---|---|---|
| 2026-11-14 | Frozen `results/tables/r6_pvalues.csv` overwritten during the T-P7a step-3 reproduction (2 of 4 rows; Holm p 0.6135 vs 0.8072) | `evaluation/r6_detector_swap.py` wrote `TABLES / "r6_pvalues.csv"` unconditionally, ignoring `--out` | `git checkout -- results/tables/r6_pvalues.csv`; later `--pvalues-out` flag + test; standing grep/git-status rule | identical to HEAD; audit_tables 18/0; test_frozen 47 passed; author confirmed (round 3) |

## Open questions for the author
1. (Resolved: check 0.7, by env repairs 1–3.)
2. docs/FUTURE_IMPLEMENTATIONS.md F4 records MEGA-GenAgg at 74.88 ± 0.38; the paper's v3 Table 16 says 74.48 ± 0.84. Correct the doc? (Not edited.)
3. Cite Malik (arXiv 2604.23494) in related work during T-P5 pass 1? Recommended.
4. (Resolved, author round 3: incident accepted; launch approved; flag approved.)
2–3. (Resolved, author round 3: GenAgg doc gets a dated correction note; cite 2604.23494.)
5. (Resolved, author round 4.) T-P2 bar ill-defined: CI [−0.0137, +0.0211] fits none of the three §3 branches. Approve the amendment in results/notes/p2_ringfold.md (written as a new dated file PREREG_AMENDMENT_1), or give another reading? Proceed to T-P3 meanwhile?

### 2026-11-15 — T-P7a GenAgg seed 1: watchdog STOP during scoring
- Training finished normally: early stop at epoch 62; best val F1 0.665 at epoch 42; epochs 530–580 s; peak VRAM during training 21,627 MiB.
- Scoring wrote the train and val parquets (val embeddings too). During test scoring VRAM rose to 24,048 MiB (18:55:10Z), above the 23,000 MiB cap, and the watchdog killed PID 32272 as the rule requires.
- No scores_test_seed1.parquet or metrics_seed1.json exists, so the 0.70 gate is NOT EVALUATED. model_best_seed1.pt is intact.
- Status: stopped, waiting for the author. Options: (a) rerun test scoring only from model_best_seed1.pt with a smaller scoring batch; (b) treat it as a stop. Seeds 2–5 not started.

### 2026-11-15 — Author decisions after the GenAgg stop (verbatim summary of the 7 items)
1. Rescore GenAgg seed 1 from the saved model with a smaller scoring batch, same 23,000 MiB watchdog, no retraining; score-only path behind a new flag with a test; validation first (stop if val F1 moves > 0.005); then test vs the 0.70 gate; log the batch as a deviation; ask before seeds 2–5.
2. score_external: weighted resampling by default, `--legacy-subsample-intervals` reproduces r14/v36; tests against r9 and r14.
3. Rescore v40/v41 as _v2 and r14/v36 under new names; points must match exactly.
4. Recheck every verdict that used an r14-style interval; changed verdicts go in Addendum B.
5. Leave ring_stats.py and scope_sensitivity.py unchanged; log the defect with a proposed fix.
6. Paper: drop the two-interval captions; PROTOCOL.md updated; proposed FINDINGS note goes in interval_consistency.md.
7. Continue in runbook order; stop at Checkpoint B.

### Deviation D-7a-1 — GenAgg scoring batch
- Seed 1 scoring uses batch 2048 (training used 4096). Applied via the new `--score-only --score-batch-size 2048 --ckpt-dir experiments/R6_megagenagg` path in `models/mega_adapter.py`; the training loop is never entered.
- Test: `tests/test_mega_score_only.py` (3 tests).
- The watchdog was rewritten with 5 s polls (scratchpad `score_watch.sh`).
- Validation check:
  - The rescore at batch 2048 has F1@0.5 0.6626 and AP 0.6223. The originals were 0.6652 and 0.6256, so Δ F1 −0.0026, within the 0.005 limit.
  - 2.2 % of scores change (max |Δ| 0.75; 15 of 965,524 decisions flip). Batch composition changes the time-windowed neighbour sampling.
  - Peak VRAM 6,946 MiB.
  - The rescored val parquet is in `experiments/R6_megagenagg/rescore_val/`; the original val scores are untouched.

### Open defect — silent multiplicity collapse in `metrics_from_evidence` (not fixed, per decision 5)
`evaluation.ring_stats.metrics_from_evidence(ev, truth_ids, weights=None)` builds `w = {i: 1 for i in ids}` and sums over `set(ids)`. A caller that passes a bootstrap resample with repeats and no weights (as `evaluation.scope_sensitivity.boot` does) silently gets every drawn target counted once. Each resample is then a ~63 % subsample, and the intervals come out about 25 % too narrow (r14, v36, and score_external before 2026-11-15).

**Proposed fix (for the author):** when `weights is None`, derive the weights from the multiset (`w = collections.Counter(ids)`) instead of assigning 1 to each distinct id. This makes `truth_ids` with repeats mean what its docstring already says. `bootstrap_over_rings` passes explicit weights and would be unaffected (r9 unchanged). `scope_sensitivity.boot` would become correct without editing it, but r14/v36 would no longer reproduce from it. So pair the fix with (a) a regression test asserting r9 is unchanged, (b) a test that unweighted repeats equal explicit weights, and (c) a note that r14/v36 then reproduce only through `score_external --legacy-subsample-intervals` (or a pinned commit).

### score_external interval fix (decision 2)
- The default is now the weighted bootstrap (`weighted_boot`, same RNG draws as before, draw counts as weights). `--legacy-subsample-intervals` selects `scope_sensitivity.boot`.
- Full test_visible ring-F1 is [0.5023, 0.6747] by default (= r9) and [0.5234, 0.6529] with the flag (= r14). Covered by `tests/test_score_external_intervals.py` (2 tests, against the r9/r14 CSVs to 1e-12).
- T-P1 reproduction re-run with the flag: 90 cells, max abs deviation 0.0, PASS.
- `evaluation/baselines_table.py` gained `--scored-dir`, so the corrected rescoring does not reuse the legacy-interval cache in `experiments/R13_baselines/scored`.
- New `evaluation/rescore_weighted_intervals.py` runs scope_sensitivity / component_scope unmodified with `boot` swapped for `weighted_boot` and the run roots pointed at `--exp-root ../RS-e2e/experiments`.
- New tables:
  - `results/tables/r14_scope_sensitivity_wci.{csv,json}` (csv sha256 2cf74967…)
  - `results/tables/v36_component_scope_wci.{csv,json}` (829a8656…)
  - Every point column is bit-identical to the frozen originals. Ring-F1 interval widths are ×1.30–1.41 (r14) and ×1.24–1.39 (v36).

### T-P7a GenAgg seed 1 — GATE PASS (2026-11-15)
- **Test edge F1 0.7558** at the threshold tuned on validation (`r6_detector_swap.edge_f1`; val scores from the batch-2048 rescore, matching test). With the original batch-4096 val scores: 0.7557.
- F1@0.5 0.7556, test AP 0.7450. Threshold ≥ 0.70 → **PASS**.
- Same rule on MEGA-GIN seed 1 gives 0.6435 (r6 five-seed mean 0.6893).
- Best val F1 0.6652 (epoch 42 of 62), mean epoch 538 s. Peak VRAM: 21,627 MiB in training, 6,610 MiB in test scoring at batch 2048.
- Record: `experiments/R6_megagenagg/gate_seed1.json`.
- Seeds 2–5 (T-P7b) not started: waiting for the author's go-ahead.

### 2026-11-15 — interval rescoring and verdict recheck (decisions 2–6), done
- New tables (frozen originals untouched; all point columns bit-identical):
  - `v40_external_baselines_v2.{csv,json}` (csv cdf30acb…)
  - `v41_hm_audit_{scope,component,threshold,tail}_v2.csv` + `v41_hm_audit_v2.json` (scope 5b45c778…)
  - `r14_scope_sensitivity_wci.*`, `v36_component_scope_wci.*`
- Verdict recheck: **no verdict changed**; table in `results/notes/interval_consistency.md`. No Addendum B; the amendment sha256 stays 705e2ccc….
- Paper:
  - `tables/component_scope.tex` rebuilt from v36_wci; the two-interval caption sentence is removed.
  - `tables/hm_audit.tex`: the subsample-interval comment is removed and the sources point to v41_v2. A broken row ending (`\` for `\`, left over from an earlier shell edit) is fixed, as is a broken `\ref` in component_scope.
  - Static checks: 0 problems.
- `docs/PROTOCOL.md`: Intervals paragraph rewritten; flag listed.
- Proposed FINDINGS note is in `results/notes/interval_consistency.md` (FINDINGS not edited).
- Research suite: **287 passed, 44 skipped, 1 xfailed**, 0 failures (+5: test_mega_score_only 3, test_score_external_intervals 2).
- `git status` on results/ and docs/: no tracked results file changed. FINDINGS, FUTURE_IMPLEMENTATIONS and deep-analysis show the earlier approved additions only.

### 2026-11-15 — pre-seeds checks (decisions 2a, 2b, 3): STOP at 2a
- **3 (outputs):** GenAgg seed 1 has `scores_{train,val,test}_seed1.parquet`, `embeddings_{val,test}_seed1.parquet`, `metrics_seed1.json`, `training_log_seed1.csv`, `model_best_seed1.pt`. Test embeddings were written by the score-only run at batch 2048. Open point: the val scores/embeddings in the run dir are from batch 4096; the batch-2048 val versions are in `rescore_val/`.
- **2b:** table in `results/notes/p7_genagg.md` and `results/notes/p7_val_test_gap.csv`. The MEGA-GIN test−val gap is +0.053 to +0.093 on every seed; GenAgg +0.091 is in range; GINe has no systematic gap.
- **2a: STOP.** MEGA-GIN seed 1 at scoring batch 2048: test edge F1 0.6309 vs shipped 0.6435 (Δ −0.0126 > 0.005); val F1@0.5 0.5329 vs 0.5722. Seeds 2–5 **not launched**, T-P8 not started; waiting for the author.

### Author decisions (C), 2026-11-15
1. Scoring batch 2048 for every compared MEGA-family score; MEGA-GIN seeds 1-5 rescored with `--score-only` into `experiments/R6_mega_sb2048` (shipped 8192 files untouched). 2. Calibration/thresholds from batch-2048 val scores. 3. MEGA detector-swap rows rebuilt from 2048 scores into a new file beside the shipped values (stop if ring rebuild > ~half a day CPU; estimate from shipped run timestamps ≈ 1.5-2 h). 4. Loader cause tested without retraining (done; `results/notes/p7_genagg.md`, FINDING: look-ahead up to 1,800 s, median 600 s at 8192, GINe same loader at 8192). 5. GenAgg seeds 2-5 approved. 6. T-P8 on CPU meanwhile. 7. Footnote + appendix gap table. 8. Continue to Checkpoint B.

### Background jobs (C)
- GPU chain (scratchpad `gpu_chain.sh`): MEGA-GIN rescoring seeds 1-5 → `models/calibrate.py` on `experiments/R6_mega_sb2048` (model_best and training logs copied in from `../RS-e2e/experiments/R6_mega`) → GenAgg seeds 2-5 (`--batch-size 4096 --score-batch-size 2048`, logs `experiments/R6_megagenagg/train_seed<S>.log`, watchdog 23,000 MiB / epoch > 900 s, 5 s polls, `watchdog_seed<S>.log`).
- Incident: the first rescoring launch passed `--embeddings-for` with no value (no embeddings written; the policy needs them). Stopped during seed 1 val; partial output moved to `experiments/R6_mega_sb2048/_aborted_noemb/`; relaunched with `--embeddings-for val test`.
- T-P8 CPU: `evaluation/budget_sweep.py --detectors gine_causal gfpxgb` → `experiments/R14_budget_sweep/`, log `run_gine_gfpxgb.log`. MEGA joins after its 2048 ring cells exist (the MEGA k = 0.10 reference is then the rebuilt 2048 row, not the shipped 8192 row: consequence of decision C-1).
- T-P8 registration rows copied into `docs/deep-analysis.md` §19; §18 (T-P7) registration added late (was due 2026-11-14).
- T-P8: gine_causal seeds 1-5 and gfpxgb seed 1 done (≈ 15 min/seed gine, 39 min gfpxgb). gfpxgb seeds 2-5 failed: their scores exist only in ../RS-e2e/experiments/R2_b0/gfpxgb_scores; rerun with --exp-root ../RS-e2e/experiments (log run_gfpxgb_s2-5.log).
- MEGA-GIN 2048 rescoring done (5/5 rc=0, ~9 min each); calibrated. Edge F1 mean 0.6856 vs 0.6893 shipped (per seed in p7_genagg.md). GenAgg seed 2 training: epochs ~586 s.
- STOP (2026-11-15): MEGA ring rows rebuilt from 2048 scores fall (B0 0.5208→0.4137, full 0.6074→0.5098) because the val grid re-chose k = 0.05 % for seeds 4 and 5 (shipped: 0.1 % for all). Seeds 1-3 within 0.017. Question to author: keep the val-chosen budget, or pin k = 0.1 % for the MEGA rebuild (as T-P7/T-P8 assume a fixed 0.1 % budget). Details in results/notes/p7_genagg.md. GenAgg seeds 2-5 and the T-P8 GINe/GFP+XGB sweeps continue; T-P8 MEGA cells are provisional.

### Author decisions (D), 2026-11-15
1. Seed budget fixed at 0.1 % for every detector in T-P7 and as the reference cell in T-P8. Pre-registration rows (paper/PREREG_2026-11-14.md §3), quoted:
   > | T-P7 | Ring recovery does not respond to a stronger edge detector at a fixed 0.1 % budget | d = B0 ring-F1(new detector) − 0.5213, 5 seeds; plus paired unit bootstrap new-full vs Multi-GINe-full on ring-F1 and added-member precision | ...
   > | T-P8 | "The budget binds, not the ranking" holds across budgets | \|B0 ring-F1(MEGA) − B0 ring-F1(Multi-GINe)\| at k ∈ {0.05, 0.10, 0.15, 0.20, 0.30} %, global and in-window rules | ...
   Implementation: `configs/threshold_rule_k010.yaml` = `configs/threshold_rule.yaml` with `grid.seed_frac_pct: [0.10]`; everything else (min_size {2,3}, objective, tie-break, cut) unchanged. Ring runs under `experiments/R6_b0_sb2048_k010`, `experiments/R6_full_sb2048_k010`.
2. MEGA 2048 ring rows rerun at 0.1 % (all five seeds; seeds 1-3 compared with the val-picked run, which already chose 0.1 %); table rebuilt as `r6_detector_swap_sb2048`; stop if any rebuilt MEGA ring-F1 is more than 0.03 from the shipped 8192 row.
3. Val-picked result kept as a labelled sensitivity table (`r6_detector_swap_sb2048_valpicked.*`, renamed from the first build, plus a per-seed budget table in the T-P8 notes). Not used in any paired test.
4. GenAgg ring rows: fixed 0.1 %, val-picked budget reported per seed beside them.
5. MEGA T-P8 sweep superseded (`experiments/R14_budget_sweep/_superseded_mega_valpicked_k/`, SUPERSEDED.txt; excluded from v42); rerun after item 2.
6. Look-ahead: R-LA added to `results/notes/p5_required_changes.md`; proposed FINDINGS note in `results/notes/p7_genagg.md`.
7. Embeddings relaunch accepted; GenAgg seeds 2-5 continue.

### 2026-11-15 — D-2 gate: MEGA batch-2048 ring rows at fixed k = 0.1 % (PASS)
- Rerun experiments/R6_{b0,full}_sb2048_k010/{mega,mega_noembed}, seeds 1–5; table rebuilt as results/tables/r6_detector_swap_sb2048.{csv,json} + r6_pvalues_sb2048.csv.
- Seeds 1–3 are identical to the val-picked runs (rings.parquet equal; metrics differ only in `seconds`). Seeds 4–5 changed, as expected (val had picked 0.05 %).
- Gate (|Δ ring-F1| ≤ 0.03 vs the shipped 8192 rows): mega/b0 0.5179 vs 0.5208 (−0.0029); mega/full 0.6023 vs 0.6074 (−0.0051); mega_noembed/full 0.5776 vs 0.5881 (−0.0105). GINe and GFP+XGB rows are unchanged (Δ 0). **PASS.**
- MEGA T-P8 sweep at k010 completed (seeds 1–5, 877–1281 s each). GFP+XGB T-P8 seeds 2–5 completed (rc=0).

### 2026-11-15 — T-P8 result (GINe, MEGA@2048 k010, GFP+XGB; GenAgg pending)
- v42 built (`budget_sweep.py --pairs-only`). Gap bar HOLDS 10/10; union bar SUPPORTED (152.0 / 156.2 / 152.8 ≥ 140); veto rows listed. Notes: results/notes/p8_budget.md. D-3 sensitivity: results/notes/p8_mega_valpicked_sensitivity.csv (finding, not paired). deep-analysis §19 Result written.
- Not done yet: figure (make_figs.py), GenAgg ring rows + T-P7c (GPU chain bi8hf5ehl, seed 2 at epoch 38, ~550 s/epoch), paper footnote/appendix, T-P9.

### 2026-11-15 — author instructions (E) and CPU-only work while GenAgg trains
- E-1 wording: p8_budget.md and deep-analysis §19 now say the 0.1 % budget is fixed by the pre-registration. The sensitivity is reported only as a finding that validation-chosen budgets are unstable. The rule is recorded for the paper in p5_required_changes.md (R-SB2048).
- E-2 paper: footnote added in paper/sections/results.tex (batch 2048; 8192 values and per-seed differences; look-ahead). New appendix table paper/tables/val_test_gap.tex (Multi-GINe and MEGA-GNN at 2048, with 8192 test F1 and the difference), with data in results/notes/p7_val_test_gap_sb2048.csv. The MEGA-GNN number swap in prose, tables and figure is listed for pass 2. No LaTeX toolchain on this machine, so it is not compiled.
- E-2 T-P9 reading: TAML cloned (shallow, read only) to external/taml at 15ebffde. Note: results/notes/p9_taml_day1_reading.md. Probable GO: the split maps to their calendar days, and the change is a config override plus an external wrapper. A separate venv is needed (pandas 3 / no pyg_lib). Cost is unmeasured: about 4–16 h of training per seed plus inference over every account. No training started.
- E-3: paper/CHECKPOINT_B.md started as a draft, with the two FINDINGS notes listed first as pending approvals.

### 2026-11-15 — author instructions (F): related-work numbers (CPU only)
- F-1 FraudGT: re-read the PDF with `pdftotext -raw`. Vanilla FraudGT HI-Small = 69.68 ± 1.58 (Table 2, Table 3, §4.2.1). The audit's 68.19 ± 2.03 was Multi-PNA's row, misread through a `-layout` row shift. The same shift made "Multi-GIN 61.06" (actually PNA). 76.41 ± 1.45 = PE-FraudGT (+Ports+Ego ID). ExSTraQt's "FraudGT (Best)" mixes variants per column. SALT-GNN's 0.679 ± 0.018 is its own rerun. Recorded as audit row 8a; row 5 corrected.
- Range sentence: the old "about 0.61–0.81" did not hold. Rewritten from verbatim numbers to 0.57 (Multi-GIN, Egressy T2) – 0.81 (ExSTraQt, FraudGT ratios). FraudGT is quoted with configurations (base 0.697, +ports+ego IDs 0.764).
- F-2 SALT-GNN: Table 2 verified verbatim (SALT-Trans 0.716 ± 0.018, SALT-GAT 0.694 ± 0.007). Cited in the edge-level paragraph; bib entry losavio2026salt added; code not released (no URL in v1). Audit row 8b.
- F-3 ExSTraQt (commit dd15862, no licence, nothing copied): features use expanding windows (train / train+val / train+val+test). Fitted scalers, PCA and IsolationForest come from the train run only; communities, flows and anomaly scores are recomputed on the expanding data, so test features see the whole test period. Audit row 8c. The paper says "graph features computed from expanding time windows".
- PDFs and code were read from the scratchpad only. Not compiled (no LaTeX).

### 2026-11-15 — DEVIATION: GenAgg seeds 4 and 5 failed; rerun with a changed memory limit
- Seed 4 (start 17:21Z): the watchdog stopped it at 17:39:46Z just after epoch 1 (581 s), total VRAM 23,010 MiB > the 23,000 limit. Seeds 2 and 3 peaked at 20,009 and 21,169 MiB.
- Seed 5 (start 17:39:47Z, same second the seed 4 kill returned): the log stops after the model build line, and the process exited at 17:41:26Z with rc=127 and no Python traceback. GPU memory was 645 MiB, so it never reached the GPU.
  - The kill was `taskkill /F /T /PID <seed-4 winpid 7516>`, recorded pid plus its child tree only. Seed 5 (winpid 24268) was not in that tree.
  - No other session in this project ran a kill command between 17:35 and 17:42Z, by transcript search. The other session's CPU jobs at that time were short pandas scripts.
  - No Application or System events were logged at 17:39–17:43Z.
  - Cause not established. The leading hypothesis: seed 5 started 0 s after the forced termination, before the driver released seed 4's context. A spurious MSYS `wait` status is also possible.
- Fixes (author instruction, 2026-11-15):
  - The watchdog kills only the recorded pid and its tree (unchanged mechanism, now logged), then waits 60 s before the next launch.
  - Limit raised to 24,000 MiB total VRAM (card 24,564; desktop ~640). The 900 s epoch-time stop is kept.
  - `models/mega_adapter.py` now prints `[mem]` per epoch: torch allocated, reserved, and the peaks since the last epoch. This is logging only. Model, batch 4096, score batch 2048, neighbours 100 100, and seeds are unchanged.
- Partial files moved to `experiments/R6_megagenagg/failed_2026-11-15/`. Seeds 4 and 5 rerun from scratch, one after the other (chain `gpu_rerun_45.sh`). If seed 4 trips again: no third try, stop and report.
- The pre-registered seed count stays 5. Seed 1–3 GenAgg ring rows are provisional, not in the paper until all five exist.

### 2026-11-16 — CPU-only work while seed 5 trains (author instructions, 4 items)
Baseline: pushed commit 0cc5f7c, clean tree at 07:59Z. Seed 5 epoch times checked before each item (pause rule: > 700 s).
- Seed 4: calibrated alone (`calibrate_s4_provisional.log`; its calibration.json saved as `calibration_s4_provisional.json`, the committed seeds 1-3 file restored). Ring runs for seed 4 at k = 0.1 % and val-picked are running (`rings_*_provisional_s4.log`).
- Matcher: opt-in `tie_break="deterministic"` added to `evaluation.ring_metrics.match_rings` (default "file_order" unchanged). Test `tests/test_matcher_tiebreak.py`: the order-independence test is strict-xfail under the shipped rule and passes under the deterministic rule. Audit `evaluation/matcher_tiebreak_audit.py` over all 487 rings files (3 windows x 4 conventions x 3 tau) running -> `results/tables/matcher_tiebreak_audit.csv`.
- Paper pass 2 (paper/ only):
  - tables/detector_swap.tex: MEGA rows at batch 2048, with a no-embedding row and a GenAgg [TBD] row.
  - results.tex: edge F1 0.6856 ± 0.0447; "batch-causal" wording; TODO list of the 8192-era prose numbers still to recompute.
  - data.tex and method.tex: look-ahead qualification (1,800 s maximum; medians 180 s at 2048, 600 s at 8192; applies to all three neural detectors).
  - results.tex: new subsection "What did not help", drafted from the m_track.md proposal and the Q0 table. M1 is descriptive only; M2 and M3 did not improve on seed-only.
  - No LaTeX toolchain on this machine, so no page count.
- T-P9: `.venv_taml` with Python 3.12, numpy 1.26.4 and scipy 1.13.1 (deviations from the README's Python 3.9: numpy 2 breaks torch 2.4; scipy 1.18 needs numpy 2). The 10 daily graphs are built (184 s; raw sha256 matches).
  - CPU dry run `dry_run_cpu.py`: day 1 has 177,272 nodes, 180,914 edges and 56 balanced batches; day 9 has 72,031 nodes and 75 batches. One forward pass plus both losses gives a finite loss.
  - The 1-epoch run has not been started.

### 2026-11-16 — items 1 and 2 results (provisional, not for paper/FINDINGS)
- Item 1: results/tables/r6_genagg_provisional_4seed.csv (k010) and _valpicked.csv. Means, seeds 1–4, ring F1: GenAgg B0 0.549 / full 0.587 / full-noembed 0.596; MEGA-GIN 0.505 / 0.597 / 0.573; GINe 0.536 / 0.603. GenAgg edge F1 0.727. Val-picked equals k010 for GenAgg and GINe; MEGA-GIN seed 4 val-picks a tighter budget (51 rings touched, full 0.387). No paired tests.
- Item 2: results/notes/matcher_tiebreak.md; headline cells unchanged (0 count changes). AUTHOR DECISION NEEDED; nothing rescored.
- Seed 5 at epoch 51, 540 s/epoch (<700 s).
- 2026-11-16 10:36Z: GenAgg seed 5 finished (rc 0, not killed, peak 20,623 MiB, 55 epochs, best epoch 35, val F1 0.6444). Test edge F1 computed; see report. Stopped per instructions.

### 2026-11-16 — Checkpoint B work (author instructions, 5 items)
- 10:5xZ T-P9 day-1: 1-epoch TAML (theirs split, seed 28) started on GPU with watchdog (VRAM > 24,000 MiB or wall > 4 h; kill recorded pid tree only). Logs experiments/R15_taml/taml_day1{,_watchdog}.log.
- Seed 5 calibrated alone (calibrate_s5.log, calibration_s5.json; committed calibration.json restored). Ring arms for seed 5 running: rings_k010_s5.log, rings_valpicked_s5.log.
- 11:02:51Z Addendum paper/PREREG_GENAGG_ADDENDUM_2026-11-16.md written before any test; sha256 ccf410d590f2589c1ffeee4db508bc3cdd92cc6e2d3e1a9375b076a453c5edd9. Test script evaluation/genagg_paired.py (wraps precision_paired.py unchanged).
- 11:07Z T-P9 day-1 DONE: 1 epoch, rc 0, not killed. 353 s/epoch train (wall 361 s), torch peak alloc 98 MiB, card peak 1,009 MiB, loss 0.368. Projection at their 250 epochs: ~24.5 h per seed of training (evaluation excluded), ~4.1 days for 5 seeds serially. No further epochs run.
- Item 4 (author decision: deterministic default for new scoring). evaluation/score_external.py default tie_break="deterministic", new flag --legacy-file-order; ring_stats.ring_evidence gains a tie_break pass-through (default file_order, so every other caller is unchanged). T-P1 reproduction with --legacy-file-order --legacy-subsample-intervals: 90 cells, max abs dev 0.0 (full and B0). Default (deterministic): points unchanged, intervals max dev 0.0013. tests/test_score_external_intervals.py pinned to --legacy-file-order (they reproduce frozen r9/r14) plus a new default test: 35 passed, 1 xfailed. docs/PROTOCOL.md Matching paragraph and flag list updated. paper/sections/data.tex matching sentence corrected.
- Item 5 a–e, g done (paper/ only): 5a results.tex partition sentence moved out of the % source line; 5b method.tex stray CR → \ref (no other stray CRs in paper/); 5c fixed 0.1 % budget + val-picked sensitivity (MEGA seeds 4, 5 pick 0.05 %; full 0.602 → 0.510) in method.tex Seeds, data.tex §3.x, results.tex swap prose, detector_swap caption; 5d "What did not help" references stated per attempt, loss breakdown reconciled (68.8 + 11.4 = 80.2; untouched counts differ); 5e §6.1 and conclusion lead with leak-free 0.251 / 0.819, day-folded in one sentence; 5g main.tex → acmart sigconf,review,anonymous (old file kept as paper/main_article_v3.tex; author and acknowledgements in commented camera-ready blocks); cut proposal paper/PAGE_BUDGET.md (nothing deleted; pages to be measured on Overleaf).

### 2026-11-16 — author re-prioritisation (stop paper writing; fix results and defects)
- Paper: no edit was mid-way at the switch; paper/sections and paper/tables frozen from here until told.
- Item 5 T-P9 GO, single seed: TAML seed 28 (their seed 1), their split, 250 epochs, started on GPU with watchdog (VRAM > 24,000 MiB or wall > 48 h; kill recorded pid tree only); scratchpad taml_seed1.sh; logs experiments/R15_taml/taml_seed1{,_watchdog}.log. TAML runs no validation and saves only at the end, so run_ours.py gained --snapshot-every (read-only hook: a state_dict copy every 10 epochs plus runs/.../epoch_loss.csv; training unchanged). Results labelled "single seed, feasibility".
- Item 2: ring_stats.metrics_from_evidence now counts repeated ids with their multiplicity; legacy_collapse_repeats=True keeps the old collapse and is passed only by scope_sensitivity.boot (frozen r14/v36, and score_external --legacy-subsample-intervals through it) and r7_heldout.boot_pattern (frozen r7; same defect, flagged in open_items). Tests: tests/test_metrics_multiplicity.py (4 passed). Full suite and the _wci equality check running.
- Item 4: docs/FINDINGS.md: three dated notes appended (intervals, look-ahead, tie-break); verified byte-identical prefix (append only).
- Seed 5 rings: k010 done (1,178 s), val-picked done (1,293 s); calibration_s5.json.
- Paired family (addendum sha256 ccf410d5…, exploratory): results/tables/r6_genagg_paired.csv, 10,000 draws, 174 rings + 47 off-ring units. Ring-F1: (i) GenAgg full − GINe full +0.0016 [−0.0299, +0.0342] p_Holm 0.91; (ii) − MEGA-GIN full −0.0112 [−0.0373, +0.0142] 0.82; (iii) B0 − GINe B0 +0.0298 [−0.0105, +0.0715] 0.57; (iv) full − no-embeddings −0.0079 [−0.0219, +0.0056] 0.78. **(iv) interval includes zero → decision rule: no retraining**; both rows reported with the policy-transfer caveat. Added-member precision descriptive only ((iii) undefined for B0 arms; ring_stats.paired_unit_bootstrap now returns NaN instead of crashing on an all-NaN metric, test added).
- Item 3 data: r6_seed_overlap_sb2048.csv (8192 check reproduces 0.415 / 128.8 / 71.5 %); r14_scope_sensitivity_sb2048.csv, v36_component_scope_sb2048.csv; r6_ring_decomposition_sb2048.csv (8192 check reproduces 83.6 / 51.6 / 24.0).
- Item 2 check: corrected metrics_from_evidence inside the r14/v36 builders = r14_wci / v36_wci, max abs dev 0.0 (evaluation/check_multiplicity_fix.py). r6_detector_swap --pvalues-out now defaults beside --out (frozen path only when --out is the frozen table); test added.
- 2026-11-16T11:39:57Z PREREG_RECOVERY_2026-11-16.md written before any Part A/B/C run; sha256 a265194cb436350fbed2c559c16835ee7b4ffa95d0841ae2219f1945d4e51d63.
- Part B DONE: results/notes/recovery_history.md; target (untouched + too-thin) 25.4/seed, with history (b) 17.2 (c 9.0, d 10.0) >= bar 8 -> STOP for author decision; nothing built. Cost: 3,585 history accounts, 101,293 in-window edges (219x the 463 seeds), illicit share 0.48 %.
- Part C feasibility STOP (input missing): currency/format codes are first-appearance per dataset and differ HI-Small vs HI-Medium; MEGA z_norm is per split (no 'HI-Small fitted normalisation' exists). results/notes/recovery_partC_feasibility.md. No GPU work run.
- Part A GATE FAIL: best ensemble E-All15 val ring-F1 0.5753 < GINe full 5-seed mean 0.5927; no test read; results/notes/recovery_ensemble.md.
- 2026-11-16T12:36:06Z PREREG_RECOVERY_AMENDMENT_2026-11-16.md (A closed at gate; B2; C corrections) written before B2/C; sha256 d2cfe2fbaf8ebc6d85a5782360aad2d82f19a557377a6960e6227e8bee54fb32.
- 2026-11-16T12:43:29Z Clean full research suite (no concurrent writers): 284 passed, 6 skipped, 2 xfailed, 0 failed (683 s). Earlier test_r6_pvalues_out failure was the concurrency race. tests/test_history_seeds.py: 4 passed.
- B2 step 0: results/tables/recovery_history_topk.csv; history-touching edges in GINe's top 0.5 % are 67.0 % illicit (316 of 479; (d) 62.4 %), top 1 % 59.3 %. Appended to recovery_history.md.
- B2: evaluation/history_seeds.py (+ tests/test_history_seeds.py, 4 passed: no label at/after the scored split's start can enter H). Six cells built in experiments/R17_history_seeds (val K 966 / test K 864; reserved 97/242/483 val). Ring runs (B0 + shipped full) running, six cells in parallel.
- Part C: input check: MEGA reads Timestamp (re-based), Amount Received, Received Currency, Payment Format; node feature constant 1; ports/tds off; bank/account ids only structural. Remapped copy experiments/R18_hm_transfer/raw/HI-Medium/formatted_transactions.csv + mapping.json (verified per-code counts; no missing category). HI-Medium processed hashes = Ring-Shield copy (8fca50f7…, b0c0130e…, 57158912…). 1 % val slice timing running with watchdog (VRAM 24,000 MiB, RAM 80 %).
- Part C STOP at split check: MEGA's 60/20/20 split on HI-Medium (train 19.49 M) != ours (train days 0-3, 9.15 M; val 4-5; test 6-27). No score; proposal in recovery_partC_feasibility.md.
- 2026-11-16T13:15:19Z Amendment addendum 2 (Part C split wrapper) appended; file sha256 now 1e81ee44d16acb28f0952455164ada25385ff883c4c8c9c532a8f11488823d64.
- 2026-11-16T13:24:30Z Part C gate 0 (HI-Small reproduction, val only) FAIL: median |diff| 1.4e-17 (pass) but Spearman 0.99786 < 0.9999, max 0.746; 13,193 of 965,524 edges differ > 1e-4 (both val days). No HI-Medium scored. Diagnostic (HI-Small only): rescoring train then val, the stored run's order, to test the RNG-stream hypothesis.
- 2026-11-16T13:42:11Z Addendum 3 (gate-0 bar replaced; noise quantification; B2 r50_both 4 h limit, deadline 16:44Z) appended, with disclosure that the same-order diagnostic was read before it; file sha256 now ccee80efefa95c8903f0873b825ff3f17a617b59daf716b876744cf931a49475. Gate 0 (a): FAIL (max |diff| 0.746 >= 1e-6). Proceeding to (b).
- 2026-11-16T14:04:08Z Gate 0 (b) PASS: orig-vs-orig and wrapper-vs-orig are both bit-identical (0 edges differ, Spearman 1.0, max 0). Scoring is deterministic for a fixed seed. The stored R6_megagenagg seed-1 scores are NOT reproduced by current scoring (val: 13,193 edges > 1e-4, max 0.746, Spearman 0.99786; test: 1,165, max 0.217, 0.99953); cause not yet identified. Noise probe: rng offset 1000 run (hs_rng1000) scoring val+test.
- 2026-11-16T14:19:07Z Gate 0 resolved: current scoring reproduces rescore_val (batch-2048) to max 8.3e-7 -> (a) passes against the correct reference; R6_megagenagg/scores_val_seed1.parquet is the batch-4096 original (open_items 21). (b) also PASS (all bit-identical). Noise quantified (open_items 20, p7_genagg.md). HI-Medium 1 % slice running.
- 2026-11-16T14:29:20Z Part C step 1 PASS: HI-Medium load 799 s; our split applied (MEGA's own (9,13) -> ours (4,6)); check_splits passed; 1 % val (38,576 edges) in 9 s -> full val ~0.25 h, test (18.9 M) ~1.2 h; peak RAM ~51 % (load), VRAM 1.2 GB. Scoring order for HI-Medium: val only, seed 1, no RNG offset.
- 2026-11-16T14:53:05Z T-P9 TAML seed 28 (their seed 1; single seed, feasibility) FINISHED by TAML's own early stopping at epoch 38 (training-loss plateau), rc 0, not killed; 12,933 s train (~340 s/epoch actual; timing.json's 52 s/epoch divides by the 250 requested). Loss 0.367 -> 0.238. Snapshots epoch 10/20/30 + final model. Card peak 14,687 MiB was shared with the GenAgg scoring runs; TAML's own torch peak 104 MiB. Not yet evaluated: TAML has no validation in its loop; their split trains on our val days 7-8.

- 2026-11-16T17:13:08Z Addendum 4 appended to PREREG_RECOVERY_AMENDMENT (sha256 aba88b162a6a8ef2a303c454a41523b57d022bedbd66a3abe2e761f76d16bc1c), written after r50_both seed-1 val 0.4821 was seen. r50_both stopped during seed 2 expansion: did not complete; seed 1 = 0.4821; stopped by author decision after one seed. B2 gate on five cells: r25_both 0.5960 > 0.5927, PASS.

- 2026-11-16T17:24Z runbook 0.7 suite, nothing else writing: `.venv312/Scripts/python.exe -m pytest tests contract/tests preprocessing/tests -q -rs` -> 348 passed, 44 skipped, 2 xfailed (394 collected). Per directory: tests 288/6/2xf (296), contract/tests 46/38 (84), preprocessing/tests 14/0 (14). Skips: tests 6 (E6 checkpoint x2, R1 seed1, expand training set, cc contract/legacy x2); contract 38 (rings-stub inputs 13, dry-run inputs 18, full contract outputs 7), all "inputs not on disk".
- B2 test read started (r25_both, once).
- 2026-11-16T17:36:12Z Part C full HI-Medium validation scoring started: scoring order = validation only (no train/test pass), GenAgg seed 1, rng-offset 0 (seeds as mega_adapter sets them), batch 2048, watchdog 24 GB VRAM / 80 % RAM. Out: experiments/R18_hm_transfer/genagg_seed1. In parallel (CPU): B2 r25_both_testhist05 rings.
- 2026-11-16T17:36:26Z B2 test read r25_both: ring-F1 0.5924 vs 0.5895, paired d +0.0029 [-0.0219, +0.0299] p 0.84. Note in results/notes/recovery_history.md.
- 2026-11-16T18:06:06Z Part C validation scored in 1545 s (3,857,689 edges, 3,904 illicit), peak VRAM 12.7 GB. Trained on HI-Small, zero-shot on HI-Medium: AP 0.5445, ROC-AUC 0.9867, best-threshold F1 0.5872; saturated at 1.0: 0.0 % (max 0.9999989). Reference HI-Medium detector AP 0.4495 (day-0 labels excluded in training) / 0.3073. GATE AP >= 0.4495: PASS. Test scoring started: order = test only, seed 1, rng-offset 0, out experiments/R18_hm_transfer/genagg_seed1.
- 2026-11-16T18:07:06Z Item 3 (open item 20): models/score.py --rng-seed (default None = unseeded, shipped behaviour), tests/test_score_rng_seed.py 4 passed. No shipped file rescored.
- 2026-11-16T18:08:07Z Item 2 (open item 21): experiments/R6_megagenagg_s1v2048 = rescore_val val scores + shipped batch-2048 test scores (copies), recalibrated on 2048 val (78 knots). Ring arms -> R6_{b0,full}_sb2048{_k010,}/megagenagg_s1v2048{,_noembed}.
- 2026-11-16T18:11:10Z Addendum 5 appended (sha256 39fd05b0f5ec8e9b889b52d8ef3f355cdd7a728228d38208a582d843c55e290f), before any HI-Medium test score or ring number was read. Reference B0 global primary = 0.0898 (closeout_a15 seeds 1-2).
- 2026-11-16T18:12:15Z Addendum 5 clarification appended (sha256 80abdee4c9f32f8824915491c042431c9a3041772cff911d3c91bf0ae2dbc6ce): full arm = policy_no_detector + affinity_no_embedding, no embeddings. Still no HI-Medium test number read.
- 2026-11-16T19:27:18Z B2 label-delay sensitivity r25_both_testhist05 (test H days 0-5): full ring-F1 0.5627 vs shipped 0.5895 (descriptive). B2 item complete.
- 2026-11-16T20:05:02Z Item 2 (open item 21) done: v2 tables and paired family identical in ring-F1 to the shipped ones; no reading changes; (iv) not triggered. Note: results/notes/open_items.md.
- 2026-11-16T20:57:58Z Part C test scoring (seed 1) STOPPED by watchdog: total VRAM 24012 MiB > 24000 after ~2h35m of scoring (data load 964 s). No test file written. Validation results unaffected.
- 2026-11-16T21:01:17Z Addendum 6 appended (sha256 3d1e6a39b2ce5128f9c666b96110fffbc2aa327428668ddf14a9ab0fb684f995): day-chunked test scoring, empty_cache every 50 batches, fallback halving, HI-Small check first. No HI-Medium test number exists.
- 2026-11-16T21:01:34Z Addendum 6 correction (sha256 31d494b18fd91174acefed56cec63a2dc4c860a9819839a00d4dd22ae52a11ec): validation scoring rate ~5,460 edges/s (707 s excl. 838 s load); TAML pause bar 4,370 edges/s.
- 2026-11-16T21:47:00Z HI-Small chunk check attempt 1 FAILED for an implementation defect, not the bar: the score_split copy in hm_transfer_score.py lacked @torch.no_grad() (mega_adapter.score_split has it), so autograd kept every batch (torch OOM at 84 GiB allocated with Windows shared-memory spill; watchdog stopped day 8 at bs2048 and bs1024). Diagnosis on HI-Small only: same block with the original score_split scored 209,433 rows, rc 0. Fix: decorator added (no score change). Attempt kept in hs_blocks_failed_nograd/. Check rerun. No HI-Medium test edge scored.
- 2026-11-16T21:56:11Z Addendum-6 HI-Small chunk check PASS (attempt 2, after the no_grad fix): blocks d8 (654,467 edges, 3,365 e/s, peak alloc 1.78 GiB / reserved 3.95 GiB) and d9-17 (209,433, 3,500 e/s, 2.14 / 4.19 GiB); concat 863,900 rows, ids unique, none missing. vs stored single pass: 9,307 edges (1.08 %) |d|>1e-4, max 0.753, median 0, Spearman 0.99954, top-0.1 % seeds 862/864 (Jaccard 0.9954 >= 0.99), B0 ring-F1 0.5504 = 0.5504 (val 0.5714 both). results/tables/chunk_check_hs_genagg_s1.json. HI-Medium blocks started: 6-7, 8-9, 10-12, 13-14, 15-27. TAML our-split seed 1 running alongside.
- 2026-11-16T23:42:03Z TAML seed 1 (28) on our split (train days 1-6): early stop at epoch 36 (training-loss plateau), 9525 s (~265 s/epoch), peak alloc 104 MiB; model in experiments/R15_taml/runs_ours/ours_e250_FraudGT_seed28 (snapshots every 10).
- 2026-11-16T23:42:13Z Addendum-6 TAML rule: HI-Medium blocks d6-7 1,761 e/s and d8-9 1,811 e/s, both < 4,370 -> rule triggered, but TAML had already finished (23:41Z), so nothing to pause. Rate is low with or without TAML (HI-Small blocks 3.4k e/s); empty_cache every 50 batches and CPU sampling are the likely cost.
- 2026-11-16T23:43:55Z T-P9 STOP-AND-ASK before any TAML scoring: TAML graphs store no account names (n_id = position in the step's sorted Account list after their leakage step); remove_leakage uses unseeded np.random.rand to place every recurring account on the train-val OR test side, so the existing graphs cannot be mapped back to our accounts. Mapping needs a seeded rebuild with names captured, which changes graph membership, so seed 1 would need retraining on the rebuilt graphs (~2.6 h GPU). Awaiting author.

### 2026-11-17 — Addendum 6: HI-Medium seed-1 test blocks done (trained on HI-Small, zero-shot on HI-Medium)
- Blocks d6-7, d8-9, d10-12, d13-14, d15-27 all rc=0 at batch 2048, no watchdog stop, no halving, no batch-1024 deviation. Peak VRAM (nvidia-smi) 5.2-10.1 GB. Last block finished 02:04:57Z.
- Concatenated to experiments/R18_hm_transfer/genagg_seed1/scores_test_seed1.parquet: 18,893,741 rows = test split, edge ids unique, none missing. Columns edge_id, timestamp, score_raw (same as the val file; no calibrated column, build_scored_edges uses score_raw for both splits).
- Seed-1 close-out started (evaluation/hm_transfer_closeout.py --seed 1, log experiments/R18_hm_transfer/closeout_seed1.log).

### 2026-11-17 — T-P9 addendum (representability gate) registered
- paper/PREREG_TP9_ADDENDUM_2026-11-17.md sha256 4dfae66887d4c77bab7d2778fe8f18fc93c5f9c51147d0926f4c21fec58525ab, written before any rebuild or count.
- TAML models kept unchanged and **not scored**: runs/ (their split, seed 28) and runs_ours/ours_e250_FraudGT_seed28 (our split, early stop epoch 36). Reason: TAML graphs store no account names and remove_leakage uses an unseeded np.random.rand, so the graphs these models were trained on cannot be mapped to our accounts.

### 2026-11-17 — T-P9 addendum steps 1-2 done; gate statistic at/above bar -> STOP for author
- Seeded CPU rebuild (np.random.seed 20261117, experiments/R15_taml/rebuild_seeded.py, builder unedited), built twice (work_seeded/build_A 164 s, build_B 140 s): all 10 steps identical (x, y, edge_index, edge_attr, n_id, names). Test graphs: step 9 74,859 nodes / 52,765 edges; step 10 14,457 / 9,735.
- Representability (evaluation/taml_representability.py -> results/tables/p9_taml_representability{.json,_per_ring.csv}, log experiments/R15_taml/representability.log):
  - 174 rings: members present 615/832; >=3 present s9 54, s10 59, either 93; >=3 connected s9 25, s10 39, across both 63; 32 rings with no member present; in-window transactions surviving as edges 338/585 (57.8 %).
  - 97 matchable: members present 453/594 (median share 0.90); >=3 present s9 44, s10 53, either 78; >=3 connected s9 25, s10 39, across both 63; 3 with none present; transactions surviving 266/460 (57.8 %).
  - Gate (declared): 63/97 = 64.9 % >= 60 % -> not NO-GO; stopped and reported with a proposed conversion rule. No retraining, no scoring.

### 2026-11-17 — T-P9 addendum 2 registered
- paper/PREREG_TP9_ADDENDUM2_2026-11-17.md sha256 ab68854d0a33f0bf564ea5de3f0c59ca40e857184c716bb0e1cef0a9f6d6c4cb, written before any training on the rebuilt graphs.

### 2026-11-17 — HI-Medium seed-1 ring rows (trained on HI-Small, zero-shot on HI-Medium): bar PASSED
- closeout primary/global: B0 ring-F1 0.4087 (R 0.3621, 1,689 rings) > 0.0898 continuation bar. proposed 0.4087 (identical rings to B0), full 0.4101 (R 0.4440, 2,549 rings), B1b 0.3099. Close-out continuing (per_day rule, day-blocks); seeds 2-5 follow per addendum 5.
- Seeds 2-5 started (sequential; full val then test day blocks; evaluation/hm_transfer_score.py gained --seed, default 1, no other change; blocks.sh passes --seed). Seed-2 val runs alongside the seed-1 close-out (CPU job; host RAM 21%).

### 2026-11-17 — Diagnosis: HI-Medium transfer seed 1, Proposed = B0 (no retuning)
- evaluation/hm_proposed_diag.py -> results/tables/hm_transfer_proposed_diag_seed1.json. Primary days 6-14, global rule, policy_no_detector at p_min 0.9, delta_t 48 h.
- 15,864 seeds in 4,962 components; 4,272,905 candidate probabilities; median 0.0, p99 0.00026, p99.9 0.0053, max 0.9054; 1 candidate >= 0.9 (80 >= 0.5). Expansion added 1 edge; stops: below_p_floor 4,900, closure 57, no_candidate 5.
- Inputs: cos_mean_included and cos_anchor NaN on 100 % of rows (no HI-Medium embeddings for the transferred model; context built with embeddings_parquet=None). No other policy feature missing. The policy drops the detector group, so no score feature enters it.
- Reading: a missing-input fallback, not a score-scale issue. The embedding group carries 36 % of the policy's gain (cos_anchor 34 %); with both NaN the booster takes default branches and almost no candidate clears 0.9. Proposed and Full rows are secondary and policy-transfer-confounded; primary stays B0 global (addendum 5).
- Side note: the dead-region head constants come from the GenAgg checkpoint (1,891,373 test edges flagged); dead_region is not a policy feature.

## 2026-11-17 HI-Medium transfer seed-1 close-out finished; seed-2 validation AP
- closeout/log_seed1.json: n_truth 2187, n_seeds 15864 for primary/global, the same as the 0.0898 bar (closeout_a15 seed 1). Same hm_closeout code, days 6-14, global rule, test_visible scope, Jaccard 0.5: item 1 comparable, no recompute needed.
- Primary global rows (P / R / F1): B0 0.4689/0.3621/0.4087; per-day B0 F1 0.3883. Full log in experiments/R18_hm_transfer/closeout_seed1.log.
- HI-Medium validation AP (trained on HI-Small, zero-shot on HI-Medium), computed from scores_val_seed<S>.parquet and Is Laundering: seed 1 0.5445, seed 2 0.5404.
- Intervals and budget shares: new evaluation/hm_transfer_intervals.py (ring bootstrap, 1000 draws) -> results/tables/hm_transfer_closeout_seed1_ci.csv and _budget_shares.csv (running on CPU).

## 2026-11-17 Author items after seed-1 acceptance
- Item 1: 0.0898 = mean of old-detector (HI-Medium-trained GINe) global B0, seeds 1 (0.1035) and 2 (0.0761); old per-day B0 0.1193 / 0.1757 (already in experiments_hi_medium/closeout_a15/log_seed{1,2}.json, not recomputed). Old val AP 0.4497 / 0.3955. Old per-day budget shares -> results/tables/hm_old_detector_budget_shares.csv (seed 2: 41.7 % of global seeds on day 14).
- Item 2: 1,000-draw intervals kept as results/tables/hm_transfer_closeout_seed1_ci_provisional1000.csv; rerun at 10,000 draws running (overwrites hm_transfer_closeout_seed1_ci.csv, a file created today).
- Item 3: STOP before writing addendum 7. The only HI-Small no-embedding policy is experiments/R3_expansion/policy_no_embedding (one policy, trained 2026-09-19 on old GINe cross scores, not per GenAgg seed). It keeps the detector group: score_quantile and dead_region, absent from policy_no_detector. Also: the transfer close-out's policy_no_detector is the HI-Medium-trained one (experiments_hi_medium/R3_expansion). Missing-share check running: evaluation/hm_proposed_diag.py --policy experiments/R3_expansion/policy_no_embedding --tag _hs_noemb_check (diagnosis only; --policy/--tag added, default behaviour unchanged).
- Item 4: Window bounds are inclusive days. block14-15 = days 14 and 15; day15 = day 15 only. Primary = days 6-14 excludes day 15; day 15 enters only the block14-15 and day15 rows.

## 2026-11-17 Addendum 7 withdrawn (author)
- Not registered, not run. Why: the only HI-Small no-embedding policy (experiments/R3_expansion/policy_no_embedding) was trained on old GINe scores and uses score_quantile and dead_region; the policy behind the existing HI-Medium Proposed/Full rows (experiments_hi_medium/R3_expansion/policy_no_detector) is HI-Medium-trained with two features (cos_anchor, cos_mean_included) missing.
- Missing-share diagnosis stopped before finishing (no output file written).
- Labels: transfer result = B0 (primary, global rule) with B1b beside it. Proposed and Full on HI-Medium: "not evaluated under transfer: policy trained on HI-Medium on the old detector, two of its features missing"; out of any paper table.
- Full's partition: affinity experiments_hi_medium/R4_partition/affinity_no_embedding, trained on HI-Medium pairs built from the old GINe cross scores (R3_cross_scores_c1prime); cut 0.3, p_min 0.9, delta_t 48 h, k 0.1 % from v33_a12_val_chosen.json (HI-Medium validation, old detector).
- Note proposal written to results/notes/hm_transfer.md.

## 2026-11-17 Seed 2 test scoring done; TAML seed 28 started
- Seed-2 blocks d6-7, d8-9, d10-12, d13-14, d15-27 all rc=0 at bs 2048; concatenated to genagg_seed2/scores_test_seed2.parquet: 18,893,741 rows, ids unique, none missing.
- Driver started TAML seed 28 at 08:14:14Z (GPU). Seed-2 close-out and 10,000-draw intervals running on CPU with CUDA hidden.

## 2026-11-17 Leak check for the HI-Medium transfer jump (diagnosis, read-only)
- Raw CSVs (data/raw): HI-Small 5,078,345 tx / 515,088 (bank, account) pairs; HI-Medium 31,898,238 tx / 2,077,023 pairs.
- Shared (bank, account) pairs: 18. Identical transactions (timestamp, from bank/account, to bank/account, amount received, payment format): 0. HI-Medium laundering transactions also in HI-Small: 0 of 35,230.
- Both datasets start 2022-09-01, so the calendars coincide, but the transactions are disjoint. No train/test leak through shared data.
