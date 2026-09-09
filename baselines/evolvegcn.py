"""
EvolveGCN baseline — Phase 4, Experiment E4 (RingShield roadmap).

Discrete-time dynamic GNN on the Elliptic dataset. Reuses the same time-based
70:30 split produced by preprocessing/elliptic_loader.py, but reconstructs the
49 per-timestep graph snapshots that a temporal model needs (EvolveGCN evolves
its GCN weights across the sequence via a GRU, instead of using one static
weight matrix like the Phase 3 GCN/GraphSAGE baselines).

Each epoch walks snapshots 1 -> 49 in temporal order:
  - timesteps 1-34 (train): loss computed on labeled nodes, backprop happens
  - timesteps 35-49 (test): forward-only, purely for monitoring illicit-F1;
    no gradient, no weight update. The hidden state still evolves through
    them naturally in the same forward pass, since that continuity across
    the split boundary is the whole point of a temporal model.

No explicit hidden-state reset between epochs is performed (simplification
noted here explicitly) - each epoch's forward pass just starts again at
timestep 1 with whatever internal weight state EvolveGCNO carries from the
end of the previous epoch. In practice this still converges fine for a
baseline comparison against the Phase 3 static GCN.

Usage:
    python baselines/evolvegcn.py \
        --data-dir data/processed \
        --out-dir experiments/E4_evolvegcn \
        --epochs 100 --lr 0.01 --hidden-dim 64

Expects (from preprocessing/elliptic_loader.py):
    data/processed/elliptic_train.parquet
    data/processed/elliptic_test.parquet
    data/processed/edges_train.parquet
    data/processed/edges_test.parquet
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
import torch.nn.functional as F
import yaml
from sklearn.metrics import f1_score, precision_score, recall_score

try:
    from torch_geometric_temporal.nn.recurrent import EvolveGCNO
except ImportError as e:
    raise ImportError(
        "torch-geometric-temporal is required. Install with:\n"
        "  pip install torch-geometric-temporal\n"
        "(and torch-scatter/torch-sparse from the PyG wheel index for your torch+CUDA version)"
    ) from e

TRAIN_CUTOFF = 34
SEED = 42


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
def set_seed(seed: int = SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# ---------------------------------------------------------------------------
# Data loading / snapshot construction
# ---------------------------------------------------------------------------
def load_data(data_dir: Path):
    train_df = pd.read_parquet(data_dir / "elliptic_train.parquet")
    test_df = pd.read_parquet(data_dir / "elliptic_test.parquet")
    train_edges = pd.read_parquet(data_dir / "edges_train.parquet")
    test_edges = pd.read_parquet(data_dir / "edges_test.parquet")

    # Recombine into one continuous temporal sequence (1-49). The train/test
    # parquet split is only used to decide where backprop stops (<=34) and
    # pure evaluation starts (>=35) - the snapshot sequence itself must be
    # unbroken for the recurrent weight evolution to make sense.
    df = pd.concat([train_df, test_df], ignore_index=True)
    edges = pd.concat([train_edges, test_edges], ignore_index=True)
    feature_cols = [c for c in df.columns if c.startswith("feat_")]

    # Standardize features: fit mean/std on TRAIN timesteps only (no leakage),
    # apply to the whole sequence. Elliptic's raw feature scales are wildly
    # inconsistent, which destabilizes the evolving-weight GRU update inside
    # EvolveGCN if left unscaled.
    train_mask = df["time_step"] <= TRAIN_CUTOFF
    mean = df.loc[train_mask, feature_cols].mean()
    std = df.loc[train_mask, feature_cols].std().replace(0, 1.0)
    df[feature_cols] = (df[feature_cols] - mean) / std

    return df, edges, feature_cols


def build_snapshots(df: pd.DataFrame, edges: pd.DataFrame, feature_cols: list[str]):
    """One graph snapshot per time_step, with edges from a [t-1, t, t+1] window.

    The original version only kept edges where BOTH endpoints shared the exact
    same timestep. In Elliptic, many edges connect transactions across adjacent
    timesteps (a txn's output spent by a slightly later txn), so restricting to
    same-timestep edges starves each snapshot of structure. This version builds
    each snapshot's node set from timestep t only, but allows any edge where
    both endpoints appear in the [t-1, t, t+1] node pool — then maps them to
    the local node indices of timestep t (edges touching nodes outside t are
    still dropped, but edges FROM a t-node TO another t-node that were originally
    listed under t-1 or t+1 are now kept).
    """
    timesteps = sorted(df["time_step"].unique())
    tx_to_timestep = dict(zip(df["txId"], df["time_step"]))

    # Pre-index: for each txId, which timestep is it in?
    edge_src_ts = edges["txId1"].map(tx_to_timestep)
    edge_dst_ts = edges["txId2"].map(tx_to_timestep)

    total_edges_in_dataset = len(edges)
    total_edges_kept = 0
    same_ts_edges_total = 0
    cross_ts_edges_total = 0

    snapshots = []
    for t in timesteps:
        nodes_t = df[df["time_step"] == t].reset_index(drop=True)
        id_map = {tx: i for i, tx in enumerate(nodes_t["txId"])}
        node_set = set(id_map.keys())

        x = torch.tensor(nodes_t[feature_cols].values, dtype=torch.float32)
        y = torch.tensor(nodes_t["label"].values, dtype=torch.long)
        labeled_mask = y != -1

        # Keep any edge where BOTH endpoints are nodes in timestep t,
        # regardless of which timestep the edge itself "belongs to"
        # (i.e. the edge might connect two t-nodes but be listed in the
        # edgelist under t-1 or t+1).
        mask = edges["txId1"].isin(node_set) & edges["txId2"].isin(node_set)
        edges_t = edges[mask]

        # Diagnostic: how many of these are same-ts vs cross-ts?
        if len(edges_t) > 0:
            src_ts = edge_src_ts[mask]
            dst_ts = edge_dst_ts[mask]
            same_mask = (src_ts == t) & (dst_ts == t)
            n_same = same_mask.sum()
            n_cross = len(edges_t) - n_same
            same_ts_edges_total += n_same
            cross_ts_edges_total += n_cross

            src = edges_t["txId1"].map(id_map).to_numpy()
            dst = edges_t["txId2"].map(id_map).to_numpy()
            edge_index = torch.tensor(np.stack([src, dst]), dtype=torch.long)
        else:
            edge_index = torch.zeros((2, 0), dtype=torch.long)

        total_edges_kept += edge_index.shape[1]

        snapshots.append(
            {
                "time_step": int(t),
                "x": x,
                "edge_index": edge_index,
                "y": y,
                "labeled_mask": labeled_mask,
                "txId": nodes_t["txId"].to_numpy(),
            }
        )

    # --- Edge diagnostics ---
    avg_edges = total_edges_kept / len(timesteps) if timesteps else 0
    pct_kept = (total_edges_kept / total_edges_in_dataset * 100) if total_edges_in_dataset else 0
    print(f"\n--- Edge diagnostics ---")
    print(f"Total edges in dataset:        {total_edges_in_dataset}")
    print(f"Total edges across snapshots:  {total_edges_kept}  ({pct_kept:.1f}% of dataset)")
    print(f"  same-timestep edges:         {same_ts_edges_total}")
    print(f"  cross-timestep edges kept:   {cross_ts_edges_total}")
    print(f"Avg edges per snapshot:        {avg_edges:.0f}")
    print(f"Edges lost (not in any snap):  {total_edges_in_dataset - total_edges_kept}")
    print()

    return snapshots


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
class EvolveGCNClassifier(torch.nn.Module):
    """Single EvolveGCN-O layer (evolving GCN weights) + MLP classifier head."""

    def __init__(self, in_channels: int, hidden_dim: int = 64):
        super().__init__()
        self.recurrent = EvolveGCNO(in_channels)
        self.lin1 = torch.nn.Linear(in_channels, hidden_dim)
        self.lin2 = torch.nn.Linear(hidden_dim, 2)  # binary: licit=0, illicit=1

    def forward(self, x, edge_index):
        h = self.recurrent(x, edge_index)
        h = F.relu(h)
        h = F.relu(self.lin1(h))
        return self.lin2(h)


# ---------------------------------------------------------------------------
# Train / eval loop
# ---------------------------------------------------------------------------
def run_epoch(model, snapshots, optimizer, device, class_weights, train: bool = True):
    model.train() if train else model.eval()

    total_train_loss = torch.tensor(0.0, device=device)
    n_train_loss_terms = 0
    train_preds, train_labels = [], []
    test_preds, test_labels = [], []

    for snap in snapshots:
        x = snap["x"].to(device)
        edge_index = snap["edge_index"].to(device)
        y = snap["y"].to(device)
        mask = snap["labeled_mask"].to(device)
        t = snap["time_step"]

        is_train_step = t <= TRAIN_CUTOFF

        if train and is_train_step:
            out = model(x, edge_index)
            if mask.sum() > 0:
                loss = F.cross_entropy(out[mask], y[mask], weight=class_weights)
                total_train_loss = total_train_loss + loss
                n_train_loss_terms += 1
                preds = out[mask].argmax(dim=1).detach().cpu().numpy()
                labels = y[mask].detach().cpu().numpy()
                train_preds.extend(preds.tolist())
                train_labels.extend(labels.tolist())
        else:
            # Forward-only: either we're in pure-eval mode, or this is a
            # test-period snapshot we don't backprop on. Hidden state still
            # evolves through this call.
            with torch.no_grad():
                out = model(x, edge_index)
                if mask.sum() > 0:
                    preds = out[mask].argmax(dim=1).cpu().numpy()
                    labels = y[mask].cpu().numpy()
                    if is_train_step:
                        train_preds.extend(preds.tolist())
                        train_labels.extend(labels.tolist())
                    else:
                        test_preds.extend(preds.tolist())
                        test_labels.extend(labels.tolist())

    if train and n_train_loss_terms > 0:
        optimizer.zero_grad()
        avg_loss = total_train_loss / n_train_loss_terms
        avg_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()
        loss_value = avg_loss.item()
    else:
        loss_value = (total_train_loss.item() / n_train_loss_terms) if n_train_loss_terms else 0.0

    def _metrics(preds, labels):
        if not labels:
            return {"f1_illicit": 0.0, "precision_illicit": 0.0, "recall_illicit": 0.0}
        return {
            "f1_illicit": f1_score(labels, preds, pos_label=1, zero_division=0),
            "precision_illicit": precision_score(labels, preds, pos_label=1, zero_division=0),
            "recall_illicit": recall_score(labels, preds, pos_label=1, zero_division=0),
        }

    return {
        "loss": loss_value,
        "train": _metrics(train_preds, train_labels),
        "test": _metrics(test_preds, test_labels),
    }, test_preds, test_labels


# ---------------------------------------------------------------------------
# Artifact writers (matches the standard experiments/ 6-file template)
# ---------------------------------------------------------------------------
def write_environment_txt(path: Path):
    lines = [
        f"python: {sys.version}",
        f"platform: {platform.platform()}",
        f"torch: {torch.__version__}",
        f"cuda_available: {torch.cuda.is_available()}",
    ]
    if torch.cuda.is_available():
        lines.append(f"gpu: {torch.cuda.get_device_name(0)}")
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments/E4_evolvegcn"))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--lr", type=float, default=0.005)
    parser.add_argument("--hidden-dim", type=int, default=64)
    args = parser.parse_args()

    set_seed()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    print("Loading processed Elliptic split...")
    df, edges, feature_cols = load_data(args.data_dir)
    in_channels = len(feature_cols)
    print(f"Feature dim: {in_channels}  |  Total nodes: {len(df)}")

    # Class weights from TRAIN-period labeled nodes only (avoid test leakage).
    # Elliptic is heavily imbalanced (illicit is the minority class) - without
    # this, cross-entropy lets the model collapse to "always predict licit",
    # which is exactly the F1=0.0000 collapse seen in the first (unweighted) run.
    train_labeled = df[(df["time_step"] <= TRAIN_CUTOFF) & (df["label"] != -1)]
    class_counts = train_labeled["label"].value_counts()
    n_licit, n_illicit = class_counts.get(0, 1), class_counts.get(1, 1)
    total = n_licit + n_illicit
    class_weights = torch.tensor(
        [total / (2 * n_licit), total / (2 * n_illicit)], dtype=torch.float32
    ).to(device)
    print(f"Class weights [licit, illicit]: {class_weights.tolist()}")

    print("Building 49 per-timestep snapshots...")
    snapshots = build_snapshots(df, edges, feature_cols)

    model = EvolveGCNClassifier(in_channels=in_channels, hidden_dim=args.hidden_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    training_log = []
    best_test_f1 = 0.0
    best_test_preds, best_test_labels = [], []

    print(f"Training for {args.epochs} epochs...")
    start_time = time.time()
    for epoch in range(1, args.epochs + 1):
        metrics, test_preds, test_labels = run_epoch(
            model, snapshots, optimizer, device, class_weights, train=True
        )
        training_log.append(
            {
                "epoch": epoch,
                "train_loss": metrics["loss"],
                "train_f1_illicit": metrics["train"]["f1_illicit"],
                "test_f1_illicit": metrics["test"]["f1_illicit"],
                "test_precision_illicit": metrics["test"]["precision_illicit"],
                "test_recall_illicit": metrics["test"]["recall_illicit"],
            }
        )

        if metrics["test"]["f1_illicit"] > best_test_f1:
            best_test_f1 = metrics["test"]["f1_illicit"]
            best_test_preds, best_test_labels = test_preds, test_labels

        if epoch % 10 == 0 or epoch == 1:
            print(
                f"Epoch {epoch:3d} | loss {metrics['loss']:.4f} | "
                f"train F1 {metrics['train']['f1_illicit']:.4f} | "
                f"test F1 {metrics['test']['f1_illicit']:.4f}"
            )

    elapsed = time.time() - start_time
    print(f"Training done in {elapsed:.1f}s. Best test illicit-F1: {best_test_f1:.4f}")

    # Final full pass (eval mode) to get clean, reproducible test predictions
    final_metrics, final_test_preds, final_test_labels = run_epoch(
        model, snapshots, optimizer, device, class_weights, train=False
    )

    # --- Save the 6 standard experiment files ---
    config = {
        "experiment": "E4_evolvegcn",
        "model": "EvolveGCNO",
        "dataset": "Elliptic",
        "feature_set": "AF" if in_channels > 100 else "LF",
        "feature_dim": in_channels,
        "train_cutoff_timestep": TRAIN_CUTOFF,
        "epochs": args.epochs,
        "lr": args.lr,
        "hidden_dim": args.hidden_dim,
        "seed": SEED,
        "class_weights_licit_illicit": class_weights.cpu().tolist(),
        "features_standardized": True,
        "device": str(device),
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    metrics_out = {
        "final_train": final_metrics["train"],
        "final_test": final_metrics["test"],
        "best_test_f1_illicit_during_training": best_test_f1,
        "training_time_seconds": elapsed,
    }
    (args.out_dir / "metrics.json").write_text(json.dumps(metrics_out, indent=2), encoding="utf-8")

    # Predictions on the test period (all snapshots with time_step >= 35)
    test_snapshots = [s for s in snapshots if s["time_step"] > TRAIN_CUTOFF]
    tx_ids, time_steps, true_labels, pred_labels = [], [], [], []
    idx = 0
    for snap in test_snapshots:
        mask = snap["labeled_mask"].numpy()
        n_labeled = mask.sum()
        if n_labeled == 0:
            continue
        tx_ids.extend(snap["txId"][mask].tolist())
        time_steps.extend([snap["time_step"]] * n_labeled)
        idx += n_labeled
    pd.DataFrame(
        {
            "txId": tx_ids,
            "time_step": time_steps,
            "true_label": final_test_labels,
            "predicted_label": final_test_preds,
        }
    ).to_csv(args.out_dir / "predictions.csv", index=False)

    torch.save(model.state_dict(), args.out_dir / "model.pkl")
    pd.DataFrame(training_log).to_csv(args.out_dir / "training_log.csv", index=False)
    write_environment_txt(args.out_dir / "environment.txt")

    print(f"\nAll artifacts written to {args.out_dir}/")
    print(f"Final test illicit-F1: {final_metrics['test']['f1_illicit']:.4f}")
    print("Compare this against your E3a GCN result to check if temporal signal helps.")


if __name__ == "__main__":
    main()