# Progress log

One line per step: date, step id, check results, artefact path.

| Date | Step | Checks | Artefacts |
|---|---|---|---|
| 2026-09-16 | 1.1 | zero-byte files: 0 remaining; listed files/dirs deleted; E7 → legacy_E7_test_tuned + README; predictions_with_ids.csv purged from history (git rev-list --objects shows 0 hits); seeds.yaml/paths.yaml parse; README matches tree | `README.md`, `configs/seeds.yaml`, `configs/paths.yaml`, `experiments/legacy_E7_test_tuned/README.md`, `.gitignore` |
| 2026-09-16 | 1.1 (follow-up) | test_attention_extraction.py deleted; score_test_set.py `--arch gatv2` removed, `--help` runs; force-pushed v2/main/modernization with --force-with-lease; 0 predictions_with_ids blobs across all local+remote refs | `score_test_set.py` |
| 2026-09-16 | 1.2 | `pytest contract/tests`: 18 passed (columns/order/dtypes, 1% dry-run deterministic, EdgeID join 100% agree incl. constant 10 s ts offset, account map == loader map, banks == accounts.csv, NaN kept & is_seed False, log written, CLI requires --seed); full run 863,900 rows, 841 NaN, 1,616 seeds | `contract/make_scored_edges.py`, `contract/schema.py`, `contract/tests/test_make_scored_edges.py`, `contract/out/scored_edges_gine_1.parquet` (+`.log.json`) |
