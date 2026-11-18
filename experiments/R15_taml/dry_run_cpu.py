"""T-P9 CPU dry run: load day-1 graph, build TAML with their IBM config, run ONE balanced batch forward
(both GNNs + both losses, as in TAML_Trainer.train_model) on CPU. No optimizer step, nothing saved.

    # from experiments/R15_taml/work
    CUDA_VISIBLE_DEVICES="" ../../../.venv_taml/Scripts/python.exe -u ../dry_run_cpu.py --day 1
"""
import argparse
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "external" / "taml"))
from TAML_algorithm import *  # noqa: F401,F403,E402  (TAML, BalancedSampler, NeighborLoader, ToUndirected, LA)
from TAML_configs import get_taml_config  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--day", type=int, default=1)
ap.add_argument("--backbone", default="FraudGT")
a = ap.parse_args()
torch.manual_seed(28)
dev = torch.device("cpu")
t0 = time.time()
data = torch.load(f"data/IBM/Graphs/Account_to_Account/acc_graph_{a.day}.pt", weights_only=False)
print(f"[dry] day {a.day}: {data.num_nodes} nodes, {data.edge_index.shape[1]} edges, x {tuple(data.x.shape)}, "
      f"edge_attr {tuple(data.edge_attr.shape)}, labels {torch.bincount(data.y.long()).tolist()} ({time.time() - t0:.1f}s)")
c = get_taml_config("IBM", a.backbone)
model = TAML(in_channels=c["input_dim"], in_channels_e=c["input_dim_e"], hidden_channels_gnn=c["hidden_units_gnn"],
             out_channels=c["output_dim"], k=c["exploration_hop"], lambda_hparam=c["lambda_hparam"],
             hidden_channels_mlp_translation=c["hidden_channels_mlp_translation"],
             hidden_channels_mlp_self_translation=c["hidden_channels_mlp_self_translation"], backbone=c["backbone"])
print(f"[dry] TAML-{a.backbone}: {sum(p.numel() for p in model.parameters()):,} params")
du = ToUndirected()(data)
sampler = BalancedSampler(du, c["batch_size"])
loader = NeighborLoader(data=du, num_neighbors=[-1] * (c["exploration_hop"] + 1), replace=False, shuffle=False, batch_sampler=sampler)
print(f"[dry] balanced batches on day {a.day}: {len(sampler)}")
t1 = time.time()
batch = next(iter(loader))
model.train()
et = model.gnn_translation(batch)
es = model.gnn_self_translation(batch)
tn, ln = batch.n_id[:batch.batch_size], batch.n_id[batch.y != 3]
m = torch.isin(data.edge_index[0], tn) & torch.isin(data.edge_index[1], ln)
mp = torch.full((batch.n_id.max().item() + 1,), -1, dtype=torch.long)
mp[batch.n_id] = torch.arange(len(batch.n_id))
te = mp[data.edge_index[:, m]]
p_t = torch.sigmoid(LA.norm(model.h_VTN_translation - et[te[1]], dim=1)
                    - LA.norm(et[te[0]] + model.mlp_translation(data.edge_attr[m]) - et[te[1]], dim=1)).clamp(1e-7, 1 - 1e-7)
yy = batch.y[te[0]] * batch.y[te[1]]
l_t = (-1 / batch.batch_size) * torch.sum(yy * torch.log(p_t) + (1 - yy) * torch.log(1 - p_t))
p_s = torch.sigmoid(LA.norm(model.h_VTN_self_translation - es[:batch.batch_size], dim=1)
                    - LA.norm(et[:batch.batch_size] + model.mlp_self_translation(batch.x[:batch.batch_size]) - es[:batch.batch_size], dim=1)).clamp(1e-7, 1 - 1e-7)
yt = batch.y[:batch.batch_size]
l_s = (-1 / batch.batch_size) * torch.sum(yt * torch.log(p_s) + (1 - yt) * torch.log(1 - p_s))
loss = c["lambda_hparam"] * l_t + (1 - c["lambda_hparam"]) * l_s
print(f"[dry] one batch: {batch.batch_size} targets, {len(batch.n_id)} nodes in 3-hop neighbourhood, {int(m.sum())} target edges; "
      f"emb {tuple(et.shape)}; loss {loss.item():.4f} (finite={bool(torch.isfinite(loss))}); {time.time() - t1:.1f}s on CPU")
