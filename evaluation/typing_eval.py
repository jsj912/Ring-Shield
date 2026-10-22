"""R5 typing table: head vs rule on matched primary-window rings (Step 8.4, check 2).

    python evaluation/typing_eval.py --out results/tables/r5_typing.csv

For every detector seed, the rings of `contract/out/rings_full_gine_causal_<S>.parquet` are
matched to `test_visible` ground-truth rings of the **primary window** at Jaccard 0.5 (the same
rule every other table uses). Only matched rings are typed -- an unmatched prediction has no true
label -- and both the learned head (the ring's `topology_type`) and the rule scorer are scored on
exactly those rings. Reported per seed and pooled: accuracy, macro-F1, per-class counts and
recall, and the 8x8 confusion matrix of the pooled head predictions (and of the rule).

The head's own grouped-CV numbers on the training rings (`experiments/R5_typing/head/head.json`)
are carried into the table as a reference column.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from contract.schema import TOPOLOGY_TYPES  # noqa: E402
from evaluation.ring_metrics import match_rings  # noqa: E402
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.rings import read_rings_parquet  # noqa: E402
from ringshield.roles import account_roles  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.typing.features import ring_features  # noqa: E402
from ringshield.typing.head import confusion  # noqa: E402
from ringshield.typing.rules import rule_type  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R5 = REPO_ROOT / "experiments" / "R5_typing"


def matched_rings(rings, se: pd.DataFrame, window, truth: dict, threshold: float) -> list:
    """[(ring, match)] for every prediction matched to a truth ring inside `window`.

    `restrict_rings` DROPS predictions with no member edge in the window, so `m.pred_idx` is a
    position in the restricted list, not in `rings`. Map it back through the same filter; reading
    `rings[m.pred_idx]` types a different ring (found by Ruhani, L4 Week 5 check, 2026-10-22)."""
    pred_sets = restrict_rings(rings, se, window)
    in_win = set(se.loc[window.mask(se["timestamp"].to_numpy()), "edge_id"].tolist())
    kept = [i for i, r in enumerate(rings) if any(e in in_win for e in r.member_edges)]
    assert len(kept) == len(pred_sets), f"restriction map {len(kept)} != restricted predictions {len(pred_sets)}"
    matches, _, _ = match_rings(pred_sets, truth, threshold)
    return [(rings[kept[m.pred_idx]], m) for m in matches]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--rings-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r5_typing.csv")
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--windows", nargs="*", default=["primary", "whole"],
                    help="primary is the headline; whole (days 8-17) is the Step 9 window sensitivity")
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--rng-seed", type=int, default=0)
    args = ap.parse_args(argv)
    paths = load_paths()
    pdir = paths["processed_dir"]
    all_windows = load_windows()
    rows = []
    for wname in args.windows:
      W = all_windows[wname]
      truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, args.scope, verbose=False)
      for S in args.seeds:
          rings = read_rings_parquet(args.rings_dir / f"rings_full_gine_causal_{S}.parquet")
          se = build_scored_edges(R1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
          se_i = se.set_index("edge_id")
          for r, m in matched_rings(rings, se, W, truth, 0.5):
              inc = sorted(set(r.seed_edges + r.expanded_edges))
              f = ring_features(se_i.loc[inc].reset_index(), account_roles(r, se), seed_ratio=len(r.seed_edges) / max(len(inc), 1))
              rows.append({"window": wname, "seed": S, "ring_id": r.ring_id, "truth_ring": m.truth_id, "jaccard": round(m.jaccard, 4),
                           "n_members": r.n_members, "true_type": patterns.get(m.truth_id, "?"),
                           "head_type": r.topology_type, "rule_type": rule_type(f),
                           "head_prob": float(max(r.topology_probs)) if r.topology_probs else np.nan,
                           "head_prob_true": float(r.topology_probs[TOPOLOGY_TYPES.index(patterns[m.truth_id])])
                           if patterns.get(m.truth_id) in TOPOLOGY_TYPES and r.topology_probs else np.nan})
    d = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(args.out, index=False)
    from sklearn.metrics import f1_score
    prim = d[d["window"] == "primary"]
    per_seed = prim.groupby("seed").apply(lambda g: pd.Series({
        "n_matched": len(g), "head_accuracy": float((g.head_type == g.true_type).mean()),
        "rule_accuracy": float((g.rule_type == g.true_type).mean())}), include_groups=False)
    head_cm, rule_cm = confusion(list(prim.true_type), list(prim.head_type)), confusion(list(prim.true_type), list(prim.rule_type))

    # Step 9: bootstrap CIs over MATCHED rings (the unit a typing accuracy is computed on), and the
    # `whole` block as the window sensitivity (amendment a).
    def boot(g: pd.DataFrame, col: str, n: int, seed: int) -> dict:
        ok = (g[col].to_numpy() == g["true_type"].to_numpy()).astype(float)
        if len(ok) == 0:
            return {"point": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
        rng = np.random.default_rng(seed)
        draws = ok[rng.integers(0, len(ok), (n, len(ok)))].mean(axis=1)
        return {"point": float(ok.mean()), "lo": float(np.percentile(draws, 2.5)),
                "hi": float(np.percentile(draws, 97.5)), "n": int(len(ok))}
    by_window = {}
    ci_rows = []
    for wname, g in d.groupby("window"):
        hb = boot(g, "head_type", args.n_bootstrap, args.rng_seed)
        rb = boot(g, "rule_type", args.n_bootstrap, args.rng_seed)
        by_window[wname] = {
            "n_matched_rings": int(len(g)), "n_seeds": int(g["seed"].nunique()),
            "head": hb, "rule": rb,
            "head_macro_f1": float(f1_score(g.true_type, g.head_type, average="macro", labels=TOPOLOGY_TYPES, zero_division=0)),
            "rule_macro_f1": float(f1_score(g.true_type, g.rule_type, average="macro", labels=TOPOLOGY_TYPES, zero_division=0)),
            "per_class": {t: {"n": int((g.true_type == t).sum()),
                              "head_recall": float((g.loc[g.true_type == t, "head_type"] == t).mean()) if (g.true_type == t).any() else None,
                              "rule_recall": float((g.loc[g.true_type == t, "rule_type"] == t).mean()) if (g.true_type == t).any() else None}
                          for t in TOPOLOGY_TYPES},
            "head_confusion": json.loads(confusion(list(g.true_type), list(g.head_type)).to_json(orient="split")),
            "rule_confusion": json.loads(confusion(list(g.true_type), list(g.rule_type)).to_json(orient="split"))}
        for scorer, b in (("head", hb), ("rule", rb)):
            ci_rows.append({"window": wname, "scorer": scorer, "n_matched_rings": b["n"], "n_seeds": int(g["seed"].nunique()),
                            "accuracy": b["point"], "accuracy_lo": b["lo"], "accuracy_hi": b["hi"],
                            "macro_f1": by_window[wname][f"{scorer}_macro_f1"],
                            "ci_source": f"bootstrap over matched rings, {args.n_bootstrap} resamples"})
    pd.DataFrame(ci_rows).to_csv(Path(str(args.out).replace(".csv", "_ci.csv")), index=False)
    chosen = json.loads((R5 / "chosen_head.json").read_text(encoding="utf-8"))
    head_json = json.loads((REPO_ROOT / chosen["chosen_dir"] / "head.json").read_text(encoding="utf-8"))
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": args.seeds, "window": "primary",
               "windows": list(by_window), "by_window": by_window,
               "n_matched_rings_total": int(len(prim)), "per_seed": json.loads(per_seed.reset_index().to_json(orient="records")),
               "pooled": {"head_accuracy": by_window["primary"]["head"]["point"],
                          "head_accuracy_ci": [by_window["primary"]["head"]["lo"], by_window["primary"]["head"]["hi"]],
                          "rule_accuracy": by_window["primary"]["rule"]["point"],
                          "rule_accuracy_ci": [by_window["primary"]["rule"]["lo"], by_window["primary"]["rule"]["hi"]],
                          "head_macro_f1": by_window["primary"]["head_macro_f1"],
                          "rule_macro_f1": by_window["primary"]["rule_macro_f1"]},
               "per_class": by_window["primary"]["per_class"],
               "head_confusion": json.loads(head_cm.to_json(orient="split")),
               "rule_confusion": json.loads(rule_cm.to_json(orient="split")),
               "head_dir": chosen["chosen_dir"], "head_selection_on_val": chosen["accuracy"],
               "head_training_cv": {k: head_json["cv"][k] for k in ("n_rings", "cv_accuracy", "oof_accuracy", "oof_macro_f1",
                                                                    "rule_accuracy", "rule_macro_f1", "class_counts")},
               "out": str(args.out)}
    Path(str(args.out).replace(".csv", ".json")).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"[typing] {len(prim)} matched primary-window rings over {len(args.seeds)} seeds")
    print(per_seed.round(3).to_string())
    for wname, b in by_window.items():
        print(f"  {wname:8s} ({b['n_matched_rings']:4d} matched rings): head {b['head']['point']:.3f} "
              f"[{b['head']['lo']:.3f}, {b['head']['hi']:.3f}] | rule {b['rule']['point']:.3f} "
              f"[{b['rule']['lo']:.3f}, {b['rule']['hi']:.3f}]")
    print("\nper class, primary (n | head recall | rule recall):")
    for t, v in summary["per_class"].items():
        h = "-" if v["head_recall"] is None else f"{v['head_recall']:.2f}"
        r = "-" if v["rule_recall"] is None else f"{v['rule_recall']:.2f}"
        print(f"  {t:15s} {v['n']:4d}  head {h}  rule {r}")
    print("\nhead confusion (rows = true, columns = predicted):")
    print(head_cm.to_string())
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
