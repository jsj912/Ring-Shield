"""
GINe (Graph Isomorphism Network with edge features) — Phase 6, Experiment E6.

Adapted from IBM's Multi-GNN architecture (Egressy et al., AAAI 2024) which
achieves 28-57% F1 on HI-Small depending on adaptations. Uses:
  - GINEConv layers with residual connections
  - Edge MLPs for edge feature updates (--emlps flag)
  - Edge-level readout: MLP on [z_src || z_dst || edge_attr]
  - LinkNeighborLoader for mini-batch training with neighborhood sampling
  - Class weights tuned to ~6-9x (NOT the full 1283x ratio — proven unstable)

Usage:
    python models/tgn.py \
        --data-dir data/processed \
        --out-dir experiments/E6_tgn \
        --epochs 100 --batch-size 8192 --emlps

Expects:
    data/raw/formatted_transactions.csv
"""

import argparse
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


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True


# ---------------------------------------------------------------------------
# Model — GINe (from IBM Multi-GNN)
# ---------------------------------------------------------------------------
class GINe(nn.Module):
    """Graph Isomorphism Network with edge features.

    Architecture (Egressy et al.):
      1. Node embedding: Linear(1, n_hidden) — AMLworld nodes have no features,
         so we use a placeholder feature of 1.0 for all nodes.
      2. Edge embedding: Linear(edge_dim, n_hidden)
      3. N GINEConv layers with residual connections + BatchNorm
      4. Optional edge MLPs: update edge features using [z_src, z_dst, edge_attr]
      5. Edge readout: MLP on [z_src || z_dst || edge_attr] → 2 classes
    """

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

        # Edge readout: concat source + dest embeddings + edge features
        x = x[edge_index.T].reshape(-1, 2 * self.n_hidden).relu()
        x = torch.cat((x, edge_attr.view(-1, edge_attr.shape[1])), 1)
        return self.mlp(x)


# ---------------------------------------------------------------------------
# Data loading — builds PyG Data objects from formatted_transactions.csv
# ---------------------------------------------------------------------------
def load_data(data_dir: Path, raw_dir: Path):
    """Load formatted_transactions.csv and build PyG graph with 60/20/20 split.

    Follows IBM's exact data loading protocol:
      - Nodes = accounts (placeholder feature of 1.0)
      - Edges = transactions (features: Timestamp, Amount Received, Currency, Format)
      - Split by day boundaries for 60/20/20
    """
    import itertools

    fmt_path = raw_dir / "formatted_transactions.csv"
    print(f"  Loading {fmt_path}...")
    df = pd.read_csv(fmt_path)

    # Normalize timestamps to start from 0
    df["Timestamp"] = df["Timestamp"] - df["Timestamp"].min()

    max_n_id = df[["from_id", "to_id"]].to_numpy().max() + 1
    n_nodes = max_n_id

    timestamps = torch.tensor(df["Timestamp"].values, dtype=torch.float32)
    y = torch.tensor(df["Is Laundering"].values, dtype=torch.long)

    ir = y.float().mean() * 100
    print(f"  Illicit ratio: {y.sum()}/{len(y)} = {ir:.2f}%")
    print(f"  Nodes: {n_nodes}, Transactions: {len(df)}")

    # Edge features
    edge_feature_cols = ["Timestamp", "Amount Received", "Received Currency", "Payment Format"]
    edge_index = torch.tensor(df[["from_id", "to_id"]].values.T, dtype=torch.long)
    edge_attr = torch.tensor(df[edge_feature_cols].values, dtype=torch.float32)

    # Node features: placeholder of 1.0 (IBM approach)
    x = torch.ones(n_nodes, 1, dtype=torch.float32)

    # --- Day-based 60/20/20 split (matching IBM) ---
    n_days = int(timestamps.max() / (3600 * 24) + 1)
    daily_inds = []
    daily_trans = []
    for day in range(n_days):
        l = day * 24 * 3600
        r = (day + 1) * 24 * 3600
        day_inds = torch.where((timestamps >= l) & (timestamps < r))[0]
        daily_inds.append(day_inds)
        daily_trans.append(day_inds.shape[0])

    split_per = [0.6, 0.2, 0.2]
    d_ts = np.array(daily_trans)
    split_scores = {}
    for i, j in itertools.combinations(range(len(d_ts)), 2):
        if j >= i:
            split_totals = [d_ts[:i].sum(), d_ts[i:j].sum(), d_ts[j:].sum()]
            total = np.sum(split_totals)
            if total == 0:
                continue
            split_props = [v / total for v in split_totals]
            score = max(abs(v - t) / t for v, t in zip(split_props, split_per))
            split_scores[(i, j)] = score

    i, j = min(split_scores, key=split_scores.get)
    split = [list(range(i)), list(range(i, j)), list(range(j, len(d_ts)))]
    print(f"  Split days: train={split[0][:3]}..., val={split[1][:3]}..., test={split[2][:3]}...")

    split_inds = {k: [] for k in range(3)}
    for k in range(3):
        for day in split[k]:
            split_inds[k].append(daily_inds[day])

    tr_inds = torch.cat(split_inds[0])
    val_inds = torch.cat(split_inds[1])
    te_inds = torch.cat(split_inds[2])

    print(f"  Train: {tr_inds.shape[0]} ({y[tr_inds].sum()} laund, "
          f"IR={y[tr_inds].float().mean()*100:.2f}%)")
    print(f"  Val:   {val_inds.shape[0]} ({y[val_inds].sum()} laund, "
          f"IR={y[val_inds].float().mean()*100:.2f}%)")
    print(f"  Test:  {te_inds.shape[0]} ({y[te_inds].sum()} laund, "
          f"IR={y[te_inds].float().mean()*100:.2f}%)")

    # --- Build PyG Data objects (IBM protocol: expanding window) ---
    # Train: only train edges
    # Val: train + val edges (evaluate only on val indices)
    # Test: all edges (evaluate only on test indices)
    e_tr = tr_inds.numpy()
    e_val = np.concatenate([tr_inds, val_inds])

    tr_data = Data(x=x, y=y[e_tr],
                   edge_index=edge_index[:, e_tr],
                   edge_attr=edge_attr[e_tr],
                   timestamps=timestamps[e_tr])

    val_data = Data(x=x, y=y[e_val],
                    edge_index=edge_index[:, e_val],
                    edge_attr=edge_attr[e_val],
                    timestamps=timestamps[e_val])

    te_data = Data(x=x, y=y,
                   edge_index=edge_index,
                   edge_attr=edge_attr,
                   timestamps=timestamps)

    # Z-normalize edge features (fit on train)
    mean = tr_data.edge_attr.mean(0)
    std = tr_data.edge_attr.std(0)
    std[std == 0] = 1.0
    tr_data.edge_attr = (tr_data.edge_attr - mean) / std
    val_data.edge_attr = (val_data.edge_attr - mean) / std
    te_data.edge_attr = (te_data.edge_attr - mean) / std

    # Add unique IDs for seed edge tracking in LinkNeighborLoader
    tr_data.edge_attr = torch.cat([torch.arange(tr_data.edge_attr.shape[0]).view(-1, 1),
                                    tr_data.edge_attr], dim=1)
    val_data.edge_attr = torch.cat([torch.arange(val_data.edge_attr.shape[0]).view(-1, 1),
                                     val_data.edge_attr], dim=1)
    te_data.edge_attr = torch.cat([torch.arange(te_data.edge_attr.shape[0]).view(-1, 1),
                                    te_data.edge_attr], dim=1)

    return tr_data, val_data, te_data, tr_inds, val_inds, te_inds


# ---------------------------------------------------------------------------
# Training & evaluation with LinkNeighborLoader
# ---------------------------------------------------------------------------
def get_loaders(tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args):
    tr_loader = LinkNeighborLoader(
        tr_data, num_neighbors=args.num_neighs,
        batch_size=args.batch_size, shuffle=True,
    )
    val_loader = LinkNeighborLoader(
        val_data, num_neighbors=args.num_neighs,
        edge_label_index=val_data.edge_index[:, val_inds],
        edge_label=val_data.y[val_inds],
        batch_size=args.batch_size, shuffle=False,
    )
    te_loader = LinkNeighborLoader(
        te_data, num_neighbors=args.num_neighs,
        edge_label_index=te_data.edge_index[:, te_inds],
        edge_label=te_data.y[te_inds],
        batch_size=args.batch_size, shuffle=False,
    )
    return tr_loader, val_loader, te_loader


def train_epoch(loader, tr_inds, model, optimizer, loss_fn, device):
    model.train()
    total_loss = 0
    total_examples = 0
    preds, gts = [], []

    for batch in loader:
        optimizer.zero_grad()

        # Find seed edges in batch
        inds = tr_inds.detach().cpu()
        batch_edge_inds = inds[batch.input_id.detach().cpu()]
        batch_edge_ids = loader.data.edge_attr.detach().cpu()[batch_edge_inds, 0]
        mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)

        # Remove the unique ID column from edge features
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
        total_examples += pred.numel()
        preds.append(pred.argmax(dim=-1).detach().cpu())
        gts.append(gt.detach().cpu())

    preds = torch.cat(preds).numpy()
    gts = torch.cat(gts).numpy()
    f1 = f1_score(gts, preds, pos_label=1, zero_division=0)
    return total_loss / max(total_examples, 1), f1


@torch.no_grad()
def evaluate(loader, inds, model, data, device):
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
        prob = F.softmax(out, dim=-1)[:, 1]
        pred = out.argmax(dim=-1)

        preds.append(pred.cpu())
        gts.append(batch.y[mask].cpu())
        probs.append(prob.cpu())

    preds = torch.cat(preds).numpy()
    gts = torch.cat(gts).numpy()
    probs = torch.cat(probs).numpy()

    metrics = {
        "f1_minority": f1_score(gts, preds, pos_label=1, zero_division=0),
        "precision_minority": precision_score(gts, preds, pos_label=1, zero_division=0),
        "recall_minority": recall_score(gts, preds, pos_label=1, zero_division=0),
        "average_precision": average_precision_score(gts, probs),
    }
    return metrics, preds, gts, probs


def write_environment(path: Path):
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}",
             f"torch: {torch.__version__}",
             f"cuda: {torch.cuda.is_available()}"]
    if torch.cuda.is_available():
        lines.append(f"gpu: {torch.cuda.get_device_name(0)}")
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
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
    parser.add_argument("--w-ce1", type=float, default=1.0,
                        help="Class weight for licit class")
    parser.add_argument("--w-ce2", type=float, default=9.0,
                        help="Class weight for illicit class (IBM uses 6-9, NOT full ratio)")
    parser.add_argument("--emlps", action="store_true",
                        help="Enable edge MLPs for edge feature updates")
    parser.add_argument("--num-neighs", nargs="+", type=int, default=[100, 100],
                        help="Number of neighbors to sample per hop")
    args = parser.parse_args()

    set_seed()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")

    # --- Load data ---
    print("\nLoading AMLworld HI-Small...")
    tr_data, val_data, te_data, tr_inds, val_inds, te_inds = load_data(
        args.data_dir, args.raw_dir
    )

    # --- Loaders ---
    print("\nCreating LinkNeighborLoaders...")
    tr_loader, val_loader, te_loader = get_loaders(
        tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args
    )

    # --- Model ---
    # Get actual edge dim (minus the ID column we prepended)
    sample_batch = next(iter(tr_loader))
    n_feats = sample_batch.x.shape[1]
    e_dim = sample_batch.edge_attr.shape[1] - 1  # -1 for the ID column

    model = GINe(
        num_features=n_feats,
        num_gnn_layers=args.n_gnn_layers,
        n_classes=2,
        n_hidden=args.n_hidden,
        edge_updates=args.emlps,
        edge_dim=e_dim,
        dropout=args.dropout,
        final_dropout=args.final_dropout,
    ).to(device)

    n_params = sum(p.numel() for p in model.parameters())
    print(f"\nGINe model: {n_params:,} parameters")
    print(f"  n_hidden={args.n_hidden}, layers={args.n_gnn_layers}, "
          f"edge_updates={args.emlps}")
    print(f"  Node features: {n_feats}, Edge features: {e_dim}")
    print(f"  Class weights: [{args.w_ce1}, {args.w_ce2}]")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss(
        weight=torch.tensor([args.w_ce1, args.w_ce2], dtype=torch.float32).to(device)
    )

    # --- Training ---
    training_log = []
    best_val_f1 = 0.0
    best_epoch = 0

    print(f"\nTraining for {args.epochs} epochs...")
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()

        train_loss, train_f1 = train_epoch(
            tr_loader, tr_inds, model, optimizer, loss_fn, device
        )

        val_metrics, _, _, _ = evaluate(val_loader, val_inds, model, val_data, device)
        elapsed = time.time() - t0

        training_log.append({
            "epoch": epoch,
            "train_loss": train_loss,
            "train_f1": train_f1,
            "val_f1": val_metrics["f1_minority"],
            "val_ap": val_metrics["average_precision"],
            "time_seconds": elapsed,
        })

        if val_metrics["f1_minority"] > best_val_f1:
            best_val_f1 = val_metrics["f1_minority"]
            best_epoch = epoch
            torch.save(model.state_dict(), args.out_dir / "model_best.pt")

        if epoch % 5 == 0 or epoch == 1:
            print(f"  Epoch {epoch:3d} | loss {train_loss:.4f} | "
                  f"train F1 {train_f1:.4f} | "
                  f"val F1 {val_metrics['f1_minority']:.4f} | "
                  f"val AP {val_metrics['average_precision']:.4f} | "
                  f"{elapsed:.1f}s")

    print(f"\nBest val F1: {best_val_f1:.4f} at epoch {best_epoch}")

    # --- Test evaluation with best model ---
    print("\nLoading best model for test evaluation...")
    model.load_state_dict(torch.load(args.out_dir / "model_best.pt", weights_only=True))
    model.to(device)

    test_metrics, test_preds, test_labels, test_probs = evaluate(
        te_loader, te_inds, model, te_data, device
    )

    print(f"\n{'='*50}")
    print(f"  Test minority-F1:  {test_metrics['f1_minority']:.4f}")
    print(f"  Test precision:    {test_metrics['precision_minority']:.4f}")
    print(f"  Test recall:       {test_metrics['recall_minority']:.4f}")
    print(f"  Test AP:           {test_metrics['average_precision']:.4f}")
    print(f"{'='*50}")
    print(f"\n  E5b GFP+XGBoost was: F1=0.534, AP=0.589")
    if test_metrics["f1_minority"] > 0.534:
        print(f"  GINe BEATS the scientific caution baseline!")
    else:
        print(f"  GINe does NOT beat E5b — report honestly per roadmap.")

    # --- Save artifacts ---
    config = {
        "experiment": "E6_tgn",
        "model": "GINe (adapted from IBM Multi-GNN)",
        "dataset": "AMLworld HI-Small",
        "split": "60/20/20 day-based",
        "epochs": args.epochs,
        "best_epoch": best_epoch,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "n_hidden": args.n_hidden,
        "n_gnn_layers": args.n_gnn_layers,
        "edge_updates": args.emlps,
        "dropout": args.dropout,
        "final_dropout": args.final_dropout,
        "w_ce1": args.w_ce1,
        "w_ce2": args.w_ce2,
        "num_neighbors": args.num_neighs,
        "n_parameters": n_params,
        "seed": SEED,
        "device": str(device),
    }
    (args.out_dir / "config.yaml").write_text(
        yaml.dump(config, sort_keys=False), encoding="utf-8")

    (args.out_dir / "metrics.json").write_text(json.dumps({
        "best_val_f1": best_val_f1,
        "best_epoch": best_epoch,
        "test": test_metrics,
    }, indent=2), encoding="utf-8")

    pd.DataFrame({
        "true_label": test_labels,
        "predicted_label": test_preds,
        "pred_prob": test_probs,
    }).to_csv(args.out_dir / "predictions.csv", index=False)

    torch.save(model.state_dict(), args.out_dir / "model.pkl")
    pd.DataFrame(training_log).to_csv(args.out_dir / "training_log.csv", index=False)
    write_environment(args.out_dir / "environment.txt")

    print(f"\nAll artifacts written to {args.out_dir}/")


if __name__ == "__main__":
    main()