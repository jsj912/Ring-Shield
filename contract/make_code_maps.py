"""Decode the integer codes in the contract back to the names AMLworld used.

    python contract/make_code_maps.py              # writes the maps + verifies against processed
    python contract/make_code_maps.py --dry-run

`scripts/format_kaggle_files.py` replaced every string in the raw transactions file with an
integer, by first appearance, and kept no record of the mapping. `currency_sent`,
`currency_received` and `payment_format` in the rings contract are those integers, so a narrative
that says "payment format 3" is quoting a number nobody can read. This recovers the mapping.

The encoding is reproduced exactly, not guessed. Per raw row, `format_kaggle_files.py` does:

    cur_recv = get_dict_val(str(row["Receiving Currency"]), currency_map)   # assigned FIRST
    cur_paid = get_dict_val(str(row["Payment Currency"]), currency_map)     # then this
    fmt      = get_dict_val(str(row["Payment Format"]), payment_format_map)

`get_dict_val` hands out `len(collection)` for an unseen name, so codes are in order of first
appearance -- and because the *receiving* currency is presented before the *payment* currency
within each row, the order is recv[0], paid[0], recv[1], paid[1], ... That interleaving is why
`currency 0` is the first row's RECEIVING currency and not simply "the first currency in the file".
`pd.factorize` assigns codes in order of first appearance, so factorising the interleaved array
reproduces the dict exactly.

Verification is end to end: the re-encoded columns are compared, row for row, against the processed
parquets. `EdgeID` cannot be used as the join key directly -- `format_kaggle_files.py` stores the
raw row index in that column, then **overwrites it** with `range(len(df))` after a stable mergesort
on Timestamp -- so the sort is replicated here instead. If any of that drifts, the assert fails and
nothing is written.

Banks are handled too, for the reason in `--help`: see the module note below.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402

RAW_COLS = ["Timestamp", "Receiving Currency", "Payment Currency", "Payment Format"]


def replay_encoding(raw: pd.DataFrame) -> tuple[dict, dict, pd.DataFrame]:
    """Reproduce format_kaggle_files.py's two string->int dicts, and the per-row codes."""
    recv = raw["Receiving Currency"].astype(str).to_numpy()
    paid = raw["Payment Currency"].astype(str).to_numpy()
    # recv[0], paid[0], recv[1], paid[1], ... -- the order get_dict_val actually saw
    interleaved = np.empty(len(raw) * 2, dtype=object)
    interleaved[0::2] = recv
    interleaved[1::2] = paid
    codes, names = pd.factorize(interleaved)           # codes in order of first appearance
    currency_map = {str(n): int(i) for i, n in enumerate(names)}

    fmt_codes, fmt_names = pd.factorize(raw["Payment Format"].astype(str).to_numpy())
    payment_format_map = {str(n): int(i) for i, n in enumerate(fmt_names)}

    per_row = pd.DataFrame({
        "raw_row": np.arange(len(raw), dtype=np.int64),
        "Received Currency": codes[0::2].astype(np.int64),
        "Sent Currency": codes[1::2].astype(np.int64),
        "Payment Format": fmt_codes.astype(np.int64),
    })
    return currency_map, payment_format_map, per_row


def edge_ids(raw: pd.DataFrame, per_row: pd.DataFrame) -> pd.DataFrame:
    """Replicate the stable sort that assigns EdgeID, so the codes can be compared row for row.

    `ts` in the formatter is `dt.timestamp() - (midnight of the first row's day).timestamp() + 10`.
    Both terms use the same local timezone, so the offset cancels and the difference is computed
    here with naive datetimes -- no tz assumption, and no dependence on the machine's locale.
    """
    dt = pd.to_datetime(raw["Timestamp"], format="%Y/%m/%d %H:%M")
    day0 = dt.iloc[0].normalize()
    ts = ((dt - day0).dt.total_seconds() + 10).astype(np.int64)
    out = per_row.assign(Timestamp=ts.to_numpy())
    out = out.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
    out["EdgeID"] = np.arange(len(out), dtype=np.int64)
    return out


def verify(encoded: pd.DataFrame, pdir: Path) -> dict:
    """Compare the re-encoded columns against the processed parquets, row for row."""
    cols = ["EdgeID", "Timestamp", "Sent Currency", "Received Currency", "Payment Format"]
    proc = pd.concat([pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=cols)
                      for s in ("train", "val", "test")], ignore_index=True)
    proc = proc.sort_values("EdgeID", kind="mergesort").reset_index(drop=True)
    assert len(proc) == len(encoded), (
        f"row count: processed {len(proc):,} vs re-encoded {len(encoded):,}; "
        f"this raw file is not the one the processed parquets were built from")
    enc = encoded.sort_values("EdgeID", kind="mergesort").reset_index(drop=True)
    report = {"n_rows": int(len(proc))}
    for c in ("Timestamp", "Sent Currency", "Received Currency", "Payment Format"):
        same = int((enc[c].to_numpy() == proc[c].to_numpy()).sum())
        report[c] = {"matching_rows": same, "mismatched": int(len(proc) - same)}
        assert same == len(proc), (
            f"{c}: {len(proc) - same:,} of {len(proc):,} rows differ -- the encoding was NOT "
            f"reproduced, so the maps would be wrong. Nothing written.")
    return report


def bank_names(raw_dir: Path, dataset: str, pdir: Path) -> tuple[dict, dict]:
    """Bank id -> name, from <dataset>_accounts.csv.

    Recorded because the opposite was assumed: bank **names do exist**. `<dataset>_accounts.csv`
    carries `Bank Name` beside `Bank ID`, and the contract's `from_bank` / `to_bank` ARE that
    `Bank ID` -- every bank code in the processed splits resolves. A name is NOT a unique key
    (several distinct ids share one name), so it is a label for display, never a join key.
    """
    f = raw_dir / f"{dataset}_accounts.csv"
    if not f.exists():
        return {}, {"present": False, "reason": f"{f.name} not found"}
    a = pd.read_csv(f, usecols=["Bank Name", "Bank ID"])
    m = a.drop_duplicates("Bank ID").set_index("Bank ID")["Bank Name"]
    proc = pd.concat([pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=["from_bank", "to_bank"])
                      for s in ("train", "val", "test")], ignore_index=True)
    used = pd.unique(pd.concat([proc["from_bank"], proc["to_bank"]]))
    resolved = int(pd.Index(used).isin(m.index).sum())
    return ({str(int(k)): str(v) for k, v in m.items()},
            {"present": True, "source": f.name, "n_bank_ids": int(m.size),
             "n_distinct_names": int(a["Bank Name"].nunique()),
             "n_banks_used_in_splits": int(len(used)), "n_resolved": resolved,
             "all_resolved": resolved == len(used),
             "name_is_unique_key": bool(a.drop_duplicates("Bank ID")["Bank Name"].is_unique)})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=None, help="default <raw_dir>/<dataset>_Trans.csv")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "contract")
    ap.add_argument("--no-banks", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    paths = load_paths()
    dataset = str(paths.get("dataset", "HI-Small"))
    raw = a.raw or (paths["raw_dir"] / f"{dataset}_Trans.csv")
    pdir = paths["processed_dir"]
    print(f"[maps] dataset {dataset}; reading {raw}")
    df = pd.read_csv(raw, usecols=RAW_COLS)
    print(f"[maps] {len(df):,} raw rows")

    cur, fmt, per_row = replay_encoding(df)
    print(f"[maps] currencies {len(cur)}, payment formats {len(fmt)}")
    enc = edge_ids(df, per_row)
    rep = verify(enc, pdir)
    print(f"[maps] VERIFIED against the processed parquets: {rep['n_rows']:,} rows, "
          f"0 mismatches on Timestamp, Sent Currency, Received Currency and Payment Format")

    inv_cur = {str(v): k for k, v in cur.items()}
    inv_fmt = {str(v): k for k, v in fmt.items()}
    print(f"[maps] currency 0 = {inv_cur['0']!r}  (the FIRST raw row's *receiving* currency)")
    print(f"[maps] payment format 0 = {inv_fmt['0']!r}")

    banks, bank_meta = ({}, {"present": False}) if a.no_banks else bank_names(paths["raw_dir"], dataset, pdir)
    if bank_meta.get("present"):
        print(f"[maps] bank names DO exist: {bank_meta['n_bank_ids']:,} ids, "
              f"{bank_meta['n_distinct_names']:,} distinct names, "
              f"{bank_meta['n_resolved']:,}/{bank_meta['n_banks_used_in_splits']:,} used banks resolved; "
              f"name unique per id: {bank_meta['name_is_unique_key']}")

    if a.dry_run:
        print("[maps] DRY RUN -- nothing written")
        return cur, fmt

    stamp = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "dataset": dataset, "source": str(raw),
             "encoder": "scripts/format_kaggle_files.py, reproduced and verified row-for-row "
                        "against the processed parquets by contract/make_code_maps.py",
             "verification": rep}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "currency_map.json").write_text(json.dumps(
        {**stamp,
         "note": "code order is first appearance, and within each raw row the RECEIVING currency "
                 "is assigned before the PAYMENT currency -- hence code 0 is the first row's "
                 "receiving currency",
         "code_to_name": inv_cur, "name_to_code": cur}, indent=2), encoding="utf-8")
    (a.out_dir / "payment_format_map.json").write_text(json.dumps(
        {**stamp, "note": "code order is first appearance in the raw file",
         "code_to_name": inv_fmt, "name_to_code": fmt}, indent=2), encoding="utf-8")
    print(f"-> {a.out_dir / 'currency_map.json'}")
    print(f"-> {a.out_dir / 'payment_format_map.json'}")
    if banks:
        (a.out_dir / "bank_names.json").write_text(json.dumps(
            {**stamp, "note": "from <dataset>_accounts.csv. The contract's from_bank / to_bank ARE "
                              "the raw Bank ID. A name is NOT unique per id: use it for display, "
                              "never as a join key.",
             "meta": bank_meta, "id_to_name": banks}, indent=2), encoding="utf-8")
        print(f"-> {a.out_dir / 'bank_names.json'}")
    return cur, fmt


if __name__ == "__main__":
    main()
