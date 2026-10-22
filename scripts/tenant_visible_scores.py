"""R10 option (b): score each tenant on the graph IT can see, not on the pooled graph.

    python scripts/tenant_visible_scores.py --tenant 12 --seeds 1 --out-root E:/JSJ/tenant_visible

Visibility rule (the platform's, platform/DECISIONS.md PR-01): an edge is visible to tenant T when
`from_bank == T or to_bank == T`. The tenant graph is every visible edge from day 0 to the end of
the test split, so the causal history the detector uses is the tenant's own history only.

Per tenant (cached under <out-root>/T<tenant>/):
  raw/formatted_transactions.csv       the formatter's rows for the visible edges, EdgeIDs kept
  processed/amlworld_{split}.parquet   the split parquets restricted to the visible edges
  processed/amlworld_gfp_features_*    GFP RECOMPUTED on the tenant graph (graph/motif_features.py,
                                       trailing, as shipped). The detector does not use GFP (its
                                       adaptations are edge_MLPs, ports, time_deltas, reverse_MP);
                                       the ring layer does, through `ringshield run --gfp`.
Per seed:
  ports / time-deltas are rebuilt by tgn.load_data from the tenant graph -- causal, trailing,
  exactly the shipped code path. The split is FORCED to the pooled one (split_days [6, 8]): left to
  itself, load_data searches for a 60/20/20 day split over whatever edges it is given, and a tenant
  subset could move the val/test boundary.
  models/score.py with the shipped checkpoint, embeddings exported, no retraining.
  Calibration: the SHIPPED calibrator_seed<S>.pkl (fit on pooled val) applied to the tenant
  score_raw. It is not refit on the tenant: the calibrated score keeps the pooled meaning.
  is_seed: score_raw > the pooled seed cutoff q_S of that seed (the platform's fixed-cutoff rule),
  NOT a quantile within the tenant.

Writes <out-root>/scored_edges_visible_<T>_<model_id>_<S>[_val].parquet + .log.json and
embeddings_visible_<T>_<model_id>_<S>_{val,test}.parquet -- names that fill the platform's
`r10.tenant_visible_scores_template` ({tenant_id}, {model_id}, {seed}) and logs carrying the fields
its validator checks (split, model_id, seed, tenant_id, seed_rule.q), and reports how far the tenant view moved the
scores away from the pooled ones on the same edges.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402

SPLITS = ("train", "val", "test")
SPLIT_DAYS = [6, 8]                      # the pooled split: train 0-5, val 6-7, test 8-17


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def peak_rss_note() -> str:
    try:
        import psutil
        return f"{psutil.Process().memory_info().rss / 2**30:.2f} GiB rss (driver)"
    except Exception:
        return "rss n/a"


def build_tenant_data(T: int, root: Path, paths: dict) -> tuple[Path, dict]:
    tdir = root / f"T{T}"
    raw, proc = tdir / "raw", tdir / "processed"
    done = tdir / "data.done.json"
    if done.exists():
        return tdir, json.loads(done.read_text(encoding="utf-8"))
    raw.mkdir(parents=True, exist_ok=True)
    proc.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    pdir, rdir = paths["processed_dir"], paths["raw_dir"]
    vis, counts = [], {}
    for s in SPLITS:
        d = pd.read_parquet(pdir / f"amlworld_{s}.parquet")
        keep = ((d["from_bank"] == T) | (d["to_bank"] == T)).to_numpy()
        v = d[keep]
        v.to_parquet(proc / f"amlworld_{s}.parquet", index=False)
        # graph/motif_features.py builds GFP from amlworld_edges_<split>.parquet, which carries no
        # EdgeID. It is row-aligned with amlworld_<split>.parquet (checked: from, to, timestamp,
        # amount identical row for row on all three splits), so the same mask selects the same edges.
        e = pd.read_parquet(pdir / f"amlworld_edges_{s}.parquet")
        assert len(e) == len(d), f"amlworld_edges_{s} is not row-aligned with amlworld_{s}"
        assert (e["Timestamp"].to_numpy() == d["Timestamp"].to_numpy()).all()
        e[keep].to_parquet(proc / f"amlworld_edges_{s}.parquet", index=False)
        vis.append(v["EdgeID"].to_numpy(np.int64))
        counts[s] = int(len(v))
    ids = np.concatenate(vis)
    fmt = pd.read_csv(rdir / "formatted_transactions.csv")
    fmt[fmt["EdgeID"].isin(ids)].to_csv(raw / "formatted_transactions.csv", index=False)
    # everything else processed_dir is expected to hold (truth, account map) is pooled metadata,
    # not graph structure: link it through unchanged
    for f in ("amlworld_ring_ground_truth.parquet", "account_bank.parquet"):
        if (pdir / f).exists() and not (proc / f).exists():
            shutil.copy2(pdir / f, proc / f)
    t_data = time.time() - t0
    t0 = time.time()
    subprocess.run([sys.executable, str(REPO_ROOT / "graph" / "motif_features.py"), "--data-dir", str(proc),
                    "--out-dir", str(proc)], cwd=REPO_ROOT, check=True)
    t_gfp = time.time() - t0
    meta = {"tenant": T, "visibility_rule": "from_bank == T or to_bank == T, days 0 .. end of test",
            "n_visible": counts, "seconds_data": round(t_data, 1), "seconds_gfp": round(t_gfp, 1),
            "sources": {s: {"path": str(pdir / f"amlworld_{s}.parquet"), "sha256": sha(pdir / f"amlworld_{s}.parquet")}
                        for s in SPLITS} | {"formatted_transactions": {"path": str(rdir / "formatted_transactions.csv"),
                                                                      "sha256": sha(rdir / "formatted_transactions.csv")}}}
    done.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return tdir, meta


def tenant_paths_yaml(tdir: Path, paths: dict) -> Path:
    y = {"dataset": str(paths.get("dataset", "HI-Small")), "raw_dir": str(tdir / "raw"),
         "processed_dir": str(tdir / "processed"), "account_bank_map": str(paths["account_bank_map"]),
         "experiments_dir": str(paths["experiments_dir"])}
    p = tdir / "paths.yaml"
    p.write_text(yaml.safe_dump(y), encoding="utf-8")
    return p


def tenant_run_dir(tdir: Path, r1: Path, S: int) -> Path:
    run = tdir / "run"
    run.mkdir(exist_ok=True)
    cfg = yaml.safe_load((r1 / "config.yaml").read_text(encoding="utf-8"))
    cfg["split_days"] = SPLIT_DAYS
    cfg["note_tenant_visible"] = "copy of the shipped R1 config with split_days forced to the pooled split"
    (run / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    ck = run / f"model_best_seed{S}.pt"
    if not ck.exists():
        os.link(r1 / f"model_best_seed{S}.pt", ck)
    return run


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", type=int, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--model-id", default="gine_causal")
    a = ap.parse_args(argv)
    paths = load_paths()
    r1 = paths["experiments_dir"] / "R1_gine_causal"
    T, root = a.tenant, a.out_root
    root.mkdir(parents=True, exist_ok=True)
    timings = {}
    t0 = time.time()
    tdir, meta = build_tenant_data(T, root, paths)
    timings["data+gfp"] = {"data_s": meta["seconds_data"], "gfp_s": meta["seconds_gfp"]}
    tp = tenant_paths_yaml(tdir, paths)
    env = {**os.environ, "RINGSHIELD_PATHS": str(tp)}
    from ringshield.scored_edges import build_scored_edges
    for S in a.seeds:
        ts = time.time()
        run = tenant_run_dir(tdir, r1, S)
        sdir = tdir / f"scores_seed{S}"
        subprocess.run([sys.executable, str(REPO_ROOT / "models" / "score.py"), "--run-dir", str(run), "--seeds", str(S),
                        "--splits", "val", "test", "--export-embeddings", "--out-dir", str(sdir), "--causal"],
                       cwd=REPO_ROOT, env=env, check=True)
        t_score = time.time() - ts
        with open(r1 / f"calibrator_seed{S}.pkl", "rb") as f:
            cal = pickle.load(f)
        cout = paths["experiments_dir"].parent / "contract" / "out"      # the research checkout's contract files
        pooled_log = json.loads((cout / f"scored_edges_{a.model_id}_{S}.parquet.log.json").read_text(encoding="utf-8"))
        q = float(pooled_log["seed_rule"]["q"])
        report = {}
        for split in ("val", "test"):
            raw_scores = pd.read_parquet(sdir / f"scores_{split}_seed{S}.parquet")
            iso = cal["model"] if isinstance(cal, dict) else cal       # calibrate.py pickles {"model": IsotonicRegression, ...}
            raw_scores["score_calibrated"] = iso.predict(raw_scores["score_raw"].to_numpy(float))
            sc_path = sdir / f"scores_{split}_seed{S}_cal.parquet"
            raw_scores.to_parquet(sc_path, index=False)
            se = build_scored_edges(sc_path, split, model_id=a.model_id, seed=S,
                                    processed_dir=tdir / "processed", keep_unscored=False)
            if q is not None:
                se["is_seed"] = se["score_raw"].to_numpy(float) > q
            suffix = "" if split == "test" else "_val"
            out = root / f"scored_edges_visible_{T}_{a.model_id}_{S}{suffix}.parquet"
            se.to_parquet(out, index=False)
            emb_src = sdir / f"embeddings_{split}_seed{S}.parquet"
            emb_out = root / f"embeddings_visible_{T}_{a.model_id}_{S}_{split}.parquet"
            if emb_src.exists():
                shutil.copy2(emb_src, emb_out)
            # how far did the tenant view move the scores?
            pooled = pd.read_parquet(cout / f"scored_edges_{a.model_id}_{S}{suffix}.parquet", columns=["edge_id", "score_raw"])
            m = se[["edge_id", "score_raw"]].merge(pooled, on="edge_id", suffixes=("_t", "_p"))
            rho = float(m["score_raw_t"].rank().corr(m["score_raw_p"].rank())) if len(m) > 2 else float("nan")
            st = set(m.loc[m["score_raw_t"] > q, "edge_id"]) if q is not None else set()
            sp = set(m.loc[m["score_raw_p"] > q, "edge_id"]) if q is not None else set()
            jac = len(st & sp) / len(st | sp) if (st | sp) else float("nan")
            # Edge-level AP on the tenant's visible edges, pooled scores vs option (b). Labels are
            # read for REPORTING only: nothing here is tuned, thresholded or selected on them.
            from sklearn.metrics import average_precision_score
            lab = pd.read_parquet(tdir / "processed" / f"amlworld_{split}.parquet", columns=["EdgeID", "Is Laundering"]) \
                .rename(columns={"EdgeID": "edge_id", "Is Laundering": "y"})
            ml = m.merge(lab, on="edge_id", how="left")
            n_pos = int(ml["y"].sum())
            ap_b = float(average_precision_score(ml["y"], ml["score_raw_t"])) if n_pos else float("nan")
            ap_p = float(average_precision_score(ml["y"], ml["score_raw_p"])) if n_pos else float("nan")
            report[split] = {"n_edges": int(len(se)), "n_matched_to_pooled": int(len(m)), "n_positive_edges": n_pos,
                             "n_seeds_fixed_cutoff": len(st), "n_seeds_pooled_visible": len(sp),
                             "spearman_vs_pooled": rho, "seed_jaccard_vs_pooled": jac,
                             "ap_pooled": ap_p, "ap_tenant_visible": ap_b,
                             "labels_use": "reporting only; nothing tuned"}
            log = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "tenant_id": int(T), "model_id": a.model_id, "seed": int(S), "split": split,
                   "score_source": "tenant_visible", "visibility_rule": meta["visibility_rule"], "n_visible": meta["n_visible"],
                   "detector": {"run_dir": str(r1), "checkpoint": str(r1 / f"model_best_seed{S}.pt"),
                                "checkpoint_sha256": sha(r1 / f"model_best_seed{S}.pt"), "retrained": False,
                                "split_days_forced": SPLIT_DAYS},
                   "calibration": {"calibrator": str(r1 / f"calibrator_seed{S}.pkl"),
                                   "calibrator_sha256": sha(r1 / f"calibrator_seed{S}.pkl"),
                                   "rule": "shipped pooled-val isotonic calibrator APPLIED to tenant score_raw; not refit"},
                   "seed_rule": {"rule": "score_raw > pooled q of this seed (platform fixed cutoff)", "q": q,
                                 "source": f"contract/out/scored_edges_{a.model_id}_{S}.parquet.log.json"},
                   "gfp": "recomputed on the tenant graph (graph/motif_features.py)",
                   "sources": meta["sources"], "vs_pooled": report[split], "out": str(out),
                   "embeddings": str(emb_out) if emb_src.exists() else None}
            Path(str(out) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
        timings[f"seed{S}"] = {"score_s": round(t_score, 1), "total_s": round(time.time() - ts, 1)}
        print(f"[tenant {T} seed {S}] score {t_score:.0f}s | test: rho {report['test']['spearman_vs_pooled']:.4f}, "
              f"seeds (b) {report['test']['n_seeds_fixed_cutoff']} vs pooled {report['test']['n_seeds_pooled_visible']}, AP {report['test']['ap_pooled']:.3f}->{report['test']['ap_tenant_visible']:.3f}, "
              f"Jaccard {report['test']['seed_jaccard_vs_pooled']:.3f}")
    timings["wall_s"] = round(time.time() - t0, 1)
    (root / f"T{T}" / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
    print(json.dumps(timings))


if __name__ == "__main__":
    main()
