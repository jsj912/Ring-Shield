"""Part C (amendment d2cfe2fb…): remap HI-Medium's currency / payment-format codes to HI-Small's numbering by name.

    .venv312/Scripts/python.exe evaluation/hm_vocab_remap.py

Sources (read-only): E:/JSJ/Ring-Shield/data/raw/HI-Small_Trans.csv, E:/JSJ/Ring-Shield/data/raw_hi_medium/{HI-Medium_Trans.csv,
formatted_transactions.csv}. The formatter numbers categories by first appearance (scripts/format_kaggle_files_fast.py:
currencies interleaved receiving/paying per row; formats alone). Both vocabularies are rebuilt that way, the HI-Medium
codes are verified against the formatted file by per-code counts, and a new copy is written to
experiments/R18_hm_transfer/raw/HI-Medium/formatted_transactions.csv with Sent/Received Currency and Payment Format
recoded to HI-Small's ids. Writes mapping.json beside it. Stops if a HI-Medium category has no HI-Small counterpart.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pc

R = Path(__file__).resolve().parents[1]
RAW_HS = Path("E:/JSJ/Ring-Shield/data/raw/HI-Small_Trans.csv")
RAW_HM = Path("E:/JSJ/Ring-Shield/data/raw_hi_medium/HI-Medium_Trans.csv")
FMT_HM = Path("E:/JSJ/Ring-Shield/data/raw_hi_medium/formatted_transactions.csv")
OUT = R / "experiments" / "R18_hm_transfer" / "raw" / "HI-Medium"


def vocab(path: Path):
    t = pc.read_csv(path, convert_options=pc.ConvertOptions(
        include_columns=["Receiving Currency", "Payment Currency", "Payment Format"]))
    rc, pcur = t["Receiving Currency"].combine_chunks(), t["Payment Currency"].combine_chunks()
    n = len(rc)
    idx = np.empty(2 * n, dtype=np.int64); idx[0::2] = np.arange(n); idx[1::2] = np.arange(n) + n
    inter = pa.chunked_array([rc, pcur]).combine_chunks().take(pa.array(idx))
    cur = inter.dictionary_encode().dictionary.to_pylist()
    fmt_enc = t["Payment Format"].combine_chunks().dictionary_encode()
    recv_counts = pd.Series(rc.to_pylist()).value_counts()
    fmt_counts = pd.Series(t["Payment Format"].combine_chunks().to_pylist()).value_counts()
    return cur, fmt_enc.dictionary.to_pylist(), recv_counts, fmt_counts


def main():
    hs_cur, hs_fmt, _, _ = vocab(RAW_HS)
    hm_cur, hm_fmt, hm_recv_counts, hm_fmt_counts = vocab(RAW_HM)
    missing = sorted(set(hm_cur) - set(hs_cur)) + sorted(set(hm_fmt) - set(hs_fmt))
    if missing:
        sys.exit(f"STOP: HI-Medium categories with no HI-Small counterpart: {missing}")
    cur_map = {i: hs_cur.index(name) for i, name in enumerate(hm_cur)}
    fmt_map = {i: hs_fmt.index(name) for i, name in enumerate(hm_fmt)}
    df = pd.read_csv(FMT_HM)
    # verify the formatted HI-Medium codes are the first-appearance codes (per-code counts match the raw names)
    got_recv = df["Received Currency"].value_counts()
    got_fmt = df["Payment Format"].value_counts()
    for code, name in enumerate(hm_cur):
        assert int(got_recv.get(code, 0)) == int(hm_recv_counts.get(name, 0)), ("currency", code, name)
    for code, name in enumerate(hm_fmt):
        assert int(got_fmt.get(code, 0)) == int(hm_fmt_counts.get(name, 0)), ("format", code, name)
    for col, mp in (("Sent Currency", cur_map), ("Received Currency", cur_map), ("Payment Format", fmt_map)):
        df[col] = df[col].map(mp).astype(np.int64)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "formatted_transactions.csv", index=False)
    meta = {"hi_small_currency": hs_cur, "hi_medium_currency": hm_cur, "currency_hm_to_hs": cur_map,
            "hi_small_format": hs_fmt, "hi_medium_format": hm_fmt, "format_hm_to_hs": fmt_map,
            "verified": "per-code counts of the formatted HI-Medium file equal the raw per-name counts",
            "rows": int(len(df)), "source": str(FMT_HM)}
    (OUT / "mapping.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("currency_hm_to_hs", "format_hm_to_hs", "rows")}, indent=1))


if __name__ == "__main__":
    main()
