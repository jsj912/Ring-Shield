"""Column contracts shared by the two teammates.

The scored_edges contract is one row per test-period transaction (edge). Column
order below *is* the contract order; make_scored_edges.py writes exactly these
columns in exactly this order.
"""

# name -> pandas dtype string used when writing / validating the parquet
SCORED_EDGES_COLUMNS = {
    "EdgeID": "int64",              # arange index the loader assigned; unique
    "from_id": "int64",             # account id (loader account_map)
    "to_id": "int64",
    "from_bank": "int64",           # bank id of the sending account
    "to_bank": "int64",             # bank id of the receiving account
    "tenant_id": "int64",           # = from_bank for now
    "timestamp": "int64",           # seconds since dataset start (test-parquet Timestamp)
    "amount_sent": "float64",
    "amount_received": "float64",
    "currency_sent": "int64",       # loader's integer encoding
    "currency_received": "int64",
    "payment_format": "int64",      # loader's integer encoding
    "true_label": "int64",          # 'Is Laundering'
    "score_raw": "float64",         # model pred_prob; NaN when the model produced none
    "score_calibrated": "float64",  # == score_raw until Step 3 adds calibration
    "is_seed": "bool",              # predicted_label == 1; False when score_raw is NaN
    "model_id": "string",
    "seed": "int64",
}

SCORED_EDGES_ORDER = list(SCORED_EDGES_COLUMNS)

# Exact header expected from score_test_set.py / attach_ids_to_predictions.py
PREDICTIONS_WITH_IDS_COLUMNS = [
    "EdgeID", "from_id", "to_id", "Timestamp",
    "true_label", "pred_prob", "predicted_label",
]

# Test-parquet -> contract renames (step 1.2, item 4)
TEST_PARQUET_RENAMES = {
    "Timestamp": "timestamp",
    "Amount Sent": "amount_sent",
    "Amount Received": "amount_received",
    "Sent Currency": "currency_sent",
    "Received Currency": "currency_received",
    "Payment Format": "payment_format",
}
