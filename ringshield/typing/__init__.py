"""Stage D -- topology typing of a ring (Step 8, R5).

    from ringshield.typing.features import ring_features, RING_FEATURES
    from ringshield.typing.rules import rule_type, rule_scores
    from ringshield.typing.head import TypingHead, train_head

`features` turns a ring (its edges plus the account roles) into the numbers both the rule
scorer and the learned head read; `rules` is the hand-written 8-way scorer (the sanity bound);
`head` is the LightGBM 8-way classifier trained on train-visible ground-truth rings.
"""
from __future__ import annotations
