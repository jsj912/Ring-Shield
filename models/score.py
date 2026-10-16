"""Score a split from a saved Multi-GINe checkpoint (replaces score_test_set.py).

    python models/score.py --run-dir experiments/R1_gine_causal --seeds 1 --splits val test train \
        --embeddings-for val test
    python models/score.py --run-dir experiments/E6_tgn --seeds 1 42 123 --splits val test --non-causal \
        --out-dir experiments/R1_gine_noncausal

The data is prepared once per process and reused for every (seed, split) pair.

Reads <run-dir>/config.yaml for the architecture flags (adaptations, n_hidden, n_gnn_layers,
num_neighbors, batch_size, causal_sampling) and <run-dir>/model_best_seed<S>.pt, builds the
split's loader with models.causal_loader.make_loader (causal = the run's setting unless
--causal / --non-causal is given) and writes

    <out-dir>/scores_<split>_seed<S>.parquet        edge_id, timestamp, score_raw
    <out-dir>/embeddings_<split>_seed<S>.parquet    edge_id + emb_000.. (with --export-embeddings)
    <out-dir>/scores_<split>_seed<S>.log.json       counts, route, checkpoint, git commit

Row count == split size, every seed scored exactly once (models/causal_loader guarantee),
zero NaN, rows in split (edge_id) order, timestamps in the loader basis. The embedding is
the input to the classifier head for the `to` edge type: cat(relu(x_src), relu(x_dst),
edge_repr) = 3 * n_hidden float32 columns (198 for n_hidden = 66).
--window-s W overrides the causal fallback window (default: the run's loader_window_s,
else 1,800 s); the value used is written to the log as loader_window_s.
--dry-run scores the 1% row sample (pipeline check only; not a reportable output).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml
from torch_geometric.data import HeteroData
from torch_geometric.nn import to_hetero

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.causal_loader import ROUTE, TO, WINDOW_S, make_loader, seed_mask  # noqa: E402
from models.tgn import AddEgoIds, GINe, _align_to_inds, load_data  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402

SPLITS = ("train", "val", "test")
ADAPTATION_FLAGS = {"edge_MLPs": "emlps", "ports": "ports", "time_deltas": "tds",
                    "reverse_MP": "reverse_mp", "ego_IDs": "ego", "GFP_features": "gfp"}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def args_from_run_config(run_dir: Path, *, dry_run: bool, dry_run_seed: int) -> tuple[types.SimpleNamespace, dict]:
    cfg = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    paths = load_paths()
    a = types.SimpleNamespace(
        raw_dir=paths["raw_dir"], data_dir=paths["processed_dir"],
        n_hidden=int(cfg["n_hidden"]), n_gnn_layers=int(cfg["n_gnn_layers"]),
        num_neighs=list(cfg["num_neighbors"]), batch_size=int(cfg["batch_size"]),
        dropout=float(cfg.get("dropout", 0.01)), final_dropout=float(cfg.get("final_dropout", 0.1)),
        dry_run=dry_run, dry_run_seed=dry_run_seed,
        window_s=int(cfg.get("loader_window_s") or WINDOW_S),
        # Step 11 (R7): a run trained with a held-out pattern carries it in its config, so every
        # stage that rebuilds that run's data (cross-scoring, re-scoring) inherits the same holdout
        # instead of silently training on labels the detector never saw.
        hold_out_pattern=cfg.get("hold_out_pattern"),
        # Step V3.3: the run's split boundaries. `tgn.load_data` reads this; without it the
        # 60/20/20 day search runs again and scores a DIFFERENT edge set than the model was
        # trained on. Silent on HI-Small (where the search reproduces the shipped split) and
        # wrong on any run that forced its boundaries, which is why it is carried explicitly.
        split_days=(list(int(x) for x in cfg["split_days"])
                    if cfg.get("split_days") else None),
        # Step V3.3: scoring rebuilds the run's data, which includes the ports / time-delta
        # columns -- 82 minutes on HI-Medium. The cache is keyed on the source file's sha256, the
        # split boundaries, the node count and the flags, so a scoring run and a training run on
        # the same split share the same entry. Set by `--feature-cache`; None keeps the old
        # behaviour. `train_label_days` is deliberately NOT read back: scoring does not train, so
        # it wants the full train edge set.
        feature_cache=None,
    )
    for name, flag in ADAPTATION_FLAGS.items():
        setattr(a, flag, name in cfg.get("adaptations", []))
    return a, cfg


def build_model(args, data, sample_batch, device):
    hetero = isinstance(data, HeteroData)
    if hetero:
        n_feats = sample_batch["node"].x.shape[1]
        e_dim = sample_batch[TO].edge_attr.shape[1]
    else:
        n_feats = sample_batch.x.shape[1]
        e_dim = sample_batch.edge_attr.shape[1]
    model = GINe(num_features=n_feats, num_gnn_layers=args.n_gnn_layers, n_classes=2, n_hidden=args.n_hidden,
                 edge_updates=args.emlps, edge_dim=e_dim, dropout=args.dropout, final_dropout=args.final_dropout)
    if hetero:
        model = to_hetero(model, data.metadata(), aggr="mean")
    return model.to(device), hetero


def head_input_module(model, hetero: bool):
    """The first Linear of the classifier head for the `to` edge type."""
    name = "mlp.0.node__to__node" if hetero else "mlp.0"
    return model.get_submodule(name)


class RunScorer:
    """Loads the run's data once; scores any (seed, split) pair from it."""

    def __init__(self, run_dir: Path, *, dry_run: bool = False, dry_run_seed: int = 1,
                 device: torch.device | None = None, feature_cache: Path | None = None):
        self.run_dir = Path(run_dir)
        self.args, self.cfg = args_from_run_config(self.run_dir, dry_run=dry_run, dry_run_seed=dry_run_seed)
        if feature_cache is not None:
            self.args.feature_cache = Path(feature_cache)
        self.dry_run = dry_run
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        t0 = time.time()
        tr, va, te, tr_inds, val_inds, te_inds, self.edge_meta = load_data(self.args.raw_dir, self.args.data_dir,
                                                                          self.args)
        self.splits = {"train": (tr, tr_inds), "val": (va, val_inds), "test": (te, te_inds)}
        self.load_seconds = round(time.time() - t0, 1)
        print(f"[score] data ready in {self.load_seconds}s")

    def score(self, seed: int, split: str, out_dir: Path, *, causal: bool | None = None,
              export_embeddings: bool = False, window_s: int | None = None) -> dict:
        assert split in SPLITS, split
        args, cfg, out_dir = self.args, self.cfg, Path(out_dir)
        if causal is None:
            causal = bool(cfg.get("causal_sampling", False))
        if window_s is None:
            window_s = args.window_s
        ckpt = self.run_dir / f"model_best_seed{seed}.pt"
        assert ckpt.exists(), ckpt
        t0 = time.time()
        data, inds = self.splits[split]
        loader = make_loader(data, inds, args, causal=causal, shuffle=False,
                             transform=AddEgoIds() if args.ego else None, window_s=window_s)
        sample = next(iter(loader))
        model, hetero = build_model(args, data, sample, self.device)
        model.load_state_dict(torch.load(ckpt, map_location=self.device, weights_only=True))
        model.eval()

        captured: dict = {}
        hook = None
        if export_embeddings:
            def _pre_hook(module, inputs):
                captured["h"] = inputs[0].detach()
            hook = head_input_module(model, hetero).register_forward_pre_hook(_pre_hook)

        probs_all, ids_all, emb_all = [], [], []
        with torch.no_grad():
            for batch in loader:
                mask, seed_global = seed_mask(batch)
                ids_all.append(seed_global.detach().cpu())
                batch = batch.to(self.device)
                if hetero:
                    out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)[TO]
                else:
                    out = model(batch.x, batch.edge_index, batch.edge_attr)
                probs_all.append(torch.softmax(out[mask], dim=-1)[:, 1].float().cpu())
                if export_embeddings:
                    emb_all.append(captured["h"][mask].float().cpu())
        if hook is not None:
            hook.remove()

        probs = torch.cat(probs_all).numpy().astype(np.float64)
        arrays = [probs] + ([torch.cat(emb_all).numpy().astype(np.float32)] if export_embeddings else [])
        aligned = _align_to_inds(inds, ids_all, *arrays)  # rows now in `inds` order
        probs = aligned[0]
        meta = self.edge_meta.iloc[inds.numpy()].reset_index(drop=True)
        assert len(meta) == len(probs) == inds.numel()
        assert not np.isnan(probs).any(), "NaN score"

        out_dir.mkdir(parents=True, exist_ok=True)
        tag = f"{split}_seed{seed}" + ("_dryrun" if self.dry_run else "")
        order = np.argsort(meta["EdgeID"].values, kind="stable")
        scores = pd.DataFrame({"edge_id": meta["EdgeID"].values[order].astype("int64"),
                               "timestamp": meta["Timestamp"].values[order].astype("int64"),
                               "score_raw": probs[order]})
        scores_path = out_dir / f"scores_{tag}.parquet"
        scores.to_parquet(scores_path, index=False)

        emb_path = emb_shape = None
        if export_embeddings:
            emb = aligned[1]
            assert not np.isnan(emb).any(), "NaN embedding"
            cols = [f"emb_{i:03d}" for i in range(emb.shape[1])]
            emb_path = out_dir / f"embeddings_{tag}.parquet"
            # Written in row-group chunks rather than as one DataFrame. A whole-split export is
            # ~14 GiB on HI-Medium's test split, and `pd.DataFrame(emb[order])` holds three copies
            # at once -- the fancy-index result, pandas' F-order copy, and the original -- which
            # OOM'd at 13.9 GiB on seed 3 after seed 2 had run in the same process.
            import pyarrow as pa
            import pyarrow.parquet as pq

            eid = scores["edge_id"].values
            schema = pa.schema([("edge_id", pa.int64())]
                               + [(c, pa.float32()) for c in cols])
            rows_per_chunk = max(1, int(2_000_000))
            n = len(order)
            with pq.ParquetWriter(emb_path, schema) as w:
                for lo in range(0, n, rows_per_chunk):
                    sel = order[lo:lo + rows_per_chunk]
                    block = emb[sel]                      # one chunk only
                    arrays = [pa.array(eid[lo:lo + len(sel)])]
                    arrays += [pa.array(block[:, j]) for j in range(block.shape[1])]
                    w.write_table(pa.Table.from_arrays(arrays, schema=schema))
                    del block, arrays
            emb_shape = [int(n), int(emb.shape[1]) + 1]

        log = {
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "run_dir": str(self.run_dir), "checkpoint": str(ckpt), "run_config_commit": cfg.get("git_commit"),
            "seed": seed, "split": split, "dry_run": self.dry_run,
            "causal": causal, "loader_route": ROUTE["route"] if causal else "non-causal",
            "loader_window_s": loader.window_s,
            "num_neighbors": args.num_neighs, "batch_size": args.batch_size,
            "n_rows": int(len(scores)), "n_split_edges": int(inds.numel()),
            "n_nan_scores": int(np.isnan(probs).sum()),
            "score_min": float(probs.min()), "score_max": float(probs.max()), "score_mean": float(probs.mean()),
            "timestamp_basis": "loader (seconds since first day 00:00 - 10 s)",
            "timestamp_min": int(scores["timestamp"].min()), "timestamp_max": int(scores["timestamp"].max()),
            "embeddings": None if emb_path is None else {
                "path": str(emb_path), "shape": emb_shape,
                "definition": "classifier-head input for the `to` edge type: cat(relu(x_src), relu(x_dst), "
                              "edge_repr), 3 * n_hidden"},
            "device": str(self.device), "seconds": round(time.time() - t0, 1),
            "data_load_seconds": self.load_seconds, "scores_path": str(scores_path),
        }
        Path(str(scores_path).replace(".parquet", ".log.json")).write_text(json.dumps(log, indent=2), encoding="utf-8")
        print(f"[score] {self.run_dir.name} seed {seed} {split}: {len(scores):,} rows, NaN {log['n_nan_scores']}, "
              f"causal={causal} ({log['loader_route']}, W={loader.window_s}), emb={emb_shape}, {log['seconds']}s "
              f"-> {scores_path}")
        return log


def score_split(run_dir: Path, seed: int, split: str, out_dir: Path, *, causal: bool | None = None,
                export_embeddings: bool = False, dry_run: bool = False, device: torch.device | None = None,
                window_s: int | None = None) -> dict:
    """One (seed, split); loads the data for this call only."""
    return RunScorer(run_dir, dry_run=dry_run, dry_run_seed=seed, device=device).score(
        seed, split, out_dir, causal=causal, export_embeddings=export_embeddings, window_s=window_s)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--seeds", "--seed", dest="seeds", type=int, nargs="+", required=True)
    ap.add_argument("--splits", "--split", dest="splits", choices=SPLITS, nargs="+", required=True)
    ap.add_argument("--out-dir", type=Path, default=None, help="default: --run-dir")
    ap.add_argument("--export-embeddings", action="store_true", help="for every split given")
    ap.add_argument("--embeddings-for", choices=SPLITS, nargs="*", default=None,
                    help="export embeddings only for these splits (overrides --export-embeddings)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--causal", dest="causal", action="store_true", default=None)
    g.add_argument("--non-causal", dest="causal", action="store_false")
    ap.add_argument("--window-s", type=int, default=None,
                    help="causal fallback window in seconds (default: the run's loader_window_s)")
    ap.add_argument("--feature-cache", type=Path, default=None,
                    help="reuse cached ports/time-delta columns (see models/tgn.py). Shares "
                         "entries with training runs on the same split; off by default.")
    ap.add_argument("--batch-size", type=int, default=None,
                    help="override the run config's batch_size for inference only. The HI-Medium "
                         "test split is 18.9 M edges and training already sits at 24.1 of 24.5 GB "
                         "of VRAM; this does not change any score, only how many edges are "
                         "resident at once.")
    ap.add_argument("--device", default=None, choices=["cpu", "cuda"],
                    help="force the scoring device. CUDA_VISIBLE_DEVICES= is NOT a reliable way to "
                         "hide the GPU here: torch.cuda.is_available() can stay True while "
                         "device_count() is 0, and the checkpoint then fails to deserialise.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    import torch
    scorer = RunScorer(args.run_dir, dry_run=args.dry_run, dry_run_seed=args.seeds[0],
                       feature_cache=args.feature_cache,
                       device=torch.device(args.device) if args.device else None)
    if args.batch_size is not None:
        print(f"[score] batch_size {scorer.args.batch_size} -> {args.batch_size} (inference only)")
        scorer.args.batch_size = int(args.batch_size)
    for seed in args.seeds:
        for split in args.splits:
            emb = (split in args.embeddings_for) if args.embeddings_for is not None else args.export_embeddings
            scorer.score(seed, split, args.out_dir or args.run_dir, causal=args.causal, export_embeddings=emb,
                         window_s=args.window_s)


if __name__ == "__main__":
    main()
