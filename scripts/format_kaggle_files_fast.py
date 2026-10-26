"""Vectorised `format_kaggle_files.py` — same output, without the per-row Python loop.

    python scripts/format_kaggle_files_fast.py data/raw/HI-Small_Trans.csv out.csv
    python scripts/format_kaggle_files_fast.py data/raw/HI-Small_Trans.csv --verify

`scripts/format_kaggle_files.py` walks the raw CSV with `iterrows`, which is fine for HI-Small's
5.1 M rows and impossible for HI-Medium's 31.9 M (it would also materialise a 31.9 M-element list
of Python lists). This reproduces it exactly with Arrow dictionary encoding, which numbers keys
**in order of first appearance** — the same rule the original's `get_dict_val` applies.

Semantics reproduced, in the original's order:

* per row the ids are assigned **Receiving Currency, Payment Currency, Payment Format, from
  account, to account** — so the interleave of the two account (and two currency) columns matters
  and is done explicitly;
* the account key is `str(bank) + str(account)` with pandas' own `str()` of the parsed value, so a
  numeric-looking bank loses its leading zeros;
* `Timestamp` is seconds from `midnight(first row's date) - 10`, computed from the calendar fields
  rather than `datetime.timestamp()` so it cannot shift across a DST boundary;
* rows are sorted by `Timestamp` with a **stable** sort (`mergesort`) and `EdgeID` is assigned
  0..n-1 *after* the sort, exactly as the original does.

`--verify` re-runs against HI-Small and checks the sha256 against `docs/data_manifest.json`'s
`formatted_transactions.csv` entry. That check is what licenses using this on HI-Medium.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_COLUMNS = ["EdgeID", "from_id", "to_id", "Timestamp", "Amount Sent", "Sent Currency",
               "Amount Received", "Received Currency", "Payment Format", "Is Laundering"]
EPOCH_OFFSET = 10


def _interleave(a: pa.Array, b: pa.Array) -> pa.Array:
    """[a0, b0, a1, b1, ...] — the order in which the original assigns ids within a row."""
    n = len(a)
    idx = np.empty(2 * n, dtype=np.int64)
    idx[0::2] = np.arange(n)
    idx[1::2] = np.arange(n) + n
    return pa.concat_arrays([a.combine_chunks() if isinstance(a, pa.ChunkedArray) else a,
                             b.combine_chunks() if isinstance(b, pa.ChunkedArray) else b]).take(idx)


def _codes_first_appearance(inter: pa.Array) -> tuple[np.ndarray, np.ndarray, int]:
    """Dictionary-encode in order of first appearance; return (codes_a, codes_b, n_unique)."""
    enc = inter.dictionary_encode()
    codes = enc.indices.to_numpy(zero_copy_only=False)
    return codes[0::2], codes[1::2], len(enc.dictionary)


def format_file(in_path: Path, out_path: Path, block_mb: int = 256) -> Path:
    print(f"Reading {in_path} …", flush=True)
    tbl = pcsv.read_csv(
        in_path,
        read_options=pcsv.ReadOptions(block_size=block_mb << 20),
        convert_options=pcsv.ConvertOptions(column_types={
            "Timestamp": pa.string(), "From Bank": pa.string(), "To Bank": pa.string(),
            "Amount Received": pa.float64(), "Amount Paid": pa.float64(),
            "Receiving Currency": pa.string(), "Payment Currency": pa.string(),
            "Payment Format": pa.string(), "Is Laundering": pa.int8()}))
    names = tbl.column_names
    # The header carries "Account" twice. Some pyarrow versions keep both names, others
    # de-duplicate the second to "Account.1", so the columns are taken POSITIONALLY -- which is
    # also what the original does (`row.iloc[2]`, `row.iloc[4]`).
    acc_from_i, acc_to_i = 2, 4
    assert names[1] == "From Bank" and names[3] == "To Bank", names
    n = tbl.num_rows
    print(f"  {n:,} rows", flush=True)

    ts_s = tbl.column("Timestamp").combine_chunks()
    # "YYYY/MM/DD HH:MM" -> day offset from the FIRST ROW's date, plus seconds of day, plus 10
    y = pc.strptime(pc.utf8_slice_codeunits(ts_s, 0, 10), format="%Y/%m/%d", unit="s")
    days = pc.cast(pc.divide(pc.cast(y, pa.int64()), pa.scalar(86400, pa.int64())), pa.int64())
    d0 = days[0].as_py()
    hh = pc.cast(pc.utf8_slice_codeunits(ts_s, 11, 13), pa.int64())
    mm = pc.cast(pc.utf8_slice_codeunits(ts_s, 14, 16), pa.int64())
    ts = (np.asarray(days) - d0) * 86400 + np.asarray(hh) * 3600 + np.asarray(mm) * 60 \
        + EPOCH_OFFSET

    def as_str(col) -> pa.Array:
        c = tbl.column(col) if isinstance(col, str) else tbl.column(col)
        return c.combine_chunks()

    # str(bank) + str(account): a numeric-looking bank is parsed then stringified, which drops
    # leading zeros; an account with hex characters stays as written. Reproduce with a cast
    # through int64 where the whole column is numeric, exactly as pandas' dtype inference does.
    def pandas_str(arr: pa.Array) -> pa.Array:
        try:
            return pc.cast(pc.cast(arr, pa.int64()), pa.string())
        except pa.ArrowInvalid:
            return arr

    fb, tb = pandas_str(as_str("From Bank")), pandas_str(as_str("To Bank"))
    fa = pandas_str(tbl.column(acc_from_i).combine_chunks())
    ta = pandas_str(tbl.column(acc_to_i).combine_chunks())
    from_key = pc.binary_join_element_wise(fb, fa, "")
    to_key = pc.binary_join_element_wise(tb, ta, "")
    from_id, to_id, n_acc = _codes_first_appearance(_interleave(from_key, to_key))
    del fb, tb, fa, ta, from_key, to_key

    cur_recv, cur_paid, _ = _codes_first_appearance(
        _interleave(as_str("Receiving Currency"), as_str("Payment Currency")))
    fmt = as_str("Payment Format").dictionary_encode().indices.to_numpy(zero_copy_only=False)

    df = pd.DataFrame({
        "EdgeID": np.arange(n, dtype=np.int64),
        "from_id": from_id.astype(np.int64), "to_id": to_id.astype(np.int64),
        "Timestamp": ts.astype(np.int64),
        "Amount Sent": tbl.column("Amount Paid").to_numpy(zero_copy_only=False),
        "Sent Currency": cur_paid.astype(np.int64),
        "Amount Received": tbl.column("Amount Received").to_numpy(zero_copy_only=False),
        "Received Currency": cur_recv.astype(np.int64),
        "Payment Format": fmt.astype(np.int64),
        "Is Laundering": tbl.column("Is Laundering").to_numpy(zero_copy_only=False).astype(np.int64),
    })[OUT_COLUMNS]
    del tbl
    print(f"  {n_acc:,} unique accounts; sorting (mergesort) …", flush=True)
    df = df.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
    df["EdgeID"] = np.arange(len(df), dtype=np.int64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  writing {out_path} …", flush=True)
    df.to_csv(out_path, index=False)
    print(f"Done. {len(df):,} transactions, {n_acc:,} unique accounts -> {out_path}")
    return out_path


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("in_path", type=Path, nargs="?")
    ap.add_argument("out_path", type=Path, nargs="?")
    ap.add_argument("--verify", action="store_true",
                    help="format HI-Small to a temp file and compare its sha256 with the manifest")
    a = ap.parse_args(argv)
    if a.verify:
        want = json.loads((REPO_ROOT / "docs" / "data_manifest.json").read_text())
        want = want["files"]["formatted_transactions.csv"]["sha256"]
        tmp = REPO_ROOT / "data" / "raw" / "formatted_transactions.__verify__.csv"
        format_file(REPO_ROOT / "data" / "raw" / "HI-Small_Trans.csv", tmp)
        got = sha256(tmp)
        ok = got == want
        print(f"\n  manifest {want}\n  produced {got}\n  {'MATCH' if ok else 'DIFFER'}")
        tmp.unlink()
        return 0 if ok else 1
    if a.in_path is None:
        ap.error("in_path is required unless --verify")
    out = a.out_path or a.in_path.parent / "formatted_transactions.csv"
    format_file(a.in_path, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
