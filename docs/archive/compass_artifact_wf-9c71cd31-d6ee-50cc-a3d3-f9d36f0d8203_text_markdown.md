# RingShield: Research-Grade Audit & Modernization Review (2024–2026)

## TL;DR
- **RingShield is a faithful but one-generation-old AML pipeline.** Its Multi-GINe backbone (F1 0.599) and GFP+XGBoost baseline (0.632) now sit well below the 2024–2026 frontier on AMLworld HI-Small — FraudGT (vanilla F1 69.68 ± 1.58, ICAIF 2024) and MEGA-GNN (up to +13.31 F1 points over Multi-GNN, TMLR 2026) — and four known methodological defects (non-causal neighbour sampling, test-set threshold/scope tuning, single-seed ring metrics, no significance testing) would each individually justify rejection today.
- **The novelty is defensible only if repositioned.** Subgraph/group-level AML evaluation is now an established sub-field (Chai et al. AAAI 2023; Elliptic2/RevClassify ICAIF 2024; Clue2Group 2026), so the contribution must be reframed as "first systematic ring-level evaluation *on AMLworld's own BEGIN/END pattern labels* with a detector-agnostic cascade plus an expressivity diagnosis," and the single most dangerous experiment — feeding GFP+XGBoost or an unsupervised density detector through the same aggregator — must be run to prove a learned GNN is necessary at all.
- **The fix is disciplined methodology and stronger baselines, not a new architecture.** Plan A (fix causality, validation-only tuning, multi-seed + permutation tests, invalidation baselines, layer-depth ablation) is realistic on a final-year timeline; Plan B adds FraudGT/MEGA-GNN detectors, temporal-model replacement for EvolveGCN, and Tide robustness suites; Plan C generalizes to Elliptic2 and an expressivity-boosted bipartite fix.

---

## A. Executive Diagnosis — What Is Outdated

RingShield is a competent re-implementation of a 2023–2024 IBM AMLworld pipeline (Multi-GNN backbone + GFP+XGBoost baseline) with a genuinely interesting downstream add-on (a detection→aggregation ring cascade). As a 2026 research contribution it is behind the frontier in five concrete ways:

1. **Backbone is one generation old.** Multi-GINe (Egressy et al., AAAI 2024) has been superseded on AMLworld HI-Small by FraudGT (Lin et al., ICAIF 2024; vanilla minority-class F1 69.68 ± 1.58, best variant PE-FraudGT 76.41 ± 1.45) and MEGA-GNN (Bilgi, Chen & Atasu, arXiv:2412.00241, "significantly outperforms state-of-the-art solutions by up to 13% [13.31 percentage points] on Anti-Money Laundering datasets," accepted TMLR 2026). RingShield's 0.599 GINe / 0.632 GFP+XGBoost figures sit clearly below these.
2. **Novelty claim is under threat.** Subgraph/group-level AML evaluation is now established (Elliptic2/RevClassify ICAIF 2024; Chai et al. AAAI 2023 sub-network discovery; Clue2Group 2026; LAS-GNN ICAIF 2025). "Invent our own ring metrics" must become "adopt/extend established subgraph-evaluation practice on AMLworld's pattern labels specifically."
3. **Known methodological defects are disqualifying if unfixed.** Non-causal neighbour sampling, test-set threshold/scope tuning, single-seed ring metrics, and absence of significance testing are exactly what a 2026 reviewer rejects on.
4. **Evaluation metric set is thin.** Minority-class F1 alone is no longer sufficient; PR-AUC/Average Precision, MCC, precision@k and calibration are expected.
5. **Temporal baseline (EvolveGCN, AAAI 2020) is stale.** The temporal-AML frontier has moved to edge-based temporal message passing (TeMP-TraG 2025), LSTM-aggregator motif models (LAS-GNN, ICAIF 2025), whole-graph temporal GNNs (Amatriciana 2025), and TGN-style models.

The good news: the ring-cascade idea is under-explored *on AMLworld's own BEGIN/END pattern labels*, and the bipartite-failure finding is scientifically interesting. The project can become a strong 2026 submission through disciplined methodology and stronger baselines rather than a novel architecture.

---

## B. Top 10 Changes, Prioritized

1. **Fix the causal leak.** Add a temporal filter to neighbour sampling so a transaction's score depends only on earlier transactions. This is the single most credibility-defining fix and restores the Time-to-Detection metric.
2. **Stop test-set tuning.** Select edge threshold and ring-scope policy on validation only; report test once. Pre-register the rule: Youden's J or max-F1-on-validation — the Tide generator paper (arXiv:2603.01863) explicitly "perform[s] threshold optimization on the validation set to determine the decision boundary that maximizes Youden's J statistic," with "PR-AUC [as] our primary evaluation metric given its robustness to class imbalance."
3. **Multi-seed everything downstream.** Run ring metrics across ≥5 seeds with confidence intervals; add significance testing (Holm-corrected permutation tests, as SALT-GNN does).
4. **Add the honest strong baseline: GFP+XGBoost scores → the same ring aggregator.** This is the experiment most likely to invalidate the "learned GNN needed" claim; run it first.
5. **Add an unsupervised, no-learning ring baseline** (connected components / dense-subgraph / GARG-AML-style density on thresholded raw features) through the same aggregator.
6. **Upgrade the backbone / add strong contemporary detectors:** FraudGT and MEGA-GNN, both of which beat Multi-GNN on HI-Small.
7. **Expand metrics:** PR-AUC/AP, MCC, precision@k, FPR at fixed recall, alongside the existing F1; report calibration (ECE) and use calibrated thresholds.
8. **Diagnose the BIPARTITE 0.000 recall with a layer-depth ablation** — Egressy et al. attribute weak bipartite/large-cycle recall to insufficient message-passing depth; 2 layers is the likely cause.
9. **Replace EvolveGCN** as the temporal baseline with an edge-temporal model (TGN and/or LAS-GNN-style LSTM aggregator).
10. **Full reproducibility harness:** config files, seeds, environment capture, experiment tracking, exact split manifest, checkpoints (see Section on reproducibility).

---

## C. Modern Benchmark Suite (Datasets)

Classification key: **(A)** keep · **(B)** keep for comparison only · **(C)** replace · **(D)** add.

- **AMLworld HI-Small** (Altman et al., NeurIPS 2023 Datasets & Benchmarks; arXiv:2306.16424). 5,078,345 transactions and 515,080 accounts (511,910 legitimate, 3,170 launderers) over 10 days; **0.102% illicit** at the transaction level (per Blanuša et al., GFP, ICAIF 2024, Table 1: "AML HI Small · 0.5 M · 5 M · 0.102% · 10 days"). **Has explicit subgraph ground truth**: a separate `HI-Small_Patterns.txt` file delimiting laundering pattern groups with BEGIN/END LAUNDERING ATTEMPT markers across the 8 pattern types (Fan-in, Fan-out, Simple cycle, Scatter-gather, Gather-scatter, Bipartite, Stack, Random). Independent exploration confirms **370 laundering pattern groups in HI-Small** (Effendi & Chattopadhyay, SPACE 2024, arXiv:2411.02926: "Data exploration revealed 370 groups of money laundering patterns, comprising various topologies such as fan-in, fan-out, gather-scatter, cycles, and random patterns"). This is why HI-Small is uniquely suited to RingShield. **Verdict: (A) keep as primary.** Criticism: synthetic, agent-based; a large fraction of illicit transactions are "not classified" into any pattern (GARG-AML reports 1,968 unclassified for HI-Small), which caps achievable ring recall and likely drives RingShield's ~0.583 recall saturation.
- **AMLworld HI-Medium / LI variants.** Larger, lower illicit rates. **Verdict: (D) add HI-Medium for scaling/generalization; (B) LI variants for comparison.**
- **AMLSim (Suzumura & Kanezashi).** The original 8-pattern agent-based generator with injected patterns; ancestor of AMLworld's patterns and used by SGM/CSGM. **Verdict: (B) comparison.**
- **SAML-D (Oztas et al., IEEE ICEBE 2023; DOI:10.1109/ICEBE59045.2023.00028).** 9,504,852 transactions, 0.1039% suspicious, 28 typologies (11 normal, 17 suspicious), 15 network structures. **Verdict: (D) add for cross-dataset generalization**, noting it is largely tabular with typology labels rather than clean per-group subgraph labels.
- **Elliptic++ (Elmougy & Liu, KDD 2023; git-disl/EllipticPlusPlus; arXiv:2306.06108).** 203,769 transactions, 822,942 wallet addresses, 49 time steps, real Bitcoin. **Verdict: (B) comparison** (real data, node/actor-level) — different domain and no AMLworld-style pattern-group labels.
- **Elliptic2 (Bellei et al., KDD MLF 2024; MITIBMxGraph/Elliptic2; arXiv:2404.19109).** 122K labeled subgraphs within a 49M-node/196M-edge background graph — **the reference dataset for subgraph-level AML learning**, benchmarked by RevClassify. **Verdict: (D) add as the "does RingShield generalize to real subgraph-labeled data" benchmark** — directly relevant to the novelty positioning.
- **Tide (arXiv:2603.01863, 2026).** Open-source customisable generator; HI (0.19%)/LI (0.10%) reference sets; explicit structural + temporal patterns; ships SOTA baselines; validation-set Youden's J thresholding; PR-AUC primary. **Verdict: (D) add** — ideal for unseen-pattern-type and concept-drift robustness because you can inject novel, user-defined patterns.
- **AMLNet (Huda et al., 2025; Zenodo 16482144/16736515; arXiv:2509.11595).** ~1.05–1.09M synthetic transactions, ~0.15–0.16% laundering, 192–195-day span, AUSTRAC-aligned. **Verdict: (B) comparison** — smaller, tabular-leaning.
- **CFDB (arXiv:2404.14746).** Customer-level fraud benchmark aggregating transactions into customer profiles (e.g., SAML-D → 855,460 customer profiles, 0.92% suspicious). **Verdict: (B) comparison only** — customer/account-level, so it **cannot feed a per-edge ring aggregator** (fails the per-edge gate).
- **SynthAML (Jensen et al., Nature Scientific Data 2023; DOI:10.1038/s41597-023-02569-2).** 20,000 alerts, 16M+ transactions, ~17% alert rate, built on Spar Nord bank data. **Verdict: (B) comparison** — alert-level, not subgraph-level.
- **TransXion (arXiv:2604.17420, 2026).** High-fidelity graph benchmark with perturbation-based (non-template) anomaly synthesis + customer context. **Verdict: (D) add if usable** — promising for realism/adversarial robustness, but very new.

---

## D. Modern Model Suite (Tiered Baseline Hierarchy)

- **Tier 0 — Classical tabular:** Logistic Regression, Random Forest. Keep both as sanity floors; standard, cheap, and not redundant — they establish that graph structure matters.
- **Tier 1 — Modern GBDT:** XGBoost; **add LightGBM** (Tide shows LightGBM wins PR-AUC in low-illicit conditions while XGBoost wins at higher prevalence — reporting both is now expected). Keep **GFP+XGBoost** as the reference-strong tabular+graph-feature baseline (0.632 F1 reported on HI-Small; note AMLNet reports GFP+XGBoost reaching F1 0.657 on a high-illicit dataset, so keep this method as a genuinely strong competitor and cite the exact dataset variant in every comparison).
- **Tier 2 — Modern graph learning:** Multi-GINe (keep as anchor/backbone), Multi-GATv2 (keep for attention/explainability), **add MEGA-GNN / MEGA-PNA** (TMLR 2026; Apache-2.0; up to +13.31 F1 over Multi-GNN; MEGA-PNA reports 74.01 ± 1.55 F1 on AML Small-HI).
- **Tier 3 — Temporal/dynamic graph:** **Replace EvolveGCN** (2020, snapshot-based, node-classification-oriented, weak on AMLworld) with **TGN** (PyG `examples/tgn.py`) and/or a **LAS-GNN-style LSTM-aggregator** temporal model (ICAIF 2025), and consider **TeMP-TraG** (edge-based temporal MP, 2025). EvolveGCN may be retained only as a labelled "legacy temporal baseline."
- **Tier 4 — Strong contemporary (graph transformer):** **FraudGT** (ICAIF 2024, Best Paper Honorable Mention; vanilla F1 69.68 ± 1.58, best variant 76.41; "consistently outperforms other models, achieving 7.8–17.8% higher F1 scores, while delivering an average of 2.4× greater throughput") as the SOTA anchor. **Add SALT-GNN** (arXiv:2607.10131, 2026) if code is released — it specifically targets the dense-neighborhood regime relevant to your BIPARTITE/FAN failure modes (SALT-Trans/SALT-GAT ≈ 0.855 overall F1 on HI-Small and dominate the densest recipient bins).

---

## E. Modern Evaluation Protocol

- **Temporal splitting:** Keep IBM's day-based 60/20/20 expanding-window split as primary — it is the canonical AMLworld convention used by Multi-GNN and most downstream work. **Note FraudGT deviates (64/19/17 on Small datasets)**, so its numbers are not perfectly comparable; flag this in every cross-paper table.
- **Causality / leakage:** Enforce temporal neighbour filtering. The AML GNN literature is **inconsistent** here: Multi-GNN and much downstream work do **not** temporally filter LinkNeighborLoader neighbours, while temporal-native models (LAS-GNN, TeMP-TraG, Amatriciana, TGN) explicitly respect time order. Cite this disagreement, adopt the causal version, and optionally report both to quantify the leak's magnitude.
- **Inductive vs transductive:** Report inductive results (test accounts/edges unseen during training) — the honest deployment setting and the correct one for "unseen time periods."
- **Class imbalance:** Report **PR-AUC / Average Precision** as the primary scalar (robust under 0.1% imbalance), plus minority-class F1, MCC, balanced accuracy, precision@k, and FPR at fixed recall. Accuracy is meaningless here.
- **Threshold selection:** Pre-register the rule (Youden's J as in Tide, or max-F1-on-validation). Never tune on test.
- **Calibration:** Report ECE; apply temperature scaling or isotonic/Platt calibration — justified because your per-seed optimal thresholds range 0.46–0.71 while F1 barely moves.
- **Repeated runs & significance:** ≥5 seeds; mean ± std; Holm-corrected permutation tests (as SALT-GNN uses: "exact permutation tests where possible and Welch's t-test" for smaller-N settings).
- **Subgroup/group-level evaluation (the crux):** Established practice exists — Chai et al. (AAAI 2023) evaluate sub-network discovery via F1 against 3-hop ego-graph ground truth; Elliptic2/RevClassify evaluate subgraph classification; AMAP uses sub-network F1. RingShield's Ring-Precision/Recall/F1 with Jaccard≥0.5 greedy one-to-one matching is reasonable and aligns with community-detection set-overlap matching, but should be (a) framed as an *adaptation of established set-overlap matching*, not a novel invention, and (b) reported with per-pattern-type recall (already done) plus confidence intervals. Also compare against the "refined evaluation metric" published in the incremental/distributed unsupervised AML work (arXiv:2604.01315).

---

## F. Required Ablations (what a 2026 reviewer will demand for a detection→aggregation cascade)

1. **Detector swap under fixed aggregator:** Multi-GINe vs MEGA-GNN vs FraudGT vs GFP+XGBoost vs unsupervised-density, all fed through the identical ring aggregator. Isolates whether the *learned detector* matters for ring-level results.
2. **Aggregator swap under fixed detector:** connected components vs density-filtered CC vs community detection (Louvain/Leiden) vs dense-subgraph mining. Isolates the aggregation mechanism's contribution.
3. **Feature-group ablation:** raw-4 vs +GFP-10 vs +ports/time-deltas, at both edge-F1 and ring-F1 levels.
4. **Graph-construction ablation:** reverse MP on/off, ego IDs on/off, port numbering on/off (mirrors Egressy's Tables 1–2) — and crucially map each to per-pattern recall.
5. **Layer-depth ablation (2 vs 3 vs 4+ layers):** the direct test of the bipartite/stack hypothesis.
6. **Temporal-component ablation:** causal vs non-causal sampling (quantify the leak), and static vs temporal aggregator.
7. **Threshold/scope sensitivity:** ring-F1 as a function of edge cutoff and min-component-size, computed on validation.

---

## G. Robustness / Generalization Experiments (AML-specific interpretation)

- **Unseen pattern types:** Hold out one pattern type in training (e.g., remove all BIPARTITE), test recall on the held-out type. Tide's custom-pattern injection is purpose-built for this.
- **Unseen time periods / temporal generalization:** Train on days 1–6, test on later days; measure decay. The expanding-window split does this partially; extend to rolling-origin evaluation.
- **Concept drift in laundering behaviour:** Use Tide/AMLworld to shift pattern mix or amount distributions between train and test; report degradation. (This was EvolveGCN's original motivation, but temporal-edge models handle drift better.)
- **Adversarial restructuring:** Perturb laundering subgraphs (add intermediary hops, split amounts, reorder timing) and measure detection robustness — TransXion's perturbation-based synthesis and MEGA-GNN's "structural and temporal fuzziness" framing are the conceptual references. **This is emerging/research-stage methodology — label it as such, not established practice.**

---

## H. 2026 Literature Map (full citations)

*Distinguishing established (peer-reviewed, replicated), emerging (peer-reviewed but recent/single-source), and experimental (preprint-only) methodology throughout.*

**Backbones / detectors**
- **[ESTABLISHED] Egressy, B., von Niederhäusern, L., Blanuša, J., Altman, E., Wattenhofer, R., Atasu, K. (2024). "Provably Powerful Graph Neural Networks for Directed Multigraphs." AAAI 2024, 38(10):11838–11846. DOI:10.1609/aaai.v38i10.29069; arXiv:2306.11586.** Ego IDs + reverse MP + port numbering make MPNNs provably able to detect any directed subgraph pattern. RingShield's backbone. Difficulty 3/5. Compute: 2-layer GNN, order-of V100-hours.
- **[ESTABLISHED] Lin, J., Guo, X., Zhu, Y., Mitchell, S., Altman, E., Shun, J. (2024). "FraudGT." ICAIF 2024, pp. 292–300. DOI:10.1145/3677052.3698648.** Edge-based message-passing gates + edge-attribute attention bias; SOTA on AMLworld HI-Small (vanilla F1 69.68 ± 1.58; best variant 76.41). Strong contemporary detector + attention for explainability. Difficulty 3/5; compute moderate (quadratic in sampled subgraph).
- **[EMERGING] Bilgi, H.Ç., Chen, L.Y., Atasu, K. (2024/2026). "Multigraph Message Passing with Bi-Directional Multi-Edge Aggregations" (MEGA-GNN; v3 retitled "MEGA: Message Passing Neural Networks for Multigraphs with EdGe Attributes"). arXiv:2412.00241. Accepted TMLR 2026.** Two-stage (parallel-edge then node) aggregation, bi-directional passing; permutation-equivariant and universal under a strict total edge order; up to +13.31 F1 over Multi-GNN. Drop-in backbone upgrade (Apache-2.0). Difficulty 3/5.
- **[EXPERIMENTAL] Losavio, L., Sovrano, F., Fenoglio, D., Gjoreski, M., Langheinrich, M. (2026). "SALT-GNN: Handling Dense Neighborhoods in Anti-Money Laundering Graphs via Statistics-Aware Attention." arXiv:2607.10131.** Degree-aware statistical aggregation + attention; dominates dense recipient bins. Code "available upon publication" — currently UNVERIFIED/unreleased. Difficulty 4/5.
- **[EMERGING] Wójcik, F. (2025). "Money Laundering Detection with Multi-Aggregation Custom Edge GIN (MAGIC)." Journal of Data Science.** GINE + multiple learnable aggregations; cheaper alternative to MEGA. Difficulty 3/5.
- **[EMERGING] LineMVGNN (MDPI AI, 2025).** Line-graph-assisted multi-view GNN for digraph AML. Comparison only.

**Feature engineering / tabular**
- **[ESTABLISHED] Blanuša, J., Cravero Baraja, M., Anghel, A., von Niederhäusern, L., Altman, E., Pozidis, H., Atasu, K. (2024). "Graph Feature Preprocessor." ICAIF 2024, pp. 222–230. DOI:10.1145/3677052.3698674; arXiv:2402.08593.** Streaming subgraph-pattern feature extraction feeding GBDT; RingShield's 0.632 baseline and the honest strong ring-cascade competitor. Available on PyPI as part of Snap ML. Difficulty 2/5.
- **[EXPERIMENTAL] BlazingAML (arXiv:2604.12241, 2026).** Multi-stage graph mining; matches GFP F1 with 210×/333× CPU/GPU speedup. Efficiency baseline. Difficulty 4/5.
- **[EXPERIMENTAL] Tariq, H. & Hassani, M. (2026). "Extracting Money Laundering Transactions from Quasi-Temporal Graph Representation" (ExSTraQt). arXiv:2604.02899; github.com/mhaseebtariq/exstraqt (verified to exist).** Lightweight supervised classifier on quasi-temporal graph features; +≤1% F1 real, +>8% synthetic. Cheap strong baseline. Difficulty 2/5.

**Temporal / dynamic**
- **[ESTABLISHED] Verlaan, S., Hulpuș, I., van Leeuwen, E.J. (2025). "LAS-GNN: A Graph Neural Network for Temporal Money Laundering Motif Detection." ICAIF 2025, pp. 256–264. DOI:10.1145/3768292.3770410.** Extends Egressy with an LSTM aggregator over timestamp-ordered edges; near-perfect on synthetic temporal motifs; explicitly notes no prior GNN AML method accounted for temporal ordering. Best temporal replacement for EvolveGCN and directly relevant to per-pattern recall. Difficulty 4/5.
- **[EXPERIMENTAL] TeMP-TraG (arXiv:2503.16901, 2025).** Edge-based temporal message passing. Difficulty 4/5.
- **[EXPERIMENTAL] Amatriciana (Di Gennaro et al., arXiv:2506.00654, 2025).** Temporal GNN over the whole transaction graph without time-slicing; also confirms HI-Small stats (5,078,345 transactions; 515,080 accounts; 3,170 launderers = 0.61% of accounts). Difficulty 4/5.
- **[ESTABLISHED, LEGACY] Pareja et al. (2020). "EvolveGCN." AAAI 2020.** Currently implemented; **demote to legacy temporal baseline.**

**Subgraph / group-level (novelty-critical)**
- **[ESTABLISHED] Bellei, C., Xu, M., Phillips, R., Robinson, T., Weber, M., Kaler, T., Leiserson, C.E., Arvind, Chen, J. (2024). "The Shape of Money Laundering: Subgraph Representation Learning on the Blockchain with the Elliptic2 Dataset." KDD MLF 2024; arXiv:2404.19109.** 122K labeled subgraphs; the reference for subgraph-level AML. Difficulty 4/5.
- **[ESTABLISHED] Song, K., Dhraief, M.A., Xu, M., Cai, L., Chen, X., Arvind, Chen, J. (2024). "Identifying Money Laundering Subgraphs on the Blockchain" (RevClassify). ICAIF 2024. DOI:10.1145/3677052.3698635.** RevClassify beats prior subgraph methods on Elliptic2. Difficulty 4/5.
- **[ESTABLISHED] Chai, Z., Yang, Y., Dan, J., Tian, S., Meng, C., Wang, W., Sun, Y. (2023). "Towards Learning to Discover Money Laundering Sub-network in Massive Transaction Network" (AMAP). AAAI 2023, 37(12):14153–14160. DOI:10.1609/aaai.v37i12.26656.** Adaptive sub-network proposer + supervised contrastive loss; sub-network F1 vs 3-hop ego-graph ground truth. **Prior art for learned sub-network discovery — must be cited to defend RingShield's novelty.** Difficulty 5/5 (AliPay data private).
- **[EXPERIMENTAL] Wang, B., Cao, J. (2026). "Clue-Guided Money Laundering Group Discovery" (Clue2Group). arXiv:2606.26189.** Analyst-in-the-loop progressive group recovery via a multi-semantic local-temporal GNN. Difficulty 5/5.
- **[EMERGING] Bit-CHetG (2024).** Subgraph contrastive learning for Bitcoin laundering-group detection. Comparison.
- **[ESTABLISHED] Li et al. (2020). "FlowScope." AAAI 2020, 34(04):4731–4738.** Multipartite flow detection — classic unsupervised group baseline.

**Unsupervised / interpretable**
- **[EMERGING] Deprez, B., Baesens, B., Verdonck, T., Verbeke, W. (2025). "GARG-AML against Smurfing." arXiv:2506.04292; github.com/B-Deprez/GARG-AML (MIT).** Interpretable second-order-neighbourhood density score for smurfing; evaluated on IBM data. **The no-learning ring baseline** that could invalidate the GNN-necessity claim. Difficulty 2/5.
- **[EXPERIMENTAL] "Detecting Complex Money Laundering Patterns with Incremental and Distributed Graph Modeling" (arXiv:2604.01315, 2026); github.com/mhaseebtariq/redirect.** Unsupervised fuzzy partitioning + a published "refined evaluation metric," on Libra + IBM data. Unsupervised comparison + metric benchmark for your ring metrics.

**Federated / privacy-preserving collaborative AML**
- **[ESTABLISHED] Tian, Z., Ding, Y., Qu, W., Yu, X., Gong, E., Liu, J., Ren, K. (2025). "Towards Collaborative Anti-Money Laundering Among Financial Institutions" (CSGM / Sim-CSGM / Prob-CSGM). WWW 2025. DOI:10.1145/3696410.3714576; arXiv:2502.19952.** First collaborative AML mining across institutions without sharing graphs; on AMLSim, Sim-CSGM reports F1 0.9522 ± 0.0033 (balanced) and 0.9833 ± 0.0012 (unbalanced) (Table 1); also tested on AMLWorld-HI. Group-discovery + privacy. Difficulty 5/5.
- **[ESTABLISHED] Effendi, F., Chattopadhyay, A. (2024/2025). "Privacy-Preserving Graph-Based Machine Learning with Fully Homomorphic Encryption for Collaborative Anti-Money Laundering." SPACE 2024, Springer LNCS (DOI:10.1007/978-3-031-80408-3_6); arXiv:2411.02926; github.com/fabecode/GraphML-FHE (Apache-2.0).** TFHE (Zama Concrete ML) GNN + GFP+XGBoost pipelines on AMLworld HI-Small; >99% on a balanced subset. Documents the 370 HI-Small pattern groups. Difficulty 5/5.

**Datasets / generators:** AMLworld — Altman et al., NeurIPS 2023 D&B, arXiv:2306.16424 (primary). Elliptic2 — arXiv:2404.19109. Elliptic++ — Elmougy & Liu, KDD 2023, arXiv:2306.06108. SAML-D — Oztas et al., IEEE ICEBE 2023, DOI:10.1109/ICEBE59045.2023.00028. Tide — arXiv:2603.01863 (2026). AMLNet — Huda et al., 2025, Zenodo/arXiv:2509.11595. CFDB — arXiv:2404.14746. SynthAML — Jensen et al., Nature Sci Data 2023, DOI:10.1038/s41597-023-02569-2. TransXion — arXiv:2604.17420 (2026).

**Expressivity theory (for the bipartite diagnosis)**
- **[ESTABLISHED] Chen, Z., Chen, L., Villar, S., Bruna, J. (2020). "Can Graph Neural Networks Count Substructures?" NeurIPS 2020.** MPNNs and 2-IGNs cannot count induced patterns of ≥3 vertices; they *can* count star-shaped patterns. Directly explains why FAN-IN/FAN-OUT (star-like) succeed while BIPARTITE (dense, non-star) fails.
- **[ESTABLISHED] Bouritsas, G., Frasca, F., Zafeiriou, S., Bronstein, M. (2022). "Improving GNN Expressivity via Subgraph Isomorphism Counting" (GSN). IEEE TPAMI.** Structural identifiers as a drop-in expressivity boost — a candidate fix for BIPARTITE.
- Egressy et al. (2024) attribute weak long-cycle/bipartite recall to insufficient message-passing depth.

---

## I. Recommended Final Architecture

A **detector-agnostic detection→aggregation cascade**, presented as the contribution, with the detector as a swappable component:

1. **Detector layer (swappable):** primary = MEGA-GNN or FraudGT (report both); anchor comparisons = Multi-GINe (current), GFP+XGBoost, and an unsupervised GARG-AML-style density detector. All must produce **per-edge** scores.
2. **Calibration layer:** temperature/isotonic scaling of per-edge scores; validation-selected threshold via Youden's J.
3. **Aggregation layer (swappable):** connected components + density/confidence filters (current) vs Louvain/Leiden vs dense-subgraph mining — reported as an ablation.
4. **Evaluation layer:** edge-level (PR-AUC/AP, F1, MCC, precision@k) + ring-level (Ring-P/R/F1, Member-Coverage, per-pattern recall) with ≥5 seeds and Holm-corrected permutation tests.
5. **Robustness harness:** unseen-pattern, temporal-generalization, drift, and adversarial-restructuring suites on AMLworld + Tide.

The headline claim should be **empirical and falsifiable**: "which detector/aggregator combination best recovers AMLworld pattern groups, and does learned detection beat unsupervised density?" — with the **bipartite-expressivity finding** as a secondary contribution.

---

## J. Implementation Roadmap (three plans)

**PLAN A — Minimum to be scientifically defensible (realistic for a final-year timeline).**
- Fix causal neighbour sampling; move all threshold/scope selection to validation; multi-seed (≥5) ring metrics with CIs; add permutation-test significance.
- Add PR-AUC/AP, MCC, precision@k; report calibration (ECE).
- Add the two invalidation baselines: GFP+XGBoost→aggregator and unsupervised-density→aggregator.
- Layer-depth ablation (2/3/4) to explain BIPARTITE.
- Full reproducibility harness.
- Effort ~3–5 weeks. Risk: low. Dependencies: existing code + Snap ML GFP. **This is the realistic minimum and should be treated as non-negotiable.**

**PLAN B — Strong 2026 version.**
- Everything in A, plus: add FraudGT and MEGA-GNN detectors through the same aggregator; replace EvolveGCN with TGN + a LAS-GNN-style temporal model; full detector-swap and aggregator-swap ablations.
- Add Tide for unseen-pattern and drift robustness; add HI-Medium for scaling.
- Effort ~8–12 weeks. Risk: medium (MEGA/FraudGT integration, temporal tuning). Dependencies: MEGA-GNN (Apache-2.0), FraudGT (no LICENSE file — see risks), PyG TGN (MIT).

**PLAN C — Ambitious / SOTA.**
- Everything in B, plus: generalize the cascade to Elliptic2 (real subgraph labels) to show cross-dataset validity; add SALT-GNN (if released) for dense-neighborhood robustness; add adversarial-restructuring robustness via TransXion-style perturbations; add an expressivity-boosted detector (GSN-style structural features) specifically to fix BIPARTITE and report it as a finding; optionally a privacy/federated extension (CSGM/FHE) as future work.
- Effort 4–6 months. Risk: high (Elliptic2 scale/tooling, SALT code availability, adversarial synthesis is research-stage). **Do not drop for difficulty — state it as the stretch target.**

**Reproducibility standards (all plans):** Git-tracked YAML/Hydra config files; fixed and logged seeds; experiment tracking (Weights & Biases or MLflow); environment capture (conda env export + `pip freeze` + CUDA/PyG/PyTorch versions); dataset versioning (DVC or a hashed manifest of the exact HI-Small download + `_Patterns.txt`); documented hyperparameter search (grid/Bayesian with search space logged); ≥5 runs with mean ± std and 95% CIs; checkpoint management with best-val selection; and an exact split manifest (day boundaries i=6, j=8; train/val/test transaction counts). These are the concrete artifacts 2026 reviewers expect.

---

## K. Risks / Things That Could Invalidate the Research

1. **The novelty claim.** Ring-level AML evaluation and sub-network discovery are established (Chai AAAI 2023; Elliptic2/RevClassify ICAIF 2024; Clue2Group 2026). RingShield must reposition as "first systematic ring-level evaluation *on AMLworld's own pattern labels*, with a detector-agnostic cascade and an expressivity diagnosis" — and must cite prior group-level work explicitly.
2. **GFP+XGBoost through the aggregator may match or beat the GNN.** GFP+XGBoost already beats Multi-GINe at the edge level (0.632 vs 0.599), so it may also win at ring level, undermining "learned GNN needed." Highest-priority experiment.
3. **Unsupervised density may suffice.** If connected-components / dense-subgraph / GARG-AML through the aggregator recovers the same rings, the learned detector is not necessary for ring-level results. **This single experiment is the strongest challenge to the hypothesis and must be run.**
4. **BIPARTITE 0.000 may be a known limitation, not a discovery.** Chen et al. (2020) and Egressy et al. (2024) predict it. Frame it as *empirical confirmation on AMLworld plus a fix*, not novel discovery.
5. **Split incompatibility.** FraudGT uses 64/19/17 on Small, not 60/20/20; cross-paper number comparisons are not apples-to-apples. State this in every comparison table.
6. **FraudGT repo has no LICENSE file** — legal ambiguity for reuse; contact authors or reimplement.
7. **Ring-recall saturation (~0.583)** is likely driven by the large "not classified" illicit fraction (~1,968 transactions in HI-Small) plus pattern types a 2-layer GNN cannot represent — a ceiling that no threshold change fixes.

---

## L. Reviewer-Style Verdict on the Experimental Methodology

*As a hostile reviewer:* The current methodology is **not yet publishable** because of four defects that individually justify rejection: (1) non-causal neighbour sampling (temporal leakage), (2) test-set selection of threshold and ring scope (optimistic bias), (3) single-seed downstream metrics with no significance testing, and (4) an under-powered metric set (F1 only). The ring-cascade is interesting but its novelty is over-claimed relative to Chai (2023), Elliptic2/RevClassify (2024) and Clue2Group (2026), and its *necessity* is unproven without the GFP+XGBoost and unsupervised-density controls. The BIPARTITE finding is presented as surprising but is theoretically predicted by Chen et al. (2020). **However**, all four defects are fixable, the dataset choice is sound (AMLworld is the only widely used benchmark with per-group BEGIN/END pattern labels), and the detector-agnostic framing plus expressivity diagnosis could make a solid ICAIF/KDD-MLF-tier contribution. **Verdict: major revision** — fix methodology (Plan A), add invalidation baselines and stronger detectors (Plan B), and reposition the novelty against prior group-level work.

---

## M. Code Availability Table

| Method | Public code / repo | License | Runs on HI-Small out-of-box? | Per-edge score (aggregator gate) | Split compatibility | Changes to feed ring aggregator |
|---|---|---|---|---|---|---|
| **Multi-GNN (Egressy)** | github.com/IBM/Multi-GNN (GIN, GAT, PNA, RGCN classes verified) | Apache-2.0 (verified) | Yes (`format_kaggle_files.py` + Kaggle HI-Small) | **Yes — per-edge** ✓ | IBM day-based 60/20/20 (canonical) | None — already RingShield's backbone |
| **FraudGT** | github.com/junhongmit/FraudGT | **No LICENSE file (UNVERIFIED/effectively unlicensed)**; paper is CC BY 4.0 | Yes (ships configs/datasets) | **Yes — per-edge** ✓ | Temporal, but **64/19/17** on Small (not 60/20/20) — not directly comparable | Export per-edge probs; re-run under IBM split for comparability |
| **MEGA-GNN** | github.com/hcagri/MEGA-GNN | Apache-2.0 (verified) | Yes (built on Multi-GNN pipeline) | **Yes — per-edge** ✓ | Multi-GNN convention; exact 60/20/20 verbatim UNVERIFIED | Export per-edge probs into aggregator |
| **GFP (Graph Feature Preprocessor)** | PyPI Snap ML; github.com/IBM/snapml-examples | Snap ML license (permissive-proprietary — verify exact terms) | Yes | Edge features; **+XGBoost → per-edge** ✓ | Split-agnostic (feature extractor) | Already integrated; feed XGBoost per-edge scores to aggregator |
| **SALT-GNN** | "available upon publication" | UNVERIFIED (unreleased) | Unknown | Expected per-edge ✓ (edge task) | Multi-GNN-style (UNVERIFIED) | N/A until released |
| **LAS-GNN** | Not located (UNVERIFIED) | UNVERIFIED | Synthetic-motif focus | Detects key accounts — **check gate (may be node-level)** | Own synthetic split | Would need per-edge export; may fail per-edge gate |
| **TGN** | PyG `examples/tgn.py` | MIT (PyG) | Needs adaptation to AMLworld edge task | **Yes — per-edge** ✓ (edge prediction) | Custom temporal | Adapt loader; export per-edge scores |
| **EvolveGCN** | github.com/IBM/EvolveGCN | Apache-2.0 | Needs snapshotting | **Node-level — fails per-edge gate** unless re-cast | Snapshot split | Add an edge-scoring head |
| **GARG-AML** | github.com/B-Deprez/GARG-AML | MIT (verified) | Yes (IBM data supported) | **Account/node-level score — fails per-edge gate directly** | Own eval | Convert node scores to edge scores (min/mean of endpoints) before aggregation |
| **ExSTraQt** | github.com/mhaseebtariq/exstraqt (exists) | UNVERIFIED (check repo) | Claims synthetic IBM data | **Per-transaction** ✓ | Own | Export per-edge scores |
| **Incremental/Distributed** | github.com/mhaseebtariq/redirect | UNVERIFIED | Libra + IBM data | Unsupervised pattern output — **check gate** | Own | Map output patterns to ring format |
| **Elliptic2 / RevClassify** | github.com/MITIBMxGraph/Elliptic2 | UNVERIFIED (check repo) | No (crypto, different graph/task) | **Subgraph-level — different task** | Own | Not applicable to AMLworld edges |
| **GraphML-FHE (Effendi)** | github.com/fabecode/GraphML-FHE | Apache-2.0 (verified) | Yes (modified HI-Small) | **Per-edge** ✓ (GIN / XGBoost) | Balanced/undersampled subset (NOT 60/20/20) | Re-run under standard split; export per-edge scores |
| **CSGM / Sim-CSGM** | Not linked in arXiv (UNVERIFIED) | UNVERIFIED | Tested on AMLWorld-HI | **Group-level output** | Own | Already group-level; different paradigm |

**Gate summary:** Methods producing **account/node-level or graph/subgraph-level** outputs (EvolveGCN, GARG-AML, LAS-GNN possibly, CSGM, Elliptic2/RevClassify) **cannot feed the per-edge ring aggregator without a conversion step** — a hard gate, not a nice-to-have. Directly per-edge-compatible detectors: Multi-GNN, FraudGT, MEGA-GNN, GFP+XGBoost, TGN (adapted), ExSTraQt, GraphML-FHE.

---

## Caveats
- **Numbers reported at different splits are not directly comparable.** FraudGT uses 64/19/17 on Small datasets vs the canonical IBM 60/20/20. Where a paper's exact split could not be verified against source (e.g., MEGA-GNN's exact 60/20/20 ratio), it is marked UNVERIFIED.
- **The AMLNet GFP+XGBoost figure of 0.657 is reported for "high illicit ratio datasets"** and may refer to a different AMLworld variant than HI-Small; RingShield's own 0.632 on HI-Small remains the correct like-for-like reference. Verify the exact variant before citing.
- **Account count discrepancy:** primary sources give 515,088 (GFP/user brief) vs 515,080 (Amatriciana); both round to ~515K and 0.10% transaction-level illicit — the small difference is likely a preprocessing/counting convention.
- **Several 2026 items are preprints** (SALT-GNN, BlazingAML, ExSTraQt, Tide, TransXion, Clue2Group, incremental/distributed) and have not completed peer review; they are labelled EXPERIMENTAL and should be cited as such.
- **License and repo statuses were verified where possible** (Multi-GNN = Apache-2.0; MEGA-GNN = Apache-2.0; GARG-AML = MIT; GraphML-FHE = Apache-2.0; FraudGT = no LICENSE file). Items marked UNVERIFIED could not be confirmed against a primary source within the research budget and should be re-checked before any code reuse.
- **The strongest single test of RingShield's core hypothesis** — whether a learned GNN detector is *necessary* for good ring-level results — is running GFP+XGBoost scores and an unsupervised density detector through the identical aggregator. Until that is done, the central contribution is unproven, not disproven.