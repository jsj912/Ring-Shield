"""T-P9 addendum 2 section 2: TAML inference on the seeded rebuild, saving per-node scores and signatures.

    # from experiments/R15_taml/work_seeded/build_A
    ../../../../.venv_taml/Scripts/python.exe -u ../../infer_seeded.py --model ../../runs_seeded/<run>/model_taml_FraudGT.pt \
        --steps 7 8 9 10 --out ../../runs_seeded/<run>/infer

The loop is TAML_Tester.test_model (TAML_algorithm.py @ 15ebffde) with its forward pass unchanged; instead of only
writing the aggregate metrics it also saves, per target node: name, label, anomaly score (mean of the signature's
anomaly scores, as theirs), signature (names), true signature (names, their get_true_signature) and their per-node
signature precision / recall. Writes <out>/step<i>.parquet and <out>/their_metrics.csv (their file format).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

TAML = Path(__file__).resolve().parents[2] / "external" / "taml"
sys.path.insert(0, str(TAML))
from TAML_algorithm import TAML  # noqa: E402
from TAML_configs import get_taml_config  # noqa: E402
from torch_geometric.loader import NeighborLoader  # noqa: E402
from torch_geometric.transforms import ToUndirected  # noqa: E402
from utils.dataset_utils import LabeledSampler  # noqa: E402
from utils.evaluation_utils import get_true_signature, set_precision, set_recall  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--model", type=Path, required=True)
ap.add_argument("--steps", type=int, nargs="+", required=True)
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--seed", type=int, default=28)
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
torch.manual_seed(a.seed); np.random.seed(a.seed)
dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
c = get_taml_config("IBM", "FraudGT")
m = TAML(in_channels=c["input_dim"], in_channels_e=c["input_dim_e"], hidden_channels_gnn=c["hidden_units_gnn"],
         out_channels=c["output_dim"], k=c["exploration_hop"], lambda_hparam=c["lambda_hparam"],
         hidden_channels_mlp_translation=c["hidden_channels_mlp_translation"],
         hidden_channels_mlp_self_translation=c["hidden_channels_mlp_self_translation"], backbone=c["backbone"]).to(dev)
m.load_state_dict(torch.load(a.model, weights_only=True))
m.eval()
G = Path("data/IBM/Graphs/Account_to_Account")
summ = []
with torch.no_grad():
    for i in a.steps:
        names = json.loads((G / f"names_{i}.json").read_text(encoding="utf-8"))
        data = torch.load(G / f"acc_graph_{i}.pt", weights_only=False).to(dev)
        du = ToUndirected()(data)
        et, es = m.gnn_translation(du), m.gnn_self_translation(du)
        loader = NeighborLoader(data=du, num_neighbors=[-1] * (m.k + 1), replace=False, shuffle=False,
                                batch_sampler=LabeledSampler(du))
        batch = next(iter(loader))
        targets = sorted(batch.n_id[:batch.batch_size].tolist())
        rows = []
        for t in targets:
            lab = int(data.y[data.n_id == t][0])
            sig, sc = m([int(t), data, et, es])
            sig = {n for n in sig if data.y[data.n_id == n][0] != 3}
            tru = get_true_signature(t, lab, data)
            rows.append({"step": i, "node": int(t), "name": names[int(t)], "label": lab,
                         "score": float(torch.mean(sc).item()),
                         "signature": [names[int(n)] for n in sorted(sig)],
                         "true_signature": [names[int(n)] for n in sorted(tru)],
                         "sig_precision": set_precision(set(tru), set(sig)), "sig_recall": set_recall(set(tru), set(sig))})
        df = pd.DataFrame(rows)
        df.to_parquet(a.out / f"step{i}.parquet", index=False)
        g = df.groupby("label")[["sig_precision", "sig_recall"]].mean()
        summ.append({"Time_step": i, "AUC-ROC": roc_auc_score(df.label, df.score), "AUC-PR": average_precision_score(df.label, df.score),
                     "Av_prec_class_1": g.loc[1, "sig_precision"], "Av_recall_class_1": g.loc[1, "sig_recall"],
                     "Av_prec_class_0": g.loc[0, "sig_precision"], "Av_recall_class_0": g.loc[0, "sig_recall"]})
        print(summ[-1], flush=True)
pd.DataFrame(summ).to_csv(a.out / "their_metrics.csv", index=False)
