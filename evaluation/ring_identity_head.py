"""Ring-identity head on frozen R1 embeddings (deep-analysis #10, registered 2026-11-12).

    python evaluation/ring_identity_head.py --emb-root ../RS-e2e/experiments/R1_gine_causal

Per detector seed: a supervised-contrastive MLP head (198 -> 128 -> 64, L2-normalised, tau 0.1) is
trained on VALIDATION ring edges (ring = class; 20x non-ring val edges as singleton classes),
early-stopped on a 20 % ring-grouped val hold-out. Then V3.0 (b) is re-run unchanged on the test
primary window with each edge embedding replaced by its head projection, and once with the raw
embedding as the reference. Bars: AUC >= 0.75 vs different-ring and >= 0.70 vs the matched null.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
import torch.nn as nn

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import evaluation.v3_diagnostics as v3  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

RNG = 20261112
TAU, LR, WD, BATCH, EPOCHS, PATIENCE, NONRING_X = 0.1, 1e-3, 1e-4, 512, 200, 20, 20


def read_emb(path: Path, ids) -> tuple[np.ndarray, np.ndarray]:
    t = pq.read_table(path)
    eid = t.column("edge_id").to_numpy()
    pos = pd.Series(np.arange(len(eid)), index=eid).reindex(list(ids)).dropna().astype(int)
    sub = t.take(pos.to_numpy())
    cols = [c for c in sub.column_names if c.startswith("emb_")]
    M = np.column_stack([sub.column(c).to_numpy() for c in cols]).astype(np.float32)
    return pos.index.to_numpy(), M


class Head(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d, 128), nn.ReLU(), nn.Linear(128, 64))

    def forward(self, x):
        return nn.functional.normalize(self.net(x), dim=1)


def supcon(z, y):
    sim = z @ z.T / TAU
    n = len(y)
    eye = torch.eye(n, dtype=torch.bool)
    sim = sim.masked_fill(eye, -1e9)
    logp = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    pos = (y[:, None] == y[None, :]) & ~eye
    has = pos.sum(1) > 0
    if not has.any():
        return z.sum() * 0
    return -((logp * pos).sum(1)[has] / pos.sum(1)[has]).mean()


def batches(y, rng):
    """Batches that keep every ring's edges together (so positives exist), filled with singletons."""
    rings = np.unique(y[y >= 0])
    rng.shuffle(rings)
    singles = np.where(y < 0)[0]
    rng.shuffle(singles)
    ring_idx = [np.where(y == r)[0] for r in rings]
    out, cur, si = [], [], 0
    per_batch_single = BATCH // 2
    for idx in ring_idx:
        cur.extend(idx.tolist())
        if len(cur) >= BATCH // 2:
            out.append(cur + singles[si:si + per_batch_single].tolist())
            si += per_batch_single
            cur = []
    if cur:
        out.append(cur + singles[si:si + per_batch_single].tolist())
    return out


def train_head(X, y, rings_train, rings_hold, rng):
    torch.manual_seed(RNG)
    Xt, yt = torch.tensor(X), torch.tensor(y)
    is_tr = np.isin(y, rings_train) | (y < 0) & (rng.random(len(y)) < 0.8)
    is_ho = np.isin(y, rings_hold) | (y < 0) & ~is_tr
    head = Head(X.shape[1])
    opt = torch.optim.Adam(head.parameters(), lr=LR, weight_decay=WD)
    best, best_state, bad, hist = np.inf, None, 0, []
    tr_idx, ho_idx = np.where(is_tr)[0], np.where(is_ho)[0]
    for ep in range(EPOCHS):
        head.train()
        for b in batches(y[tr_idx], rng):
            ii = torch.tensor(tr_idx[b])
            loss = supcon(head(Xt[ii]), yt[ii])
            opt.zero_grad(); loss.backward(); opt.step()
        head.eval()
        with torch.no_grad():
            vl = float(np.mean([supcon(head(Xt[torch.tensor(ho_idx[b])]), yt[torch.tensor(ho_idx[b])]).item()
                                for b in batches(y[ho_idx], np.random.default_rng(0))]))
        hist.append(vl)
        if vl < best - 1e-4:
            best, best_state, bad = vl, {k: v.clone() for k, v in head.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= PATIENCE:
                break
    head.load_state_dict(best_state)
    return head, {"epochs_run": ep + 1, "best_holdout_loss": best, "first_holdout_loss": hist[0]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--emb-root", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v38_ring_identity_head")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    val = pd.read_parquet(pdir / "amlworld_val.parquet", columns=["EdgeID", "ring_id"])
    heads, train_meta = {}, {}
    for s in a.seeds:
        rng = np.random.default_rng(RNG + s)
        ring_e = val[val.ring_id > 0]
        non = val[val.ring_id <= 0].sample(n=NONRING_X * len(ring_e), random_state=RNG + s)
        ids = np.concatenate([ring_e.EdgeID.to_numpy(), non.EdgeID.to_numpy()])
        lab = dict(zip(ring_e.EdgeID, ring_e.ring_id))
        got, X = read_emb(a.emb_root / f"embeddings_val_seed{s}.parquet", ids)
        y = np.array([int(lab.get(e, -1 - i)) for i, e in enumerate(got)])
        rings = np.unique(y[y >= 0]); rng.shuffle(rings)
        hold = rings[: max(1, len(rings) // 5)]
        head, meta = train_head(X, y, rings[len(hold):], hold, rng)
        heads[s] = head
        train_meta[s] = {**meta, "n_ring_edges": int((y >= 0).sum()), "n_rings": int(len(rings)), "n_holdout_rings": int(len(hold))}
        print(f"seed {s}: head trained {train_meta[s]}", flush=True)

    v3.SCORES = a.emb_root                        # R1 scores + test embeddings for part_b
    raw_loader = v3.load_embeddings
    results = {}
    for name in ("raw", "head"):
        def loader(seed, edge_ids, _name=name):
            d = raw_loader(seed, edge_ids)
            if _name == "raw" or not d:
                return d
            keys = list(d)
            with torch.no_grad():
                Z = heads[seed](torch.tensor(np.stack([d[k] for k in keys]).astype(np.float32))).numpy().astype(np.float64)
            return {k: Z[i] for i, k in enumerate(keys)}
        v3.load_embeddings = loader
        df, _ = v3.part_b(a.seeds, truth, patterns, W, pdir, np.random.default_rng(20260930))
        df.insert(0, "embedding", name)
        results[name] = df
    v3.load_embeddings = raw_loader
    d = pd.concat(results.values(), ignore_index=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(str(a.out) + ".csv", index=False)
    x = d[d.population == "same_ring_cross_component"].groupby(["embedding", "pool"])[
        ["auc_vs_different_ring", "auc_vs_matched_random", "n_pairs"]].mean()
    verdict = {}
    for pool in ("class_b", "under_covered"):
        if ("head", pool) in x.index:
            r = x.loc[("head", pool)]
            verdict[pool] = bool(r.auc_vs_different_ring >= 0.75 and r.auc_vs_matched_random >= 0.70)
    stage1 = any(verdict.values())
    Path(str(a.out) + ".json").write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds, "rng": RNG,
         "head": {"arch": "198-128-64 relu, l2", "tau": TAU, "lr": LR, "wd": WD, "batch": BATCH, "max_epochs": EPOCHS,
                  "patience": PATIENCE, "nonring_multiple": NONRING_X},
         "training": train_meta, "pooled_auc": json.loads(x.reset_index().to_json(orient="records")),
         "stage1_pass_by_pool": verdict, "stage1_pass": stage1}, indent=2), encoding="utf-8")
    print(x.round(4).to_string())
    print(f"Stage 1 pass by pool: {verdict} -> {'PASS' if stage1 else 'FAIL'}")


if __name__ == "__main__":
    main()
