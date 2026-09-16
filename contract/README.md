# contract/

The two hand-off files between the edge-scoring side and the ring side.

| File | Producer | Schema |
|---|---|---|
| `out/scored_edges_<model>_<seed>.parquet` | `make_scored_edges.py` (Step 1.2) | `schema.py::SCORED_EDGES_COLUMNS` |
| `out/rings_<model>_<seed>.parquet` | Step 1.3 (not yet written) | — |

Parquets are git-ignored; the `*.log.json` next to each one (row counts, NaN count,
inputs, git commit) is committed and is the only thing quoted from these folders.

```bash
python contract/make_scored_edges.py --preds experiments/E6_tgn/predictions_with_ids.csv --model-id gine --seed 1
python -m pytest contract/tests -q
```

Notes on `scored_edges`:

- `timestamp` is the loader's (test-parquet) value. The model scripts re-base time to
  their own minimum, so `predictions_with_ids.csv` is exactly 10 s lower; the script
  asserts this offset is one global constant and records it in the log.
- `from_bank`/`to_bank` come from an account→bank map rebuilt from `HI-Small_Trans.csv`
  with the loader's key rule and validated 100% against `HI-Small_accounts.csv`; it is
  cached at `data/processed/amlworld_account_bank_map.parquet`. `tenant_id = from_bank`.
- `score_calibrated == score_raw` until Step 3. Rows with no model score are kept with
  `score_raw = NaN`, `is_seed = False`.
