"""T-P9 addendum (2026-11-17) step 1: rebuild TAML's IBM graphs with a fixed numpy seed and the node names saved.

    # from experiments/R15_taml/work_seeded/build_<tag>/build  (layout the builder expects: ../data/IBM/...)
    CUDA_VISIBLE_DEVICES= ../../../../../.venv_taml/Scripts/python.exe -u ../../../rebuild_seeded.py --seed 20261117

TAML's builder (external/taml/dataset_scripts/build_ibm_graph_dataset.py @ 15ebffde) is not edited. Its function
definitions are executed as written; its top-level sequence is executed verbatim after np.random.seed(seed). The one
addition: build_graph_data is wrapped to also write, per step, the sorted account-name list that defines n_id
(../data/IBM/Graphs/Account_to_Account/names_<step>.json), computed the same way the builder computes node_idx.
"""
import argparse
import json
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "external" / "taml" / "dataset_scripts" / "build_ibm_graph_dataset.py"
MARK = "# IBM-AML graph dataset builder"

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--seed", type=int, required=True)
a = ap.parse_args()

text = SRC.read_text(encoding="utf-8")
assert text.count(MARK) == 1
defs, top = text.split(MARK)
ns = {"__name__": "taml_builder"}
exec(compile(defs, str(SRC), "exec"), ns)
orig = ns["build_graph_data"]
node_cols = None


def build_graph_data(nodes, edges, time_step):
    g = orig(nodes, edges, time_step)
    names = sorted(nodes[nodes["Time_step"] == time_step]["Account"].unique().tolist())
    assert len(names) == g.num_nodes, (time_step, len(names), g.num_nodes)
    out = Path("../data/IBM/Graphs/Account_to_Account") / f"names_{time_step}.json"
    out.write_text(json.dumps(names), encoding="utf-8")
    return g


ns["build_graph_data"] = build_graph_data
np.random.seed(a.seed)
print(f"[rebuild_seeded] np.random.seed({a.seed}); executing builder top level verbatim", flush=True)
exec(compile(MARK + top, str(SRC), "exec"), ns)
