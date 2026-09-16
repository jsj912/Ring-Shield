"""
Re-score the test set from a saved checkpoint, keeping each prediction's
global edge index so the output can be joined to the raw transactions.

Why this is needed: models/gatv2.py and models/tgn.py select seed edges with
    mask = torch.isin(batch.edge_attr[:, 0], batch_edge_ids)
which searches the SAMPLED SUBGRAPH for the seed IDs. A seed edge only appears
there if neighbour sampling happened to draw it, so a small fraction of test
edges are silently never scored, and the surviving rows come out in subgraph
order rather than te_inds order. Column 0 is the arange row index added at
load time, so the identity of each scored edge is available -- the training
script just throws it away.

No retraining required. This is a single forward pass over the test loader.

Place in the repo root (next to models/) and run with EXACTLY the flags used
for training:

    python score_test_set.py --arch gine ^
        --raw-dir data/raw --data-dir data/processed ^
        --ckpt experiments/E6_tgn/model_best_seed1.pt ^
        --threshold 0.46 ^
        --out experiments/E6_tgn/predictions_with_ids.csv ^
        --n-hidden 66 ^
        --emlps --ports --tds --reverse-mp --ego --gfp ^
        --num-neighs 100 100

Take --threshold from the matching per_seed entry in metrics.json
("best_threshold"). Unscored edges are written with pred_prob = NaN and
predicted_label = 0 so downstream code sees the full test set.

NOTE on --n-hidden: gatv2.py defaults to 64, tgn.py defaults to 66. Pass the
right one for the architecture or the checkpoint will not load.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch_geometric.data import HeteroData
from torch_geometric.nn import to_hetero


def mask_and_ids(batch, loader, inds, is_hetero):
    """Like _get_mask_and_clean, but also returns the global edge indices."""
    inds_cpu = inds.detach().cpu()
    if is_hetero:
        store = batch["node", "to", "node"]
        batch_edge_inds = inds_cpu[store.input_id.detach().cpu()]
        seed_ids = loader.data["node", "to", "node"].edge_attr.detach().cpu()[
            batch_edge_inds, 0]
        col0 = store.edge_attr[:, 0].detach().cpu()
        mask = torch.isin(col0, seed_ids)
        ids = col0[mask].long()
        store.edge_attr = store.edge_attr[:, 1:]
        batch["node", "rev_to", "node"].edge_attr = \
            batch["node", "rev_to", "node"].edge_attr[:, 1:]
    else:
        batch_edge_inds = inds_cpu[batch.input_id.detach().cpu()]
        seed_ids = loader.data.edge_attr.detach().cpu()[batch_edge_inds, 0]
        col0 = batch.edge_attr[:, 0].detach().cpu()
        mask = torch.isin(col0, seed_ids)
        ids = col0[mask].long()
        batch.edge_attr = batch.edge_attr[:, 1:]
    return mask, ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", choices=["gine"], required=True)
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--threshold", type=float, required=True,
                    help="best_threshold for this seed, from metrics.json")
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    ap.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--n-hidden", type=int, default=64,
                    help="64 for gatv2, 66 for gine (matches their defaults)")
    ap.add_argument("--n-heads", type=int, default=4)
    ap.add_argument("--n-gnn-layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.01)
    ap.add_argument("--final-dropout", type=float, default=0.1)
    ap.add_argument("--batch-size", type=int, default=8192)
    ap.add_argument("--emlps", action="store_true")
    ap.add_argument("--ports", action="store_true")
    ap.add_argument("--tds", action="store_true")
    ap.add_argument("--reverse-mp", action="store_true")
    ap.add_argument("--ego", action="store_true")
    ap.add_argument("--gfp", action="store_true")
    ap.add_argument("--num-neighs", nargs="+", type=int, default=[100, 100])
    args = ap.parse_args()
    args.num_neighs = list(args.num_neighs)

    from models.tgn import GINe as Net, load_data, get_loaders

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    print("Loading data ...")
    # load_data returns 6 values in the original repo and 7 in the current
    # version (te_meta appended). Tolerate both.
    _ret = load_data(args.raw_dir, args.data_dir, args)
    tr_data, val_data, te_data, tr_inds, val_inds, te_inds = _ret[:6]
    te_meta = _ret[6] if len(_ret) > 6 else None
    is_hetero = isinstance(tr_data, HeteroData)

    tr_loader, val_loader, te_loader = get_loaders(
        tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args)

    sample = next(iter(tr_loader))
    if is_hetero:
        n_feats = sample["node"].x.shape[1]
        e_dim = sample["node", "to", "node"].edge_attr.shape[1] - 1
    else:
        n_feats = sample.x.shape[1]
        e_dim = sample.edge_attr.shape[1] - 1
    print(f"  n_feats={n_feats}, edge_dim={e_dim}, hetero={is_hetero}")

    kwargs = dict(
        num_features=n_feats, num_gnn_layers=args.n_gnn_layers, n_classes=2,
        n_hidden=args.n_hidden, edge_updates=args.emlps, edge_dim=e_dim,
        dropout=args.dropout, final_dropout=args.final_dropout,
    )
    model = Net(**kwargs)
    if is_hetero:
        model = to_hetero(model, te_data.metadata(), aggr="mean")
    model = model.to(device)

    print(f"Loading {args.ckpt} ...")
    state = torch.load(args.ckpt, map_location=device, weights_only=True)
    model.load_state_dict(state)
    model.eval()
    print("  Checkpoint loaded.")

    all_ids, all_probs = [], []
    with torch.no_grad():
        for n, batch in enumerate(te_loader):
            mask, ids = mask_and_ids(batch, te_loader, te_inds, is_hetero)
            batch = batch.to(device)
            if is_hetero:
                out = model(batch.x_dict, batch.edge_index_dict,
                            batch.edge_attr_dict)
                out = out[("node", "to", "node")]
            else:
                out = model(batch.x, batch.edge_index, batch.edge_attr)
            probs = torch.softmax(out[mask], dim=-1)[:, 1]
            all_ids.append(ids.numpy())
            all_probs.append(probs.cpu().numpy())
            if n % 20 == 0:
                print(f"  batch {n}: {len(ids)} scored")

    ids = np.concatenate(all_ids)
    probs = np.concatenate(all_probs)
    print(f"\nScored {len(ids)} rows ({len(np.unique(ids))} unique)")

    # An edge reachable from both endpoints can be scored twice; average.
    scored = pd.DataFrame({"row": ids, "pred_prob": probs})
    n_dup = len(scored) - scored["row"].nunique()
    if n_dup:
        print(f"  {n_dup} duplicate scorings -> averaging")
        scored = scored.groupby("row", as_index=False)["pred_prob"].mean()

    te = te_inds.numpy()
    if te_meta is not None:
        print("Using te_meta returned by load_data().")
        out = te_meta.copy().reset_index(drop=True)
        if len(out) != len(te):
            raise SystemExit(
                f"te_meta has {len(out)} rows but te_inds has {len(te)}. "
                f"These must match -- check load_data().")
    else:
        print("load_data() returned no te_meta; rebuilding from raw CSV.")
        df = pd.read_csv(args.raw_dir / "formatted_transactions.csv")
        out = pd.DataFrame({
            "EdgeID": df["EdgeID"].values[te],
            "from_id": df["from_id"].values[te],
            "to_id": df["to_id"].values[te],
            "Timestamp": df["Timestamp"].values[te],
        })

    y_all = te_data["node", "to", "node"].y if is_hetero else te_data.y
    out["true_label"] = y_all.detach().cpu().numpy()[te]
    out["row"] = te
    out = out.merge(scored, on="row", how="left")

    n_missing = int(out["pred_prob"].isna().sum())
    n_missing_pos = int(out.loc[out["pred_prob"].isna(), "true_label"].sum())
    print(f"\nTest edges:      {len(out)}")
    print(f"Never sampled:   {n_missing} ({n_missing / len(out) * 100:.3f}%)")
    print(f"  ...of which laundering: {n_missing_pos}")
    if n_missing_pos:
        print("  These are unrecoverable recall. Report the number in the "
              "paper, or raise --num-neighs and re-score.")

    out["predicted_label"] = (
        out["pred_prob"].fillna(0.0) >= args.threshold).astype(int)
    out = out.drop(columns=["row"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"\nWrote {len(out)} rows -> {args.out}")

    # Recompute F1 over scored edges only, to confirm the checkpoint matches
    # what metrics.json reported.
    from sklearn.metrics import f1_score, average_precision_score
    ok = out["pred_prob"].notna()
    f1 = f1_score(out.loc[ok, "true_label"], out.loc[ok, "predicted_label"],
                  pos_label=1, zero_division=0)
    ap_ = average_precision_score(out.loc[ok, "true_label"],
                                  out.loc[ok, "pred_prob"])
    print(f"Sanity check on scored edges: minority-F1={f1:.4f}  AP={ap_:.4f}")
    print("If F1 is far from the metrics.json value for this seed, the flags "
          "or threshold do not match the training run.")


if __name__ == "__main__":
    main()