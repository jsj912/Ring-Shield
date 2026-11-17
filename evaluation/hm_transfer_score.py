"""Part C: score with HI-Small-trained MEGA-GenAgg seed 1, on OUR split (PREREG_RECOVERY amendment, addendum 2).

    # gate 0, HI-Small reproduction (default paths file)
    .venv312/Scripts/python.exe -u evaluation/hm_transfer_score.py --dataset hi_small --splits val --out-dir <scratch>/hs_repro
    # HI-Medium (trained on HI-Small, zero-shot on HI-Medium)
    RINGSHIELD_PATHS=experiments/R18_hm_transfer/paths_hm_transfer.yaml \
    .venv312/Scripts/python.exe -u evaluation/hm_transfer_score.py --dataset hi_medium --splits val [--slice-frac 0.01] --out-dir <dir>

models/mega_adapter.py and MEGA's code run unmodified in --score-only mode (checkpoint + training log from
experiments/R6_megagenagg; GenAgg/GenAgg; scoring batch 2048; neighbours 100 100). The only intervention: MEGA's
`get_data` picks its day split with `min(split_scores, key=...)`; a module-level `min` in MEGA's data_loading namespace
returns the (i, j) day cut points of OUR processed split when called on `split_scores`, and defers to builtins.min
otherwise. mega_adapter.check_splits still asserts edge-for-edge equality with our processed split. Normalisation is
MEGA's own z_norm per data object: train edges / train+val edges / all edges.
--test-days LO HI (addendum 6): score only the test edges of processed days LO..HI (Timestamp // 86400) in this
process; the graph, normalisation and every setting are unchanged. torch.cuda.empty_cache() every --empty-cache-every
batches (does not change any score); peak allocated / reserved memory and the scoring rate are printed.
--slice-frac < 1 is a timing probe: it scores the earliest fraction of the split, prints time and memory, and exits
without writing.
"""
from __future__ import annotations

import argparse
import builtins
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
T0 = time.time()


def our_cut_points(raw_dir: Path, processed_dir: Path) -> tuple[int, int]:
    """(i, j) in MEGA's day indexing ((Timestamp - min) // 86400 of formatted_transactions.csv) such that days < i are
    our train split and days < j are our train + val split. Asserts the split is day-aligned in that indexing."""
    ts = pd.read_csv(raw_dir / "formatted_transactions.csv", usecols=["Timestamp"])["Timestamp"].to_numpy(np.int64)
    day = (ts - ts.min()) // 86400
    cuts = []
    for s in ("train", "val"):
        ids = pd.read_parquet(processed_dir / f"amlworld_{s}.parquet", columns=["EdgeID"])["EdgeID"].to_numpy()
        cuts.append(int(day[ids].max()) + 1)
    i, j = cuts
    tr = pd.read_parquet(processed_dir / "amlworld_train.parquet", columns=["EdgeID"])["EdgeID"].to_numpy()
    assert int((day < i).sum()) == len(tr), "our train split is not day-aligned in MEGA's day indexing"
    return i, j


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=["hi_small", "hi_medium"], required=True)
    ap.add_argument("--splits", nargs="+", default=["val"])
    ap.add_argument("--seed", type=int, default=1, help="GenAgg checkpoint seed (addendum 5: seeds 2-5 after the seed-1 bar)")
    ap.add_argument("--slice-frac", type=float, default=1.0)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--rng-offset", type=int, default=0,
                    help="add this to every RNG seed mega_adapter sets (sampling-noise runs only; HI-Small only)")
    ap.add_argument("--test-days", type=int, nargs=2, default=None, metavar=("LO", "HI"))
    ap.add_argument("--empty-cache-every", type=int, default=50)
    ap.add_argument("--diag-orig-score-split", action="store_true", help="diagnostic: keep mega_adapter.score_split")
    ap.add_argument("--score-batch-size", type=int, default=2048, help="2048 pre-registered; 1024 only as the addendum-6 fallback")
    a = ap.parse_args()
    if a.test_days:
        assert a.splits == ["test"], "--test-days scores the test split only"
        assert f"d{a.test_days[0]}-{a.test_days[1]}" in str(a.out_dir), "block runs write to a d<lo>-<hi> directory"
    env = os.environ.get("RINGSHIELD_PATHS", "")
    if a.dataset == "hi_medium":
        assert env.endswith("paths_hm_transfer.yaml"), "set RINGSHIELD_PATHS to the HI-Medium transfer paths file"
    else:
        assert env == "", "HI-Small reproduction uses the default configs/paths.yaml"
        assert "R6_megagenagg" not in str(a.out_dir), "never write into the shipped GenAgg directory"
    if a.slice_frac < 1.0:
        assert "slice" in a.out_dir.name, "a slice run must write to a *slice* directory"

    import models.mega_adapter as ma
    if a.rng_offset:
        assert a.dataset == "hi_small" and "rng" in a.out_dir.name, "rng-offset runs are HI-Small noise probes only"
        import random as _r
        _t, _n, _p = ma.torch.manual_seed, ma.np.random.seed, _r.seed
        _c = ma.torch.cuda.manual_seed_all
        ma.torch.manual_seed = lambda s_: _t(s_ + a.rng_offset)
        ma.torch.cuda.manual_seed_all = lambda s_: _c(s_ + a.rng_offset)
        ma.np.random.seed = lambda s_: _n(s_ + a.rng_offset)
        ma.random.seed = lambda s_=None: _p(None if s_ is None else s_ + a.rng_offset)
        print(f"[rng] every seed offset by {a.rng_offset}", flush=True)
    from preprocessing.account_bank import load_paths
    paths = load_paths()
    i, j = our_cut_points(paths["raw_dir"], paths["processed_dir"])
    print(f"[split] our cut points in MEGA's day indexing: train days < {i}, val days {i}..{j - 1}, test days >= {j}", flush=True)
    dl = ma.upstream()["data_loading"]

    def forced_min(*args, **kw):
        if args and isinstance(args[0], dict) and "key" in kw and all(isinstance(k, tuple) and len(k) == 2 for k in args[0]):
            assert (i, j) in args[0], f"cut points {(i, j)} not among MEGA's candidates"
            print(f"[split] MEGA's own choice {builtins.min(*args, **kw)} replaced by ours {(i, j)}", flush=True)
            return (i, j)
        return builtins.min(*args, **kw)
    dl.min = forced_min

    if a.test_days:
        lo, hi = a.test_days
        te = pd.read_parquet(paths["processed_dir"] / "amlworld_test.parquet", columns=["EdgeID", "Timestamp"])
        keep = np.sort(te.loc[(te.Timestamp // 86400).between(lo, hi), "EdgeID"].to_numpy())
        orig_check = ma.check_splits

        def check_then_block(inds_of, processed_dir):
            orig_check(inds_of, processed_dir)          # full split asserted first
            t = inds_of["test"]
            m = np.isin(t.numpy(), keep)
            inds_of["test"] = t[ma.torch.from_numpy(m)]
            print(f"[block] test days {lo}..{hi}: {int(m.sum()):,} of {len(t):,} test edges", flush=True)
            assert int(m.sum()) == len(keep)
        ma.check_splits = check_then_block

    N = a.empty_cache_every

    @ma.torch.no_grad()                                   # as mega_adapter.score_split (omitted at first: 2026-11-16 defect)
    def score_split_ec(model, data, inds, args, device, hetero, want_embeddings, causal=True):
        """mega_adapter.score_split with torch.cuda.empty_cache() every N batches and memory/rate logging."""
        torch = ma.torch
        model.eval()
        loader = ma.make_loader(data, inds, args, causal=causal, shuffle=False, transform=ma.build_transform(args))
        captured: dict = {}
        hook = ma.head_module(model).register_forward_pre_hook(
            lambda m, i: captured.__setitem__("h", i[0].detach())) if want_embeddings else None
        probs, embs, ids = [], [], []
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        t0 = None
        for k, batch in enumerate(loader):
            if t0 is None:
                t0 = time.time()
            mask, seed_global = ma.seed_mask(batch)
            ids.append(seed_global.detach().cpu())
            batch = batch.to(device)
            out = model(batch)
            probs.append(torch.softmax(out[mask], dim=-1)[:, 1].float().cpu())
            if want_embeddings:
                embs.append(captured["h"][mask].float().cpu())
            if N and (k + 1) % N == 0 and torch.cuda.is_available():
                del batch, out
                torch.cuda.empty_cache()
        if hook is not None:
            hook.remove()
        dt = time.time() - (t0 or time.time())
        if torch.cuda.is_available():
            print(f"[block-mem] peak allocated {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB, peak reserved "
                  f"{torch.cuda.max_memory_reserved() / 2**20:.0f} MiB, empty_cache every {N} batches", flush=True)
        print(f"[block-rate] {inds.numel():,} edges in {dt:.0f}s of scoring = {inds.numel() / max(dt, 1e-9):,.0f} edges/s", flush=True)
        arrays = [torch.cat(probs).numpy().astype(np.float64)]
        if want_embeddings:
            arrays.append(torch.cat(embs).numpy().astype(np.float32))
        return ma._align_to_inds(inds, ids, *arrays)
    if not a.diag_orig_score_split:
        ma.score_split = score_split_ec

    if a.slice_frac < 1.0:
        orig = ma.score_split

        def sliced(model, data, inds, args, device, hetero, want_emb, causal=True):
            n = max(1, int(len(inds) * a.slice_frac))
            t0 = time.time()
            orig(model, data, inds[:n], args, device, hetero, want_emb, causal=causal)
            dt = time.time() - t0
            import psutil
            import torch
            peak = torch.cuda.max_memory_allocated() / 2 ** 20 if torch.cuda.is_available() else 0.0
            vm = psutil.virtual_memory()
            print(f"[hm-slice] scored {n:,} of {len(inds):,} edges in {dt:.0f}s -> projected full split "
                  f"{dt * len(inds) / n / 3600:.2f} h | torch peak alloc {peak:.0f} MiB | process RSS "
                  f"{psutil.Process().memory_info().rss / 2 ** 30:.1f} GiB | host RAM {vm.percent:.1f} % of "
                  f"{vm.total / 2 ** 30:.0f} GiB | wall since start {time.time() - T0:.0f}s", flush=True)
            sys.exit(0)
        ma.score_split = sliced
    ma.main(["--seeds", str(a.seed), "--edge-agg-type", "genagg", "--node-agg-type", "genagg", "--batch-size", "4096",
             "--score-batch-size", str(a.score_batch_size), "--num-neighs", "100", "100", "--score-only",
             "--ckpt-dir", str(R / "experiments" / "R6_megagenagg"), "--out-dir", str(a.out_dir),
             "--splits", *a.splits, "--embeddings-for"])


if __name__ == "__main__":
    main()
