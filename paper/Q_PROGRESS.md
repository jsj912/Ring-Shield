# Q track progress

| step | status | command | outputs (sha256) |
|---|---|---|---|
| Reading | done | — | notes in results/notes/q_track.md |
| Ref check B0 | PASS 0.52132 | `score_external.py --rings ../RS-e2e/experiments/R2_b0/gine_causal/seed{1..5}/rings.parquet --split test --window primary --out results/tables/q0_ref_b0` | q0_ref_b0/config.json lists input sha256 |
| Ref check full | PASS 0.58945 | same, `experiments/R4_partition/runs/average/seed{1..5}`, `--out results/tables/q0_ref_full` | q0_ref_full/ |
| Q0 tests | 9 pass | `python -m pytest tests/test_q0_buckets.py` | — |
| Q0 | done, reported; awaiting go-ahead for prereg | `CUDA_VISIBLE_DEVICES="" python -m evaluation.q0_loss_decomposition` | q0_buckets.csv dfed40dc…; _by_pattern 290d1ef3…; _per_ring 6366f8fb…; .json 1779eb80… |
| Q0 bucket-a detail + val window | done | `python -m evaluation.q0_loss_decomposition` and `--split val --out-prefix results/tables/q0_val_buckets` | q0_*_a_by_visible.csv, q0_*_a_how.csv, q0_val_buckets*.csv |
| Rebuild-route check | PASS, 0/870 buckets differ | `--rebuild` on test; embeddings for seeds 2-5 and checkpoints read-only from ../RS-e2e/experiments/R1_gine_causal (sha256 logged in q_track.md) | — |
| Prereg | frozen | — | paper/PREREG_Q_2026-11-15.md aa991ccee83d0f103a9f3af692d4f638705a33a824637893d6749ae97dbbff45 |
| Prereg amendment (Q1 budget definition) | frozen, before any Q data | — | paper/PREREG_Q_AMENDMENT_2026-11-15.md 04b847f28dbda35c17d536701046d195c29550b149da96e456990bf7e2947101 |
| Prereg amendment 2 (Q2-top3 description) | frozen, before any Q2 data | — | paper/PREREG_Q_AMENDMENT2_2026-11-15.md 6770c1b53678c96e22bc805cf6c3ab5f931f6befceefd448b8ed8bbf59105de8 |
| Q3 | done (descriptive) | `python -m evaluation.q3_overlap` | q3_overlap.csv, .json |
| Q1 | STOPPED by rule: 0 ties at q on every seed | inline, see q_track.md | q1_ties.csv d352c73e… |
| Q5 | plan written | — | q_track.md |
| Q6 | validation chose shipped on all seeds; test Δ 0 | `q6_rescue --split val`; `--select`; `--split test --cells-from choices.json` | val_grid.csv, choices.json, q6_vs_full/ |
| Q2 | top3 chosen on val; test WORSE Δ −0.138, Holm p 0.0004 | `q2_account_seeds --split val`; `--split test --variants top3`; score_external + --compare | q2_test_{b0,full}/, q2_vs_full/, q_family_holm.csv |
| Q4 | dropped by author: merges + splits = 2.8 rings/seed | — | — |

Resource check: R6_megagenagg seed 3 epochs at 530–551 s, under the 600 s pause line. CPU capped at ≤ 8 threads.
bb655dbb290038dd*results/tables/q_family_holm.csv
74f0fc5bf1680025*experiments/Q6_rescue/choices.json
956e1e21bccc6814*results/tables/q2_vs_full/compare.csv

Close-out 2026-11-15: Q6 row corrected (arm identical ring for ring; excluded from Holm; the ±0.0043 is a tie-break artefact in greedy matching). Q2 secondary columns in q2_secondary.csv (added-member precision not available without a rerun). Q6 validation grid in q6_val_grid*.csv; candidates in experiments/Q6_rescue/val_candidates/ (git-ignored). T-P5 paragraphs in q_track.md. Q5 not started. TRACK CLOSED.
Q7 tie audit 2026-11-15: `python -m evaluation.q7_tie_audit` → q7_tie_audit.csv, q7_tie_audit_pairs.csv; no point estimate moves under 200 orders; no verdict affected; FINDINGS note proposed in q_track.md. Stopped.
