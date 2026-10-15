"""Week 3: which detector features drove a ring's seed edges (spec 4.4, XR-13 / XR-14).

    model = load_feature_model(cfg, seed)                    # the 17-feature GFP+XGBoost refit, same seed
    rows = load_feature_rows(cfg, model, edge_ids)            # one row per edge, the model's own feature order
    fx = FeatureExplainer(model, rows)
    shap = fx.shap_values([seed edge ids])                    # edges x features, log-odds units
    feature_weights = ring_feature_weights(shap, top_n=10)    # [(feature_name, mean_shap, top_edge_id), ...]

What SHAP says. For one transaction the model's output (in log-odds) is split exactly into
"the average output" + one contribution per feature. A positive contribution pushed the model towards
"laundering", a negative one away from it. The contributions add up to the output exactly (tested).

Which model. The spec puts SHAP on GFP+XGBoost because its inputs have names, even though the rings come
from the GNN. The retired 28-feature model is not used; the R2_b0 refit (17 features: 7 transaction fields
and 10 trailing GFP graph features) is. Its feature list is read from the model file, never re-derived.

Which rows. The model was trained on `amlworld_<split>.parquet` joined 1:1 on EdgeID with the trailing GFP
parquet. Research's own loader (`baselines/gfp_xgboost_aml.load_split_for_refit`) cannot be imported here --
its module imports optuna, which is not installed -- so the same join is done below, with the same
assertions, and `verify_rows` proves it is the same input: the model's predictions on these rows equal the
shipped scores exactly.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import xgboost as xgb

from explainability.contract_io import repo_path

FEATURE_WEIGHT_COLUMNS = ["feature_name", "mean_shap", "top_edge_id"]


def load_feature_model(cfg: dict, seed: int) -> xgb.Booster:
    path = repo_path(cfg["feature_weights"]["model"].format(seed=seed))
    booster = xgb.Booster()
    booster.load_model(str(path))
    if not booster.feature_names:
        raise ValueError(f"{path}: the model file carries no feature names; refusing to guess the order")
    return booster


def model_features(booster: xgb.Booster) -> list[str]:
    """The feature list, in the order the model was trained with (XR-13: from the model file)."""
    return list(booster.feature_names)


def load_feature_rows(cfg: dict, booster: xgb.Booster, edge_ids, split_parquet: str | None = None,
                      gfp_parquet: str | None = None) -> pd.DataFrame:
    """The model's input rows for `edge_ids`, indexed by edge_id, columns in the model's order (float32)."""
    feats = model_features(booster)
    split_path = repo_path(split_parquet or cfg["inputs"]["split_parquet"])
    gfp_path = repo_path(gfp_parquet or cfg["research_inputs"]["gfp"])
    meta = pq.ParquetFile(gfp_path).schema_arrow.metadata or {}
    if b"gfp" not in meta or not json.loads(meta[b"gfp"]).get("trailing"):
        raise ValueError(f"{gfp_path}: not the trailing GFP parquet the model was trained on (no 'gfp' metadata)")
    gfp = pd.read_parquet(gfp_path)
    split_cols = ["EdgeID"] + [c for c in feats if c not in gfp.columns]
    df = pd.read_parquet(split_path, columns=split_cols)
    if not (gfp["EdgeID"].is_unique and df["EdgeID"].is_unique and len(gfp) == len(df)):
        raise ValueError(f"{gfp_path} and {split_path} are not one row per EdgeID each")
    want = pd.Index(sorted(set(map(int, edge_ids))), dtype="int64")
    df = df[df["EdgeID"].isin(want)].merge(gfp[gfp["EdgeID"].isin(want)], on="EdgeID", how="inner",
                                           validate="one_to_one")
    missing = want.difference(df["EdgeID"])
    if len(missing):
        raise ValueError(f"{len(missing)} edges have no feature row, e.g. {list(missing[:5])}")
    absent = [c for c in feats if c not in df.columns]
    if absent:
        raise ValueError(f"model features missing from the data: {absent}")
    rows = df.set_index("EdgeID").loc[want, feats].astype(np.float32)
    rows.index.name = "edge_id"
    if rows.isna().any().any():
        raise ValueError("feature rows contain missing values")
    return rows


def verify_rows(booster: xgb.Booster, rows: pd.DataFrame, shipped_scores_path) -> float:
    """Largest |model prediction on our rows - shipped score|; 0 means the rows are the training input."""
    shipped = pd.read_parquet(repo_path(shipped_scores_path), columns=["edge_id", "score_raw"]).set_index("edge_id")
    pred = booster.predict(xgb.DMatrix(rows.to_numpy(), feature_names=model_features(booster)))
    return float(np.abs(pred - shipped.loc[rows.index, "score_raw"].to_numpy()).max()) if len(rows) else 0.0


class FeatureExplainer:
    """SHAP (TreeExplainer, exact for trees) for a fixed set of feature rows."""

    def __init__(self, booster: xgb.Booster, rows: pd.DataFrame):
        import shap                                    # imported here: only Week 3 needs it
        self.booster, self.rows = booster, rows
        self.features = model_features(booster)
        self.explainer = shap.TreeExplainer(booster)
        # The base value ("average output") is taken from XGBoost's own decomposition, not from
        # explainer.expected_value: shap 0.50 misreads XGBoost 3's base_score (stored as "[5.42E-1]") and is off
        # by a constant there, while its per-feature values equal XGBoost's exactly (tested). The bias column of
        # pred_contribs is the same for every row.
        x0 = rows.iloc[:1].to_numpy() if len(rows) else np.zeros((1, len(self.features)), dtype=np.float32)
        self.expected_value = float(booster.predict(xgb.DMatrix(x0, feature_names=self.features),
                                                    pred_contribs=True)[0, -1])

    def _x(self, edge_ids) -> np.ndarray:
        return self.rows.loc[list(map(int, edge_ids))].to_numpy()

    def shap_values(self, edge_ids) -> pd.DataFrame:
        ids = list(map(int, edge_ids))
        if not ids:
            return pd.DataFrame(columns=self.features, dtype=np.float64)
        sv = np.asarray(self.explainer.shap_values(self._x(ids)), dtype=np.float64)
        return pd.DataFrame(sv, index=pd.Index(ids, name="edge_id"), columns=self.features)

    def margin(self, edge_ids) -> np.ndarray:
        """The model's raw output (log-odds) for these edges: what SHAP values add up to."""
        return self.booster.predict(xgb.DMatrix(self._x(edge_ids), feature_names=self.features), output_margin=True)


def ring_feature_weights(shap_values: pd.DataFrame, top_n: int) -> list[dict]:
    """Mean SHAP per feature over the ring's seed edges, top `top_n` by absolute value (XR-14).

    Order: larger |mean| first; equal |mean| -> the model's feature order (so the result never depends on
    how a sort breaks ties). top_edge_id: the edge with the largest |SHAP| for that feature; ties -> smaller
    edge_id. No edges -> [] (the narrative then drops its feature clause)."""
    if shap_values.empty:
        return []
    mean = shap_values.mean(axis=0)
    order = sorted(range(len(mean)), key=lambda i: (-abs(float(mean.iloc[i])), i))[:top_n]
    ids = shap_values.index.to_numpy(np.int64)
    out = []
    for i in order:
        col = np.abs(shap_values.iloc[:, i].to_numpy())
        best = ids[col == col.max()].min()
        out.append({"feature_name": mean.index[i], "mean_shap": float(mean.iloc[i]), "top_edge_id": int(best)})
    return out
