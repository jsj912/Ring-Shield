"""5-fold cross-scoring of the TRAIN split (Step 6.3, required before the expansion training set).

    python ringshield/expand/cross_score.py --run-dir experiments/R1_gine_causal \\
        --out-dir experiments/R3_cross_scores --epochs 30            # train + score all folds, assemble
    python ringshield/expand/cross_score.py ... --folds 2 3          # a subset of folds
    python ringshield/expand/cross_score.py ... --assemble-only      # rebuild the joined file
    python ringshield/expand/cross_score.py ... --dry-run --epochs 1

Why: the expansion policy is trained on train-period rings, and its detector feature for a
candidate must come from a model that never saw that candidate. R1's models were trained on
the whole train split, so their train scores are in-sample. Here the train DAYS are cut into
5 contiguous folds (day-aligned, chosen to balance edge counts: {0}, {1}, {2, 3}, {4}, {5}),
and for every fold k a causal Multi-GINe with R1's configuration (same adaptations, sizes,
loss weights, lr, causal fallback window; `--epochs` 30) is trained on the edges of the other
folds only -- the held-out days are removed from the training GRAPH as well as from the
labels -- with the checkpoint chosen on the real validation split (days 6-7), exactly as R1
chooses its checkpoints. The fold model then scores the held-out fold with the full train
split as the causal neighbourhood graph (only edges at or before the batch's latest seed are
visible, as in test-time scoring).

Outputs in --out-dir:
    fold<k>/model_best.pt, training_log.csv, fold.json (train_days, held_out_days, edge
        counts, best epoch, val F1, held-out AP / F1 at the val-tuned threshold / oracle F1)
    scores_fold<k>.parquet                    edge_id, timestamp, score_raw (held-out fold)
    cross_scores_train.parquet                every train edge once: edge_id, timestamp, day, fold,
        score_raw, score_quantile (rank / N within the fold, the policy's detector feature),
        dead_region (the fold model's head constants, ringshield/expand/dead_region.py),
        score_calibrated (R1 seed 1's val calibrator applied; recorded, NOT used by the policy
        -- fold models and R1 are on different scales, Step 6 amendment a)
    cross_scores.json                         fold table + the assertion record
    embeddings_fold<k>.parquet                (--embed-edges) head-input embeddings of the requested
        edges under the fold-k model: candidate edges of fold k and the included edges of the
        rings they belong to, so a policy row compares a candidate with its ring under ONE model
        (the candidate never seen by it; the included edges are known members anyway)
    config.yaml, environment.txt

    python ringshield/expand/cross_score.py --out-dir ... --embed-edges needed.parquet   # edge_id, fold

Assertion (check 1): for every row of cross_scores_train.parquet, the edge's day is not in
train_days[fold]; the fold configs record both sides. One scored edge per train edge.

Caveats recorded in cross_scores.json: the z-normalisation statistics of the edge features are
R1's (fit on all six train days, unsupervised); the val split used for checkpoint selection
carries the full train graph as neighbourhood context (no labels of the held-out fold are used).
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import yaml
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score
from torch_geometric.data import HeteroData

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from models.causal_loader import REV, ROUTE, TO, make_loader, seed_mask  # noqa: E402
from models.score import args_from_run_config, build_model, git_commit, head_input_module  # noqa: E402
from models.tgn import AddEgoIds, _align_to_inds, evaluate, load_data, train_epoch, tune_threshold  # noqa: E402
from ringshield.expand.dead_region import dead_region_mask, head_constants  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

N_FOLDS = 5
TRAIN_SEED = 1          # "R1 seed 1": the fold models use the same seed
DEFAULT_OUT = REPO_ROOT / "experiments" / "R3_cross_scores"


def days_of(timestamps) -> np.ndarray:
    w = load_windows()["val"]
    return w.days_of(timestamps)


def fold_assignment(day_counts: dict[int, int], n_folds: int = N_FOLDS) -> list[list[int]]:
    """Contiguous, day-aligned folds that minimise the largest fold (edge count); ties -> the
    partition with the smallest variance. Brute force over the C(D-1, K-1) boundary choices."""
    import itertools
    days = sorted(day_counts)
    assert len(days) >= n_folds, f"{len(days)} train days < {n_folds} folds"
    best, best_key = None, None
    for cuts in itertools.combinations(range(1, len(days)), n_folds - 1):
        bounds = [0, *cuts, len(days)]
        folds = [days[a:b] for a, b in zip(bounds[:-1], bounds[1:])]
        sizes = [sum(day_counts[d] for d in f) for f in folds]
        key = (max(sizes), float(np.var(sizes)))
        if best_key is None or key < best_key:
            best, best_key = folds, key
    return best


def subset_hetero(data: HeteroData, keep: torch.Tensor) -> HeteroData:
    """A new HeteroData holding only the `to` edges where keep is True (and their reverses); the
    global-id column (edge_attr[:, 0]) is reset to the new positions, as models.tgn.load_data does."""
    sub = HeteroData()
    sub["node"].x = data["node"].x
    to, rev = data[TO], data[REV]
    n = int(keep.sum())
    attr = to.edge_attr[keep].clone()
    attr[:, 0] = torch.arange(n, dtype=attr.dtype)
    sub[TO].edge_index = to.edge_index[:, keep]
    sub[TO].edge_attr = attr
    sub[TO].y = to.y[keep]
    sub[TO].timestamps = to.timestamps[keep]
    rattr = rev.edge_attr[keep].clone()
    rattr[:, 0] = torch.arange(n, dtype=rattr.dtype)
    sub[REV].edge_index = rev.edge_index[:, keep]
    sub[REV].edge_attr = rattr
    sub[REV].timestamps = to.timestamps[keep]
    return sub


@torch.no_grad()
def score_edges(model, data, inds: torch.Tensor, args, device, *, export_embeddings: bool = False):
    """Causal scoring of `inds` (positions into data's `to` edges) -> (probs, embeddings|None) in
    `inds` order. Same loop as models/score.py::RunScorer.score."""
    model.eval()
    hetero = isinstance(data, HeteroData)
    loader = make_loader(data, inds, args, causal=True, shuffle=False,
                         transform=AddEgoIds() if args.ego else None, window_s=args.window_s)
    captured: dict = {}
    hook = None
    if export_embeddings:
        hook = head_input_module(model, hetero).register_forward_pre_hook(lambda m, i: captured.__setitem__("h", i[0].detach()))
    probs_all, ids_all, emb_all = [], [], []
    for batch in loader:
        mask, seed_global = seed_mask(batch)
        ids_all.append(seed_global.detach().cpu())
        batch = batch.to(device)
        out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)[TO] if hetero else \
            model(batch.x, batch.edge_index, batch.edge_attr)
        probs_all.append(torch.softmax(out[mask], dim=-1)[:, 1].float().cpu())
        if export_embeddings:
            emb_all.append(captured["h"][mask].float().cpu())
    if hook is not None:
        hook.remove()
    probs = torch.cat(probs_all).numpy().astype(np.float64)
    arrays = [probs] + ([torch.cat(emb_all).numpy().astype(np.float32)] if export_embeddings else [])
    aligned = _align_to_inds(inds, ids_all, *arrays)
    assert not np.isnan(aligned[0]).any(), "NaN score"
    return aligned[0], (aligned[1] if export_embeddings else None)


def write_environment(path: Path):
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}", f"torch: {torch.__version__}",
             f"cuda: {torch.cuda.is_available()}", f"git_commit: {git_commit()}"]
    if torch.cuda.is_available():
        lines.append(f"gpu: {torch.cuda.get_device_name(0)}")
    try:
        lines.append("\n# pip freeze\n" + subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    except Exception:  # pragma: no cover
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


class CrossScorer:
    def __init__(self, run_dir: Path, out_dir: Path, *, epochs: int, dry_run: bool, device=None):
        self.run_dir, self.out_dir, self.epochs, self.dry_run = Path(run_dir), Path(out_dir), int(epochs), dry_run
        self.args, self.cfg = args_from_run_config(self.run_dir, dry_run=dry_run, dry_run_seed=TRAIN_SEED)
        self.args.causal = True
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        t0 = time.time()
        self.tr_data, self.val_data, _, self.tr_inds, self.val_inds, _, self.edge_meta = load_data(
            self.args.raw_dir, self.args.data_dir, self.args)
        assert isinstance(self.tr_data, HeteroData), "R1 uses reverse MP (HeteroData)"
        n_tr = self.tr_data[TO].edge_index.size(1)
        assert torch.equal(self.tr_inds, torch.arange(n_tr)), "train edges are expected to be the first rows"
        self.tr_meta = self.edge_meta.iloc[:n_tr].reset_index(drop=True)
        self.day = days_of(self.tr_meta["Timestamp"].values)
        counts = pd.Series(self.day).value_counts().sort_index()
        self.folds = fold_assignment({int(d): int(c) for d, c in counts.items()})
        print(f"[cross_score] data ready in {time.time() - t0:.0f}s; train days {counts.to_dict()}; "
              f"folds {self.folds}")
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ one fold
    def run_fold(self, k: int) -> dict:
        held = self.folds[k]
        train_days = sorted(d for f in self.folds if f is not held for d in f)
        fold_dir = self.out_dir / f"fold{k}"
        fold_dir.mkdir(parents=True, exist_ok=True)
        random.seed(TRAIN_SEED); np.random.seed(TRAIN_SEED); torch.manual_seed(TRAIN_SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(TRAIN_SEED)

        day_t = torch.as_tensor(self.day)
        keep = ~torch.isin(day_t, torch.as_tensor(held))
        held_inds = torch.where(~keep)[0]
        assert not set(self.day[keep.numpy()].tolist()) & set(held), "held-out day inside the training graph"
        fold_data = subset_hetero(self.tr_data, keep)
        fold_inds = torch.arange(int(keep.sum()))
        print(f"\n[cross_score] fold {k}: held-out days {held} ({held_inds.numel():,} edges); training on days "
              f"{train_days} ({fold_inds.numel():,} edges, {int(fold_data[TO].y.sum()):,} illicit)")

        args, device = self.args, self.device
        transform = AddEgoIds() if args.ego else None
        tr_loader = make_loader(fold_data, fold_inds, args, causal=True, shuffle=True, transform=transform, window_s=args.window_s)
        val_loader = make_loader(self.val_data, self.val_inds, args, causal=True, shuffle=False, transform=transform, window_s=args.window_s)
        model, hetero = build_model(args, fold_data, next(iter(tr_loader)), device)
        cfg = self.cfg
        optimizer = torch.optim.Adam(model.parameters(), lr=float(cfg["lr"]))
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=10, min_lr=1e-5)
        loss_fn = nn.CrossEntropyLoss(weight=torch.tensor([float(cfg["w_ce1"]), float(cfg["w_ce2"])]).to(device))

        log, best_f1, best_epoch = [], -1.0, 0
        ckpt = fold_dir / "model_best.pt"
        for epoch in range(1, self.epochs + 1):
            t0 = time.time()
            loss, tr_f1 = train_epoch(tr_loader, fold_inds, model, optimizer, loss_fn, device, hetero)
            vm, _, _, _ = evaluate(val_loader, self.val_inds, model, device, hetero)
            scheduler.step(vm["f1_minority"])
            log.append({"epoch": epoch, "train_loss": loss, "train_f1": tr_f1, "val_f1": vm["f1_minority"],
                        "val_ap": vm["average_precision"], "lr": optimizer.param_groups[0]["lr"], "time_s": time.time() - t0})
            if vm["f1_minority"] > best_f1:
                best_f1, best_epoch = vm["f1_minority"], epoch
                torch.save(model.state_dict(), ckpt)
            print(f"    fold {k} epoch {epoch:3d} | loss {loss:.4f} | trF1 {tr_f1:.4f} | valF1 {vm['f1_minority']:.4f} | "
                  f"valAP {vm['average_precision']:.4f} | {time.time() - t0:.0f}s", flush=True)
        pd.DataFrame(log).to_csv(fold_dir / "training_log.csv", index=False)
        model.load_state_dict(torch.load(ckpt, map_location=device, weights_only=True))

        # threshold on VAL (nothing chosen on the held-out fold), then score the held-out fold with the
        # full train split as the causal neighbourhood graph
        thr = float(tune_threshold(val_loader, self.val_inds, model, device, hetero))
        t0 = time.time()
        probs, _ = score_edges(model, self.tr_data, held_inds, args, device)
        y = self.tr_data[TO].y[held_inds].numpy()
        meta = self.tr_meta.iloc[held_inds.numpy()]
        sc = pd.DataFrame({"edge_id": meta["EdgeID"].values.astype(np.int64),
                           "timestamp": meta["Timestamp"].values.astype(np.int64), "score_raw": probs})
        order = np.argsort(sc["edge_id"].values, kind="stable")
        sc = sc.iloc[order].reset_index(drop=True)
        tag = "_dryrun" if self.dry_run else ""
        sc.to_parquet(self.out_dir / f"scores_fold{k}{tag}.parquet", index=False)
        pred = (probs >= thr).astype(int)
        f1_grid = max(f1_score(y, (probs >= t).astype(int), zero_division=0) for t in np.arange(0.05, 0.95, 0.01))
        consts = head_constants(torch.load(ckpt, map_location="cpu", weights_only=True))
        info = {"fold": k, "held_out_days": [int(d) for d in held], "train_days": [int(d) for d in train_days],
                "n_train_edges": int(fold_inds.numel()), "n_train_illicit": int(fold_data[TO].y.sum()),
                "n_held_out_edges": int(held_inds.numel()), "n_held_out_illicit": int(y.sum()),
                "epochs": self.epochs, "best_epoch": best_epoch, "best_val_f1": float(best_f1),
                "val_tuned_threshold": thr, "train_seed": TRAIN_SEED,
                "held_out": {"f1_at_val_threshold": float(f1_score(y, pred, zero_division=0)),
                             "precision_at_val_threshold": float(precision_score(y, pred, zero_division=0)),
                             "recall_at_val_threshold": float(recall_score(y, pred, zero_division=0)),
                             "average_precision": float(average_precision_score(y, probs)),
                             "f1_oracle_threshold": float(f1_grid), "base_rate": float(y.mean())},
                "head_constants": consts, "n_dead_region": int(dead_region_mask(probs, consts).sum()),
                "checkpoint": str(ckpt), "scores": str(self.out_dir / f"scores_fold{k}{tag}.parquet"),
                "mean_epoch_time_s": float(np.mean([r["time_s"] for r in log])), "score_seconds": round(time.time() - t0, 1),
                "loader_route": ROUTE["route"], "loader_window_s": int(args.window_s), "git_commit": git_commit(),
                "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (fold_dir / "fold.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        print(f"[cross_score] fold {k}: best val F1 {best_f1:.4f} @ epoch {best_epoch}; held-out AP "
              f"{info['held_out']['average_precision']:.4f}, F1 {info['held_out']['f1_at_val_threshold']:.4f} "
              f"(val thr {thr:.2f}; oracle {f1_grid:.4f}); dead-region {info['n_dead_region']:,}", flush=True)
        del tr_loader, val_loader, model, optimizer
        torch.cuda.empty_cache()
        return info

    def embed(self, needed: pd.DataFrame) -> dict:
        """Head-input embeddings for `needed` (edge_id, fold) under each fold's saved model; merged
        into embeddings_fold<k>.parquet (existing rows kept). Returns {fold: n_rows_written}."""
        tag = "_dryrun" if self.dry_run else ""
        eids = self.tr_meta["EdgeID"].to_numpy(np.int64)
        assert np.all(np.diff(eids) > 0)
        done = {}
        for k, grp in needed.groupby("fold"):
            k = int(k)
            ckpt = self.out_dir / f"fold{k}" / "model_best.pt"
            assert ckpt.exists(), f"fold {k} not trained: {ckpt}"
            want = np.unique(grp["edge_id"].to_numpy(np.int64))
            out_path = self.out_dir / f"embeddings_fold{k}{tag}.parquet"
            have = pd.read_parquet(out_path, columns=["edge_id"])["edge_id"].to_numpy(np.int64) if out_path.exists() else np.zeros(0, np.int64)
            todo = np.setdiff1d(want, have)
            if len(todo) == 0:
                done[k] = 0
                continue
            pos = np.searchsorted(eids, todo)
            assert np.all(eids[pos] == todo), "requested edge ids are not train edges"
            inds = torch.as_tensor(pos, dtype=torch.long)
            t0 = time.time()
            loader_sample = make_loader(self.tr_data, inds[:1], self.args, causal=True, window_s=self.args.window_s,
                                        transform=AddEgoIds() if self.args.ego else None)
            model, _ = build_model(self.args, self.tr_data, next(iter(loader_sample)), self.device)
            model.load_state_dict(torch.load(ckpt, map_location=self.device, weights_only=True))
            _, emb = score_edges(model, self.tr_data, inds, self.args, self.device, export_embeddings=True)
            new = pd.DataFrame(emb, columns=[f"emb_{i:03d}" for i in range(emb.shape[1])])
            new.insert(0, "edge_id", todo)
            if len(have):
                new = pd.concat([pd.read_parquet(out_path), new], ignore_index=True).sort_values("edge_id")
            new.to_parquet(out_path, index=False)
            done[k] = int(len(todo))
            print(f"[cross_score] fold {k}: embedded {len(todo):,} edges ({time.time() - t0:.0f}s) -> {out_path}", flush=True)
            del model
            torch.cuda.empty_cache()
        return done

    def write_config(self, argv_folds):
        cfg = {"experiment": self.out_dir.name, "step": "6.3 cross-scoring of the train split",
               "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": git_commit(),
               "run_dir": str(self.run_dir), "r1_config": {k: v for k, v in self.cfg.items() if k != "seeds"},
               "epochs": self.epochs, "train_seed": TRAIN_SEED, "n_folds": len(self.folds),
               "folds": [[int(d) for d in f] for f in self.folds], "folds_run": argv_folds,
               "fold_rule": "contiguous day-aligned folds minimising the largest fold's edge count",
               "held_out_removed_from": "training graph and labels", "checkpoint_selection": "val split (days 6-7) F1, as R1",
               "scoring_graph": "full train split, causal loader (edges <= the batch's latest seed)",
               "dry_run": bool(self.dry_run)}
        (self.out_dir / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
        write_environment(self.out_dir / "environment.txt")


def assemble(out_dir: Path, run_dir: Path, *, dry_run: bool = False) -> dict:
    """Join the fold score files into cross_scores_train.parquet and check the assertion."""
    import pickle
    tag = "_dryrun" if dry_run else ""
    folds = sorted(out_dir.glob("fold*/fold.json"))
    assert folds, f"no fold.json under {out_dir}"
    infos = [json.loads(p.read_text(encoding="utf-8")) for p in folds]
    parts = []
    for info in infos:
        k = info["fold"]
        sc = pd.read_parquet(out_dir / f"scores_fold{k}{tag}.parquet")
        sc["fold"] = np.int64(k)
        sc["day"] = days_of(sc["timestamp"].values).astype(np.int64)
        assert not set(sc["day"].unique().tolist()) & set(info["train_days"]), (
            f"fold {k}: scored an edge from a training day {sorted(set(sc['day'].unique()) & set(info['train_days']))}")
        assert set(sc["day"].unique().tolist()) <= set(info["held_out_days"]), (k, sc["day"].unique())
        r = sc["score_raw"].rank(method="average").to_numpy()
        sc["score_quantile"] = r / len(sc)
        sc["dead_region"] = dead_region_mask(sc["score_raw"].to_numpy(), info["head_constants"])
        parts.append(sc)
    df = pd.concat(parts, ignore_index=True).sort_values("edge_id").reset_index(drop=True)
    assert df["edge_id"].is_unique, "an edge was scored by more than one fold"
    train_days = {i["fold"]: set(i["train_days"]) for i in infos}
    viol = sum(int(d in train_days[f]) for d, f in zip(df["day"].tolist(), df["fold"].tolist()))
    assert viol == 0, f"{viol} edges scored by a model trained on their day"
    cal_path = run_dir / f"calibrator_seed{TRAIN_SEED}.pkl"
    if cal_path.exists():
        with open(cal_path, "rb") as fh:
            iso = pickle.load(fh)["model"]      # models/calibrate.py pickles {"seed", "method", "model"}
        df["score_calibrated"] = iso.predict(df["score_raw"].to_numpy())
    else:
        df["score_calibrated"] = np.nan
    out = out_dir / f"cross_scores_train{tag}.parquet"
    df.to_parquet(out, index=False)
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": git_commit(),
               "n_rows": int(len(df)), "n_folds": len(infos), "dry_run": dry_run,
               "assertion": {"rule": "day(edge) not in train_days[fold(edge)] for every row; one row per train edge",
                             "violations": viol, "passed": viol == 0},
               "folds": [{k: v for k, v in i.items() if k not in ("checkpoint", "scores")} for i in infos],
               "columns": {"score_raw": "fold model softmax", "score_quantile": "rank / N of score_raw within the fold "
                           "(the policy's detector feature, amendment a)", "dead_region": "score_raw == a head constant "
                           "of the fold model", "score_calibrated": f"R1 seed {TRAIN_SEED} val calibrator applied; recorded, "
                           "not used by the policy"},
               "n_dead_region": int(df["dead_region"].sum()),
               "caveats": ["edge-feature z-normalisation statistics are R1's (all six train days, unsupervised)",
                           "checkpoint selection on the val split whose loader carries the full train graph as "
                           "neighbourhood context (no held-out labels are used)"],
               "out": str(out)}
    (out_dir / f"cross_scores{tag}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[cross_score] assembled {len(df):,} rows -> {out}; assertion passed ({viol} violations); "
          f"dead-region {summary['n_dead_region']:,}")
    for i in infos:
        h = i["held_out"]
        print(f"  fold {i['fold']} held-out days {i['held_out_days']}: AP {h['average_precision']:.4f} | F1 "
              f"{h['f1_at_val_threshold']:.4f} @ val thr {i['val_tuned_threshold']:.2f} | oracle {h['f1_oracle_threshold']:.4f} "
              f"| best val F1 {i['best_val_f1']:.4f} (epoch {i['best_epoch']})")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, default=REPO_ROOT / "experiments" / "R1_gine_causal")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--folds", type=int, nargs="*", default=None, help="fold indices to run (default all)")
    ap.add_argument("--assemble-only", action="store_true")
    ap.add_argument("--embed-edges", type=Path, default=None, help="parquet (edge_id, fold): export embeddings, no training")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.assemble_only:
        assemble(args.out_dir, args.run_dir, dry_run=args.dry_run)
        return
    if args.embed_edges is not None:
        cs = CrossScorer(args.run_dir, args.out_dir, epochs=args.epochs, dry_run=args.dry_run)
        cs.embed(pd.read_parquet(args.embed_edges))
        return
    cs = CrossScorer(args.run_dir, args.out_dir, epochs=args.epochs, dry_run=args.dry_run)
    folds = list(range(len(cs.folds))) if not args.folds else args.folds
    cs.write_config(folds)
    for k in folds:
        cs.run_fold(k)
    done = {int(p.parent.name[4:]) for p in args.out_dir.glob("fold*/fold.json")}
    if done == set(range(len(cs.folds))):
        assemble(args.out_dir, args.run_dir, dry_run=args.dry_run)
    else:
        print(f"[cross_score] folds done {sorted(done)}; run the rest, then --assemble-only")


if __name__ == "__main__":
    main()
