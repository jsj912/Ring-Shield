"""T-P9 wrapper around TAML (external/taml @ 15ebffde). No TAML file is edited; overrides are passed as arguments.

    # from experiments/R15_taml/work (TAML loads data/IBM/Graphs/... relative to the working directory)
    ../../../.venv_taml/Scripts/python.exe -u ../run_ours.py --split theirs --epochs 1 --seed 28   # day-1 timing run
    ../../../.venv_taml/Scripts/python.exe -u ../run_ours.py --split ours   --epochs 250 --seed 28

--split theirs : training days 1-8 (their final-training rule, validation folded in)
--split ours   : training days 1-6 (our train window; days 7-8 stay validation, 9-10 test)
--epochs       : overrides config_taml["num_epochs"] (their default 250); everything else is their IBM default.
Only training runs here. Test scoring and signatures come from a separate wrapper (not yet written).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch

TAML = Path(__file__).resolve().parents[2] / "external" / "taml"
sys.path.insert(0, str(TAML))
from TAML_algorithm import train_taml  # noqa: E402
from TAML_configs import get_taml_config  # noqa: E402

SPLITS = {"theirs": [1, 2, 3, 4, 5, 6, 7, 8], "ours": [1, 2, 3, 4, 5, 6]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=sorted(SPLITS), required=True)
    ap.add_argument("--epochs", type=int, required=True)
    ap.add_argument("--seed", type=int, default=28, help="their seeds: 28 1999 1130 5898 820")
    ap.add_argument("--backbone", default="FraudGT", choices=["FraudGT", "GATe", "GAT", "GIN", "GCN"])
    ap.add_argument("--out-dir", type=Path, default=Path("runs"))
    a = ap.parse_args(argv)
    if not Path("data/IBM/Graphs/Account_to_Account/acc_graph_1.pt").exists():
        sys.exit("run from experiments/R15_taml/work after build_graphs.sh")

    random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed); torch.cuda.manual_seed(a.seed)  # as run_taml.py
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    cfg = get_taml_config("IBM", a.backbone)
    cfg["num_epochs"] = a.epochs
    run = a.out_dir / f"{a.split}_e{a.epochs}_{a.backbone}_seed{a.seed}"
    run.mkdir(parents=True, exist_ok=True)
    (run / "config.json").write_text(json.dumps({**{k: str(v) for k, v in cfg.items()}, "training_steps": SPLITS[a.split],
                                                 "seed": a.seed, "taml_commit": "15ebffde"}, indent=2), encoding="utf-8")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    train_taml(training_steps=SPLITS[a.split], device=device, pt_model_file_name=str(run / f"model_taml_{a.backbone}.pt"),
               dataset_choice="IBM", config_taml=cfg)
    dt = time.time() - t0
    peak = torch.cuda.max_memory_allocated() / 2 ** 20 if device.type == "cuda" else 0.0
    (run / "timing.json").write_text(json.dumps({"train_s": dt, "epochs": a.epochs, "s_per_epoch": dt / a.epochs,
                                                 "peak_alloc_mib": peak, "device": str(device)}, indent=2), encoding="utf-8")
    print(f"[taml] {a.split} {a.epochs} epoch(s): {dt:.0f} s ({dt / a.epochs:.0f} s/epoch), peak alloc {peak:.0f} MiB")


if __name__ == "__main__":
    main()
