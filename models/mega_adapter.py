"""MEGA-GNN as a second detector (Step 10, R6) -- an adapter, not a fork.

    python models/mega_adapter.py --dry-run                       # one epoch, timing only
    python models/mega_adapter.py --seeds 1 2 3 4 5
    python models/calibrate.py --scores-dir experiments/R6_mega --seeds 1 2 3 4 5

**Nothing in `third_party/mega_gnn` is edited.** Their model (`models.MultiMPNN`), their data
objects (`data_loading.get_data`) and their feature construction (parallel-edge flattening, ego
ids) are imported as published. `get_data` is pointed at `data/raw/formatted_transactions.csv`,
the same file our own detector reads, and performs the same IBM 60/20/20 day split -- the adapter
asserts the resulting splits are exactly our `data/processed/amlworld_{train,val,test}.parquet`
edge sets, so nothing about the evaluation windows changes. Two of their imports are pybind11
extensions shipped as Linux / Python 3.9 binaries; `third_party/shims/` provides a pure-python
`ports_cpp` with identical semantics (unused here: their AML command does not pass `--ports`) and
a `negative_sampling` stub that raises (their link-prediction task only, which we never run). The
shims go on `sys.path` ahead of the clone.

**Sampling route.** Their loader is `LinkNeighborLoader`, so this run uses **our** causal loader
(`models/causal_loader.py`) exactly as R1 does -- same seed guarantee, same temporal filter, same
fallback window W = 1,800 s. The active route is recorded in `config.yaml` (`loader_route`) and
footnoted per detector in the r6 table.

`simp_edge_batch` (their parallel-edge grouping) is dropped from the data objects and recomputed
per batch here, after the causal filter has run: the loader appends the seed edges back and drops
non-causal ones, so a pre-sliced grouping would not line up. Recomputing is equivalent -- batch
node ids are a relabelling of the global ones, so two edges share an endpoint pair locally iff
they do globally -- and it is `find_parallel_edges`'s semantics without its per-edge python loop.

**Defaults.** `model_settings.json["gin"]["params"]` (their AML tuning: lr 0.003213, n_hidden 64,
2 GNN layers, w_ce 1 / 6.275, dropout 0.0098 / 0.105) with the flags of their published AML
command (`--model gin --emlps --reverse_mp --ego --flatten_edges --edge_agg_type gin
--task edge_class`; note it passes neither `--ports` nor `--tds`). Deviations, all recorded in
`config.yaml`: early stopping on validation minority-F1 under R1's rule (patience 20) inside
their published 80-epoch budget rather than a fixed 80, our causal loader, and seeds 1-5 from
`configs/seeds.yaml`. One train+val epoch measured 239 s here, against 246-266 s for R1's
Multi-GINe, so a seed costs about what R1's seeds cost.

Outputs, in our formats so every downstream step works unchanged:
`scores_{train,val,test}_seed<S>.parquet` (edge_id, timestamp, score_raw -- `models/calibrate.py`
adds `score_calibrated`), `embeddings_{val,test}_seed<S>.parquet` (the classifier head's input,
3 x n_hidden), `model_best_seed<S>.pt`, `training_log_seed<S>.csv`, `metrics_seed<S>.json`,
`config.yaml`, `environment.txt`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import platform
import random
import subprocess
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import yaml
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score

REPO_ROOT = Path(__file__).resolve().parents[1]
MEGA = REPO_ROOT / "third_party" / "mega_gnn"
SHIMS = REPO_ROOT / "third_party" / "shims"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _add_upstream_paths() -> None:
    """Their directories go at the END of sys.path: `models` must keep resolving to our own
    package (a namespace package, which loses to their top-level models.py wherever their
    directory comes first), and the shims must shadow their Linux-only compiled modules."""
    for p in (str(SHIMS), str(MEGA), str(MEGA / "genagg")):
        if p not in sys.path:
            sys.path.append(p)


from torch_geometric.data import HeteroData  # noqa: E402

from models.causal_loader import REV, ROUTE, TO, WINDOW_S, make_loader, seed_mask  # noqa: E402
from models.tgn import _align_to_inds  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402

SPLITS = ("train", "val", "test")
_UPSTREAM: dict = {}
# their published AML command: --model gin --emlps --reverse_mp --ego --flatten_edges
#                              --edge_agg_type gin --n_epochs 80 --task edge_class
MEGA_FLAGS = dict(model="gin", task="edge_class", emlps=True, reverse_mp=True, ego=True,
                  flatten_edges=True, edge_agg_type="gin", node_agg_type="sum",
                  ports=False, ports_batch=False, tds=False, reverse_mp_lp=False, adamm_hetero=False)


def upstream() -> dict:
    """Import their modules unchanged.

    Their model lives in `third_party/mega_gnn/models.py`, whose name collides with our own
    `models/` package -- and ours is already imported, so `from models import MultiMPNN` inside
    their `training.py` would find the wrong one. Their model module is therefore loaded from its
    file and registered as `models` only for the duration of their imports, then ours is put back.
    `training.py` also imports wandb at module level; `third_party/shims/wandb.py` stands in for
    it (we use only `get_model` from that module and never their training loops).
    """
    if _UPSTREAM:
        return _UPSTREAM
    _add_upstream_paths()
    import importlib.util
    spec = importlib.util.spec_from_file_location("mega_models", MEGA / "models.py")
    mega_models = importlib.util.module_from_spec(spec)
    sys.modules["mega_models"] = mega_models
    ours = sys.modules.get("models")
    sys.modules["models"] = mega_models
    try:
        spec.loader.exec_module(mega_models)
        import data_loading
        import train_util
        import training
    finally:
        if ours is not None:
            sys.modules["models"] = ours
        else:  # pragma: no cover
            sys.modules.pop("models", None)
    _UPSTREAM.update(models=mega_models, data_loading=data_loading, train_util=train_util, training=training)
    return _UPSTREAM


def git_commit(repo: Path = REPO_ROOT) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def mega_flags(edge_agg_type: str = "gin", node_agg_type: str = "sum") -> dict:
    """MEGA_FLAGS with the two aggregator choices overridden. The defaults are the published
    MEGA-GIN command (R6); MEGA-GenAgg is `genagg` / `genagg` -- the paper (App. C.5) uses
    GenAgg at both the parallel-edge and the neighbour stage."""
    return {**MEGA_FLAGS, "edge_agg_type": edge_agg_type, "node_agg_type": node_agg_type}


def mega_args(raw_dir: Path, batch_size: int, num_neighs, seed: int, device: str, window_s: int,
              flags: dict | None = None):
    """The argparse namespace their code reads. `data` is the raw directory's name, so their
    f"{aml_data}/{data}/formatted_transactions.csv" resolves to our own raw CSV."""
    return types.SimpleNamespace(batch_size=batch_size, num_neighs=list(num_neighs), seed=seed, device=device,
                                 data=raw_dir.name, window_s=window_s, inference=False, finetune=False,
                                 testing=True, tqdm=False, save_model=False, unique_name=None, n_epochs=0,
                                 **(flags or MEGA_FLAGS))


def load_mega_data(args, raw_dir: Path):
    """Their `get_data`, unmodified, reading our raw CSV."""
    data_loading = upstream()["data_loading"]
    cfg = {"paths": {"aml_data": str(raw_dir.parent), "model_to_load": "", "model_to_save": ""}}
    assert (raw_dir / "formatted_transactions.csv").exists(), raw_dir
    return data_loading.get_data(args, cfg)


def check_splits(inds_of: dict, processed_dir: Path) -> None:
    """Their day split must be our day split, or the evaluation windows would not apply."""
    for split, inds in inds_of.items():
        ids = np.sort(inds.numpy())
        ours = np.sort(pd.read_parquet(processed_dir / f"amlworld_{split}.parquet",
                                       columns=["EdgeID"])["EdgeID"].to_numpy())
        assert ids.shape == ours.shape and (ids == ours).all(), (
            f"MEGA's {split} split differs from ours: {ids.shape} vs {ours.shape}")
    print("[mega] split check: their IBM 60/20/20 day split == our amlworld_{train,val,test}.parquet")


def drop_simp_edge_batch(data) -> None:
    """Remove the per-edge grouping from the data object (recomputed per batch, see the docstring)."""
    stores = [data[k] for k in (TO, REV)] if isinstance(data, HeteroData) else [data]
    for st in stores:
        if "simp_edge_batch" in st:
            del st["simp_edge_batch"]


def _groups(edge_index: torch.Tensor) -> torch.Tensor:
    """Contiguous ids grouping parallel edges (same ordered endpoint pair). Vectorised
    equivalent of their `find_parallel_edges`; their aggregator re-uniques them anyway."""
    if edge_index.numel() == 0:
        return torch.zeros(0, dtype=torch.long, device=edge_index.device)
    key = edge_index[0].to(torch.int64) * (int(edge_index.max()) + 1) + edge_index[1].to(torch.int64)
    return torch.unique(key, return_inverse=True)[1]


class AddSimpEdgeBatch:
    """Recompute `simp_edge_batch` on each store after the seed/causal fix."""

    def __call__(self, batch):
        if isinstance(batch, HeteroData):
            for k in (TO, REV):
                batch[k].simp_edge_batch = _groups(batch[k].edge_index)
        else:
            batch.simp_edge_batch = _groups(batch.edge_index)
        return batch


def _ego_ids(args):
    """Their `AddEgoIds`, unchanged apart from satisfying a newer PyG.

    It overrides `BaseTransform.__call__` and predates PyG making `forward` abstract, so the
    published class cannot be instantiated here; the subclass adds the missing method and routes
    it straight back to their implementation.
    """
    base = upstream()["train_util"].AddEgoIds
    if not args.ego:
        return None

    class EgoIds(base):
        def forward(self, data):
            return base.__call__(self, data)

    return EgoIds()


def build_transform(args):
    simp = AddSimpEdgeBatch()
    ego = _ego_ids(args)

    def run(batch):
        batch = simp(batch)
        return ego(batch) if ego is not None else batch
    return run


@contextlib.contextmanager
def _untraced_index_select():
    """Undo PyG's monkey-patch of `torch.index_select` while `to_hetero` traces their model.

    `torch_geometric.hash_tensor` replaces the global `torch.index_select` with a wrapper that
    accepts non-tensor indices for its own `HashTensor`. The wrapper starts with
    `if isinstance(dim, int) and (dim < -input.dim() ...)`, and under `torch.fx` symbolic tracing
    `input.dim()` is a Proxy, so the branch raises `TraceError` -- which is what happens when
    `to_hetero` traces their `GnnHelper.forward` (`torch.index_select` at models.py:489). The
    original function is restored for the duration of the trace and PyG's wrapper is put back
    immediately afterwards; nothing here uses `HashTensor`, and the traced graph calls
    `torch.index_select` again at run time, on real tensors, through whichever function is
    installed then. Their model code is untouched.
    """
    import torch_geometric.hash_tensor as ht
    patched = getattr(ht, "_old_index_select", None)
    if patched is None or torch.index_select is patched:  # pragma: no cover - other PyG versions
        yield
        return
    current = torch.index_select
    torch.index_select = patched
    try:
        yield
    finally:
        torch.index_select = current


def build_model(sample_batch, params, args):
    """Their `training.get_model`, with wandb's `config` replaced by the settings dict."""
    training = upstream()["training"]
    cfg = types.SimpleNamespace(n_gnn_layers=int(params["n_gnn_layers"]), n_hidden=round(float(params["n_hidden"])),
                                final_dropout=float(params["final_dropout"]), dropout=float(params["dropout"]))
    with _untraced_index_select():
        return training.get_model(sample_batch, cfg, args)


def head_module(model) -> nn.Module:
    """The first Linear of their edge-classification head (input = [src, dst, edge] embeddings)."""
    try:
        return model.get_submodule("mlp.0")
    except AttributeError:
        for n, m in model.named_modules():
            if n.startswith("mlp") and hasattr(m, "weight"):
                return m
    raise RuntimeError("could not locate the classifier head of MultiMPNN")


def run_epoch(loader, inds, model, optimizer, loss_fn, device, hetero: bool, train: bool) -> dict:
    model.train(train)
    preds, gts, probs, ids = [], [], [], []
    total_loss = total_n = 0.0
    for batch in loader:
        mask, seed_global = seed_mask(batch)
        ids.append(seed_global.detach().cpu())
        batch = batch.to(device)
        with torch.set_grad_enabled(train):
            out = model(batch)[mask]
            gt = (batch[TO].y if hetero else batch.y)[mask]
            loss = loss_fn(out, gt)
            if train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
        total_loss += float(loss) * out.shape[0]
        total_n += out.shape[0]
        probs.append(torch.softmax(out, dim=-1)[:, 1].detach().float().cpu())
        preds.append(out.argmax(dim=-1).detach().cpu())
        gts.append(gt.detach().cpu())
    p, g, pr = _align_to_inds(inds, ids, *(torch.cat(x).numpy() for x in (preds, gts, probs)))
    return {"loss": total_loss / max(total_n, 1.0), "f1": f1_score(g, p, pos_label=1, zero_division=0),
            "precision": precision_score(g, p, pos_label=1, zero_division=0),
            "recall": recall_score(g, p, pos_label=1, zero_division=0),
            "average_precision": float(average_precision_score(g, pr))}


@torch.no_grad()
def score_split(model, data, inds, args, device, hetero: bool, want_embeddings: bool, causal: bool = True):
    model.eval()
    loader = make_loader(data, inds, args, causal=causal, shuffle=False, transform=build_transform(args))
    captured: dict = {}
    hook = head_module(model).register_forward_pre_hook(
        lambda m, i: captured.__setitem__("h", i[0].detach())) if want_embeddings else None
    probs, embs, ids = [], [], []
    for batch in loader:
        mask, seed_global = seed_mask(batch)
        ids.append(seed_global.detach().cpu())
        batch = batch.to(device)
        out = model(batch)
        probs.append(torch.softmax(out[mask], dim=-1)[:, 1].float().cpu())
        if want_embeddings:
            embs.append(captured["h"][mask].float().cpu())
    if hook is not None:
        hook.remove()
    arrays = [torch.cat(probs).numpy().astype(np.float64)]
    if want_embeddings:
        arrays.append(torch.cat(embs).numpy().astype(np.float32))
    return _align_to_inds(inds, ids, *arrays)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments" / "R6_mega")
    ap.add_argument("--epochs", type=int, default=80, help="their published AML budget")
    ap.add_argument("--patience", type=int, default=20, help="R1's early-stopping rule, on val minority-F1")
    ap.add_argument("--batch-size", type=int, default=8192)
    ap.add_argument("--num-neighs", type=int, nargs="+", default=[100, 100])
    ap.add_argument("--window-s", type=int, default=WINDOW_S)
    ap.add_argument("--splits", nargs="+", default=list(SPLITS))
    ap.add_argument("--embeddings-for", nargs="*", default=["val", "test"])
    ap.add_argument("--non-causal", action="store_true",
                    help="their own sampling (no temporal filter), as a control for the r6 footnote; "
                         "use a separate --out-dir, never for a reported detector row")
    ap.add_argument("--dry-run", action="store_true",
                    help="load the data, build the model, run one train+val epoch, report the epoch time; writes nothing")
    ap.add_argument("--edge-agg-type", default="gin", choices=["gin", "genagg", "pna", "sum"],
                    help="parallel-edge aggregator (their --edge_agg_type); gin = published MEGA-GIN")
    ap.add_argument("--node-agg-type", default="sum", choices=["sum", "genagg"],
                    help="neighbour aggregator inside GINEConv (their --node_agg_type); MEGA-GenAgg sets both to genagg")
    a = ap.parse_args(argv)
    flags = mega_flags(a.edge_agg_type, a.node_agg_type)
    variant = {("gin", "sum"): "MEGA-GIN", ("genagg", "genagg"): "MEGA-GenAgg"}.get(
        (a.edge_agg_type, a.node_agg_type), f"MEGA edge={a.edge_agg_type} node={a.node_agg_type}")
    t_start = time.time()
    paths = load_paths()
    out_dir = a.out_dir
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    params = json.loads((MEGA / "model_settings.json").read_text(encoding="utf-8"))["gin"]["params"]
    print(f"[mega] {variant} on {paths.get('dataset', 'HI-Small')}; device {device}; their AML defaults {params}")

    args = mega_args(paths["raw_dir"], a.batch_size, a.num_neighs, a.seeds[0], str(device), a.window_s, flags)
    t0 = time.time()
    tr_data, val_data, te_data, tr_inds, val_inds, te_inds = load_mega_data(args, paths["raw_dir"])
    inds_of = {"train": tr_inds, "val": val_inds, "test": te_inds}
    data_of = {"train": tr_data, "val": val_data, "test": te_data}
    check_splits(inds_of, paths["processed_dir"])
    add_arange_ids = upstream()["train_util"].add_arange_ids
    add_arange_ids([tr_data, val_data, te_data])
    for d in (tr_data, val_data, te_data):
        drop_simp_edge_batch(d)
    hetero = isinstance(tr_data, HeteroData)
    print(f"[mega] data ready in {time.time() - t0:.0f}s (hetero={hetero}); "
          f"train {tr_inds.numel():,} val {val_inds.numel():,} test {te_inds.numel():,}", flush=True)

    # our edge ids: EdgeID == row position in formatted_transactions.csv, and their loader never
    # reorders rows, so a split index is that edge's EdgeID (check_splits asserts this)
    fmt = pd.read_csv(paths["raw_dir"] / "formatted_transactions.csv", usecols=["EdgeID", "Timestamp"])
    edge_id, ts_csv = fmt["EdgeID"].to_numpy(np.int64), fmt["Timestamp"].to_numpy(np.int64)
    assert (edge_id == np.arange(len(edge_id))).all(), "EdgeID is no longer the row position"

    if not a.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for seed in a.seeds:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        args.seed = seed
        transform = build_transform(args)
        causal = not a.non_causal
        tr_loader = make_loader(tr_data, tr_inds, args, causal=causal, shuffle=True, transform=transform)
        val_loader = make_loader(val_data, val_inds, args, causal=causal, shuffle=False, transform=transform)
        model = build_model(next(iter(tr_loader)), params, args).to(device)
        n_params = sum(p.numel() for p in model.parameters())
        optimizer = torch.optim.Adam(model.parameters(), lr=float(params["lr"]))
        loss_fn = nn.CrossEntropyLoss(weight=torch.tensor([float(params["w_ce1"]), float(params["w_ce2"])]).to(device))
        print(f"[mega] seed {seed}: MultiMPNN {n_params:,} params; loader route {ROUTE['route']}"
              f"{'' if ROUTE['route'] == 'native' else f' (window {a.window_s}s)'}", flush=True)

        best_f1, best_epoch, log, waited = -1.0, 0, [], 0
        ckpt = out_dir / f"model_best_seed{seed}.pt"
        for epoch in range(1, a.epochs + 1):
            t_ep = time.time()
            tr_m = run_epoch(tr_loader, tr_inds, model, optimizer, loss_fn, device, hetero, train=True)
            va_m = run_epoch(val_loader, val_inds, model, optimizer, loss_fn, device, hetero, train=False)
            log.append({"epoch": epoch, "time_s": time.time() - t_ep,
                        **{f"train_{k}": v for k, v in tr_m.items()}, **{f"val_{k}": v for k, v in va_m.items()}})
            print(f"    epoch {epoch:3d} | loss {tr_m['loss']:.4f} | trF1 {tr_m['f1']:.4f} | "
                  f"valF1 {va_m['f1']:.4f} | valAP {va_m['average_precision']:.4f} | "
                  f"{log[-1]['time_s']:.0f}s", flush=True)
            if a.dry_run:
                t = log[-1]["time_s"]
                print(f"[mega] DRY RUN: {t:.0f}s for one train+val epoch on this machine -> "
                      f"{t * a.epochs * len(a.seeds) / 3600:.1f} h for {a.epochs} epochs x {len(a.seeds)} seeds "
                      f"(before scoring). Nothing written.")
                return log
            if va_m["f1"] > best_f1:
                best_f1, best_epoch, waited = va_m["f1"], epoch, 0
                torch.save(model.state_dict(), ckpt)
            else:
                waited += 1
                if waited >= a.patience:
                    print(f"    early stop at epoch {epoch}")
                    break
        model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True))
        pd.DataFrame(log).to_csv(out_dir / f"training_log_seed{seed}.csv", index=False)

        for split in a.splits:
            inds = inds_of[split]
            want_emb = split in (a.embeddings_for or [])
            arrays = score_split(model, data_of[split], inds, args, device, hetero, want_emb, causal=causal)
            pos = inds.numpy()
            order = np.argsort(edge_id[pos], kind="stable")
            sc = pd.DataFrame({"edge_id": edge_id[pos][order], "timestamp": ts_csv[pos][order],
                               "score_raw": arrays[0][order]})
            assert sc["edge_id"].is_unique and not sc["score_raw"].isna().any()
            sc.to_parquet(out_dir / f"scores_{split}_seed{seed}.parquet", index=False)
            msg = f"[mega] seed {seed} {split}: {len(sc):,} rows scored"
            if want_emb:
                emb = arrays[1][order]
                e = pd.DataFrame(emb, columns=[f"emb_{i:03d}" for i in range(emb.shape[1])])
                e.insert(0, "edge_id", sc["edge_id"].to_numpy())
                e.to_parquet(out_dir / f"embeddings_{split}_seed{seed}.parquet", index=False)
                msg += f", embeddings {emb.shape}"
            print(msg, flush=True)

        (out_dir / f"metrics_seed{seed}.json").write_text(json.dumps(
            {"seed": seed, "best_val_f1": best_f1, "best_epoch": best_epoch, "epochs_run": len(log),
             "mean_epoch_time_s": float(np.mean([r["time_s"] for r in log])), "n_params": n_params,
             "val_at_best": {k: v for k, v in log[best_epoch - 1].items() if k.startswith("val_")}},
            indent=2), encoding="utf-8")
        summary.append({"seed": seed, "best_val_f1": best_f1, "best_epoch": best_epoch})

    cfg = {"experiment": out_dir.name, "step": "10 (R6 detector swap)", "model_id": "mega",
           "model": f"MEGA-GNN / MultiMPNN ({variant})",
           "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": git_commit(),
           "upstream": {"repo": "https://github.com/hcagri/MEGA-GNN", "commit": git_commit(MEGA),
                        "license": "Apache-2.0", "model_code_edited": False,
                        "shims": ["ports_cpp (pure python; unused -- their AML command has no --ports)",
                                  "negative_sampling (stub; link-prediction task only)"]},
           "params": params, "flags": flags, "seeds": a.seeds, "epochs": a.epochs, "patience": a.patience,
           "batch_size": a.batch_size, "num_neighbors": list(a.num_neighs),
           "causal_sampling": not a.non_causal,
           "loader_route": ("mega_native_noncausal" if a.non_causal else f"ours_{ROUTE['route']}"),
           "loader_window_s": None if ROUTE["route"] == "native" else a.window_s,
           "deviations_from_upstream": [
               f"early stopping on val minority-F1 (patience {a.patience}, R1's rule) inside their "
               f"published {a.epochs}-epoch budget, instead of a fixed 80",
               "our causal loader (models/causal_loader.py) in place of their LinkNeighborLoader call "
               "-- same loader class, temporal guarantee added",
               "simp_edge_batch recomputed per batch after the causal filter (equivalent grouping)",
               "seeds 1-5 from configs/seeds.yaml instead of their single seed"]
           + (["GenAgg as published: MLPAutoencoder's inverse-objective forward hook never fires "
               "(GenAgg calls f.forward() directly, bypassing hooks), so f^-1 is trained only by the "
               "task loss; the node-stage GenAgg is one instance shared by every GINE layer"]
              if "genagg" in (a.edge_agg_type, a.node_agg_type) else []),
           "data": {"source": "data/raw/formatted_transactions.csv (the file our own detector reads)",
                    "split": "their get_data, asserted identical to amlworld_{train,val,test}.parquet",
                    "label_informed_preprocessing": False},
           "calibration": "models/calibrate.py --scores-dir <out-dir> (isotonic, fit on val only)",
           "summary": summary, "seconds": round(time.time() - t_start, 1)}
    (out_dir / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
    env = [f"python: {sys.version}", f"platform: {platform.platform()}", f"torch: {torch.__version__}",
           f"cuda: {torch.cuda.is_available()}", f"mega_gnn_commit: {git_commit(MEGA)}"]
    try:
        env.append("\n# pip freeze\n" + subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    except Exception:  # pragma: no cover
        pass
    (out_dir / "environment.txt").write_text("\n".join(env), encoding="utf-8")
    print(f"[mega] {len(summary)} seed(s) -> {out_dir}  ({cfg['seconds']} s)")


if __name__ == "__main__":
    main()
