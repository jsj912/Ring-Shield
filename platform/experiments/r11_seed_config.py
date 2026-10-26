"""Write the platform config for one detector seed of the five-seed R11 (docs/R11.md, registered 2026-10-25).

    python -m experiments.r11_seed_config --seed 3              # -> platform/out/r11/config_seed3.yaml
    python -m experiments.r11_seed_config --seed 3 --tenant 1   # -> config_seed3_build_T1.yaml

Everything seed-specific moves together: the active seed, the shipped full model of that seed, the
pooled scores and embeddings, the fixed pooled cutoff (from that seed's score log), the gate's
validation inputs and base model, and the tenant ring file the verdicts were made on. Everything
else is platform/config.yaml unchanged.

With --tenant, the config is for building that bank's rings (build_tenant_rings.py): the scores are
the bank's own visible file and the cutoff source is its log, whose seed_rule.q must equal the pooled
cutoff, as the seed-1 build of 2026-10-22 did.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
BASE_CONFIG = PLATFORM_ROOT / "config.yaml"
RINGS_DIR = "data/platform_tenant_runs/r11_seed{seed}/T{{tenant_id}}"


def seed_config(seed: int, base: dict | None = None) -> dict:
    config = dict(base if base is not None else yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8")))
    config = {key: value for key, value in config.items() if not key.startswith("_")}   # load_platform_config adds _path
    model_id = config["active_model_id"]
    scores = f"contract/out/scored_edges_{model_id}_{seed}.parquet"
    log = json.loads((REPO_ROOT / f"{scores}.log.json").read_text(encoding="utf-8"))
    config.update({
        "active_seed": seed,
        "model_dir": f"models/artifacts/full_{model_id}_seed{seed}",
        "scored_edges": scores,
        "embeddings": f"experiments/R1_{model_id}/embeddings_test_seed{seed}.parquet",
        "seed_score_cutoff": float(log["seed_rule"]["q"]),
        "seed_score_cutoff_source": f"{scores}.log.json:seed_rule.q",
    })
    l6 = dict(config["l6"])
    retrain = dict(l6["retrain"])
    retrain.update({
        "val_scored_edges": f"contract/out/scored_edges_{model_id}_{seed}_val.parquet",
        "val_embeddings": f"experiments/R1_{model_id}/embeddings_val_seed{seed}.parquet",
        "base_model_dir": f"models/artifacts/full_{model_id}_seed{seed}",
        "label_rings_template": RINGS_DIR.format(seed=seed) + "/tenant_{tenant_id}_rings.parquet",
    })
    l6["retrain"] = retrain
    config["l6"] = l6
    return config


def tenant_build_config(seed: int, tenant: int, base: dict | None = None) -> dict:
    config = seed_config(seed, base)
    scores = f"data/tenant_visible/scored_edges_visible_{tenant}_{config['active_model_id']}_{seed}.parquet"
    q = float(json.loads((REPO_ROOT / f"{scores}.log.json").read_text(encoding="utf-8"))["seed_rule"]["q"])
    if q != config["seed_score_cutoff"]:
        raise ValueError(f"seed {seed}: bank {tenant}'s score log cutoff {q} is not the pooled cutoff")
    config.update({"scored_edges": scores, "seed_score_cutoff_source": f"{scores}.log.json:seed_rule.q"})
    return config


def config_path(seed: int, tenant: int | None = None) -> Path:
    suffix = "" if tenant is None else f"_build_T{tenant}"
    return PLATFORM_ROOT / "out" / "r11" / f"config_seed{seed}{suffix}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, required=True, choices=(1, 2, 3, 4, 5))
    parser.add_argument("--tenant", type=int, help="write the ring-building config for this bank instead")
    args = parser.parse_args(argv)
    config = seed_config(args.seed) if args.tenant is None else tenant_build_config(args.seed, args.tenant)
    out = config_path(args.seed, args.tenant)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
