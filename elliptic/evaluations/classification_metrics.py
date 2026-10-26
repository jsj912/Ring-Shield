from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score, confusion_matrix
import json

def compute_metrics(y_true, y_pred, y_score=None):
    metrics = {
        "illicit_f1": f1_score(y_true, y_pred, pos_label=1),
        "illicit_precision": precision_score(y_true, y_pred, pos_label=1),
        "illicit_recall": recall_score(y_true, y_pred, pos_label=1),
    }
    if y_score is not None:
        metrics["roc_auc"] = roc_auc_score(y_true, y_score)
    metrics["confusion_matrix"] = confusion_matrix(y_true, y_pred).tolist()
    return metrics

def save_metrics(metrics, path):
    with open(path, "w") as f:
        json.dump(metrics, f, indent=2)