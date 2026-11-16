# Method track (M1/M2/M3) — progress

Pre-registration: `paper/PREREG_METHOD_2026-11-15.md` sha256 `5b14316ffb34f3469935435fad5c94bd582cba283903826ca9cbd197729b4d49` (frozen from this line on).

| Step | Status | Command | Outputs | sha256 / note |
|---|---|---|---|---|
| Reading | done 2026-11-15 | — | — | — |
| Ref check B0 | PASS 0.5213 | `score_external.py --rings ../RS-e2e/experiments/R2_b0/gine_causal/seed{1..5}/rings.parquet --split test --window primary --out experiments/M1_verifier/refcheck/b0` | refcheck/b0 | B0 rings read from RS-e2e (absent here) |
| Ref check full | PASS 0.5894 | same, `experiments/R4_partition/runs/average/seed{1..5}` | refcheck/full | |
| Ref check ring-folded full | PASS 0.5893 | same, `experiments/R4_partition_ringfold/average/seed{1..5}` | refcheck/full_rf | |
| git status results/ docs/ after runs | unchanged | — | refcheck/git_status_before.txt | |
| Pre-registration | written | — | paper/PREREG_METHOD_2026-11-15.md | 5b14316ffb34f3469935435fad5c94bd582cba283903826ca9cbd197729b4d49 |
| Amendment | written | — | paper/PREREG_METHOD_AMENDMENT_2026-11-15.md | 7feb2334cd74bb1e187cb604bf6271259feb0fd93295ed2c21120b3ab37795bd |
| Amendment 2 | written | — | paper/PREREG_METHOD_AMENDMENT2_2026-11-15.md | 60dbe5c13348f8efaf0e2b8ebe3a72e8986afdffcbf6a3a466175411df802b2b |
| v42 0.2% seed-1 repro | PASS exact (B0 0.557, full 0.582, AMP 0.5278) | budget_sweep.py --detectors gine_causal --seeds 1 --k-grid 0.20 --rules global --exp-out experiments/M1_verifier/repro --out experiments/M1_verifier/repro/v42_repro.csv | experiments/M1_verifier/repro | |
| Checkpoint copies | sha256 OK (12 files) | cp from experiments/R3_ringfold/cross_scores | experiments/M1_verifier/embed/originals.sha256 | |
| Generator vs REF, val seed 1 | PASS 0.5852 = 0.5852 (154 rings) | python -m evaluation.m1_verifier refgen --split val --seed 1 | experiments/M1_verifier/refgen/val_k0.10_seed1 | R1 read from ../RS-e2e/experiments/R1_gine_causal (scores byte-identical to local; local lacks checkpoints/embeddings for seeds 2-5) |
| Generator vs REF, test seed 1 | PASS 0.6109 = 0.6109 | refgen --split test --seed 1 + score_external | experiments/M1_verifier/refgen/test_k0.10_seed1 | |
| Embedding closure | done, 3 iterations (555,264 + 10,568 + 43 edges; final run 0 missing) | discover --iter N / export --needed embed/needed_iterN.parquet | experiments/M1_verifier/embed/ | export time 26-42 s per fold + ~27 min data load per call; CPU |
| Embedding check (amendment 2 §6) | PASS all folds: median cosine 0.99987 / 0.99999 / 0.99993 / 0.99978 / 0.99966 | m1_verifier check | embed/check.csv, embed/check_tail.txt | heavy tail: cos<0.99 for 7.9 / 1.2 / 1.4 / 12.6 / 12.9 % of edges; min cosine 0.086 (fold 4) |
| Train candidates | 1,097 rings, 75 positives (220 train truth rings); 318 of 4,832 trajectories cross folds | candidates --split train --seed 1 | candidates/train/seed1 | one cell shared by seeds 1-5 |
| Val candidates seed 1 (0.2 %) | 283 rings, val F1 0.418 (P 0.325 R 0.586) | candidates --split val --seed 1 | candidates/val/seed1 | |
| Tests | 6 passed | pytest tests/test_m1_verifier.py | | |
| **Seed-1 validation gate** | **PASS**: M1-V 0.6204 (t 0.1, 88 rings, 487 accounts) > REF 0.5852 (154 rings, 686 accounts) | fit --seed 1 | fit/seed1/fit.json | M1-V-IS 0.6148; M1-S 0.5753 (q 0.5). Author approved continuing. |

Refcheck file hashes:
```
3025e678c70ef85ff34a6764eb7422ea833c1bb6557ba7d0565ffe1768da3024 *b0/summary.csv
b53e3fdd32c5f9892b41dad1efea7f21385a961b8f5858117474e4853a3b2e04 *full/summary.csv
5ab678558c68fb029f8a4c6f9d9c5702783ebea74d3f807e6afa5a61c6d603e3 *full_rf/summary.csv
fac4520c1a5344daccde3660427308b6b3762c6f66afbe14c0fb4cb181716f65 *b0/config.json
2f0ad52caf33ca97feaf48d846388a8b0985a23a760dd6aac8ca3935723a3538 *full/config.json
569b8b591da989c76d2d5fe6d349d6ae3009427db6f09dc0b92c57eecdb1b323 *full_rf/config.json
```

## M1 seeds 2-5 and test (2026-11-15)

Threshold rule: chosen **per seed** on validation (prereg §2), frozen grid t 0.1-0.9.

| Step | Status | Command | Outputs | sha256 / note |
|---|---|---|---|---|
| Val candidates + fit, seeds 2-5 | done | candidates --split val --seed S; fit --seed S | candidates/val, fit/seed{S} | val M1-V 0.5316 / 0.5679 / 0.5714 / 0.5517 vs REF 0.5074 / 0.5742 / 0.5528 / 0.5570 |
| Chosen cells frozen | done before any test scoring | m1_verifier chosen | experiments/M1_verifier/chosen_cells.json | dea2ac41eee4bfc3e76ff2057f7f9df40dac56710dfd192cc2ce1e83cdbbfbec |
| Test candidates, apply, score (once) | done | candidates --split test; apply; score_external x4; --compare M1-V vs refcheck/full_rf | experiments/M1_verifier/test | |
| Side metrics | done | m1_verifier report | results/tables/m1_test_arms.json, m1_test_arms_per_seed.csv | ac4b85f5..., 4c4e1054... |
| **Primary result** | **R6 INCONCLUSIVE**: +0.0040 [-0.0409, +0.0457], p 0.85, p_Holm 1.00; AMP 0.830 | (script in session) | results/tables/m1_primary.json, m1_per_seed.csv | feadd03e..., b785dc83... |
| Post hoc a, b, c (outside Holm) | done after primary on disk | candidates --k 0.1 --tag _k010; posthoc --part a/b/c; score + compare | experiments/M1_verifier/posthoc, results/tables/m1_posthoc*.csv | 57632a28... (m1_posthoc.csv) |
| Notes | written | — | results/notes/m_track.md | 3bd46df0b25dd73748fd2265765d57647370f0cb8d08ecd96fdc1ceb361825b5 |
| M2, M3, HI-Medium | not started (author: stop after M1) | | | |

## M2 and M3 to the seed-1 validation gate (2026-11-15)

| Step | Status | Command | Outputs | sha256 / note |
|---|---|---|---|---|
| M1 notes: secondary trade + post hoc (c) uninformative | done | — | results/notes/m_track.md | |
| M2 tests | 9 passed | pytest tests/test_m2_motif.py | | |
| **M2 seed-1 val gate** | **FAIL -> R0**: best M2-G (T24, f5, L4, g 0.01) 0.5693 < 0.5852 | python -m evaluation.m2_motif grid --seed 1 | experiments/M2_motif/val/seed1, results/tables/m2_gate.json, m2_val_grid_seed1.csv | 18ea738bd5d33187 f3c21bee60d7076c ; 11 s compute; caps never bound |
| M3 tests | 5 passed | pytest tests/test_m3_flow.py | | |
| **M3 seed-1 val gate** | **FAIL -> R0**: best (eps 0.01, D 6 h, 1 hop) 0.5693 < 0.5852 | python -m evaluation.m3_flow grid --seed 1 | experiments/M3_flow/val/seed1, results/tables/m3_gate.json, m3_val_grid_seed1.csv | f083c712b0236e24 96f5e55bba0677d2 ; 7 s compute |
| Track summary + Holm (m = 3) | written | — | results/notes/m_track.md | a2ff9d435cab189a31ae759050da4476b514bf9fa3d4dcc4f1e839c47bb8c650 |
| HI-Medium | not started | | | |

## Files created by this track (2026-11-15)

Key hashes (sha256):
```
5b14316ffb34f3469935435fad5c94bd582cba283903826ca9cbd197729b4d49 *paper/PREREG_METHOD_2026-11-15.md
7feb2334cd74bb1e187cb604bf6271259feb0fd93295ed2c21120b3ab37795bd *paper/PREREG_METHOD_AMENDMENT_2026-11-15.md
60dbe5c13348f8efaf0e2b8ebe3a72e8986afdffcbf6a3a466175411df802b2b *paper/PREREG_METHOD_AMENDMENT2_2026-11-15.md
dea2ac41eee4bfc3e76ff2057f7f9df40dac56710dfd192cc2ce1e83cdbbfbec *experiments/M1_verifier/chosen_cells.json
feadd03e52d3d89765cd259a5e7e5bc385219ecb7acf41c544078de4930476b7 *results/tables/m1_primary.json
18ea738bd5d331879badf8881a3e880f72ecf992ae28ff610a9b8b3a0b0b29c8 *results/tables/m2_gate.json
f083c712b0236e241febe919f0816ee163bec2412d6b2d09cf58d8c6480c577a *results/tables/m3_gate.json
f7409a6ff7698b4470f23e7d6c1deb44d3fdec2cc5038cb0314b4c5cdad75b36 *results/notes/m_track.md
```

All files (code, tests, notes, tables; experiment folders listed as directories with file counts):

- `paper/PREREG_METHOD_2026-11-15.md`
- `paper/PREREG_METHOD_AMENDMENT_2026-11-15.md`
- `paper/PREREG_METHOD_AMENDMENT2_2026-11-15.md`
- `paper/METHOD_PROGRESS.md`
- `evaluation/m1_verifier.py`
- `evaluation/m2_motif.py`
- `evaluation/m3_flow.py`
- `tests/test_m1_verifier.py`
- `tests/test_m2_motif.py`
- `tests/test_m3_flow.py`
- `results/notes/m_track.md`
- `results/tables/m1_per_seed.csv`
- `results/tables/m1_posthoc.csv`
- `results/tables/m1_posthoc_a_val.csv`
- `results/tables/m1_posthoc_b_val.csv`
- `results/tables/m1_posthoc_c_val.csv`
- `results/tables/m1_primary.json`
- `results/tables/m1_test_arms.json`
- `results/tables/m1_test_arms_per_seed.csv`
- `results/tables/m2_gate.json`
- `results/tables/m2_val_grid_seed1.csv`
- `results/tables/m3_gate.json`
- `results/tables/m3_val_grid_seed1.csv`
- `experiments/M1_verifier/` (272 files)
- `experiments/M2_motif/` (3 files)
- `experiments/M3_flow/` (2 files)
