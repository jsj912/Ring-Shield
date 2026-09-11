"""
Multi-GINe — Phase 6, Experiment E6 (RingShield roadmap).

GINe with IBM's full Multi-GNN adaptations (Egressy et al., AAAI 2024):
  1. Edge MLPs for edge feature updates
  2. Port numbering — unique neighbor indices as extra edge features
  3. Time deltas — time between consecutive transactions per node
  4. LR scheduler (ReduceOnPlateau) to prevent late-training collapse
  5. Early stopping on val F1

Usage:
    python models/tgn.py \
        --data-dir data/processed --raw-dir data/raw \
        --out-dir experiments/E6_tgn \
        --epochs 100 --emlps --ports --tds

Expects:
    data/raw/formatted_transactions.csv
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

from torch_geometric.data import Data
from torch_geometric.loader import LinkNeighborLoader
from torch_geometric.nn import GINEConv, BatchNorm, Linear

SEED = 42


def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True


# ===========================================================================
# Port numbering & time deltas (adapted from IBM Multi-GNN data_util.py)
# ===========================================================================
def to_adj_nodes_with_times(edge_index, timestamps, num_nodes):
    """Build adjacency lists with timestamps for port numbering."""
    ts = timestamps.reshape(-1, 1) if timestamps is not None else torch.zeros(edge_index.shape[1], 1)
    edges = torch.cat((edge_index.T, ts), dim=1)
    adj_list_in = {i: [] for i in range(num_nodes)}
    adj_list_out = {i: [] for i in range(num_nodes)}
    for u, v, t in edges:
        u, v, t = int(u), int(v), int(t)
        adj_list_out[u].append((v, t))
        adj_list_in[v].append((u, t))
    return adj_list_in, adj_list_out


def to_adj_edges_with_times(edge_index, timestamps, num_nodes):
    """Build adjacency lists with edge indices and timestamps for time deltas."""
    ts = timestamps.reshape(-1, 1) if timestamps is not None else torch.zeros(edge_index.shape[1], 1)
    edges = torch.cat((edge_index.T, ts), dim=1)
    adj_edges_out = {i: [] for i in range(num_nodes)}
    adj_edges_in = {i: [] for i in range(num_nodes)}
    for idx, (u, v, t) in enumerate(edges):
        u, v, t = int(u), int(v), int(t)
        adj_edges_out[u].append((idx, v, t))
        adj_edges_in[v].append((idx, u, t))
    return adj_edges_in, adj_edges_out


def compute_ports(edge_index, adj_list):
    """Assign port numbers: unique neighbor index sorted by first interaction time."""
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
    """Compute time between consecutive transactions for each node."""
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


def add_ports_and_tds(data, add_ports_flag, add_tds_flag):
    """Add port numbering and/or time deltas as extra edge feature columns."""
    num_nodes = int(data.x.shape[0])
    timestamps = data.timestamps if hasattr(data, "timestamps") else None

    extra_feats = []

    if add_ports_flag:
        print("    Adding port numbering...")
        adj_in, adj_out = to_adj_nodes_with_times(data.edge_index, timestamps, num_nodes)
        in_ports = compute_ports(data.edge_index, adj_in)
        out_ports = compute_ports(data.edge_index.flipud(), adj_out)
        extra_feats.extend([in_ports, out_ports])

    if add_tds_flag:
        print("    Adding time deltas...")
        adj_edges_in, adj_edges_out = to_adj_edges_with_times(data.edge_index, timestamps, num_nodes)
        in_tds = compute_time_deltas(data.edge_index, timestamps, adj_edges_in)
        out_tds = compute_time_deltas(data.edge_index, timestamps, adj_edges_out)
        extra_feats.extend([in_tds, out_tds])

    if extra_feats:
        data.edge_attr = torch.cat([data.edge_attr] + extra_feats, dim=1)

    return data


# ===========================================================================
# Model — GINe (from IBM Multi-GNN)
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
                nn.Linear(n_hidden, n_hidden),
                nn.ReLU(),
                nn.Linear(n_hidden, n_hidden),
            ), edge_dim=n_hidden)

            if self.edge_updates:
                self.emlps.append(nn.Sequential(
                    nn.Linear(3 * n_hidden, n_hidden),
                    nn.ReLU(),
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
def load_data(raw_dir: Path, args):
    fmt_path = raw_dir / "formatted_transactions.csv"
    print(f"  Loading {fmt_path}...")
    df = pd.read_csv(fmt_path)
    df["Timestamp"] = df["Timestamp"] - df["Timestamp"].min()

    max_n_id = df[["from_id", "to_id"]].to_numpy().max() + 1
    timestamps = torch.tensor(df["Timestamp"].values, dtype=torch.float32)
    y = torch.tensor(df["Is Laundering"].values, dtype=torch.long)

    print(f"  Illicit ratio: {y.sum()}/{len(y)} = {y.float().mean()*100:.2f}%")
    print(f"  Nodes: {max_n_id}, Transactions: {len(df)}")

    edge_feature_cols = ["Timestamp", "Amount Received", "Received Currency", "Payment Format"]
    edge_index = torch.tensor(df[["from_id", "to_id"]].values.T, dtype=torch.long)
    edge_attr = torch.tensor(df[edge_feature_cols].values, dtype=torch.float32)
    x = torch.ones(max_n_id, 1, dtype=torch.float32)

    # Day-based 60/20/20 split
    n_days = int(timestamps.max() / (3600 * 24) + 1)
    daily_inds, daily_trans = [], []
    for day in range(n_days):
        l, r = day * 86400, (day + 1) * 86400
        day_inds = torch.where((timestamps >= l) & (timestamps < r))[0]
        daily_inds.append(day_inds)
        daily_trans.append(day_inds.shape[0])

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

    split_inds = {k: torch.cat([daily_inds[d] for d in split[k]]) for k in range(3)}
    tr_inds, val_inds, te_inds = split_inds[0], split_inds[1], split_inds[2]

    for name, inds in [("Train", tr_inds), ("Val", val_inds), ("Test", te_inds)]:
        print(f"  {name}: {inds.shape[0]} ({y[inds].sum()} laund, IR={y[inds].float().mean()*100:.2f}%)")

    # Build PyG Data (expanding window)
    e_tr = tr_inds.numpy()
    e_val = np.concatenate([tr_inds, val_inds])

    tr_data = Data(x=x, y=y[e_tr], edge_index=edge_index[:, e_tr],
                   edge_attr=edge_attr[e_tr], timestamps=timestamps[e_tr])
    val_data = Data(x=x, y=y[e_val], edge_index=edge_index[:, e_val],
                    edge_attr=edge_attr[e_val], timestamps=timestamps[e_val])
    te_data = Data(x=x, y=y, edge_index=edge_index,
                   edge_attr=edge_attr, timestamps=timestamps)

    # Add ports and time deltas BEFORE normalization (they're new feature columns)
    if args.ports or args.tds:
        print("  Adding port/time-delta features...")
        for name, data in [("train", tr_data), ("val", val_data), ("test", te_data)]:
            print(f"    {name} ({data.edge_attr.shape[1]} cols before)...")
            data = add_ports_and_tds(data, args.ports, args.tds)
            if name == "train":
                tr_data = data
            elif name == "val":
                val_data = data
            else:
                te_data = data
            print(f"    → {data.edge_attr.shape[1]} cols after")

    # Z-normalize (fit on train)
    mean = tr_data.edge_attr.mean(0)
    std = tr_data.edge_attr.std(0)
    std[std == 0] = 1.0
    tr_data.edge_attr = (tr_data.edge_attr - mean) / std
    val_data.edge_attr = (val_data.edge_attr - mean) / std
    te_data.edge_attr = (te_data.edge_attr - mean) / std

    # Prepend unique ID column for seed edge tracking
    for data in [tr_data, val_data, te_data]:
        data.edge_attr = torch.cat([
            torch.arange(data.edge_attr.shape[0]).view(-1, 1).float(),
            data.edge_attr,
        ], dim=1)

    return tr_data, val_data, te_data, tr_inds, val_inds, te_inds


# ===========================================================================
# Training & evaluation
# ===========================================================================
def get_loaders(tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args):
    tr_loader = LinkNeighborLoader(
        tr_data, num_neighbors=args.num_neighs,
        batch_size=args.batch_size, shuffle=True)
    val_loader = LinkNeighborLoader(
        val_data, num_neighbors=args.num_neighs,
        edge_label_index=val_data.edge_index[:, val_inds],
        edge_label=val_data.y[val_inds],
        batch_size=args.batch_size, shuffle=False)
    te_loader = LinkNeighborLoader(
        te_data, num_neighbors=args.num_neighs,
        edge_label_index=te_data.edge_index[:, te_inds],
        edge_label=te_data.y[te_inds],
        batch_size=args.batch_size, shuffle=False)
    return tr_loader, val_loader, te_loader


def train_epoch(loader, tr_inds, model, optimizer, loss_fn, device):
    model.train()
    total_loss = total_ex = 0
    preds, gts = [], []
    for batch in loader:
        optimizer.zero_grad()
        inds = tr_inds.detach().cpu()
        batch_edge_inds = inds[batch.input_id.detach().cpu()]
        batch_edge_ids = loader.data.edge_attr.detach().cpu()[batch_edge_inds, 0]
        mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)
        batch.edge_attr = batch.edge_attr[:, 1:]
        batch.to(device)
        out = model(batch.x, batch.edge_index, batch.edge_attr)
        pred = out[mask]
        gt = batch.y[mask]
        loss = loss_fn(pred, gt)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()
        total_loss += float(loss) * pred.numel()
        total_ex += pred.numel()
        preds.append(pred.argmax(dim=-1).detach().cpu())
        gts.append(gt.detach().cpu())
    preds = torch.cat(preds).numpy()
    gts = torch.cat(gts).numpy()
    return total_loss / max(total_ex, 1), f1_score(gts, preds, pos_label=1, zero_division=0)


@torch.no_grad()
def evaluate(loader, inds, model, device):
    model.eval()
    preds, gts, probs = [], [], []
    for batch in loader:
        inds_cpu = inds.detach().cpu()
        batch_edge_inds = inds_cpu[batch.input_id.detach().cpu()]
        batch_edge_ids = loader.data.edge_attr.detach().cpu()[batch_edge_inds, 0]
        mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)
        batch.edge_attr = batch.edge_attr[:, 1:]
        batch.to(device)
        out = model(batch.x, batch.edge_index, batch.edge_attr)
        out = out[mask]
        probs.append(F.softmax(out, dim=-1)[:, 1].cpu())
        preds.append(out.argmax(dim=-1).cpu())
        gts.append(batch.y[mask].cpu())
    preds = torch.cat(preds).numpy()
    gts = torch.cat(gts).numpy()
    probs = torch.cat(probs).numpy()
    return {
        "f1_minority": f1_score(gts, preds, pos_label=1, zero_division=0),
        "precision_minority": precision_score(gts, preds, pos_label=1, zero_division=0),
        "recall_minority": recall_score(gts, preds, pos_label=1, zero_division=0),
        "average_precision": average_precision_score(gts, probs),
    }, preds, gts, probs


def write_environment(path: Path):
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}",
             f"torch: {torch.__version__}", f"cuda: {torch.cuda.is_available()}"]
    if torch.cuda.is_available():
        lines.append(f"gpu: {torch.cuda.get_device_name(0)}")
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


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
    parser.add_argument("--num-neighs", nargs="+", type=int, default=[100, 100])
    parser.add_argument("--patience", type=int, default=20,
                        help="Early stopping patience (epochs without val F1 improvement)")
    args = parser.parse_args()

    set_seed()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")

    # --- Load data ---
    print("\nLoading AMLworld HI-Small...")
    tr_data, val_data, te_data, tr_inds, val_inds, te_inds = load_data(args.raw_dir, args)

    # --- Loaders ---
    print("\nCreating LinkNeighborLoaders...")
    tr_loader, val_loader, te_loader = get_loaders(
        tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args)

    # --- Model ---
    sample_batch = next(iter(tr_loader))
    n_feats = sample_batch.x.shape[1]
    e_dim = sample_batch.edge_attr.shape[1] - 1  # minus ID column

    model = GINe(
        num_features=n_feats, num_gnn_layers=args.n_gnn_layers,
        n_classes=2, n_hidden=args.n_hidden,
        edge_updates=args.emlps, edge_dim=e_dim,
        dropout=args.dropout, final_dropout=args.final_dropout,
    ).to(device)

    n_params = sum(p.numel() for p in model.parameters())
    adaptations = []
    if args.emlps:
        adaptations.append("edge_MLPs")
    if args.ports:
        adaptations.append("ports")
    if args.tds:
        adaptations.append("time_deltas")
    adapt_str = " + ".join(adaptations) if adaptations else "none"

    print(f"\nGINe model: {n_params:,} parameters")
    print(f"  Adaptations: {adapt_str}")
    print(f"  Node features: {n_feats}, Edge features: {e_dim}")
    print(f"  Class weights: [{args.w_ce1}, {args.w_ce2}]")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="max", factor=0.5, patience=10, min_lr=1e-5, verbose=True)
    loss_fn = nn.CrossEntropyLoss(
        weight=torch.tensor([args.w_ce1, args.w_ce2], dtype=torch.float32).to(device))

    # --- Training with early stopping ---
    training_log = []
    best_val_f1 = 0.0
    best_epoch = 0
    patience_counter = 0

    print(f"\nTraining for up to {args.epochs} epochs (patience={args.patience})...")
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        train_loss, train_f1 = train_epoch(tr_loader, tr_inds, model, optimizer, loss_fn, device)
        val_metrics, _, _, _ = evaluate(val_loader, val_inds, model, device)
        elapsed = time.time() - t0

        val_f1 = val_metrics["f1_minority"]
        scheduler.step(val_f1)

        training_log.append({
            "epoch": epoch, "train_loss": train_loss, "train_f1": train_f1,
            "val_f1": val_f1, "val_ap": val_metrics["average_precision"],
            "lr": optimizer.param_groups[0]["lr"], "time_seconds": elapsed,
        })

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_epoch = epoch
            patience_counter = 0
            torch.save(model.state_dict(), args.out_dir / "model_best.pt")
        else:
            patience_counter += 1

        if epoch % 5 == 0 or epoch == 1:
            lr_now = optimizer.param_groups[0]["lr"]
            print(f"  Epoch {epoch:3d} | loss {train_loss:.4f} | "
                  f"train F1 {train_f1:.4f} | val F1 {val_f1:.4f} | "
                  f"val AP {val_metrics['average_precision']:.4f} | "
                  f"lr {lr_now:.6f} | {elapsed:.1f}s")

        if patience_counter >= args.patience:
            print(f"\n  Early stopping at epoch {epoch} (no improvement for {args.patience} epochs)")
            break

    print(f"\nBest val F1: {best_val_f1:.4f} at epoch {best_epoch}")

    # --- Test with best model ---
    print("\nLoading best model for test evaluation...")
    model.load_state_dict(torch.load(args.out_dir / "model_best.pt", weights_only=True))
    model.to(device)

    test_metrics, test_preds, test_labels, test_probs = evaluate(
        te_loader, te_inds, model, device)

    print(f"\n{'='*50}")
    print(f"  Test minority-F1:  {test_metrics['f1_minority']:.4f}")
    print(f"  Test precision:    {test_metrics['precision_minority']:.4f}")
    print(f"  Test recall:       {test_metrics['recall_minority']:.4f}")
    print(f"  Test AP:           {test_metrics['average_precision']:.4f}")
    print(f"{'='*50}")
    print(f"\n  E5b GFP+XGBoost was: F1=0.534, AP=0.589")
    if test_metrics["f1_minority"] > 0.534:
        print("  Multi-GINe BEATS the scientific caution baseline!")
    else:
        print("  Multi-GINe does NOT beat E5b — report honestly per roadmap.")

    # --- Save artifacts ---
    config = {
        "experiment": "E6_tgn",
        "model": "Multi-GINe (IBM Multi-GNN adaptations)",
        "adaptations": adapt_str,
        "dataset": "AMLworld HI-Small",
        "split": "60/20/20 day-based",
        "epochs_run": len(training_log),
        "best_epoch": best_epoch,
        "batch_size": args.batch_size, "lr": args.lr,
        "n_hidden": args.n_hidden, "n_gnn_layers": args.n_gnn_layers,
        "edge_updates": args.emlps, "ports": args.ports, "tds": args.tds,
        "dropout": args.dropout, "final_dropout": args.final_dropout,
        "w_ce1": args.w_ce1, "w_ce2": args.w_ce2,
        "num_neighbors": args.num_neighs,
        "patience": args.patience,
        "n_parameters": n_params, "seed": SEED, "device": str(device),
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({
        "best_val_f1": best_val_f1, "best_epoch": best_epoch,
        "test": test_metrics,
    }, indent=2), encoding="utf-8")

    pd.DataFrame({"true_label": test_labels, "predicted_label": test_preds,
                   "pred_prob": test_probs}).to_csv(args.out_dir / "predictions.csv", index=False)
    torch.save(model.state_dict(), args.out_dir / "model.pkl")
    pd.DataFrame(training_log).to_csv(args.out_dir / "training_log.csv", index=False)
    write_environment(args.out_dir / "environment.txt")

    print(f"\nAll artifacts written to {args.out_dir}/")


if __name__ == "__main__":
    main()