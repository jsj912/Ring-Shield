# Amendment 2 to PREREG_Q_2026-11-15.md (2026-11-15)

Amends `paper/PREREG_Q_2026-11-15.md` (sha256 aa991ccee83d0f103a9f3af692d4f638705a33a824637893d6749ae97dbbff45); amendment 1 (sha256 04b847f28dbda35c17d536701046d195c29550b149da96e456990bf7e2947101) is unchanged. Written before any Q2 data was computed.

## Q2-top3 description (correction)

The frozen file says that under Q2-top3 "an account with several high-scoring edges outranks one with a
single higher edge". Under the registered rule (the mean of the three highest scores, or of all
scores if the account has fewer than three), that is false. An account with one edge scored s has
a(v) = s, and it outranks an account whose three best edges average below s
(`tests/test_q2_account_seeds.py::test_top3_ranks_multi_edge_accounts_lower`). Q2-top3 penalises
accounts that have one high edge among weaker ones. It does not reward having many edges. The
rule, the variants, the variant choice on validation and the readings are unchanged. Only this
description is corrected.
