"""V3.2 gap #1: does every pattern transaction actually exist in the release's `_Trans.csv`?

    python preprocessing/verify_patterns.py --dataset HI-Small      # control: must be clean
    python preprocessing/verify_patterns.py --dataset HI-Medium

`docs/V3_OBSERVABILITY.md` counted HI-Medium's rings straight out of `HI-Medium_Patterns.txt`
without checking that each of those lines is a real transaction. A pattern line that has no row
in `_Trans.csv` would inflate every ring count in that document and would be unreachable by any
detector. This closes that gap before a split is built on those counts.

A pattern line and a transaction row are the **same 11 comma-separated fields in the same order**
(verified on both releases), so the check is done on raw text and needs no account map at all --
in particular none of `rebuild_account_map`'s per-row `iterrows` pass, which is O(rows) in Python
and would take hours on 31.9 M rows. The file is streamed in byte blocks and never held whole.

Three key levels are counted, because they answer different questions:

    strict      all 11 fields                              -- the line exists verbatim
    requested   timestamp, both bank+account, both amounts -- V3.2's key; ignores currency,
                                                              payment format and the label
    loose       timestamp, both bank+account               -- what `amlworld_loader` merges on
                                                              (`from_id`, `to_id`, `Timestamp`),
                                                              so its row count is the loader's

For HI-Small the loose level must reproduce the shipped 3,209 pattern lines -> 3,455 flagged
rows (`docs/PROGRESS.md`, Step 3a); that is the control this script is trusted by.

Writes `results/tables/v3_pattern_match_<dataset>.json`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RAW = REPO_ROOT / "data" / "raw"
OUT = REPO_ROOT / "results" / "tables"
BLOCK = 1 << 26                                  # 64 MiB
_BEGIN = re.compile(rb"BEGIN LAUNDERING ATTEMPT - ([A-Z\-]+)")
EXPECTED_HEADER = (b"Timestamp,From Bank,Account,To Bank,Account,Amount Received,"
                   b"Receiving Currency,Amount Paid,Payment Currency,Payment Format,"
                   b"Is Laundering")


def keys_of(line: bytes) -> tuple[bytes, bytes, bytes]:
    """(strict, requested, loose) keys for one raw CSV line. Field order:
    0 Timestamp | 1 From Bank | 2 Account | 3 To Bank | 4 Account | 5 Amount Received |
    6 Receiving Currency | 7 Amount Paid | 8 Payment Currency | 9 Payment Format | 10 Is Laundering"""
    p = line.split(b",", 8)
    loose = b",".join(p[:5])
    return line, loose + b"," + p[5] + b"," + p[7], loose


def read_pattern_lines(path: Path) -> list[tuple[int, str, bytes]]:
    """(ring_id, pattern_type, raw line) for every transaction line inside a BEGIN/END block."""
    out = []
    rid, pat = 0, None
    with open(path, "rb") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(b"BEGIN LAUNDERING ATTEMPT"):
                m = _BEGIN.match(line)
                pat = m.group(1).decode() if m else None
                rid += 1
                continue
            if line.startswith(b"END LAUNDERING ATTEMPT"):
                pat = None
                continue
            if pat is None or line.count(b",") < 10:
                continue
            out.append((rid, pat, line))
    return out


def scan(trans: Path, want_loose: set, want_req: set, want_strict: set) -> tuple[Counter, Counter, Counter, int]:
    """One streaming pass: how many transaction rows match each pattern key, per level."""
    hit_loose, hit_req, hit_strict = Counter(), Counter(), Counter()
    n, rest = 0, b""
    with open(trans, "rb") as f:
        first = True
        while True:
            block = f.read(BLOCK)
            if not block:
                break
            block = rest + block
            lines = block.split(b"\n")
            rest = lines.pop()
            for line in lines:
                if line.endswith(b"\r"):
                    line = line[:-1]
                if first:
                    first = False
                    assert line == EXPECTED_HEADER, f"unexpected header: {line[:120]!r}"
                    continue
                if not line:
                    continue
                n += 1
                p = line.split(b",", 8)
                if len(p) < 9:
                    continue
                loose = b",".join(p[:5])
                if loose in want_loose:
                    hit_loose[loose] += 1
                    req = loose + b"," + p[5] + b"," + p[7]
                    if req in want_req:
                        hit_req[req] += 1
                    if line in want_strict:
                        hit_strict[line] += 1
            if n % 20_000_000 < 2_000_000:
                print(f"      {n:,} rows", flush=True)
    if rest.strip():
        line = rest.strip()
        n += 1
        p = line.split(b",", 8)
        if len(p) >= 9:
            loose = b",".join(p[:5])
            if loose in want_loose:
                hit_loose[loose] += 1
                req = loose + b"," + p[5] + b"," + p[7]
                if req in want_req:
                    hit_req[req] += 1
                if line in want_strict:
                    hit_strict[line] += 1
    return hit_loose, hit_req, hit_strict, n


def report(level: str, want: Counter, hits: Counter) -> dict:
    """`want` counts pattern lines per key (a key can repeat in the pattern file)."""
    matched = [k for k in want if hits.get(k, 0) >= 1]
    unmatched = [k for k in want if hits.get(k, 0) == 0]
    dup = [k for k in want if hits.get(k, 0) > 1]
    lines_matched = sum(want[k] for k in matched)
    return {"level": level,
            "distinct_keys": len(want),
            "pattern_lines": int(sum(want.values())),
            "keys_matched": len(matched),
            "keys_unmatched": len(unmatched),
            "keys_matched_more_than_once": len(dup),
            "pattern_lines_matched": lines_matched,
            "pattern_lines_unmatched": int(sum(want.values())) - lines_matched,
            "transaction_rows_matched": int(sum(hits.values())),
            "examples_unmatched": [k.decode(errors="replace") for k in unmatched[:5]]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="HI-Medium")
    ap.add_argument("--out-dir", type=Path, default=OUT)
    a = ap.parse_args(argv)
    pat_path = RAW / f"{a.dataset}_Patterns.txt"
    trans_path = RAW / f"{a.dataset}_Trans.csv"
    for p in (pat_path, trans_path):
        assert p.exists(), p
    rows = read_pattern_lines(pat_path)
    n_rings = len({r for r, _, _ in rows})
    print(f"[verify] {a.dataset}: {len(rows):,} pattern transaction lines in {n_rings:,} rings")

    want_strict, want_req, want_loose = Counter(), Counter(), Counter()
    for _, _, line in rows:
        s, r, l = keys_of(line)
        want_strict[s] += 1
        want_req[r] += 1
        want_loose[l] += 1
    print(f"[verify] distinct keys: strict {len(want_strict):,}, requested {len(want_req):,}, "
          f"loose {len(want_loose):,}")
    print(f"[verify] streaming {trans_path.name} ({trans_path.stat().st_size / 1e9:.1f} GB)…",
          flush=True)
    hl, hr, hs, n_rows = scan(trans_path, set(want_loose), set(want_req), set(want_strict))
    print(f"[verify] {n_rows:,} transaction rows read")

    res = [report("strict", want_strict, hs), report("requested", want_req, hr),
           report("loose", want_loose, hl)]
    for d in res:
        print(f"\n  == {d['level']} ==")
        for k in ("distinct_keys", "pattern_lines", "keys_matched", "keys_unmatched",
                  "keys_matched_more_than_once", "pattern_lines_matched",
                  "pattern_lines_unmatched", "transaction_rows_matched"):
            print(f"     {k:32s} {d[k]:,}")
        if d["examples_unmatched"]:
            print("     unmatched examples:")
            for e in d["examples_unmatched"]:
                print(f"       {e}")

    ok = all(d["keys_unmatched"] == 0 for d in res)
    payload = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "dataset": a.dataset, "pattern_lines": len(rows), "rings": n_rings,
               "transaction_rows": n_rows, "levels": res, "all_matched": ok}
    a.out_dir.mkdir(parents=True, exist_ok=True)
    p = a.out_dir / f"v3_pattern_match_{a.dataset}.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n-> {p}")
    print(f"[verify] {a.dataset}: "
          + ("every pattern transaction exists in the transaction file"
             if ok else "*** UNMATCHED PATTERN TRANSACTIONS -- STOP ***"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
