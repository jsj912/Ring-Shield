"""
Multi-GINe v2 — Phase 6, Experiment E6 (RingShield roadmap).

Full IBM Multi-GNN adaptations + RingShield additions:
  1. Edge MLPs (--emlps)
  2. Port numbering (--ports)
  3. Time deltas (--tds)
  4. Reverse message passing (--reverse-mp) — HeteroData with to/rev_to edge types
  5. Ego IDs (--ego) — binary node flag marking seed edge endpoints
  6. GFP edge features (--gfp) — per-edge pattern features from motif_features.py
  7. Threshold tuning on val set (automatic)
  8. LR scheduler + early stopping
  9. Multi-seed runs (--seeds 1 42 123)

Usage (full Multi-GINe):
    python models/tgn.py \
        --raw-dir data/raw --data-dir data/processed \
        --out-dir experiments/E6_tgn \
        --epochs 100 --emlps --ports --tds --reverse-mp --ego --gfp \
        --seeds 1 42 123
"""

import argparse
import itertools
import json
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import yaml
from sklearn.metrics import f1_score, precision_score, recall_score, average_precision_score

from torch_geometric.data import Data, HeteroData
from torch_geometric.nn import GINEConv, BatchNorm, Linear, to_hetero
from torch_geometric.transforms import BaseTransform

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.causal_loader import ROUTE as LOADER_ROUTE, WINDOW_S, make_loader, seed_mask  # noqa: E402

DRY_RUN_FRAC = 0.01


# ===========================================================================
# Port numbering & time deltas (from IBM data_util.py)
# ===========================================================================
def to_adj_nodes_with_times(edge_index, timestamps, num_nodes):
    ts = timestamps.reshape(-1, 1) if timestamps is not None else torch.zeros(edge_index.shape[1], 1)
    edges = torch.cat((edge_index.T, ts), dim=1)
    adj_in = {i: [] for i in range(num_nodes)}
    adj_out = {i: [] for i in range(num_nodes)}
    for u, v, t in edges:
        u, v, t = int(u), int(v), int(t)
        adj_out[u].append((v, t))
        adj_in[v].append((u, t))
    return adj_in, adj_out


def to_adj_edges_with_times(edge_index, timestamps, num_nodes):
    ts = timestamps.reshape(-1, 1) if timestamps is not None else torch.zeros(edge_index.shape[1], 1)
    edges = torch.cat((edge_index.T, ts), dim=1)
    adj_in = {i: [] for i in range(num_nodes)}
    adj_out = {i: [] for i in range(num_nodes)}
    for idx, (u, v, t) in enumerate(edges):
        u, v, t = int(u), int(v), int(t)
        adj_out[u].append((idx, v, t))
        adj_in[v].append((idx, u, t))
    return adj_in, adj_out


def compute_ports(edge_index, adj_list):
    ports = torch.zeros(edge_index.shape[1], 1)
    ports_dict = {}
    for v, nbs in adj_list.items():
        if len(nbs) < 1:
            continue
        a = np.array(nbs)
        a = a[a[:, -1].argsort()]
        _, idx = np.unique(a[:, [0]], return_index=True, axis=0)
        nbs_unique = a[np.sort(idx)][:, 0]
        for i, u in enumerate(nbs_unique):
            ports_dict[(u, v)] = i
    for i, e in enumerate(edge_index.T):
        key = tuple(e.numpy())
        ports[i] = ports_dict.get(key, 0)
    return ports


def compute_time_deltas(edge_index, timestamps, adj_edges_list):
    n_edges = edge_index.shape[1]
    tds = torch.zeros(n_edges, 1)
    if timestamps is None:
        return tds
    for v, edges in adj_edges_list.items():
        if len(edges) < 1:
            continue
        a = np.array(edges)
        a = a[a[:, -1].argsort()]
        a_tds = [0] + [a[k + 1, -1] - a[k, -1] for k in range(a.shape[0] - 1)]
        for edge_idx, td in zip(a[:, 0].astype(int), a_tds):
            tds[edge_idx] = td
    return tds


def add_ports_and_tds(data, add_ports, add_tds):
    num_nodes = int(data.x.shape[0])
    timestamps = data.timestamps if hasattr(data, "timestamps") else None
    extra = []
    if add_ports:
        adj_in, adj_out = to_adj_nodes_with_times(data.edge_index, timestamps, num_nodes)
        extra.append(compute_ports(data.edge_index, adj_in))
        extra.append(compute_ports(data.edge_index.flipud(), adj_out))
    if add_tds:
        adj_in, adj_out = to_adj_edges_with_times(data.edge_index, timestamps, num_nodes)
        extra.append(compute_time_deltas(data.edge_index, timestamps, adj_in))
        extra.append(compute_time_deltas(data.edge_index, timestamps, adj_out))
    if extra:
        data.edge_attr = torch.cat([data.edge_attr] + extra, dim=1)
    return data


# ===========================================================================
# Ego IDs (from IBM train_util.py)
# ===========================================================================
class AddEgoIds(BaseTransform):
    """Mark seed-edge endpoint nodes with a 1 in an extra feature column."""
    def forward(self, data):
        if isinstance(data, HeteroData):
            x = data['node'].x
            device = x.device
            ids = torch.zeros((x.shape[0], 1), device=device)
            nodes = torch.unique(data['node', 'to', 'node'].edge_label_index.view(-1)).to(device)
            ids[nodes] = 1
            data['node'].x = torch.cat([x, ids], dim=1)
        else:
            x = data.x
            device = x.device
            ids = torch.zeros((x.shape[0], 1), device=device)
            nodes = torch.unique(data.edge_label_index.view(-1)).to(device)
            ids[nodes] = 1
            data.x = torch.cat([x, ids], dim=1)
        return data


# ===========================================================================
# HeteroData creation for reverse MP (from IBM data_util.py)
# ===========================================================================
def create_hetero_obj(x, y, edge_index, edge_attr, timestamps, swap_ports):
    """Create HeteroData with forward (to) and reverse (rev_to) edges."""
    data = HeteroData()
    data['node'].x = x
    data['node', 'to', 'node'].edge_index = edge_index
    data['node', 'rev_to', 'node'].edge_index = edge_index.flipud()
    data['node', 'to', 'node'].edge_attr = edge_attr.clone()
    data['node', 'rev_to', 'node'].edge_attr = edge_attr.clone()
    if swap_ports:
        # Swap in/out port numberings for reverse edges
        data['node', 'rev_to', 'node'].edge_attr[:, [-1, -2]] = \
            data['node', 'rev_to', 'node'].edge_attr[:, [-2, -1]]
    data['node', 'to', 'node'].y = y
    data['node', 'to', 'node'].timestamps = timestamps
    return data


# ===========================================================================
# Model — GINe
# ===========================================================================
class GINe(nn.Module):
    def __init__(self, num_features, num_gnn_layers, n_classes=2,
                 n_hidden=66, edge_updates=False, edge_dim=None,
                 dropout=0.0, final_dropout=0.5):
        super().__init__()
        self.n_hidden = n_hidden
        self.num_gnn_layers = num_gnn_layers
        self.edge_updates = edge_updates
        self.final_dropout = final_dropout

        self.node_emb = nn.Linear(num_features, n_hidden)
        self.edge_emb = nn.Linear(edge_dim, n_hidden)

        self.convs = nn.ModuleList()
        self.emlps = nn.ModuleList()
        self.batch_norms = nn.ModuleList()

        for _ in range(self.num_gnn_layers):
            conv = GINEConv(nn.Sequential(
                nn.Linear(n_hidden, n_hidden), nn.ReLU(),
                nn.Linear(n_hidden, n_hidden),
            ), edge_dim=n_hidden)
            if self.edge_updates:
                self.emlps.append(nn.Sequential(
                    nn.Linear(3 * n_hidden, n_hidden), nn.ReLU(),
                    nn.Linear(n_hidden, n_hidden),
                ))
            self.convs.append(conv)
            self.batch_norms.append(BatchNorm(n_hidden))

        self.mlp = nn.Sequential(
            Linear(n_hidden * 3, 50), nn.ReLU(), nn.Dropout(self.final_dropout),
            Linear(50, 25), nn.ReLU(), nn.Dropout(self.final_dropout),
            Linear(25, n_classes),
        )

    def forward(self, x, edge_index, edge_attr):
        src, dst = edge_index
        x = self.node_emb(x)
        edge_attr = self.edge_emb(edge_attr)
        for i in range(self.num_gnn_layers):
            x = (x + F.relu(self.batch_norms[i](self.convs[i](x, edge_index, edge_attr)))) / 2
            if self.edge_updates:
                edge_attr = edge_attr + self.emlps[i](
                    torch.cat([x[src], x[dst], edge_attr], dim=-1)) / 2
        x = x[edge_index.T].reshape(-1, 2 * self.n_hidden).relu()
        x = torch.cat((x, edge_attr.view(-1, edge_attr.shape[1])), 1)
        return self.mlp(x)


# ===========================================================================
# Data loading
# ===========================================================================
def load_gfp_features(data_dir, split, edge_ids):
    """Load per-edge GFP features if available, apply log1p to high-magnitude cols.

    Rows are aligned to `edge_ids` (the split's EdgeID values, in order) through the
    parquet's EdgeID column, so a row subset (--dry-run) or a re-keyed parquet is handled;
    when the parquet is already in split order this equals the old positional read.
    """
    gfp_path = data_dir / f"amlworld_gfp_features_{split}.parquet"
    if not gfp_path.exists():
        return None
    gfp = pd.read_parquet(gfp_path)
    assert "EdgeID" in gfp.columns, f"{gfp_path} has no EdgeID column"
    gfp_cols = [c for c in gfp.columns if c != "EdgeID"]
    gfp = gfp.set_index("EdgeID").reindex(np.asarray(edge_ids))
    assert not gfp.isna().any().any(), f"{gfp_path}: GFP rows missing for some EdgeIDs of the {split} split"
    # log1p transform for high-magnitude features (fan_out max ~49k)
    for col in gfp_cols:
        gfp[col] = np.log1p(gfp[col].values.astype(np.float32))
    return torch.tensor(gfp[gfp_cols].values, dtype=torch.float32)


def load_data(raw_dir, data_dir, args):
    fmt_path = raw_dir / "formatted_transactions.csv"
    print(f"  Loading {fmt_path}...")
    df = pd.read_csv(fmt_path)
    max_n_id = df[["from_id", "to_id"]].to_numpy().max() + 1
    # Timestamps stay in the LOADER basis (seconds since first day 00:00 - 10 s), the same
    # basis as data/processed/amlworld_*.parquet. The old `Timestamp - min` rebase is gone;
    # after z-normalisation the constant made no difference to the model, and every output
    # file (scores, embeddings, predictions) is now directly joinable to the parquets.
    tr_pq = data_dir / "amlworld_train.parquet"
    if tr_pq.exists():
        pq_min = int(pd.read_parquet(tr_pq, columns=["Timestamp"])["Timestamp"].min())
        assert int(df["Timestamp"].min()) == pq_min, (
            f"formatted_transactions.csv Timestamp basis (min {int(df['Timestamp'].min())}) differs from "
            f"{tr_pq} (min {pq_min}); regenerate one of them")
    if getattr(args, "dry_run", False):
        seed = getattr(args, "dry_run_seed", 1)
        df = df.sample(frac=DRY_RUN_FRAC, random_state=seed).sort_values("EdgeID").reset_index(drop=True)
        print(f"  DRY RUN: {len(df)} rows ({DRY_RUN_FRAC:.0%}, seed {seed}); node table kept at {max_n_id} ids")
    timestamps = torch.tensor(df["Timestamp"].values, dtype=torch.float32)
    y = torch.tensor(df["Is Laundering"].values, dtype=torch.long)

    print(f"  Illicit: {y.sum()}/{len(y)} = {y.float().mean()*100:.2f}%")
    print(f"  Nodes: {max_n_id}, Transactions: {len(df)}")

    edge_feature_cols = ["Timestamp", "Amount Received", "Received Currency", "Payment Format"]
    edge_index = torch.tensor(df[["from_id", "to_id"]].values.T, dtype=torch.long)
    edge_attr = torch.tensor(df[edge_feature_cols].values, dtype=torch.float32)
    x = torch.ones(max_n_id, 1, dtype=torch.float32)

    # Day-based 60/20/20 split
    n_days = int(timestamps.max() / 86400 + 1)
    daily_inds, daily_trans = [], []
    for day in range(n_days):
        l, r = day * 86400, (day + 1) * 86400
        di = torch.where((timestamps >= l) & (timestamps < r))[0]
        daily_inds.append(di)
        daily_trans.append(di.shape[0])

    d_ts = np.array(daily_trans)
    split_per = [0.6, 0.2, 0.2]
    best_score, best_ij = float("inf"), (0, 0)
    for i, j in itertools.combinations(range(len(d_ts)), 2):
        if j < i:
            continue
        st = [d_ts[:i].sum(), d_ts[i:j].sum(), d_ts[j:].sum()]
        total = sum(st)
        if total == 0:
            continue
        score = max(abs(v / total - t) / t for v, t in zip(st, split_per))
        if score < best_score:
            best_score, best_ij = score, (i, j)

    i, j = best_ij
    split = [list(range(i)), list(range(i, j)), list(range(j, len(d_ts)))]
    split_cat = {k: torch.cat([daily_inds[d] for d in split[k]]) for k in range(3)}
    tr_inds, val_inds, te_inds = split_cat[0], split_cat[1], split_cat[2]

    for name, inds in [("Train", tr_inds), ("Val", val_inds), ("Test", te_inds)]:
        print(f"  {name}: {inds.shape[0]} ({y[inds].sum()} laund, IR={y[inds].float().mean()*100:.2f}%)")

    # Expanding window data objects
    e_tr = tr_inds.numpy()
    e_val = np.concatenate([tr_inds, val_inds])

    tr_data = Data(x=x, y=y[e_tr], edge_index=edge_index[:, e_tr],
                   edge_attr=edge_attr[e_tr], timestamps=timestamps[e_tr])
    val_data = Data(x=x, y=y[e_val], edge_index=edge_index[:, e_val],
                    edge_attr=edge_attr[e_val], timestamps=timestamps[e_val])
    te_data = Data(x=x, y=y, edge_index=edge_index,
                   edge_attr=edge_attr, timestamps=timestamps)

    # Add GFP edge features if requested
    if args.gfp:
        print("  Loading GFP per-edge features...")
        # GFP features are computed for the SPLIT parquets (train/val/test separately)
        # But our PyG Data objects use expanding windows, so we need to handle this:
        # tr_data edges = train edges only
        # val_data edges = train + val edges
        # te_data edges = all edges
        edge_ids = df["EdgeID"].values
        gfp_tr = load_gfp_features(data_dir, "train", edge_ids[tr_inds.numpy()])
        gfp_val = load_gfp_features(data_dir, "val", edge_ids[val_inds.numpy()])
        gfp_te = load_gfp_features(data_dir, "test", edge_ids[te_inds.numpy()])

        if gfp_tr is not None and gfp_val is not None and gfp_te is not None:
            tr_data.edge_attr = torch.cat([tr_data.edge_attr, gfp_tr], dim=1)
            gfp_val_combined = torch.cat([gfp_tr, gfp_val], dim=0)
            val_data.edge_attr = torch.cat([val_data.edge_attr, gfp_val_combined], dim=1)
            gfp_all = torch.cat([gfp_tr, gfp_val, gfp_te], dim=0)
            te_data.edge_attr = torch.cat([te_data.edge_attr, gfp_all], dim=1)
            n_gfp = gfp_tr.shape[1]
            print(f"    Added {n_gfp} GFP features (log1p transformed)")
        else:
            print("    WARNING: GFP feature files not found, skipping")
            args.gfp = False

    # Ports and time deltas
    if args.ports or args.tds:
        print("  Adding ports/time-delta features...")
        for name, data in [("train", tr_data), ("val", val_data), ("test", te_data)]:
            n_before = data.edge_attr.shape[1]
            data = add_ports_and_tds(data, args.ports, args.tds)
            print(f"    {name}: {n_before} -> {data.edge_attr.shape[1]} edge features")
            if name == "train":
                tr_data = data
            elif name == "val":
                val_data = data
            else:
                te_data = data

    # Z-normalize (fit on train)
    mean = tr_data.edge_attr.mean(0)
    std = tr_data.edge_attr.std(0)
    std[std == 0] = 1.0
    tr_data.edge_attr = (tr_data.edge_attr - mean) / std
    val_data.edge_attr = (val_data.edge_attr - mean) / std
    te_data.edge_attr = (te_data.edge_attr - mean) / std

    # Prepend unique ID column
    for data in [tr_data, val_data, te_data]:
        data.edge_attr = torch.cat([
            torch.arange(data.edge_attr.shape[0]).view(-1, 1).float(),
            data.edge_attr], dim=1)

    # Convert to HeteroData if reverse MP is enabled
    if args.reverse_mp:
        print("  Converting to HeteroData for reverse message passing...")
        swap_ports = args.ports  # swap port numberings on reverse edges
        tr_data = create_hetero_obj(tr_data.x, tr_data.y, tr_data.edge_index,
                                     tr_data.edge_attr, tr_data.timestamps, swap_ports)
        val_data = create_hetero_obj(val_data.x, val_data.y, val_data.edge_index,
                                      val_data.edge_attr, val_data.timestamps, swap_ports)
        te_data = create_hetero_obj(te_data.x, te_data.y, te_data.edge_index,
                                     te_data.edge_attr, te_data.timestamps, swap_ports)

    # Per-edge metadata for ALL edges, in data order (global edge index == row). Callers
    # slice it with tr_inds / val_inds / te_inds. Timestamp is loader basis.
    edge_meta = pd.DataFrame({
        "EdgeID": df["EdgeID"].values,
        "from_id": df["from_id"].values,
        "to_id": df["to_id"].values,
        "Timestamp": df["Timestamp"].values,
    })

    return tr_data, val_data, te_data, tr_inds, val_inds, te_inds, edge_meta


# ===========================================================================
# Loaders
# ===========================================================================
def get_loaders(tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args):
    """Train / val / test loaders from models.causal_loader.make_loader.

    Seeds: train = every train edge (shuffled), val = val edges, test = test edges, as
    before. `args.causal` selects causal sampling; False keeps today's sampler. Every
    batch carries `seed_mask` / `seed_global` and has the global-id column stripped.
    """
    transform = AddEgoIds() if args.ego else None
    causal = bool(getattr(args, "causal", False))
    tr_loader = make_loader(tr_data, tr_inds, args, causal=causal, shuffle=True, transform=transform)
    val_loader = make_loader(val_data, val_inds, args, causal=causal, shuffle=False, transform=transform)
    te_loader = make_loader(te_data, te_inds, args, causal=causal, shuffle=False, transform=transform)
    return tr_loader, val_loader, te_loader


# ===========================================================================
# Training & evaluation
# ===========================================================================
def _get_mask_and_clean(batch, loader, inds, is_hetero):
    """Seed mask of a batch from make_loader (id column already stripped).

    Returns (mask over the `to` edges, global seed indices in the same order). Every seed
    edge of the batch is present exactly once, so `mask.sum() == len(input_id)`.
    """
    mask, seed_global = seed_mask(batch)
    return mask, seed_global


def _align_to_inds(inds, seed_globals, *arrays):
    """Reorder per-seed arrays (collected in batch order) into the order of `inds`."""
    inds = inds.detach().cpu()
    got = torch.cat(seed_globals)
    pos = torch.full((int(max(inds.max(), got.max())) + 1,), -1, dtype=torch.long)
    pos[inds] = torch.arange(inds.numel())
    order = pos[got]
    assert (order >= 0).all(), "scored an edge that is not a seed"
    assert order.numel() == inds.numel() and torch.unique(order).numel() == inds.numel(), (
        f"scored {order.numel()} edges for {inds.numel()} seeds")
    inv = torch.empty_like(order)
    inv[order] = torch.arange(order.numel())
    inv = inv.numpy()
    return [a[inv] for a in arrays]


def train_epoch(loader, inds, model, optimizer, loss_fn, device, is_hetero):
    model.train()
    total_loss = total_ex = 0
    preds_all, gts_all = [], []

    for batch in loader:
        optimizer.zero_grad()
        mask, _ = _get_mask_and_clean(batch, loader, inds, is_hetero)
        batch.to(device)

        if is_hetero:
            out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)
            out = out[('node', 'to', 'node')]
            gt = batch['node', 'to', 'node'].y[mask]
        else:
            out = model(batch.x, batch.edge_index, batch.edge_attr)
            gt = batch.y[mask]

        pred = out[mask]
        loss = loss_fn(pred, gt)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        total_loss += float(loss) * pred.numel()
        total_ex += pred.numel()
        preds_all.append(pred.argmax(dim=-1).detach().cpu())
        gts_all.append(gt.detach().cpu())

    preds_all = torch.cat(preds_all).numpy()
    gts_all = torch.cat(gts_all).numpy()
    return total_loss / max(total_ex, 1), f1_score(gts_all, preds_all, pos_label=1, zero_division=0)


@torch.no_grad()
def evaluate(loader, inds, model, device, is_hetero, threshold=0.5):
    model.eval()
    preds_all, gts_all, probs_all, ids_all = [], [], [], []

    for batch in loader:
        mask, seed_global = _get_mask_and_clean(batch, loader, inds, is_hetero)
        ids_all.append(seed_global.detach().cpu())
        batch.to(device)

        if is_hetero:
            out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)
            out = out[('node', 'to', 'node')]
            gt = batch['node', 'to', 'node'].y[mask]
        else:
            out = model(batch.x, batch.edge_index, batch.edge_attr)
            gt = batch.y[mask]

        out = out[mask]
        prob = F.softmax(out, dim=-1)[:, 1]
        pred = (prob >= threshold).long()

        probs_all.append(prob.cpu())
        preds_all.append(pred.cpu())
        gts_all.append(gt.cpu())

    preds_all = torch.cat(preds_all).numpy()
    gts_all = torch.cat(gts_all).numpy()
    probs_all = torch.cat(probs_all).numpy()
    # batches may come in time-window order; return everything in the order of `inds`
    preds_all, gts_all, probs_all = _align_to_inds(inds, ids_all, preds_all, gts_all, probs_all)
    assert not np.isnan(probs_all).any(), "NaN probability for a seed edge"

    return {
        "f1_minority": f1_score(gts_all, preds_all, pos_label=1, zero_division=0),
        "precision_minority": precision_score(gts_all, preds_all, pos_label=1, zero_division=0),
        "recall_minority": recall_score(gts_all, preds_all, pos_label=1, zero_division=0),
        "average_precision": average_precision_score(gts_all, probs_all),
    }, preds_all, gts_all, probs_all


def tune_threshold(loader, inds, model, device, is_hetero):
    """Sweep thresholds on val set to find optimal F1."""
    print("  Tuning decision threshold on val set...")
    # First get all probs
    _, _, gts, probs = evaluate(loader, inds, model, device, is_hetero, threshold=0.5)

    best_f1, best_thresh = 0, 0.5
    for thresh in np.arange(0.05, 0.95, 0.01):
        preds = (probs >= thresh).astype(int)
        f1 = f1_score(gts, preds, pos_label=1, zero_division=0)
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = thresh

    print(f"  Best threshold: {best_thresh:.2f} (val F1: {best_f1:.4f})")
    return best_thresh


# ===========================================================================
# Single run
# ===========================================================================
def run_single_seed(seed, args, device):
    """Run one full training cycle with a given seed. Returns test metrics."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    print(f"\n{'='*60}")
    print(f"  SEED {seed}")
    print(f"{'='*60}")

    tr_data, val_data, te_data, tr_inds, val_inds, te_inds, edge_meta = load_data(
        args.raw_dir, args.data_dir, args)
    te_meta = edge_meta.iloc[te_inds.numpy()].reset_index(drop=True)

    is_hetero = isinstance(tr_data, HeteroData)

    tr_loader, val_loader, te_loader = get_loaders(
        tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args)

    # Model
    sample_batch = next(iter(tr_loader))
    if is_hetero:
        n_feats = sample_batch['node'].x.shape[1]
        e_dim = sample_batch['node', 'to', 'node'].edge_attr.shape[1]  # id column already stripped
    else:
        n_feats = sample_batch.x.shape[1]
        e_dim = sample_batch.edge_attr.shape[1]

    model = GINe(
        num_features=n_feats, num_gnn_layers=args.n_gnn_layers,
        n_classes=2, n_hidden=args.n_hidden,
        edge_updates=args.emlps, edge_dim=e_dim,
        dropout=args.dropout, final_dropout=args.final_dropout,
    )

    if is_hetero:
        model = to_hetero(model, te_data.metadata(), aggr='mean')

    model = model.to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  Model: {n_params:,} params, edge_dim={e_dim}, n_feats={n_feats}")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=10, min_lr=1e-5)
    loss_fn = nn.CrossEntropyLoss(
        weight=torch.tensor([args.w_ce1, args.w_ce2], dtype=torch.float32).to(device))

    # Training
    training_log = []
    best_val_f1 = 0.0
    best_epoch = 0
    patience_counter = 0

    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss, train_f1 = train_epoch(
            tr_loader, tr_inds, model, optimizer, loss_fn, device, is_hetero)
        val_metrics, _, _, _ = evaluate(
            val_loader, val_inds, model, device, is_hetero)
        elapsed = time.time() - t0

        val_f1 = val_metrics["f1_minority"]
        scheduler.step(val_f1)

        training_log.append({
            "epoch": epoch, "train_loss": train_loss, "train_f1": train_f1,
            "val_f1": val_f1, "val_ap": val_metrics["average_precision"],
            "lr": optimizer.param_groups[0]["lr"], "time_s": elapsed,
        })

        if val_f1 > best_val_f1:
            best_val_f1, best_epoch = val_f1, epoch
            patience_counter = 0
            torch.save(model.state_dict(), args.out_dir / f"model_best_seed{seed}.pt")
        else:
            patience_counter += 1

        if epoch % 5 == 0 or epoch == 1:
            print(f"    Epoch {epoch:3d} | loss {train_loss:.4f} | "
                  f"trF1 {train_f1:.4f} | valF1 {val_f1:.4f} | "
                  f"valAP {val_metrics['average_precision']:.4f} | "
                  f"lr {optimizer.param_groups[0]['lr']:.6f} | {elapsed:.0f}s")

        if patience_counter >= args.patience:
            print(f"    Early stop at epoch {epoch}")
            break

    print(f"  Best val F1: {best_val_f1:.4f} at epoch {best_epoch}")

    # Load best model
    model.load_state_dict(torch.load(args.out_dir / f"model_best_seed{seed}.pt", weights_only=True))
    model.to(device)

    # Tune threshold on val
    best_thresh = tune_threshold(val_loader, val_inds, model, device, is_hetero)

    # Test with tuned threshold
    test_metrics, test_preds, test_labels, test_probs = evaluate(
        te_loader, te_inds, model, device, is_hetero, threshold=best_thresh)

    print(f"\n  Test (threshold={best_thresh:.2f}):")
    print(f"    minority-F1:  {test_metrics['f1_minority']:.4f}")
    print(f"    precision:    {test_metrics['precision_minority']:.4f}")
    print(f"    recall:       {test_metrics['recall_minority']:.4f}")
    print(f"    AP:           {test_metrics['average_precision']:.4f}")

    # Save per-seed artifacts
    pd.DataFrame(training_log).to_csv(
        args.out_dir / f"training_log_seed{seed}.csv", index=False)

    assert len(test_labels) == len(te_meta), (
        f"Prediction count {len(test_labels)} != test edge count {len(te_meta)}")
    pred_df = te_meta.copy()
    pred_df["true_label"] = test_labels
    pred_df["predicted_label"] = test_preds
    pred_df["pred_prob"] = test_probs
    pred_df.to_csv(args.out_dir / f"predictions_seed{seed}.csv", index=False)

    result = {
        "seed": seed,
        "best_val_f1": best_val_f1,
        "best_epoch": best_epoch,
        "best_threshold": float(best_thresh),
        "test": test_metrics,
        "n_params": n_params,
        "epochs_run": len(training_log),
        "mean_epoch_time_s": float(np.mean([r["time_s"] for r in training_log])),
        "training_log": training_log,
    }
    per_seed = {k: v for k, v in result.items() if k != "training_log"}
    (args.out_dir / f"metrics_seed{seed}.json").write_text(json.dumps(per_seed, indent=2), encoding="utf-8")
    return result


# ===========================================================================
# Main
# ===========================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments/E6_tgn"))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=8192)
    parser.add_argument("--lr", type=float, default=0.006)
    parser.add_argument("--n-hidden", type=int, default=66)
    parser.add_argument("--n-gnn-layers", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.01)
    parser.add_argument("--final-dropout", type=float, default=0.1)
    parser.add_argument("--w-ce1", type=float, default=1.0)
    parser.add_argument("--w-ce2", type=float, default=9.0)
    parser.add_argument("--emlps", action="store_true", help="Edge MLPs")
    parser.add_argument("--ports", action="store_true", help="Port numbering")
    parser.add_argument("--tds", action="store_true", help="Time deltas")
    parser.add_argument("--reverse-mp", action="store_true", help="Reverse message passing")
    parser.add_argument("--ego", action="store_true", help="Ego IDs for seed nodes")
    parser.add_argument("--gfp", action="store_true", help="Include GFP per-edge features")
    parser.add_argument("--num-neighs", nargs="+", type=int, default=[100, 100])
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42])
    parser.add_argument("--arch", choices=["gine"], default="gine", help="model architecture (only gine)")
    parser.add_argument("--causal", action="store_true",
                        help="causal neighbour sampling (models/causal_loader.py); default keeps the "
                             "original sampler")
    parser.add_argument("--window-s", type=int, default=WINDOW_S,
                        help="causal fallback window in seconds (seeds batched in contiguous windows "
                             f"this wide; within-batch leak <= this); default {WINDOW_S}")
    parser.add_argument("--dry-run", action="store_true",
                        help=f"train on a {DRY_RUN_FRAC:.0%} row sample of formatted_transactions.csv")
    args = parser.parse_args()
    args.dry_run_seed = args.seeds[0]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")

    adaptations = []
    for flag, name in [(args.emlps, "edge_MLPs"), (args.ports, "ports"),
                       (args.tds, "time_deltas"), (args.reverse_mp, "reverse_MP"),
                       (args.ego, "ego_IDs"), (args.gfp, "GFP_features")]:
        if flag:
            adaptations.append(name)
    print(f"  Adaptations: {' + '.join(adaptations) if adaptations else 'none'}")
    print(f"  Seeds: {args.seeds}")

    # Run for each seed
    all_results = []
    for seed in args.seeds:
        result = run_single_seed(seed, args, device)
        all_results.append(result)

    # Aggregate results over EVERY seed present in out-dir (this invocation's seeds plus
    # any metrics_seed*.json written by earlier invocations), so seeds can be run in
    # separate processes.
    all_results = []
    for f in sorted(args.out_dir.glob("metrics_seed*.json")):
        all_results.append(json.loads(f.read_text(encoding="utf-8")))
    all_results.sort(key=lambda r: r["seed"])
    seeds_all = [r["seed"] for r in all_results]
    print(f"\n{'='*60}")
    print(f"  AGGREGATE RESULTS ({len(seeds_all)} seeds: {seeds_all})")
    print(f"{'='*60}")

    test_f1s = [r["test"]["f1_minority"] for r in all_results]
    test_aps = [r["test"]["average_precision"] for r in all_results]

    for r in all_results:
        print(f"  Seed {r['seed']}: F1={r['test']['f1_minority']:.4f}, "
              f"AP={r['test']['average_precision']:.4f}, thresh={r['best_threshold']:.2f}")

    mean_f1 = np.mean(test_f1s)
    std_f1 = np.std(test_f1s) if len(test_f1s) > 1 else 0
    mean_ap = np.mean(test_aps)
    std_ap = np.std(test_aps) if len(test_aps) > 1 else 0

    print(f"\n  Mean F1:  {mean_f1:.4f} ± {std_f1:.4f}")
    print(f"  Mean AP:  {mean_ap:.4f} ± {std_ap:.4f}")

    print(f"\n  E5b GFP+XGBoost was: F1=0.534, AP=0.589")
    if mean_f1 > 0.534:
        print("  Multi-GINe BEATS the scientific caution baseline!")
    else:
        print("  Multi-GINe does NOT beat E5b — report honestly per roadmap.")

    # Save final config + aggregate metrics
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
                                         text=True).strip()
    except Exception:
        commit = "unknown"
    config = {
        "experiment": args.out_dir.name,
        "model": "Multi-GINe v2",
        "arch": args.arch,
        "git_commit": commit,
        "adaptations": adaptations,
        "dataset": "AMLworld HI-Small",
        "split": "60/20/20 day-based",
        "seeds": seeds_all,
        "epochs": args.epochs, "patience": args.patience,
        "batch_size": args.batch_size, "lr": args.lr,
        "n_hidden": args.n_hidden, "n_gnn_layers": args.n_gnn_layers,
        "w_ce1": args.w_ce1, "w_ce2": args.w_ce2,
        "num_neighbors": args.num_neighs,
        "n_parameters": all_results[0]["n_params"],
        "causal_sampling": bool(args.causal),
        "loader_route": LOADER_ROUTE["route"] if args.causal else "non-causal",
        "loader_window_s": (args.window_s if LOADER_ROUTE["route"] == "fallback" else None) if args.causal else None,
        "dry_run": bool(args.dry_run),
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    # Training-time summary only; the reported edge metrics come from
    # evaluation/edge_metrics.py on the score files (metrics.json is written there).
    metrics_out = {
        "mean_test_f1": mean_f1, "std_test_f1": std_f1,
        "mean_test_ap": mean_ap, "std_test_ap": std_ap,
        "per_seed": [{
            "seed": r["seed"],
            "best_val_f1": r["best_val_f1"],
            "best_epoch": r["best_epoch"],
            "best_threshold": r["best_threshold"],
            "epochs_run": r.get("epochs_run"),
            "mean_epoch_time_s": r.get("mean_epoch_time_s"),
            "test": r["test"],
        } for r in all_results],
    }
    (args.out_dir / "training_summary.json").write_text(json.dumps(metrics_out, indent=2), encoding="utf-8")

    # Save best seed's predictions as the main predictions.csv
    best_seed_result = max(all_results, key=lambda r: r["best_val_f1"])
    best_seed = best_seed_result["seed"]
    import shutil
    shutil.copy(args.out_dir / f"predictions_seed{best_seed}.csv",
                args.out_dir / "predictions.csv")
    shutil.copy(args.out_dir / f"model_best_seed{best_seed}.pt",
                args.out_dir / "model.pkl")
    shutil.copy(args.out_dir / f"training_log_seed{best_seed}.csv",
                args.out_dir / "training_log.csv")

    # Environment
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}",
             f"torch: {torch.__version__}", f"cuda: {torch.cuda.is_available()}"]
    if torch.cuda.is_available():
        lines.append(f"gpu: {torch.cuda.get_device_name(0)}")
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    (args.out_dir / "environment.txt").write_text("\n".join(lines), encoding="utf-8")

    print(f"\nAll artifacts written to {args.out_dir}/")


if __name__ == "__main__":
    main()