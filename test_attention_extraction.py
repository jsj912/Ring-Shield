"""
Decide whether the saved Multi-GATv2 checkpoint can actually yield attention
weights. The whole GATv2-over-GINe architecture decision rests on this.

The problem with GATv2e.forward_with_attention(): training wraps the model in
to_hetero(), so the saved state_dict has keys like
    convs.0.conv.node__to__node.att
The raw GATv2e has no such keys, and load_state_dict() will fail. The path in
the log has never been executed.

The fix is not a separate forward method. Rebuild the hetero model exactly as
training did, load the checkpoint into it, then patch each GATv2Conv instance
so it captures attention as a side effect while returning its normal output.
The traced GraphModule stays untouched.

Place this in the repo root (next to models/) and run:

    python test_attention_extraction.py ^
        --raw-dir data/raw --data-dir data/processed ^
        --ckpt experiments/E6_gatv2/model.pkl ^
        --emlps --ports --tds --reverse-mp --ego --gfp ^
        --num-neighs 100 100

Pass EXACTLY the flags used in the training run, or edge_dim will not match.
"""

import argparse
from pathlib import Path
from types import SimpleNamespace

import torch
from torch_geometric.data import HeteroData
from torch_geometric.nn import GATv2Conv, to_hetero

from models.gatv2 import GATv2e, load_data, get_loaders


def attach_attention_capture(model):
    """Patch every GATv2Conv instance to record attention on each call.

    Returns (captured_list, conv_names). Each captured entry holds the
    edge_index and per-head alpha for one conv invocation. Note that with
    add_self_loops=True the returned edge_index includes appended self-loops,
    so it is LONGER than the edge_index passed in.
    """
    captured = []
    conv_names = []

    for name, module in model.named_modules():
        if not isinstance(module, GATv2Conv):
            continue
        conv_names.append(name)
        original = module.forward

        def patched(*a, _orig=original, _name=name, **kw):
            kw["return_attention_weights"] = True
            out, (attn_ei, alpha) = _orig(*a, **kw)
            captured.append({
                "conv": _name,
                "edge_index": attn_ei.detach().cpu(),
                "alpha": alpha.detach().cpu(),
            })
            return out  # caller sees the normal single return value

        module.forward = patched

    return captured, conv_names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    ap.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    ap.add_argument("--ckpt", type=Path, default=Path("experiments/E6_gatv2/model.pkl"))
    ap.add_argument("--n-hidden", type=int, default=64)
    ap.add_argument("--n-heads", type=int, default=4)
    ap.add_argument("--n-gnn-layers", type=int, default=2)
    ap.add_argument("--dropout", type=float, default=0.01)
    ap.add_argument("--final-dropout", type=float, default=0.1)
    ap.add_argument("--batch-size", type=int, default=4096)
    ap.add_argument("--emlps", action="store_true")
    ap.add_argument("--ports", action="store_true")
    ap.add_argument("--tds", action="store_true")
    ap.add_argument("--reverse-mp", action="store_true")
    ap.add_argument("--ego", action="store_true")
    ap.add_argument("--gfp", action="store_true")
    ap.add_argument("--num-neighs", nargs="+", type=int, default=[100, 100])
    args = ap.parse_args()

    args.num_neighs = list(args.num_neighs)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print("Loading data (this replays the full preprocessing) ...")
    tr_data, val_data, te_data, tr_inds, val_inds, te_inds, te_meta = load_data(
        args.raw_dir, args.data_dir, args)
    is_hetero = isinstance(tr_data, HeteroData)
    print(f"  is_hetero = {is_hetero}")

    tr_loader, val_loader, te_loader = get_loaders(
        tr_data, val_data, te_data, tr_inds, val_inds, te_inds, args)

    batch = next(iter(te_loader))
    if is_hetero:
        n_feats = batch["node"].x.shape[1]
        e_dim = batch["node", "to", "node"].edge_attr.shape[1] - 1
    else:
        n_feats = batch.x.shape[1]
        e_dim = batch.edge_attr.shape[1] - 1
    print(f"  n_feats={n_feats}, edge_dim={e_dim}")

    model = GATv2e(
        num_features=n_feats, num_gnn_layers=args.n_gnn_layers,
        n_classes=2, n_hidden=args.n_hidden, n_heads=args.n_heads,
        edge_updates=args.emlps, edge_dim=e_dim,
        dropout=args.dropout, final_dropout=args.final_dropout,
    )
    if is_hetero:
        model = to_hetero(model, te_data.metadata(), aggr="mean")
    model = model.to(device)

    print(f"Loading checkpoint {args.ckpt} ...")
    state = torch.load(args.ckpt, map_location=device, weights_only=True)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing or unexpected:
        print(f"  !! missing keys:    {len(missing)}")
        for k in missing[:5]:
            print(f"       {k}")
        print(f"  !! unexpected keys: {len(unexpected)}")
        for k in unexpected[:5]:
            print(f"       {k}")
        print("  Checkpoint does not match this architecture. Check that the "
              "flags above are identical to the training command.")
        return
    print("  Checkpoint loaded cleanly.")

    model.eval()
    captured, conv_names = attach_attention_capture(model)
    print(f"Patched {len(conv_names)} GATv2Conv modules:")
    for n in conv_names:
        print(f"    {n}")

    # Strip the EdgeID column the training loop removes before forward()
    with torch.no_grad():
        batch = batch.to(device)
        if is_hetero:
            for et in batch.edge_types:
                batch[et].edge_attr = batch[et].edge_attr[:, 1:]
            out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)
        else:
            batch.edge_attr = batch.edge_attr[:, 1:]
            out = model(batch.x, batch.edge_index, batch.edge_attr)

    print(f"\nForward pass OK. Captured {len(captured)} attention tensors.")
    for c in captured:
        ei, alpha = c["edge_index"], c["alpha"]
        print(f"  {c['conv']}")
        print(f"      edge_index {tuple(ei.shape)}  alpha {tuple(alpha.shape)}")
        print(f"      alpha range [{alpha.min():.4f}, {alpha.max():.4f}]  "
              f"mean {alpha.mean():.4f}")

    if not captured:
        print("\nNo attention captured. GATv2 gives you nothing E8 can use -- "
              "go back to Multi-GINe (0.599) and use a post-hoc explainer.")
        return

    flat = torch.cat([c["alpha"].reshape(-1) for c in captured])
    print(f"\nAll alphas: n={flat.numel()}, std={flat.std():.4f}")
    if flat.std() < 1e-3:
        print("WARNING: attention is nearly uniform. Technically extractable, "
              "but it will not produce a meaningful explanation for E8. "
              "Treat that as a negative result and say so in the paper.")
    else:
        print("Attention varies across neighbours -- usable for E8.")
        print("Next: decide how to combine the 'to' and 'rev_to' conv "
              "attention, since to_hetero mean-aggregates the two.")


if __name__ == "__main__":
    main()
