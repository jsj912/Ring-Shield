"""
Pandas-based replacement for IBM Multi-GNN's format_kaggle_files.py.
Produces the same formatted_transactions.csv output without needing datatable.

Usage:
    python scripts/format_kaggle_files.py data/raw/HI-Small_Trans.csv
"""

import sys
import os
from datetime import datetime
import pandas as pd

if len(sys.argv) < 2:
    print("Usage: python format_kaggle_files.py <path/to/HI-Small_Trans.csv>")
    sys.exit(1)

in_path = sys.argv[1]
out_path = os.path.join(os.path.dirname(in_path), "formatted_transactions.csv")

print(f"Reading {in_path} ...")
raw = pd.read_csv(in_path)

currency_map = {}
payment_format_map = {}
account_map = {}

def get_dict_val(name, collection):
    if name not in collection:
        collection[name] = len(collection)
    return collection[name]

rows = []
first_ts = None

for i, row in raw.iterrows():
    dt_obj = datetime.strptime(str(row["Timestamp"]), "%Y/%m/%d %H:%M")
    ts = dt_obj.timestamp()

    if first_ts is None:
        start_time = datetime(dt_obj.year, dt_obj.month, dt_obj.day)
        first_ts = start_time.timestamp() - 10

    ts = ts - first_ts

    cur_recv = get_dict_val(str(row["Receiving Currency"]), currency_map)
    cur_paid = get_dict_val(str(row["Payment Currency"]), currency_map)
    fmt = get_dict_val(str(row["Payment Format"]), payment_format_map)

    from_acc = str(row["From Bank"]) + str(row.iloc[2])
    to_acc = str(row["To Bank"]) + str(row.iloc[4])
    from_id = get_dict_val(from_acc, account_map)
    to_id = get_dict_val(to_acc, account_map)

    amount_recv = float(row["Amount Received"])
    amount_paid = float(row["Amount Paid"])
    is_laundering = int(row["Is Laundering"])

    rows.append([i, from_id, to_id, int(ts), amount_paid, cur_paid,
                 amount_recv, cur_recv, fmt, is_laundering])

    if (i + 1) % 100000 == 0:
        print(f"  processed {i + 1} rows...")

print(f"Processed {len(rows)} rows total. Sorting by timestamp...")

df = pd.DataFrame(rows, columns=[
    "EdgeID", "from_id", "to_id", "Timestamp",
    "Amount Sent", "Sent Currency", "Amount Received", "Received Currency",
    "Payment Format", "Is Laundering"
])

# Stable sort: rows with equal timestamps keep their raw-file order, so EdgeID is
# reproducible across pandas/numpy builds (the default introsort is not stable).
df = df.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
df["EdgeID"] = range(len(df))

df.to_csv(out_path, index=False)
print(f"Done. Output written to {out_path}")
print(f"  {len(df)} transactions, {len(account_map)} unique accounts")