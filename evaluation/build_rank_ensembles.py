"""Part A step 1 (paper/PREREG_RECOVERY_2026-11-16.md): rank-averaged ensemble scores, per split.

    .venv312/Scripts/python.exe evaluation/build_rank_ensembles.py

Within each split, each model's score_raw -> percentile rank over that split's edges (average ranks for ties,
scaled to (0, 1]); the ensemble score is the mean rank. Writes experiments/R16_ensemble/<name>/scores_{val,test}_seed1.parquet
(edge_id, timestamp, score_raw). Calibration is applied afterwards with models/calibrate.py (val only).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[1]
E, REF = R / "experiments", R.parent / "RS-e2e" / "experiments"
SRC = {"genagg": E / "R6_megagenagg", "megagin": E / "R6_mega_sb2048", "gine": REF / "R1_gine_causal"}
ENS = {"E-GenAgg5": ["genagg"], "E-2048": ["genagg", "megagin"], "E-All15": ["genagg", "megagin", "gine"]}
OUT = E / "R16_ensemble"


def ranks(split: str, fam: str, s: int) -> pd.Series:
    d = pd.read_parquet(SRC[fam] / f"scores_{split}_seed{s}.parquet", columns=["edge_id", "timestamp", "score_raw"])
    d = d.set_index("edge_id")
    return d["score_raw"].rank(method="average", pct=True), d["timestamp"]


def main():
    meta = {}
    for split in ("val", "test"):
        cache, ts_ref = {}, None
        for fam in SRC:
            for s in range(1, 6):
                r, ts = ranks(split, fam, s)
                cache[(fam, s)] = r
                if ts_ref is None:
                    ts_ref = ts
                assert set(r.index) == set(ts_ref.index), f"{fam} seed {s} {split}: edge sets differ"
        idx = ts_ref.index
        for name, fams in ENS.items():
            cols = [cache[(f, s)].reindex(idx).to_numpy() for f in fams for s in range(1, 6)]
            score = np.mean(cols, axis=0)
            out = OUT / name
            out.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"edge_id": idx.to_numpy(), "timestamp": ts_ref.to_numpy(), "score_raw": score}).to_parquet(
                out / f"scores_{split}_seed1.parquet", index=False)
            meta.setdefault(name, {})[split] = {"n_edges": int(len(idx)), "n_models": len(cols),
                                                "models": [f"{f}:seed{s}" for f in fams for s in range(1, 6)],
                                                "unique_scores": int(pd.Series(score).nunique())}
            print(name, split, meta[name][split]["n_models"], "models,", len(idx), "edges", flush=True)
    meta["sources"] = {k: str(v) for k, v in SRC.items()}
    meta["note"] = "GINe scores are batch 8192 (look-ahead median 600 s); GenAgg and MEGA-GIN batch 2048 (180 s)."
    (OUT / "ensembles.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
