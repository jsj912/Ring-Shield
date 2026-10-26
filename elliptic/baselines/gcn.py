import os
import time
import torch
import torch.nn.functional as F
import yaml
import numpy as np
import pandas as pd
import sys
sys.path.append(".")
from torch_geometric.nn import GCNConv
from sklearn.metrics import f1_score, precision_recall_curve
from evaluations.classification_metrics import compute_metrics, save_metrics

# ---- 1. Load the fixed seed and the graph object ----
seed = yaml.safe_load(open("configs/seed.yaml"))["seed"]
torch.manual_seed(seed)

# weights_only=False is required here (PyTorch 2.6+ default), safe since this is a
# file we generated ourselves in Phase 2, not something downloaded from elsewhere
data = torch.load("data/processed/elliptic_graph.pt", weights_only=False)

# ---- 2. Derive train_proper / val masks from the same split config used in Phase 1,
#         applied to the graph's node-level train_mask instead of DataFrame rows ----
split_cfg = yaml.safe_load(open("configs/elliptic_split.yaml"))
val_lo, val_hi = split_cfg["val_timesteps"]
train_proper_mask = data.train_mask & (data.time_step < val_lo)
val_mask = data.train_mask & (data.time_step >= val_lo) & (data.time_step <= val_hi)


# ---- 3. Model definition — 2-layer GCN ----
class GCN(torch.nn.Module):
    def __init__(self, in_dim, hidden_dim=100, out_dim=2):
        super().__init__()
        self.conv1 = GCNConv(in_dim, hidden_dim)
        self.conv2 = GCNConv(hidden_dim, out_dim)

    def forward(self, x, edge_index):
        x = F.relu(self.conv1(x, edge_index))
        x = F.dropout(x, p=0.5, training=self.training)
        return self.conv2(x, edge_index)


def train_model(train_mask_to_use, use_class_weights, epochs=200):
    torch.manual_seed(seed)
    model = GCN(in_dim=data.x.size(1))
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    if use_class_weights:
        y_train = data.y[train_mask_to_use]
        n_pos = (y_train == 1).sum().item()
        n_neg = (y_train == 0).sum().item()
        weight = torch.tensor([1.0, n_neg / max(n_pos, 1)])
    else:
        weight = None

    log_rows = []
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        out = model(data.x, data.edge_index)
        loss = F.cross_entropy(out[train_mask_to_use], data.y[train_mask_to_use], weight=weight)
        loss.backward()
        optimizer.step()
        log_rows.append({"epoch": epoch, "loss": loss.item()})
    return model, log_rows


def get_scores(model, mask):
    model.eval()
    with torch.no_grad():
        out = model(data.x, data.edge_index)
        scores = F.softmax(out[mask], dim=1)[:, 1].numpy()
        y_true = data.y[mask].numpy()
    return y_true, scores


# ---- 4. Compare class-weighted vs unweighted loss, same idea as E1's class_weight
#         sweep — trained on train_proper, evaluated on val ----
print("Comparing class-weighting strategies on validation...")
results = {}
for use_weights in [True, False]:
    model, _ = train_model(train_proper_mask, use_weights, epochs=200)
    y_val_true, y_val_scores = get_scores(model, val_mask)
    y_val_pred = (y_val_scores >= 0.5).astype(int)
    f1 = f1_score(y_val_true, y_val_pred, pos_label=1)
    results[use_weights] = f1
    print(f"class_weights={use_weights}: val F1 (threshold=0.5) = {f1:.4f}")

best_use_weights = max(results, key=results.get)
print(f"\nBest config: class_weights={best_use_weights} (val F1={results[best_use_weights]:.4f})")

# ---- 5. With the winning config, train ONCE on train_proper_mask and KEEP this
#         exact model — do not retrain a second model on more data. Tree ensembles
#         barely shift score calibration when retrained on a slightly larger
#         training set; a neural net trained via gradient descent is a genuinely
#         different optimization run each time, so a threshold tuned on one
#         model's score distribution can fail to transfer to a freshly-retrained
#         model's distribution (this is exactly what caused the val->test
#         collapse in the earlier version of this script: val F1=0.7955,
#         test F1=0.4058, using a threshold tuned on a DIFFERENT model than the
#         one it was applied to). Trading ~5 timesteps of training data (30-34)
#         for score-distribution consistency between the tuned threshold and the
#         final evaluated model. ----
start_time = time.time()
final_model, log_rows = train_model(train_proper_mask, best_use_weights, epochs=200)
training_time_seconds = time.time() - start_time

y_val_true, y_val_scores = get_scores(final_model, val_mask)
precisions, recalls, thresholds = precision_recall_curve(y_val_true, y_val_scores)
f1_scores = 2 * precisions * recalls / (precisions + recalls + 1e-10)
best_idx = np.argmax(f1_scores[:-1])
best_threshold = thresholds[best_idx]
print(f"Best threshold on validation: {best_threshold:.4f} (val F1={f1_scores[best_idx]:.4f})")

# ---- 6. Evaluate the SAME model used for threshold tuning — no second training run ----
y_test_true, y_test_scores = get_scores(final_model, data.test_mask)
y_test_pred = (y_test_scores >= best_threshold).astype(int)

metrics = compute_metrics(y_test_true, y_test_pred, y_test_scores)
metrics["chosen_class_weights"] = best_use_weights
metrics["chosen_threshold"] = float(best_threshold)
metrics["training_time_seconds"] = training_time_seconds
metrics["note"] = (
    "Final model trained on timesteps 1-29 only (train_proper_mask), NOT refit on "
    "the full 1-34 train_mask, to preserve score-distribution consistency between "
    "the validation-tuned threshold and the model it is applied to. An earlier "
    "version of this script retrained a second model on the full train_mask before "
    "evaluating, which caused a val->test F1 collapse (0.7955 -> 0.4058) because the "
    "threshold was tuned on one model's score distribution and applied to a "
    "different, freshly-retrained model's distribution."
)

out_dir = "experiments/E3a_gcn"
os.makedirs(out_dir, exist_ok=True)
save_metrics(metrics, f"{out_dir}/metrics.json")
pd.DataFrame(log_rows).to_csv(f"{out_dir}/training_log.csv", index=False)
torch.save(final_model.state_dict(), f"{out_dir}/model.ckpt")
pd.DataFrame({"y_true": y_test_true, "y_pred": y_test_pred, "y_score": y_test_scores}).to_csv(
    f"{out_dir}/predictions.csv", index=False
)

print("\nFinal test illicit F1:", metrics["illicit_f1"])
print("Training time:", round(training_time_seconds, 1), "seconds")
print("Weber et al. 2019 target: ~0.628")