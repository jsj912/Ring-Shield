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
