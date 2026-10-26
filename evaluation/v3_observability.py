"""V3.1 -- ring observability vs window length on HI-Medium and HI-Large. Measurement only.

    python evaluation/v3_observability.py --parts profile          # per-day volume (streams the CSVs)
    python evaluation/v3_observability.py                          # everything

This step decides **data**, not method. It asks how much of a ring is visible inside a test window
of a given length, on the two larger AMLworld releases, so that a later step can pick a dataset
and a split without discovering the HI-Small ceiling again.

1. Raw files are hashed into `docs/data_manifest.json` (`scripts/data_manifest.py --datasets`).
2. Per-day transaction volume and prevalence, streamed with only the two columns the measurement
   needs. HI-Large is ~17 GB and is never held in memory.
3. Pattern groups parsed exactly as `preprocessing/amlworld_loader.parse_patterns` does -- the
   parser here is checked against the shipped HI-Small ground truth (370 rings, 3,209
   transactions, per-ring min/max timestamps identical) before it is used on anything else.
4. Contiguous test windows of 2 / 7 / 14 / 21 days inside the clean region: in-scope rings under
   `test_visible`, rings with >= 3 visible members, rings fully contained, and the implied
   ring-recall ceiling. Each length at two positions, with HI-Small's primary window alongside.
5. Feasibility: edges per day, and GFP / GNN cost projected from measured HI-Small runtimes.

Outputs `results/tables/v3_day_profile_<dataset>.csv`, `v3_ring_spans.csv`, `v3_windows.csv`,
`v3_feasibility.csv` and `results/tables/v3_observability.json`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RAW = REPO_ROOT / "data" / "raw"
OUT = REPO_ROOT / "results" / "tables"
DATASETS = ("HI-Small", "HI-Medium", "HI-Large")

# --- clean-region criteria, from docs/TEST_TAIL.md and FINDINGS C8 -------------------------------
# C8: day 0 is a warm-up -- it carries a multiple of the interior volume at many times the
# per-minute density. TEST_TAIL: the run ends in a collapse, days holding a fraction of a per cent
# of the volume at a base rate two orders of magnitude above the interior.
WARMUP_VOLUME_RATIO = 2.0      # leading day counts as warm-up above this multiple of the interior median
TAIL_VOLUME_FRAC = 0.05        # trailing day counts as shutdown below this fraction of the median
TAIL_BASE_RATE_RATIO = 10.0    # ... and above this multiple of the median day's base rate
SECONDS_PER_DAY = 86400
EPOCH_OFFSET = 10              # format_kaggle_files.py: first_ts = midnight(day 0) - 10

# --- measured HI-Small runtimes, for the projections in part 5 ----------------------------------
HI_SMALL_EDGES = 5_078_345
HI_SMALL_TRAIN_EDGES = 3_248_921
HI_SMALL_GFP_MINUTES = 25.0            # PROGRESS 3b-y: "cost ~ 25 min GFP regen" for all 3 splits
HI_SMALL_EPOCH_S = 255.0               # training_summary.json, mean over 5 seeds
HI_SMALL_EPOCHS = 44.4                 # mean epochs_run over 5 seeds
HI_SMALL_HOURS_PER_SEED = HI_SMALL_EPOCH_S * HI_SMALL_EPOCHS / 3600.0

# Candidate splits (day ranges are inclusive, in the clean region of each dataset). Test always
# sits at the END of the clean region, because training days must precede it.
SPLITS = [
    # HI-Medium. Day 0 is the warm-up: excluded from evaluation, kept in TRAIN exactly as the
    # shipped HI-Small split keeps it (train = days 0-5 there).
    {"name": "M1  HI-Medium, 7 d test", "dataset": "HI-Medium",
     "train": (0, 6), "val": (7, 8), "test": (9, 15)},
    {"name": "M2  HI-Medium, 10 d test", "dataset": "HI-Medium",
     "train": (0, 3), "val": (4, 5), "test": (6, 15)},
    {"name": "M3  HI-Medium, 12 d test", "dataset": "HI-Medium",
     "train": (0, 1), "val": (2, 3), "test": (4, 15)},
    {"name": "M1x HI-Medium, 7 d test, no warm-up", "dataset": "HI-Medium",
     "train": (1, 6), "val": (7, 8), "test": (9, 15)},
    # HI-Large: a contiguous slice well away from both the warm-up and the shutdown tail.
    {"name": "L1  HI-Large d55-96, 7 d test", "dataset": "HI-Large",
     "train": (55, 82), "val": (83, 89), "test": (90, 96)},
    {"name": "L2  HI-Large d55-96, 21 d test", "dataset": "HI-Large",
     "train": (55, 68), "val": (69, 75), "test": (76, 96)},
]


# ============================================================ raw scan

def day_profile(dataset: str, block_mb: int = 64) -> pd.DataFrame:
    """Per-calendar-day edge count, illicit count and active minutes, streamed.

    Only `Timestamp` and `Is Laundering` are read. The file is consumed in blocks and never
    materialised; HI-Large is ~182 M rows."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.csv as pcsv
    path = RAW / f"{dataset}_Trans.csv"
    ro = pcsv.ReadOptions(block_size=block_mb << 20)
    co = pcsv.ConvertOptions(include_columns=["Timestamp", "Is Laundering"],
                             column_types={"Timestamp": pa.string(), "Is Laundering": pa.int8()})
    edges: Counter = Counter()
    illicit: Counter = Counter()
    minutes: dict[str, set] = defaultdict(set)
    n = 0
    reader = pcsv.open_csv(path, read_options=ro, convert_options=co)
    for batch in reader:
        ts = batch.column("Timestamp")
        d = pc.utf8_slice_codeunits(ts, 0, 10)
        t = pa.table({"d": d, "lab": batch.column("Is Laundering")})
        agg = t.group_by("d").aggregate([("lab", "sum"), ("lab", "count")])
        for dd, s, c in zip(agg.column("d").to_pylist(), agg.column("lab_sum").to_pylist(),
                            agg.column("lab_count").to_pylist()):
            edges[dd] += int(c)
            illicit[dd] += int(s or 0)
        hm = pc.utf8_slice_codeunits(ts, 0, 16)
        vc = pc.value_counts(hm)
        for st in vc.to_pylist():
            key = st["values"]
            minutes[key[:10]].add(key[11:])
        n += batch.num_rows
        if n % 20_000_000 < batch.num_rows:
            print(f"      {dataset}: {n:,} rows", flush=True)
    days = sorted(edges)
    d0 = date.fromisoformat(days[0].replace("/", "-"))
    rows = []
    for dd in days:
        dt = date.fromisoformat(dd.replace("/", "-"))
        rows.append({"dataset": dataset, "date": dd, "day": (dt - d0).days,
                     "edges": edges[dd], "illicit": illicit[dd],
                     "base_rate": illicit[dd] / edges[dd],
                     "active_minutes": len(minutes[dd]),
                     "edges_per_active_minute": edges[dd] / max(len(minutes[dd]), 1)})
    print(f"  [profile] {dataset}: {n:,} rows over {len(rows)} days, first {days[0]}", flush=True)
    return pd.DataFrame(rows)


def clean_region(prof: pd.DataFrame) -> dict:
    """Warm-up day(s), shutdown tail and the clean region between them.

    The **tail is found first**. A warm-up test that compares a day against the median of
    everything after it is meaningless once the shutdown days are in that median -- every body
    day beats a 400-edge day by more than 2x -- so the warm-up rule is applied to the non-tail
    days only."""
    e = prof.set_index("day")["edges"]
    br = prof.set_index("day")["base_rate"]
    med = float(e.median())
    med_br = float(br.median())
    tail = []
    for d in reversed(list(e.index)):
        if e[d] < TAIL_VOLUME_FRAC * med and br[d] > TAIL_BASE_RATE_RATIO * med_br:
            tail.append(int(d))
        else:
            break
    tail = sorted(tail)
    body = e[~e.index.isin(tail)]
    warm = []
    for d in body.index:
        interior = body[body.index > d]
        if len(interior) and body[d] > WARMUP_VOLUME_RATIO * float(interior.median()):
            warm.append(int(d))
        else:
            break
    lo = (max(warm) + 1) if warm else int(e.index.min())
    hi = (min(tail) - 1) if tail else int(e.index.max())
    body = prof[(prof["day"] >= lo) & (prof["day"] <= hi)]
    return {"warmup_days": warm, "tail_days": tail, "clean_lo": lo, "clean_hi": hi,
            "clean_days": hi - lo + 1,
            "median_edges_per_day": med,
            "clean_edges": int(body["edges"].sum()),
            "clean_edges_per_day": float(body["edges"].mean()),
            "clean_base_rate": float(body["illicit"].sum() / max(body["edges"].sum(), 1)),
            "tail_edges": int(prof[prof["day"].isin(tail)]["edges"].sum()),
            "tail_base_rate": (float(prof[prof["day"].isin(tail)]["illicit"].sum()
                                     / max(prof[prof["day"].isin(tail)]["edges"].sum(), 1))
                               if tail else float("nan"))}


# ============================================================ patterns

_BEGIN = re.compile(r"BEGIN LAUNDERING ATTEMPT - ([A-Z\-]+)")


def _norm(v: str) -> str:
    """format_kaggle_files.py builds the account key as str(pandas value); a numeric-looking
    field loses its leading zeros, a hex one does not."""
    try:
        return str(int(v))
    except ValueError:
        return v


def parse_patterns(path: Path, first_date: date) -> pd.DataFrame:
    """Ring-labelled transactions from a *_Patterns.txt, in the loader's time basis.

    Timestamps are built from the calendar fields rather than `datetime.timestamp()` so the
    result cannot shift across a DST boundary; on HI-Small this reproduces the shipped
    ground-truth timestamps exactly (asserted by `check_parser`)."""
    rows = []
    rid, pat = 0, None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("BEGIN LAUNDERING ATTEMPT"):
                m = _BEGIN.match(line)
                pat = m.group(1) if m else None
                rid += 1
                continue
            if line.startswith("END LAUNDERING ATTEMPT"):
                pat = None
                continue
            if pat is None:
                continue
            p = line.split(",")
            if len(p) < 11:
                continue
            ds, hm = p[0].split(" ")
            y, mo, dd = (int(x) for x in ds.split("/"))
            hh, mi = (int(x) for x in hm.split(":"))
            rows.append((rid, pat,
                         _norm(p[1]) + _norm(p[2]), _norm(p[3]) + _norm(p[4]),
                         (date(y, mo, dd) - first_date).days * SECONDS_PER_DAY
                         + hh * 3600 + mi * 60 + EPOCH_OFFSET,
                         float(p[5])))
    return pd.DataFrame(rows, columns=["ring_id", "pattern_type", "src", "dst", "ts", "amount"])


def check_parser() -> None:
    """The parser must reproduce the shipped HI-Small ground truth before it is trusted."""
    gt = pd.read_parquet(REPO_ROOT / "data" / "processed" / "amlworld_ring_ground_truth.parquet")
    got = parse_patterns(RAW / "HI-Small_Patterns.txt", date(2022, 9, 1))
    a = got.groupby("ring_id")["ts"].agg(["min", "max", "size"])
    b = gt.groupby("ring_id")["timestamp_int"].agg(["min", "max", "size"])
    assert len(got) == len(gt), f"transactions {len(got)} != {len(gt)}"
    assert got["ring_id"].nunique() == gt["ring_id"].nunique(), "ring count differs"
    j = a.join(b, lsuffix="_p", rsuffix="_g", how="inner")
    assert len(j) == len(b) and (j["min_p"] == j["min_g"]).all() and \
           (j["max_p"] == j["max_g"]).all() and (j["size_p"] == j["size_g"]).all(), \
           "per-ring timestamps differ from the shipped ground truth"
    print(f"  [parser] HI-Small check: {len(got)} transactions in {got['ring_id'].nunique()} "
          f"rings, per-ring timestamps identical to the shipped ground truth")


def ring_spans(rings: pd.DataFrame) -> pd.DataFrame:
    g = rings.groupby("ring_id")
    return pd.DataFrame({
        "pattern_type": g["pattern_type"].first(),
        "n_txn": g.size(),
        "n_accounts": g.apply(lambda d: len(set(d["src"]) | set(d["dst"])), include_groups=False),
        "t_min": g["ts"].min(), "t_max": g["ts"].max(),
        "span_h": (g["ts"].max() - g["ts"].min()) / 3600.0}).reset_index()


# ============================================================ window sweep

def window_row(rings: pd.DataFrame, spans: pd.DataFrame, lo: int, hi: int) -> dict:
    """`test_visible` scope: a ring is in scope with >= 1 transaction in [lo, hi]; its scored
    members are the accounts of its in-window transactions only.

    Two thresholds are reported and they mean different things.

    `ge3_members` is the denominator of the project's existing `ring_recall_ge3`
    (`ringshield/evaluate.py`) and is the comparator used throughout V3.1/V3.2. It is **not** an
    upper bound on ring recall: a truth ring with 2 visible members can still be matched, because
    a 3-account prediction containing both scores Jaccard 2/3 = 0.667 >= 0.5. On HI-Small's
    shipped primary window 11.4 matched rings per seed have fewer than 3 visible members.

    `ge2_members` IS the structural bound. A 1-member truth ring cannot reach the 0.5 bar against
    any prediction of >= min_size 3 accounts (best case 1/3), so rings with a single visible
    member are unmatchable and everything else is not excluded a priori."""
    vis = rings[(rings["ts"] >= lo) & (rings["ts"] <= hi)]
    if vis.empty:
        return {"in_scope": 0, "ge3_members": 0, "ge2_members": 0, "fully_contained": 0,
                "ceiling": float("nan"), "bound_ge2": float("nan"),
                "median_visible_members": 0.0, "median_visible_txn": 0.0}
    mem = vis.groupby("ring_id").apply(
        lambda d: len(set(d["src"]) | set(d["dst"])), include_groups=False)
    ntx = vis.groupby("ring_id").size()
    s = spans.set_index("ring_id").loc[mem.index]
    contained = int(((s["t_min"] >= lo) & (s["t_max"] <= hi)).sum())
    return {"in_scope": int(len(mem)), "ge3_members": int((mem >= 3).sum()),
            "ge2_members": int((mem >= 2).sum()),
            "fully_contained": contained,
            "ceiling": float((mem >= 3).sum() / len(mem)),
            "bound_ge2": float((mem >= 2).sum() / len(mem)),
            "median_visible_members": float(mem.median()),
            "median_visible_txn": float(ntx.median())}


def day_bounds(d_lo: int, n_days: int) -> tuple[int, int]:
    return (EPOCH_OFFSET + d_lo * SECONDS_PER_DAY,
            EPOCH_OFFSET + (d_lo + n_days) * SECONDS_PER_DAY - 1)


def sweep(dataset: str, rings: pd.DataFrame, spans: pd.DataFrame, reg: dict,
          lengths=(2, 7, 14, 21)) -> list[dict]:
    rows = []
    lo, hi = reg["clean_lo"], reg["clean_hi"]
    for L in lengths:
        if L > reg["clean_days"]:
            rows.append({"dataset": dataset, "window_days": L, "position": "-",
                         "day_lo": None, "day_hi": None, "fits": False})
            continue
        starts = {"early": lo, "late": hi - L + 1}
        if starts["early"] == starts["late"]:
            starts = {"only": lo}
        for pos, s in starts.items():
            b = day_bounds(s, L)
            r = {"dataset": dataset, "window_days": L, "position": pos,
                 "day_lo": s, "day_hi": s + L - 1, "fits": True}
            r.update(window_row(rings, spans, *b))
            rows.append(r)
    return rows


# ============================================================ feasibility

def test_at_end(dataset: str, rings: pd.DataFrame, spans: pd.DataFrame, reg: dict,
                lengths=range(2, 22)) -> list[dict]:
    """Ceiling as a function of test-window length when the window sits at the END of the clean
    region, which is where a test split has to sit -- training days must precede it. This is the
    curve the split decision is read off, not the free-placement sweep above."""
    rows = []
    hi = reg["clean_hi"]
    for L in lengths:
        s = hi - L + 1
        if s < reg["clean_lo"]:
            break
        r = {"dataset": dataset, "test_days": L, "day_lo": s, "day_hi": hi,
             "train_val_days_available": s - reg["clean_lo"]}
        r.update(window_row(rings, spans, *day_bounds(s, L)))
        r["fully_contained_share"] = r["fully_contained"] / max(r["in_scope"], 1)
        rows.append(r)
    return rows


def ceiling_decomposition(dataset: str, rings: pd.DataFrame, spans: pd.DataFrame,
                          lo_day: int, hi_day: int) -> dict:
    """Why the rings below the >= 3-member bar are below it: too few accounts *anywhere* in the
    ring, or enough accounts but too few of them visible in this window. Only the second kind is
    something a longer window could fix."""
    b = day_bounds(lo_day, hi_day - lo_day + 1)
    vis = rings[(rings["ts"] >= b[0]) & (rings["ts"] <= b[1])]
    g = vis.groupby("ring_id")
    mem = g.apply(lambda d: len(set(d["src"]) | set(d["dst"])), include_groups=False)
    ntx = g.size()
    s = spans.set_index("ring_id").loc[mem.index]
    bad = mem < 3
    n_bad = int(bad.sum())
    return {"dataset": dataset, "day_lo": lo_day, "day_hi": hi_day, "in_scope": int(len(mem)),
            "below_bar": n_bad, "below_bar_share": float(bad.mean()),
            "of_which_ring_has_lt3_accounts_total": int((s["n_accounts"][bad] < 3).sum()),
            "share_structurally_too_small": float((s["n_accounts"][bad] < 3).mean())
            if n_bad else float("nan"),
            "median_whole_ring_accounts": float(s["n_accounts"][bad].median()) if n_bad else 0.0,
            "median_whole_ring_txn": float(s["n_txn"][bad].median()) if n_bad else 0.0,
            "median_visible_txn": float(ntx[bad].median()) if n_bad else 0.0}


def project(name: str, n_edges_total: int, n_train_edges: int) -> dict:
    """GFP and GNN cost scaled linearly from the measured HI-Small runtimes. Linear is the
    optimistic direction for the GNN (neighbour sampling grows with degree, and degree grows with
    volume on a fixed account population), so these are lower bounds."""
    return {"split": name, "edges_total": int(n_edges_total), "train_edges": int(n_train_edges),
            "gfp_minutes": HI_SMALL_GFP_MINUTES * n_edges_total / HI_SMALL_EDGES,
            "gnn_hours_per_seed": HI_SMALL_HOURS_PER_SEED * n_train_edges / HI_SMALL_TRAIN_EDGES,
            "gnn_hours_5_seeds": 5 * HI_SMALL_HOURS_PER_SEED * n_train_edges / HI_SMALL_TRAIN_EDGES}


# ============================================================ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets", nargs="+", default=list(DATASETS))
    ap.add_argument("--parts", nargs="+", default=["profile", "patterns", "windows", "feasibility"])
    ap.add_argument("--out-dir", type=Path, default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    check_parser()
    payload = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "note": "measurement only; this step decides data, not method",
               "criteria": {"warmup_volume_ratio": WARMUP_VOLUME_RATIO,
                            "tail_volume_frac": TAIL_VOLUME_FRAC,
                            "tail_base_rate_ratio": TAIL_BASE_RATE_RATIO,
                            "source": "docs/TEST_TAIL.md and FINDINGS C8"}}

    profiles, regions = {}, {}
    for ds in a.datasets:
        p = a.out_dir / f"v3_day_profile_{ds}.csv"
        if "profile" in a.parts and not p.exists():
            day_profile(ds).to_csv(p, index=False)
        if p.exists():
            profiles[ds] = pd.read_csv(p)
            regions[ds] = clean_region(profiles[ds])
            r = regions[ds]
            print(f"  [region] {ds}: days {profiles[ds]['day'].min()}-{profiles[ds]['day'].max()}, "
                  f"warm-up {r['warmup_days']}, tail {r['tail_days']}, "
                  f"clean {r['clean_lo']}-{r['clean_hi']} ({r['clean_days']} d), "
                  f"{r['clean_edges_per_day']:,.0f} edges/day, base rate {r['clean_base_rate']:.4%}")
    payload["regions"] = regions

    if "patterns" not in a.parts:
        return profiles, regions
    all_spans, win_rows = [], []
    end_rows: dict[str, list] = {}
    ring_cache: dict[str, tuple] = {}
    for ds in a.datasets:
        if ds not in profiles:
            continue
        first = date.fromisoformat(profiles[ds]["date"].iloc[0].replace("/", "-"))
        rings = parse_patterns(RAW / f"{ds}_Patterns.txt", first)
        sp = ring_spans(rings)
        sp.insert(0, "dataset", ds)
        all_spans.append(sp)
        print(f"  [rings] {ds}: {len(sp)} rings, {len(rings)} pattern transactions, "
              f"first day {first}, span median {sp['span_h'].median():.1f} h")
        if "windows" in a.parts:
            win_rows += sweep(ds, rings, sp, regions[ds])
            end_rows[ds] = test_at_end(ds, rings, sp, regions[ds])
            ring_cache[ds] = (rings, sp)
            if ds == "HI-Small":                       # the shipped reference window
                r = {"dataset": "HI-Small", "window_days": 2, "position": "SHIPPED primary",
                     "day_lo": 8, "day_hi": 9, "fits": True}
                r.update(window_row(rings, sp, *day_bounds(8, 2)))
                win_rows.append(r)
    S = pd.concat(all_spans, ignore_index=True)
    S.to_csv(a.out_dir / "v3_ring_spans.csv", index=False)
    print("\n== ring count and span (hours) by pattern ==")
    t = S.groupby(["dataset", "pattern_type"]).agg(
        rings=("ring_id", "size"), median_txn=("n_txn", "median"),
        median_accounts=("n_accounts", "median"), median_span_h=("span_h", "median"),
        p90_span_h=("span_h", lambda v: float(np.percentile(v, 90))))
    print(t.round(2).to_string())
    print("\n== overall span ==")
    o = S.groupby("dataset")["span_h"].describe(percentiles=[0.25, 0.5, 0.75, 0.9]).round(2)
    print(o.to_string())
    payload["spans_by_pattern"] = json.loads(t.reset_index().to_json(orient="records"))
    payload["spans_overall"] = json.loads(o.reset_index().to_json(orient="records"))

    if win_rows:
        W = pd.DataFrame(win_rows)
        W.to_csv(a.out_dir / "v3_windows.csv", index=False)
        print("\n== observability by window length ==")
        print(W[W["fits"]][["dataset", "window_days", "position", "day_lo", "day_hi", "in_scope",
                            "ge3_members", "fully_contained", "ceiling",
                            "median_visible_members"]].round(3).to_string(index=False))
        payload["windows"] = json.loads(W.to_json(orient="records"))

    if ring_cache:
        dec = [ceiling_decomposition(ds, *ring_cache[ds], regions[ds]["clean_lo"],
                                     regions[ds]["clean_hi"]) for ds in ring_cache]
        DEC = pd.DataFrame(dec)
        DEC.to_csv(a.out_dir / "v3_ceiling_decomposition.csv", index=False)
        print("\n== why rings fall below the 3-member bar (whole clean region) ==")
        print(DEC.round(3).to_string(index=False))
        payload["ceiling_decomposition"] = json.loads(DEC.to_json(orient="records"))

    if end_rows:
        E = pd.concat([pd.DataFrame(v) for v in end_rows.values()], ignore_index=True)
        E.to_csv(a.out_dir / "v3_test_at_end.csv", index=False)
        print("\n== ceiling by test-window length, window at the END of the clean region ==")
        print(E[["dataset", "test_days", "day_lo", "day_hi", "train_val_days_available",
                 "in_scope", "ge3_members", "ceiling", "fully_contained_share"]]
              .round(3).to_string(index=False))
        payload["test_at_end"] = json.loads(E.to_json(orient="records"))

    if "feasibility" in a.parts:
        F = []
        for ds in a.datasets:
            if ds not in regions:
                continue
            r = regions[ds]
            F.append({"dataset": ds, "clean_days": r["clean_days"],
                      "edges_per_day": r["clean_edges_per_day"],
                      "clean_edges": r["clean_edges"], "base_rate": r["clean_base_rate"]})
        FD = pd.DataFrame(F)
        FD.to_csv(a.out_dir / "v3_feasibility.csv", index=False)
        print("\n== clean-region volume ==")
        print(FD.round(5).to_string(index=False))
        payload["feasibility"] = json.loads(FD.to_json(orient="records"))

        rows = []
        for sp_def in SPLITS:
            ds = sp_def["dataset"]
            if ds not in regions or ds not in ring_cache:
                continue
            prof = profiles[ds].set_index("day")["edges"]
            n = {k: int(prof.loc[sp_def[k][0]:sp_def[k][1]].sum()) for k in ("train", "val", "test")}
            rings, sp = ring_cache[ds]
            tl, th = sp_def["test"]
            w = window_row(rings, sp, *day_bounds(tl, th - tl + 1))
            cost = project(sp_def["name"], sum(n.values()), n["train"])
            rows.append({**{"name": sp_def["name"], "dataset": ds,
                            "train_days": f"{sp_def['train'][0]}-{sp_def['train'][1]}",
                            "val_days": f"{sp_def['val'][0]}-{sp_def['val'][1]}",
                            "test_days": f"{tl}-{th}", "test_len": th - tl + 1,
                            "train_edges": n["train"], "val_edges": n["val"],
                            "test_edges": n["test"]},
                         **{k: v for k, v in w.items()},
                         "fully_contained_share": w["fully_contained"] / max(w["in_scope"], 1),
                         "gfp_minutes": cost["gfp_minutes"],
                         "gnn_hours_per_seed": cost["gnn_hours_per_seed"],
                         "gnn_hours_5_seeds": cost["gnn_hours_5_seeds"]})
        SP = pd.DataFrame(rows)
        SP.to_csv(a.out_dir / "v3_splits.csv", index=False)
        print("\n== candidate splits ==")
        print(SP[["name", "train_days", "val_days", "test_days", "train_edges", "in_scope",
                  "ge3_members", "ceiling", "fully_contained_share", "gfp_minutes",
                  "gnn_hours_per_seed", "gnn_hours_5_seeds"]].round(3).to_string(index=False))
        payload["splits"] = json.loads(SP.to_json(orient="records"))
        payload["cost_basis"] = {
            "hi_small_edges": HI_SMALL_EDGES, "hi_small_train_edges": HI_SMALL_TRAIN_EDGES,
            "hi_small_gfp_minutes": HI_SMALL_GFP_MINUTES,
            "hi_small_mean_epoch_s": HI_SMALL_EPOCH_S, "hi_small_mean_epochs": HI_SMALL_EPOCHS,
            "hi_small_hours_per_seed": HI_SMALL_HOURS_PER_SEED,
            "scaling": "linear in edge count; optimistic for the GNN (neighbour sampling grows "
                       "with degree, and degree grows with volume on a fixed account population)"}

    (a.out_dir / "v3_observability.json").write_text(json.dumps(payload, indent=2, default=str),
                                                     encoding="utf-8")
    print(f"\n-> {a.out_dir / 'v3_observability.json'}")
    return profiles, regions


if __name__ == "__main__":
    main()
