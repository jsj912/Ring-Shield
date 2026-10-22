"""Step 3b-x (5): print the four CAUSAL_LEAK.md tables (markdown) from the artefacts.

    python evaluation/causal_leak_tables.py

Reads docs/window_leak_val_w1800.json (1), docs/ring_time_spread.json (2),
results/tables/r1_window_sensitivity.csv (3) and the two training logs
experiments/R1_gine_causal/training_log_seed1.csv vs experiments/R1x_gine_causal_w300/
training_log_seed1.csv (4). Prints only; docs/CAUSAL_LEAK.md is written by hand from this
output so the numbers there are never typed in.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")  # markdown arrows / dashes on a cp1252 console

REPO_ROOT = Path(__file__).resolve().parents[1]
LEAK = REPO_ROOT / "docs" / "window_leak_val_w1800.json"
SPREAD = REPO_ROOT / "docs" / "ring_time_spread.json"
SENS = REPO_ROOT / "results" / "tables" / "r1_window_sensitivity.csv"
LOG_R1 = REPO_ROOT / "experiments" / "R1_gine_causal" / "training_log_seed1.csv"
LOG_W300 = REPO_ROOT / "experiments" / "R1x_gine_causal_w300" / "training_log_seed1.csv"
STDOUT_W300 = REPO_ROOT / "experiments" / "R1x_gine_causal_w300" / "train.log"  # fallback: run stopped before the CSV
EPOCHS = (1, 5, 10, 20, 30)


def pct(v, nd=2):
    return "–" if v is None else f"{100 * v:.{nd}f}%"


def table_leak():
    j = json.loads(LEAK.read_text(encoding="utf-8"))
    print(f"### 1. In-window future neighbours, val, W = {j['window_s']} s "
          f"({j['n_batches']} batches, {j['n_seeds']:,} seeds, {j['n_illicit_seeds']:,} illicit; "
          f"seed→batch-max gap mean {j['seed_to_batch_max_gap_s']['mean']:.0f} s, "
          f"p90 {j['seed_to_batch_max_gap_s']['p90']:.0f} s)\n")
    print("| seeds | hop | n | empty hop | mean frac | p50 | p90 | p99 | seeds with ≥1 future | pooled frac | edges |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for g in ("illicit", "licit"):
        d = j["by_group"][g]
        for hop in ("hop1", "hop2", "hop1+2"):
            s = d[hop]["both_stores"]
            print(f"| {g} | {hop} | {s['n_seeds']:,} | {s['n_seeds_with_empty_hop']:,} | {pct(s['mean'])} | "
                  f"{pct(s['p50'])} | {pct(s['p90'])} | {pct(s['p99'])} | {pct(s['share_seeds_with_any_future'])} | "
                  f"{pct(s['pooled_fraction'])} | {s['total_edges']:,} |")
    ill = j["by_group"]["illicit"]["share_with_future_illicit_neighbour"]
    print(f"\nIllicit seeds with ≥ 1 in-window-future neighbour that is itself illicit: "
          f"hop 1 {pct(ill['hop1'])}, hop 2 {pct(ill['hop2'])}, either {pct(ill['either'])} "
          f"(n = {ill['n_illicit_seeds']:,}).")
    for g in ("illicit", "licit"):
        d = j["by_group"][g]
        print(f"Per store, {g}, hop 1 pooled: to {pct(d['hop1']['to']['pooled_fraction'])}, "
              f"rev_to {pct(d['hop1']['rev_to']['pooled_fraction'])}; hop 2: to {pct(d['hop2']['to']['pooled_fraction'])}, "
              f"rev_to {pct(d['hop2']['rev_to']['pooled_fraction'])}.")
    print()


def table_spread():
    j = json.loads(SPREAD.read_text(encoding="utf-8"))
    bins = list(j["bins_s"].keys())
    a = j["all_patterns"]
    print(f"### 2. Same-ring pair time gaps ({a['n_rings']} rings, {a['n_rings_single_txn']} single-transaction, "
          f"{a['n_pairs']:,} pairs)\n")
    print("| pattern | rings | pairs | " + " | ".join(f"< {b}" for b in bins) + " | median gap | p90 gap | median ring span |")
    print("|---|---|---|" + "---|" * len(bins) + "---|---|---|")
    rows = [("all", a)] + sorted(j["per_pattern"].items())
    for name, r in rows:
        fr = r["frac_pairs_under"]
        gap = r["gap_s"]
        span = r["ring_span_s"]
        print(f"| {name} | {r['n_rings']} | {r['n_pairs']:,} | " + " | ".join(pct(fr[b], 1) for b in bins) +
              f" | {gap['median'] / 3600:.1f} h | {gap['p90'] / 3600:.1f} h | {span['median'] / 3600:.1f} h |")
    print()


def table_sensitivity():
    df = pd.read_csv(SENS)
    windows = sorted(df.window_s.unique())
    seeds = sorted(df.seed.unique())
    print("### 3. Scoring-only window sensitivity (R1 checkpoints, val-tuned threshold per seed and window)\n")
    print("| seed | " + " | ".join(f"val F1 / AP W={w}" for w in windows) + " | " +
          " | ".join(f"test F1 / AP W={w}" for w in windows) + " |")
    print("|---|" + "---|" * (2 * len(windows)))
    for seed in list(seeds) + ["mean", "sd"]:
        cells = []
        for split in ("val", "test"):
            for w in windows:
                d = df[df.window_s == w]
                if seed == "mean":
                    f1, ap = d[f"{split}_f1"].mean(), d[f"{split}_ap"].mean()
                elif seed == "sd":
                    f1, ap = d[f"{split}_f1"].std(ddof=1), d[f"{split}_ap"].std(ddof=1)
                else:
                    r = d[d.seed == seed]
                    if r.empty:                       # window capped before this seed was scored
                        cells.append("–")
                        continue
                    f1, ap = r.iloc[0][f"{split}_f1"], r.iloc[0][f"{split}_ap"]
                cells.append(f"{f1:.3f} / {ap:.3f}")
        print(f"| {seed} | " + " | ".join(cells) + " |")
    thr = df.pivot(index="seed", columns="window_s", values="threshold")
    print("\nThresholds (val-tuned): " + "; ".join(
        f"seed {s}: " + ", ".join(f"W={w} {thr.loc[s, w]:.2f}" for w in windows if not pd.isna(thr.loc[s, w]))
        for s in seeds))
    n_per = {w: int((df.window_s == w).sum()) for w in windows}
    print("Seeds per window: " + ", ".join(f"W={w}: {n}" for w, n in n_per.items()))
    common = sorted(set.intersection(*[set(df[df.window_s == w].seed) for w in windows]))
    if common and len(common) < len(seeds):
        c = df[df.seed.isin(common)]
        print(f"Means over the {len(common)} seeds every window has ({common}): " + "; ".join(
            f"W={w} val F1 {c[c.window_s == w].val_f1.mean():.4f} test F1 {c[c.window_s == w].test_f1.mean():.4f} "
            f"test AP {c[c.window_s == w].test_ap.mean():.4f}" for w in windows))
    print()


def _log_w300() -> pd.DataFrame:
    """training_log_seed1.csv if the run finished, else the epoch lines printed to train.log."""
    if LOG_W300.exists():
        return pd.read_csv(LOG_W300).set_index("epoch")
    pat = re.compile(r"\s*Epoch\s+(\d+) \| loss ([\d.]+) \| trF1 ([\d.]+) \| valF1 ([\d.]+) \| valAP ([\d.]+) \| "
                     r"lr ([\d.]+) \| (\d+)s")
    rows = []
    for line in STDOUT_W300.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.match(line)
        if m:
            e, loss, trf1, vf1, vap, lr, t = m.groups()
            rows.append({"epoch": int(e), "train_loss": float(loss), "train_f1": float(trf1), "val_f1": float(vf1),
                         "val_ap": float(vap), "lr": float(lr), "time_s": float(t)})
    return pd.DataFrame(rows).set_index("epoch")


def table_training():
    a = pd.read_csv(LOG_R1).set_index("epoch")
    b = _log_w300()
    src = "training_log_seed1.csv" if LOG_W300.exists() else "train.log stdout (run stopped after epoch 5; " \
                                                              "tgn.py prints epochs 1 and every 5th)"
    print(f"### 4. Training sensitivity, seed 1: R1 (W = 1,800 s) vs W = 300 s "
          f"({len(b)} epochs logged at W = 300; source: {src})\n")
    print("| epoch | val F1 W=1800 | val F1 W=300 | Δ | val AP W=1800 | val AP W=300 | Δ | epoch s W=1800 | epoch s W=300 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for e in EPOCHS:
        if e not in b.index or e not in a.index:
            print(f"| {e} | – | – | – | – | – | – | – | – |")
            continue
        ra, rb = a.loc[e], b.loc[e]
        print(f"| {e} | {ra.val_f1:.4f} | {rb.val_f1:.4f} | {rb.val_f1 - ra.val_f1:+.4f} | {ra.val_ap:.4f} | "
              f"{rb.val_ap:.4f} | {rb.val_ap - ra.val_ap:+.4f} | {ra.time_s:.0f} | {rb.time_s:.0f} |")
    last = int(b.index.max())
    print(f"\nBest val F1 (thr 0.5) up to epoch {last}: W=1800 {a.val_f1.loc[:last].max():.4f} "
          f"(epoch {int(a.val_f1.loc[:last].idxmax())}), W=300 {b.val_f1.max():.4f} (epoch {int(b.val_f1.idxmax())}). "
          f"Epoch time: W=1800 mean {a.time_s.mean():.0f} s over {len(a)} epochs (epochs 1/5: "
          f"{a.time_s.loc[1]:.0f}/{a.time_s.loc[5]:.0f} s); W=300: "
          f"{', '.join(f'epoch {int(e)} {t:.0f} s' for e, t in b.time_s.items())}.")
    print()


if __name__ == "__main__":
    for fn, path in ((table_leak, LEAK), (table_spread, SPREAD), (table_sensitivity, SENS),
                     (table_training, LOG_W300 if LOG_W300.exists() else STDOUT_W300)):
        if path.exists():
            fn()
        else:
            print(f"[skip] {path.relative_to(REPO_ROOT)} not there yet\n", file=sys.stderr)
