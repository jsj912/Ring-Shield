"""FeatureContext for a scored split at inference time (val / test with an R1 detector seed).

    ctx = build_context(scored_edges, gfp_parquet=..., embeddings_parquet=..., checkpoint=...)

score_quantile = rank / N of score_raw within the frame given (amendment a), dead_region from
the detector checkpoint's head constants (amendment d; `head_constants=[c1, c2]` may be given
instead of a checkpoint), GFP counts from the split's parquet, embeddings from the R1 export
(optional: without them the cosine features are NaN, which LightGBM treats as missing).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ringshield.expand.dead_region import dead_region_mask, head_constants_from_checkpoint
from ringshield.expand.features import EmbeddingStore, FeatureContext
from ringshield.expand.index import SplitIndex


def build_context(scored_edges: pd.DataFrame, *, gfp_parquet: Path | None = None, embeddings_parquet: Path | None = None,
                  checkpoint: Path | None = None, head_constants: list[float] | None = None,
                  index: SplitIndex | None = None) -> FeatureContext:
    se = scored_edges.set_index("edge_id")
    q = se["score_raw"].rank(method="average") / len(se)
    if head_constants is None and checkpoint is not None:
        head_constants = head_constants_from_checkpoint(Path(checkpoint))
    dead = pd.Series(dead_region_mask(se["score_raw"].to_numpy(), head_constants), index=se.index) if head_constants else None
    gfp = None
    if gfp_parquet is not None:
        gfp = pd.read_parquet(gfp_parquet)
        gfp = gfp[gfp["EdgeID"].isin(se.index)]
    emb = EmbeddingStore.from_parquet(embeddings_parquet, edge_ids=se.index.to_numpy()) if embeddings_parquet is not None else None
    ctx = FeatureContext.build(scored_edges, score_quantile=q, dead_region=dead, gfp=gfp, emb=emb, index=index)
    ctx.meta = {"gfp_parquet": str(gfp_parquet) if gfp_parquet else None, "embeddings_parquet": str(embeddings_parquet) if embeddings_parquet else None,
                "checkpoint": str(checkpoint) if checkpoint else None, "head_constants": head_constants,
                "n_dead_region": int(dead.sum()) if dead is not None else 0}
    return ctx
