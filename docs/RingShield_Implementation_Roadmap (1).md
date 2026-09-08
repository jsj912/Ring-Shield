# RingShield — Executable Implementation Roadmap
### From Literature Survey to Working Baseline→GNN→Proposed-Model Pipeline
Prepared as research-supervisor / ML-architect analysis of `MPP1_FINAL_RINGSHIELD.pdf` and `Literature_Review.xlsx` (44 papers, 4 sheets: Bibliography, Technical Summary, Experimental Results, Critical Analysis).

---

## 1. Project Understanding

**Problem.** Detect *coordinated fraud rings* (not isolated fraudulent transactions) in real time, using a heterogeneous, time-evolving transaction graph (users, devices, cards, merchants, IPs), with analyst-facing explanations and a hybrid rules→ML→TGNN cascade.

**What the four-pillar design actually asks you to build (per Ch.1/Ch.3/Ch.4 of the report):**
1. Temporal heterogeneous graph over transactions (FR03).
2. A **three-layer hybrid cascade**: rule heuristics → XGBoost/LightGBM → TGN/TGAT on escalated subgraphs (FR04).
3. A **ring-level output**: not a per-node/per-edge score but a `{ring_id, member_entity_ids, confidence, topology_type, time_window}` record (FR04.5) — this is the field's structural blind spot per your own Table 2.1/2.2 and confirmed independently by paper #13 (Cheng et al. 2025 survey).
4. **Explainability that reuses TGNN attention** — explicitly *no separate backward pass, no GNNExplainer/PGExplainer/TempME machinery* (Sub-system 4, §4.1.2). This is a real, load-bearing design decision — see Contradiction C3 below.
5. Feedback/retraining loop (FR07) that is **manually triggered**, not automatic drift-triggered.

**What is genuinely novel here vs. the literature (your own G1–G9):**
- **G1 (ring-level output as primary unit)** is the sharpest, most defensible novelty. No paper in your 44-paper corpus outputs a ring record with a member list; every fraud-GNN paper (CARE-GNN, PC-GNN, CaT-GNN, BWGNN, FFD-DHG, HTGNN, TGNN+) stops at node/edge-level scoring.
- **G3 (community-level explanation)** — reusing TGN/TGAT attention for *ring-level* (not node-level) narrative explanation is a genuine, small, implementable extension of TempME/attention-based work.
- **G8 (ring-level evaluation protocol)** is a prerequisite for claiming G1 at all — you cannot say "we detect rings" without a ring-precision/recall/member-coverage metric. AMLworld's labeled laundering patterns (Fan-In, Fan-Out, Cycle, Scatter-Gather) are the only dataset in your corpus that makes this measurable.
- Everything else (temporal modeling, explainability primitives, drift vocabulary, hybrid cascade, heterogeneous graph) is **well-trodden ground you should replicate/adapt, not reinvent.**

**Distinguishing research-critical vs. supporting vs. unnecessary components (architecture reality check):**

| Component (from Ch.3/Ch.4) | Classification | Reasoning |
|---|---|---|
| Rule-based heuristic layer (FR04.2) | Supporting | Needed to complete the "three-layer cascade" claim, but is not itself a research contribution — implement as ~30 lines of pandas/SQL rules, do not over-engineer. |
| XGBoost/LightGBM tabular layer (FR04.3) | **Research-critical** | This is Stage-2 of your experimental story (stronger-than-LR baseline) AND a permanent pipeline component. Also your strongest comparator per paper #35 (GFP+XGBoost beating GNNs on AML minority-F1) — a genuine scientific caution you must engage with, not ignore. |
| TGN/TGAT detection layer (FR04.4) | **Research-critical** | Core backbone of the proposed contribution. |
| Ring aggregation (turning escalated candidates into a ring record, FR04.5) | **Research-critical — and currently UNSPECIFIED.** | Neither the report nor any single paper in your corpus defines *how* individual TGNN-flagged entities get grouped into a ring. This is your actual algorithmic contribution and needs a concrete design decision now (see §23, Decision D1). |
| Explainability via reused attention (FR05.1–05.3) | **Research-critical** | Directly maps to G3; cheap to implement since TGN-attn/TGAT already computes the weights. |
| Alert/Case management UI (FR06, FR08) | Implementation/supporting | Needed for the SaaS narrative and Phase-2 demo, but has **zero research content**. Do not spend research-cycle time here; build last, build minimally (a Streamlit or bare React+FastAPI CRUD app is enough). |
| Feedback & retraining (FR07) | Supporting | Necessary for completeness (and for eventually testing FR07.3's "no regression" gate) but is standard MLOps, not a research question. |
| Multi-tenant SaaS control plane | **Unnecessary for Phase-1/Phase-2 research** — and NFR02.2 already says so | NFR02.2 explicitly scopes the project as **single-tenant**, with multi-tenancy as *future work*. Do not build tenant isolation, auth-per-tenant, or cross-tenant anything. Keep it a design-only discussion in the report. |
| Drift detection/monitoring module | **Overstated in Abstract/Ch.1, downgraded in Ch.3 — contradiction, see C1** | Table 2.1 rates RingShield's own "Drift Robustness" as **No**. FR07.2 is an *administrator-triggered* retrain, not automatic drift detection. Treat drift as **out of scope for implementation**, at most a small offline ADWIN-style experiment in Phase-2 stretch goals, not a system component. |
| Kafka/Flink/Neo4j/Redis/K8s (explicitly excluded in §3.4) | **Correctly excluded already** | Good instinct in the original report — do not add these back in "for realism." NetworkX + PostgreSQL + direct function calls is right-sized for a student project. |
| Full 7-entity heterogeneous schema with geographic nodes (G6) | Optional/stretch | Real datasets available to you (Elliptic, AMLworld, IEEE-CIS) support at most 2–5 entity types with real semantics. Building a schema for entity types your data doesn't actually populate is over-engineering — implement only what your chosen datasets can populate (see §11).

---

## 2. Research Gap & Contribution

Your own literature survey (Table 2.1/2.2, Ch.2.9–2.10) already states this correctly — restated as a testable claim set:

- **Claim A (baseline insufficiency):** Non-relational models (LR, RF, XGBoost) and even static/temporal node-level GNNs (GCN, GraphSAGE, TGN) cannot recover ring membership even when they detect individual suspicious nodes with reasonable accuracy. → tested by Experiments E1–E6, E12 (§7).
- **Claim B (ring-level detection is achievable via cascade + aggregation):** A lightweight aggregation step over TGNN-escalated candidates recovers labeled laundering-pattern rings (Fan-In/Out, Cycle, Scatter-Gather in AMLworld) with materially better ring-precision/recall than a naive connected-components baseline over the raw graph. → tested by E7, E12.
- **Claim C (explainability is nearly free):** Reusing TGN/TGAT attention weights for ring-level narrative explanation adds negligible latency/compute over the base detector (per your own precedent: CaT-GNN's causal module adds only +2.2–2.8% runtime; you should replicate a similarly small overhead number). → tested by E8, E10.
- **Claim D (cascade preserves latency budget):** The three-layer cascade keeps P95 end-to-end latency within NFR01.1/01.2 because the expensive TGNN only runs on escalated candidates, not the full graph. → tested by E10, E13.

Everything else in the report (multi-tenancy, drift, full production deployment) is **narrative/future-work**, not something Phase-2 needs to experimentally prove.

---

## 3. Literature → Implementation Mapping

Legend: **A**=MUST REPLICATE · **B**=SHOULD REPLICATE · **C**=ADAPT · **D**=REFERENCE ONLY · **E**=DO NOT IMPLEMENT

| # | Paper | Method | Dataset | What to replicate | Why | Exact experiment | Class |
|---|---|---|---|---|---|---|---|
| 18 | Weber et al., Elliptic Dataset | LR, RF, MLP, GCN, EvolveGCN | Elliptic | Exact 70:30 **time-based** split; illicit-class F1 as headline metric; the LR/RF/MLP/GCN/EvolveGCN model set itself | This is the *only* paper in your corpus giving you a ready-made, real-world, apples-to-apples baseline ladder on a dataset you already listed (Table 3.21). Reproducing it is your fastest path to a scientifically defensible Stage-1–3 | **E1–E4** (§7) | **A** |
| 6 | EvolveGCN | GRU/LSTM-evolved GCN weights | Elliptic (overlap) | Discrete-time dynamic GNN baseline, evolving-parameters idea | Direct dataset overlap with #18; gives you a *dynamic-but-not-continuous-time* baseline to sit between static GCN and TGN | **E4** | **A** |
| 27 | Kipf & Welling, GCN | Spectral graph conv | Elliptic | 2-layer GCN architecture, propagation rule | Foundational static-GNN baseline; needed to show "graph structure alone ≠ automatic win" (RF beat GCN in #18 — a scientific caution you must reproduce, not hide) | **E3** | **A** |
| 26 | Hamilton et al., GraphSAGE | Inductive sampling+aggregation | Elliptic / AMLworld | Mean/pool aggregator, inductive sampling | Needed because RingShield's own architecture note (FR04.4, "TGN- or TGAT-based") descends from this lineage; also directly used as a strong fraud baseline in paper #10 | **E3** | **A** |
| 2 | Rossi et al., TGN | Memory + message + embedding modules | AMLworld HI-Small | Full TGN-attn architecture (memory module, message function, embedding module) | This *is* your proposed detection engine's backbone (FR04.4). Not optional. | **E6** | **A** |
| 3 | Xu et al., TGAT | Functional time encoding + temporal attention | AMLworld (fallback) | Time-encoding function, attention layer, if TGN underperforms or attention interpretability is prioritized | Alternate backbone explicitly allowed by FR04.4 ("TGN- **or** TGAT-based") | Backbone swap experiment, optional | **B** |
| 19 | Altman et al., AMLworld/IBM-AML | Synthetic AML generator + GIN/PNA/GFP baselines | AMLworld | The dataset itself (HI-Small), its labeled laundering patterns (Fan-In, Fan-Out, Cycle, Scatter-Gather), and its GIN/PNA baseline numbers for sanity-checking your own pipeline | This is the **only dataset in your entire corpus with ring-shaped ground truth** — it is the dataset that makes G1/G8 measurable at all | **E5, E7, E12** | **A** |
| 35 | Blanuša et al., Graph Feature Preprocessor (GFP) | Streaming motif mining + XGBoost/LightGBM | AMLworld | The finding that engineered graph motif features + gradient boosting can **beat GNNs** on AML minority-F1, at far higher throughput | This is the single most important scientific caution in your corpus — you must show your TGN-based cascade beats (or honestly report it doesn't beat) this non-GNN baseline, or your "GNN is necessary" claim is unsupported | **E5b** (GFP-style features + XGBoost baseline) | **A** |
| 17 | Weber-style tabular baselines (LR/RF/MLP) | — | Elliptic + AMLworld | Non-graph baselines already covered by #18; extend the same code to AMLworld | Keeps preprocessing identical across datasets per your leakage-control requirement (§7 in this doc) | **E1, E2** | **A** |
| 22 | Gama et al., Concept Drift Survey | Drift taxonomy, DDM/ADWIN | N/A (methodological) | Vocabulary only (sudden/gradual/incremental/recurring) for the report's discussion; **do not implement DDM/ADWIN as a system component** given Table 2.1 marks your own Drift Robustness = No | Needed for Ch.2.6/Ch.5 narrative correctness, not for code | Optional 1-cell offline drift-sensitivity check (stretch), see §15 | **D** (report), **E** (implementation) |
| 14 | Ying et al., GNNExplainer | Mask-optimization post-hoc explainer | — | Concept only (mutual-information mask framing) for the report's Ch.2.4 discussion | Your Sub-system 4 explicitly avoids GNNExplainer's per-instance optimization cost (too slow for NFR01.2's 2s budget) — cite it, do not implement it | — | **D** |
| 15 | Luo et al., PGExplainer | Parameterized/inductive explainer | — | Concept only | Same reasoning — inductive idea is *conceptually* what you're doing by reusing TGN's own trained attention (free, no separate explainer network needed) | — | **D** |
| 16 | Chen & Ying, TempME | Temporal motif explainer | — | Concept only, cite as the closest prior art to your XAI feature | Full TempME (information-bottleneck motif encoder) is **too heavy for Phase-2 scope** — you get 80% of the analyst value from raw attention-path ranking (FR05.1) for a fraction of the engineering cost | — | **D**, optionally **C** if team has bandwidth after E1–E10 |
| 17 (T-GNNExplainer) | Xia et al. | MCTS Explorer-Navigator | — | Concept only | Explicitly too slow (MCTS) for your latency NFRs — cited as a cautionary counter-example in the report itself | — | **E** |
| 7, 8 | CARE-GNN, PC-GNN | Camouflage-resistant / imbalance-aware static fraud GNNs | YelpChi/Amazon | Neighbor-filtering concept only, or a lightweight re-implementation if team has spare cycles | Canonical fraud-GNN baselines *for review/citation purposes*; their datasets (Yelp/Amazon review-fraud) do not match your financial-transaction domain, so full replication adds cost without proportionate scientific value for *your* claims | Optional stretch static-fraud-GNN baseline only if E1–E10 finish early | **C** (concept), **E** (full replication) unless bandwidth allows |
| 11 | Tang et al., BWGNN | Spectral band-pass filters | YelpChi/Amazon/T-Finance | None for implementation | Elegant but orthogonal to your temporal/ring contribution; static-only, wrong domain data | — | **E** |
| 20 | Egressy et al. | Port numbering + ego IDs + reverse MP | AMLworld | Concept for report; the *idea* (not full re-implementation) that directed-pattern detectability is provably achievable with simple GNN adaptations | Strengthens your methodology chapter's justification for why a message-passing GNN *can* in principle detect cycles/fan-in/fan-out, supporting your ring-detection premise theoretically | — | **D**, or **C** (add reverse-message-passing + port numbers to your TGN/GraphSAGE edges as a cheap architectural add-on) if time allows in ablation |
| 21 | LAS-GNN | Weight+time-aware LSTM aggregator | Synthetic | Concept only | Very recent (2025), closest conceptual precedent to temporal ring-formation — cite as frontier positioning, do not attempt full re-implementation (no public benchmark/code) | — | **D** |
| 1, 5, 4, 24 | JODIE, DyRep, Dynamic-GNN survey, TGB | — | — | Citation/background only | Historical/foundational lineage for Ch.2.2; TGB's leakage-free negative-sampling protocol is worth adopting as a *methodology* pattern (see §7 leakage controls) even without using TGB datasets | — | **D** |
| 30 | HTGNN (Nguyen & Le) | GAT+LSTM+Transformer, Lambda architecture (BatchNet/SpeedNet) | IEEE-CIS | The **BatchNet/SpeedNet split concept** (precompute entity embeddings offline, fuse online) as a latency-budget pattern for your system-evaluation phase | Directly relevant precedent for NFR01.1/01.2 — shows sub-2ms inference is achievable with this pattern | System-design pattern only, not a model to reproduce | **C** |
| 33 | BRIGHT | Two-stage directed graph, GCN/GAT | eBay proprietary | Concept: candidate-generation-then-refine pattern | Precedent for cascade latency design | — | **D** |
| 10 | GraphSAGE vs Fraudsters (Kumar & Kataria) | GraphSAGE vs XGBoost/LightGBM/DNN | Kaggle tabular (KNN-graph) | **Methodological pattern**: build a graph from tabular data via k-NN when no native graph exists | Directly usable if you add IEEE-CIS as a secondary dataset (it has no native entity graph) | Optional E5c if IEEE-CIS is used | **C** |
| 37, 39, 40 | Federated-learning fraud papers | FedAvg/DSFL/etc. | IEEE-CIS/ULB/BAF | None for implementation | Multi-tenancy/federation explicitly out of scope per NFR02.2 — cite only for the report's Ch.2.7/Ch.5 narrative about future work | — | **E** |
| 9 | CaT-GNN | Causal temporal GAT, causal/environment neighbor split | S-FFSD | Concept only: cite the **+2.2–2.8% runtime overhead** figure as your target ceiling for explainability/robustness add-ons | Gives you a quantitative benchmark to compare your own explainability-overhead measurement against | — | **D** |
| 29 | FFD-DHG | Fraud-aware GCN + RL feature fusion | FiGraph | None | Different domain (annual corporate filings, not transactions); node-level only | — | **E** |
| 12, 13, 25, 23, 31, 32, 34 | GeniePath, GNN-fraud survey, GAD survey, ROLAND, Attentional ST-GNN, TGNN+, D3-GNN | — | — | Citation/background for Ch.2 narrative and Ch.5 conclusion | Provide taxonomy, terminology, and precedent quotes already used correctly in your Chapter 2 — no code needed | — | **D** |

**Minimum scientifically defensible implementation set (the actual "must build" list):** Logistic Regression, Random Forest, XGBoost/LightGBM, GCN, GraphSAGE, EvolveGCN, TGN (or TGAT), GFP-style graph-motif-features+XGBoost, your ring-aggregation module, and attention-reuse explainability. **That is 9 models + 1 novel aggregation step** — not 15+.

---

## 4. What We Should Replicate

1. Weber et al.'s exact Elliptic evaluation protocol (time-based 70:30 split, illicit-F1 headline metric) — **A**.
2. AMLworld HI-Small as the ring-ground-truth dataset, using Altman et al.'s and Blanuša et al.'s published GIN/PNA/GFP+XGBoost numbers as sanity-check targets for your own re-implementation (your numbers should land in the same ballpark; if wildly different, you have a bug, not a discovery) — **A**.
3. TGN's memory/message/embedding module architecture as your Detection-Layer-3 backbone — **A**.
4. GFP's core idea (motif counts — cycles, fan-in/out, scatter-gather — as engineered tabular features into XGBoost) as your strongest non-GNN comparator — **A/C** (adapt: you don't need GFP's full streaming C++-grade engine, a batch NetworkX motif-counter over your AMLworld snapshot is sufficient for Phase-2).
5. TGB's leakage-free negative-sampling/evaluation-split *methodology* (not its datasets) — **C**.
6. HTGNN's BatchNet/SpeedNet latency-budget pattern for your system evaluation stage — **C**.

## 5. What We Should NOT Replicate

1. **Do not** re-implement GNNExplainer, PGExplainer, T-GNNExplainer, or TempME. Your own architecture explicitly rejects this (Sub-system 4: "no separate backward pass"). Implementing any of them would *contradict* your own proposed design.
2. **Do not** re-implement CARE-GNN/PC-GNN/BWGNN/FFD-DHG/HTGNN/TGNN+ in full. They are wrong-domain (Yelp/Amazon) or unavailable (proprietary eBay/cross-border data) or simply not necessary to your specific claims — cite, don't code.
3. **Do not** implement federated learning (papers #37, #39, #40) — multi-tenancy is explicitly out of scope per NFR02.2.
4. **Do not** implement Kafka/Flink/RedisGraph/Triton/D3-GNN-style distributed streaming infrastructure — your own §3.4 already correctly excludes these; keep it excluded.
5. **Do not** implement automatic drift detection (ADWIN/DDM) as a running system component — Table 2.1 self-rates your Drift Robustness as "No"; at most, run one offline drift-sensitivity experiment as a stretch goal (§15).
6. **Do not** implement a full 7-entity heterogeneous schema if your chosen datasets can't populate it — AMLworld gives you accounts/banks; Elliptic gives you transactions only. Build the schema your data supports (2–4 real entity types), document the rest as architecture (not implementation).

---

## 6. Experimental Story / Research Hypotheses

```
Stage 1  Simple baseline                 → Logistic Regression                [DONE / IN PROGRESS]
Stage 2  Stronger tabular baselines      → Random Forest, XGBoost/LightGBM
Stage 3  Graph-aware non-GNN baseline    → GFP-style motif features + XGBoost  (your key scientific caution)
Stage 4  Static GNN baselines            → GCN, GraphSAGE (optional GAT)
Stage 5  Discrete-time dynamic baseline  → EvolveGCN
Stage 6  Continuous-time TGNN            → TGN (or TGAT)                       (proposed backbone)
Stage 7  Ring aggregation (novel)        → connected-components / similarity clustering over TGN-escalated subgraph
Stage 8  Full hybrid cascade (proposed)  → Rules → XGBoost → TGN → Ring Aggregation → Explainability
Stage 9  Ablation                        → remove each cascade stage / temporal component / attention-reuse
Stage 10 Explainability evaluation       → fidelity + latency of attention-reuse narrative generation
Stage 11 System/latency evaluation       → P95 latency, throughput vs NFR01.1/01.2/01.4
```

Each stage's result *gates* the next: if Stage 3 (GFP+XGBoost) already achieves ring-adjacent detection as well as a TGN, that is itself a valid, reportable, scientifically honest finding (a "negative-ish" result that still supports the thesis that ring-level *output* — not raw detection power — is the actual gap, since GFP+XGBoost still can't produce a ring record).

---

## 7. Complete Experiment Registry

Random seed policy: **seed=42** fixed across all experiments unless explicitly running a seed-sensitivity check (3 seeds × final model only, in Phase-9).

| ID | Experiment | Model | Dataset | Split | Key Metrics | Purpose | Leads To |
|---|---|---|---|---|---|---|---|
| E1 | LR baseline | Logistic Regression (`class_weight='balanced'`) | Elliptic | Time-based 70:30 (per Weber et al.) | Illicit-F1, Precision, Recall, ROC-AUC | Stage-1 baseline, already started | E2 |
| E2a | RF baseline | Random Forest | Elliptic | same | Illicit-F1 (target ≈0.70–0.80, replicate Weber's 0.796) | Stronger tabular baseline; sanity-check reproduction of #18 | E2b |
| E2b | XGBoost/LightGBM baseline | XGBoost | Elliptic | same | Illicit-F1 | FR04.3's actual model choice — must be evaluated on its own before graph models | E3 |
| E3a | Static GNN — GCN | 2-layer GCN | Elliptic | same, node features + graph | Illicit-F1 (target ≈0.60–0.65, replicate Weber's 0.628) | Reproduce the "RF beats GCN" caution — critical validity check | E3b |
| E3b | Static GNN — GraphSAGE | 2-layer GraphSAGE (mean aggr.) | Elliptic | same | Illicit-F1, training time | Inductive baseline, lineage for FR04.4 | E4 |
| E4 | Discrete-time dynamic GNN | EvolveGCN-O | Elliptic (49 timesteps) | same | Illicit-F1 vs GCN/GraphSAGE | Tests whether *any* temporal signal helps before committing to continuous-time TGN | E5 |
| E5a | Dataset switch + graph-native baselines | LR/RF/XGBoost re-run | AMLworld HI-Small | Time-ordered, account-level | AP, minority-F1 (sanity check vs Altman et al. Table 13/14) | Establishes non-graph baseline on the *ring-labeled* dataset before touching rings | E5b |
| E5b | Graph-motif + XGBoost (GFP-style) | Motif-count features (cycle/fan-in/out/scatter-gather counts via NetworkX) + XGBoost | AMLworld HI-Small | same | minority-F1 vs Blanuša et al.'s GFP+XGBoost numbers | **Key scientific caution baseline** — must beat or honestly fail to beat this | E6 |
| E6 | Continuous-time TGNN | TGN-attn (memory+message+embedding modules) | AMLworld HI-Small | Time-ordered, leakage-free (historical negative sampling per TGB protocol) | AP, minority-F1, per-account fraud score | Core proposed backbone — Stage 6 | E7 |
| E7 | **Ring aggregation (novel)** | Connected-components / threshold-clustering over TGN-escalated candidate subgraph, edges weighted by TGN attention | AMLworld HI-Small | same | **Ring-Precision, Ring-Recall, Member-Coverage, Time-to-Detection** (new protocol, defined in E12) vs ground-truth Fan-In/Out/Cycle/Scatter-Gather labels | Directly tests Claim B / closes G1+G8 | E8 |
| E8 | Explainability (attention reuse) | Top-5 evidence-path extraction from TGN attention + template narrative (FR05.1–05.3) | AMLworld HI-Small (subset of confirmed rings from E7) | qualitative + n=30 analyst-style spot check | Explanation latency (target <2s per NFR01.2), qualitative fidelity | Tests Claim C / closes G3 | E9 |
| E9 | **Full hybrid cascade (proposed system)** | Rules (FR04.2) → XGBoost (E2b) → TGN (E6) → Ring Aggregation (E7) → Explainability (E8) | AMLworld HI-Small | same | End-to-end Ring-F1, escalation rate (% of transactions reaching TGN layer), P95 latency | The actual proposed contribution, integrated | E10 |
| E10 | Ablation — remove rule layer | Cascade without Stage 1 (everything through XGBoost) | AMLworld HI-Small | same | Ring-F1 delta, latency delta | Does the rule layer meaningfully reduce TGN load without hurting recall? | E11 |
| E11 | Ablation — remove XGBoost layer | Rules → TGN directly (skip tabular pre-filter) | AMLworld HI-Small | same | Ring-F1 delta, latency delta, escalation-rate delta | Isolates XGBoost layer's contribution to precision/latency trade-off | E12 |
| E12 | Ablation — static graph instead of temporal | Replace TGN with GCN inside the same cascade | AMLworld HI-Small | same | Ring-F1 delta | Tests whether temporal modeling specifically (not just "a GNN") drives ring-detection gains — **the sharpest test of your core claim** | E13 |
| E13 | Ablation — no ring aggregation | Report node-level TGN scores directly (no clustering step) vs ring-labeled ground truth (majority-vote per ring) | AMLworld HI-Small | same | Ring-F1 (computed by collapsing node predictions into pseudo-rings) vs E7's real ring output | Proves ring-aggregation step is not just cosmetic | — |
| E14 | System/latency evaluation | Full cascade under simulated streaming load | AMLworld or PaySim (replay) | N/A (system test) | P95 end-to-end latency, throughput (txn/s), explanation latency | Validates NFR01.1/01.2/01.4 | Phase 8 |
| E15 (optional/stretch) | Seed sensitivity | Best config (E9) × 3 seeds | AMLworld HI-Small | same | Std. dev. of Ring-F1 | Reproducibility rigor for the paper | Phase 9 |
| E16 (optional/stretch) | Secondary dataset generalization | E9's frozen config, no re-tuning | IEEE-CIS (via KNN-constructed graph, per paper #10's method) | 80:20 chronological | AP, minority-F1 (no ring metric — IEEE-CIS has no ring labels) | Tests generalization beyond synthetic AML data | — |

**Standard output files per experiment (see §21 for full template):** `config.yaml`, `metrics.json`, `predictions.csv`, `confusion_matrix.png`, `model.ckpt` (or `.pkl`), `training_log.csv`, `environment.txt`.

---

## 8. End-to-End Implementation Roadmap

### Phase 0 — Dataset & Experimental Setup *(you are ~here)*
- **Objective:** Lock down datasets, splits, leakage-free preprocessing shared across all baselines.
- **Tasks:** Download/verify Elliptic + AMLworld HI-Small; write one shared `preprocessing.py` that both datasets flow through; define and freeze the temporal split logic; set up `experiments/` registry structure (§20).
- **Exit criteria:** `data/processed/elliptic_{train,test}.parquet` and `data/processed/amlworld_hi_small_{train,test}.parquet` exist, are checksummed, and a `SPLIT_MANIFEST.md` documents exact cutoffs.

### Phase 1 — Baseline ML (E1, E2a, E2b)
- **Objective:** Establish Stage-1/2 non-graph baselines on Elliptic.
- **Deliverables:** `baselines/logistic_regression.py`, `baselines/random_forest.py`, `baselines/xgboost_baseline.py`; `results/phase1_metrics.csv`.
- **Exit criteria:** All three models trained, evaluated, metrics saved; LR/RF numbers within reasonable range of Weber et al.'s published F1 (0.543 LR / 0.796 RF) — large deviation = investigate before proceeding.

### Phase 2 — Graph Construction (Elliptic native graph + AMLworld graph builder)
- **Objective:** Build reusable graph-construction code for both datasets.
- **Deliverables:** `graph/build_elliptic_graph.py` (loads native edge list), `graph/build_amlworld_graph.py` (accounts as nodes, transactions as directed timestamped edges), `graph/motif_features.py` (NetworkX-based cycle/fan-in/out/scatter-gather counters for E5b).
- **Exit criteria:** `torch_geometric.data.Data` (static) and PyG-Temporal-compatible `TemporalData` objects saved to disk for both datasets; motif feature table generated for AMLworld.

### Phase 3 — Static GNN Baselines (E3a, E3b)
- **Objective:** GCN and GraphSAGE on Elliptic.
- **Deliverables:** `baselines/gcn.py`, `baselines/graphsage.py`.
- **Exit criteria:** Illicit-F1 recorded; GCN result should land near Weber's 0.628 (if far off, check for label leakage via full-graph training on future timesteps).

### Phase 4 — Discrete-Time Dynamic Baseline (E4)
- **Objective:** EvolveGCN on Elliptic's 49 timesteps.
- **Deliverables:** `baselines/evolvegcn.py`.
- **Exit criteria:** Comparable or better than GCN; documents whether *any* temporal signal helps at all before the expensive TGN work.

### Phase 5 — Graph-Aware Non-GNN Baseline (E5a, E5b) — dataset switch
- **Objective:** Re-run tabular baselines + GFP-style motif+XGBoost on AMLworld HI-Small.
- **Deliverables:** `baselines/gfp_xgboost.py`.
- **Exit criteria:** minority-F1 recorded; this becomes the benchmark every subsequent GNN result must beat to justify the TGN's added complexity.

### Phase 6 — Proposed TGNN Backbone (E6)
- **Objective:** Train TGN-attn on AMLworld HI-Small for per-account/per-edge fraud scoring.
- **Deliverables:** `models/tgn.py` (using PyTorch Geometric Temporal or a from-scratch TGN implementation), `experiments/E6_tgn/`.
- **Exit criteria:** AP/minority-F1 in the same ballpark as Altman et al.'s reported GIN/PNA numbers; model checkpoint saved for reuse in E7–E9.

### Phase 7 — Ring Aggregation (E7) — **the core novel component**
- **Objective:** Convert TGN-escalated candidate subgraphs into ring records.
- **Deliverables:** `models/ring_aggregator.py`; new evaluation module `evaluation/ring_metrics.py` implementing Ring-Precision/Recall/Member-Coverage/Time-to-Detection.
- **Exit criteria:** Ring-F1 computed against AMLworld's labeled patterns; result compared against E5b and E13 (no-aggregation ablation).

### Phase 8 — Explainability (E8)
- **Objective:** Reuse TGN attention for FR05.1–05.3 (evidence paths, top drivers, narrative).
- **Deliverables:** `explainability/attention_explainer.py`, `explainability/narrative_templates.py`.
- **Exit criteria:** Explanation latency measured (<2s target); 20–30 example explanations saved for qualitative review in the report.

### Phase 9 — Full Cascade Integration + Ablation (E9–E13)
- **Objective:** Wire Rules→XGBoost→TGN→Ring-Aggregation→Explainability into one pipeline; run all four ablations.
- **Deliverables:** `pipeline/hybrid_cascade.py`; `results/ablation_table.csv`.
- **Exit criteria:** Ablation table complete with all four configurations' Ring-F1 and latency; each ablation's hypothesis (§12) confirmed or refuted with a number.

### Phase 10 — System/Latency Evaluation (E14) + FR/NFR validation
- **Objective:** Measure P95 latency, throughput, explanation latency under simulated load.
- **Deliverables:** `system_eval/latency_bench.py`, `results/nfr_validation.csv`.
- **Exit criteria:** Every testable NFR (§17) has a measured pass/fail result.

### Phase 11 — Reproducibility, Documentation, Report Writing
- **Objective:** Freeze final configs, write results into the Phase-2 report, generate all figures.
- **Deliverables:** Final experiment registry export, all figures in `results/figures/`, updated Chapter 4/5 draft.
- **Exit criteria:** Every number quoted in the report traces to a file in `results/`.

---

## 9. Current Position: Logistic Regression

You are inside **Phase 1, Experiment E1**. Concretely, "Logistic Regression started" means you should currently have (or be building):
- A dataset loader for Elliptic's 166 features / 203,769 nodes / 49 timesteps.
- A **time-based** train/test split (steps 1–34 train, 35–49 test, matching Weber et al.'s 70:30 chronological split — **not** a random split; see §9 leakage discussion).
- `class_weight='balanced'` or explicit class weighting (illicit is only ~2% of labeled nodes).
- Illicit-class F1, precision, recall as primary metrics (not overall accuracy — 77% of nodes are unlabeled/excluded, and licit vastly outnumbers illicit).

**INSUFFICIENT INFORMATION — NEEDS DECISION:** Whether your current LR implementation uses local features only (LF, 94-dim) or all features (AF, 166-dim including 72 aggregated neighbor features) — Weber et al. report both. Decide now and use the **same** feature set for every subsequent baseline (RF, XGBoost, GCN) to keep the comparison fair (see §10 leakage/fairness controls).

---

## 10. DO THIS NEXT

**Today (finish Phase 1 / E1):**
1. Confirm your Elliptic split is the time-based 70:30 (steps 1–34 / 35–49), not `sklearn.train_test_split` random split. If it's currently random, **fix this before recording any results** — a random split leaks future graph structure into training and every downstream comparison becomes invalid.
2. Decide LF vs AF feature set (see decision above) and document it in `configs/elliptic_features.yaml`.
3. Finish LR training; save `results/E1_logistic_regression/metrics.json`, `predictions.csv`, `model.pkl`, `config.yaml` per the template in §21.
4. Compare your illicit-F1 against Weber et al.'s reported 0.543 (LR). If wildly different (e.g., >0.15 absolute gap), debug before moving on — the two most likely causes are (a) wrong split, (b) not weighting for class imbalance.

**Next (Phase 1, remainder — E2a, E2b):**
5. Implement Random Forest with identical preprocessing/split as E1. Target: F1 ≈ 0.796 (Weber et al.).
6. Implement XGBoost with identical preprocessing/split. This is also your FR04.3 production component — write it once, reuse the code later in the cascade (Phase 9).
7. Write `results/phase1_summary.md` comparing LR vs RF vs XGBoost — this is your Stage-1→Stage-2 experimental-story evidence.

**After that (Phase 2 — Graph Construction):**
8. Build the Elliptic native graph object (`torch_geometric.data.Data`) from the provided edge list — nodes = transactions (not accounts), edges = payment flows, 166 node features, single edge type.
9. Implement GCN (E3a) and GraphSAGE (E3b) on this graph object, same time-based split. Target GCN F1 ≈ 0.628.
10. **Checkpoint decision:** if GCN underperforms RF/XGBoost as expected (replicating Weber et al.), do not panic — write this up explicitly as your Stage-3 scientific caution ("graph structure alone, without temporal or ring-level modeling, does not automatically beat tabular baselines" — this is a *correct*, citable, expected finding that motivates the rest of your pipeline).
11. Proceed to EvolveGCN (E4), then switch datasets to AMLworld HI-Small for E5 onward (Phase 5–7), following the roadmap in §8.

Do not skip ahead to TGN/ring-aggregation before E1–E4 are complete and logged — the ablation table in Phase 9 depends on having every earlier stage's number on record.

---

## 11. Dataset & Preprocessing Pipeline

**Datasets selected (with rationale):**

| Dataset | Role | Why | Native graph? | Ring labels? |
|---|---|---|---|---|
| **Elliptic** | Stages 1–4 (LR→RF→XGBoost→GCN/SAGE→EvolveGCN) | Only real-world, publicly labeled, graph-native transaction dataset in your corpus with an established, reproducible baseline protocol (paper #18) | Yes (203,769 nodes, 234,355 edges, 49 timesteps) | **No** (binary illicit/licit only) |
| **AMLworld HI-Small** | Stages 5–11 (graph-motif baseline → TGN → ring aggregation → explainability → cascade → ablation) | Only dataset with actual **ring-shaped ground truth** (Fan-In, Fan-Out, Cycle, Scatter-Gather patterns) — required to measure G1/G8 at all | Yes (directed, temporal, multi-account) | **Yes** |
| IEEE-CIS (optional, E16 stretch) | Generalization check only | Tabular only, requires KNN-graph construction (per paper #10); no ring labels | No (must construct via k-NN, per #10) | No |
| PaySim (optional) | System/latency replay only (E14) | Good for simulating streaming throughput, not for classification metrics | Weak/synthetic | No |

**Pipeline (with leakage checkpoints marked):**

```
Raw Dataset (Elliptic CSVs / AMLworld transaction logs)
   │
   ├─ Cleaning (dtype fixes, missing-value handling)                [before split — dataset-wide constants only]
   │
   ├─ TEMPORAL SPLIT BOUNDARY  ◄── must happen before any statistic is computed
   │     Elliptic: timesteps 1–34 = train, 35–49 = test
   │     AMLworld: chronological cutoff at 70th percentile of transaction timestamps
   │
   ├─ Feature engineering (per-entity aggregates, motif counts)      [fit ONLY on train, applied to test — never fit on full data]
   │
   ├─ Label processing (illicit/licit; ring-pattern labels for AMLworld)
   │
   ├─ Graph construction                                             [test-period edges/nodes NEVER visible when building train-time graph]
   │
   ├─ Model input (feature matrix + edge index + timestamps)
   │
   ├─ Training → Prediction → Evaluation
   │
   ├─ Explainability (attention extraction, post-hoc, test-set only)
   │
   └─ (later) Dashboard / System demo
```

**Preprocessing steps that must be IDENTICAL across every baseline for a fair comparison (Elliptic track):**
- Same LF-vs-AF feature-set decision (§9).
- Same class-imbalance handling strategy (class-weighting, not SMOTE — SMOTE on graph-structured minority nodes can synthesize implausible graph neighborhoods; class-weighting is simpler and defensible).
- Same time-based split boundary (steps 34/35).
- Same evaluation metric definitions (illicit-F1 computed only over *labeled* nodes, excluding the ~77% unlabeled).

---

## 12. Graph Construction Plan

**Elliptic (native graph, Stages 1–4):**
- **Node** = a Bitcoin transaction (not an account).
- **Edge** = a payment flow between two transactions (directed).
- **Node features** = 166-dim (94 local + 72 one-hop-aggregated), pre-computed by the dataset authors.
- **Edge features** = none provided natively.
- **Label** = licit(0)/illicit(1)/unknown per node.
- **Graph type**: homogeneous, directed, discrete-time (49 snapshots).
- **Library**: PyTorch Geometric `Data` object per snapshot, or one `Data` object with a `time_step` node attribute for full-history models (EvolveGCN needs per-snapshot; GCN/GraphSAGE can train transductively across all labeled train-period nodes at once).

**AMLworld HI-Small (Stages 5–11):**
- **Node** = a bank account.
- **Edge** = a transaction, timestamped, directed, with amount and currency as edge features.
- **Node features**: none provided natively for accounts — you must engineer them (degree, in/out transaction count, aggregate amount statistics over a rolling window) — this is legitimate, expected feature engineering, not leakage, **as long as it's computed only from information available strictly before the prediction timestamp**.
- **Label**: transaction-level laundering flag; **ring/pattern label** derivable from the dataset's documented pattern generator output (Fan-In, Fan-Out, Cycle, Scatter-Gather, Random) — you will need to map transaction-level laundering flags into **connected-component ring groups** per documented pattern to build your ring-level ground truth (this mapping logic itself is a piece of code you must write and document — see Decision D1 in §23).
- **Graph type**: heterogeneous-lite (single node type = account; single edge type = transaction, but weighted/timestamped), directed, temporal multigraph.
- **Timestamps**: represented as Unix epoch or relative offset from the dataset's start date; used directly by TGN's time-encoding.
- **Preventing future leakage into earlier timestamps**: when building the *training-time* graph snapshot for any given prediction, only include edges with `timestamp < prediction_time`. For TGN, this is handled natively by its raw-message-store / memory-update mechanism (a message from a future edge is never applied before its timestamp) — but you must verify your data loader feeds events in strict timestamp order, not shuffled.
- **Library**: PyTorch Geometric Temporal's `TemporalData`, or a custom `(src, dst, t, msg)` event-stream format matching TGN's original reference implementation.

**Transition from static → temporal representation:** Elliptic graph (static Stages 1–4) → AMLworld temporal event-stream (Stages 5–11) is a **deliberate dataset switch**, not a representation upgrade of the same data — do not attempt to force Elliptic into a continuous-time TGN; it lacks the fine-grained timestamps AMLworld provides (Elliptic only has 49 coarse snapshots, no true event ordering within a snapshot).

---

## 13. Baseline Models

| Baseline | Necessary because | Literature support | Establishes | Limitation it demonstrates | Vs. proposed |
|---|---|---|---|---|---|
| Logistic Regression | Simplest possible sanity floor | Paper #18 | Non-relational features carry *some* signal | No relational reasoning at all | Proposed model must clear this by a wide margin |
| Random Forest | Strongest simple tabular model; **historically beat GCN on this exact dataset** | Paper #18 | Tabular models can be surprisingly strong | Still no explicit graph reasoning, no ring output | Sets the "graph must earn its complexity" bar |
| XGBoost/LightGBM | Actual FR04.3 production component | Papers #18 (as MLP/RF proxy), #35 (GFP+XGBoost) | Gradient boosting as both a baseline *and* a permanent pipeline stage | No native relational reasoning without engineered graph features | Directly reused inside the proposed cascade |
| GFP-style motif+XGBoost | **The critical scientific caution** | Paper #35 | Engineered graph-topology features can rival GNNs at much lower cost | Cannot output an end-to-end learned ring representation; handcrafted motifs may miss novel structures | Must be beaten (or the report must honestly explain why not) to justify TGN's added complexity |
| GCN | Foundational static GNN | Papers #18, #27 | Whether *any* graph convolution helps at all | Ignores temporal order; oversmooths; historically underperformed RF on Elliptic | Baseline for "graph but not temporal, not ring-level" |
| GraphSAGE | Inductive baseline, lineage for FR04.4 | Papers #26, #10 | Inductive generalization to unseen nodes | Still node-level only, still static | Same limitation class as GCN, added for inductive-setting completeness |
| EvolveGCN | Discrete-time dynamic baseline | Paper #6 | Whether *coarse-grained* temporal modeling (snapshot-level) already captures most of the gain | Cannot use fine-grained event ordering, still node-level | Tests whether continuous-time TGN complexity is actually necessary |
| TGN(-attn) | **Proposed backbone** | Paper #2 | Continuous-time, memory-based entity representations | Still node/edge-level *on its own* — no ring output without the aggregation step you add | This is Layer 3 of your cascade |

**Do not add** GAT, CARE-GNN, PC-GNN, BWGNN, TGAT-as-a-separate-full-run unless E1–E9 finish with time to spare — see §3 classification for exactly which are optional stretch (Class B) vs required (Class A).

---

## 14. Proposed Model Implementation

Break the proposed system into implementation components, in dependency order:

```
Component A: Data Ingestion & Entity Resolution (FR01, FR02)
        │  (feeds timestamped events into the graph builder)
        ▼
Component B: Temporal Graph Builder (FR03)
        │  (maintains incremental TemporalData / event stream)
        ▼
Component C: Rule Heuristic Layer (FR04.2)
        │  (cheap filter — velocity burst, shared-device threshold)
        ▼
Component D: Tabular ML Layer — XGBoost (FR04.3)              [= E2b, reused]
        │  (escalates candidates above calibrated threshold)
        ▼
Component E: TGN Detection Layer (FR04.4)                     [= E6, reused]
        │  (produces per-entity fraud score + attention weights, subgraph-restricted)
        ▼
Component F: Ring Aggregation (FR04.5) — NOVEL                [= E7]
        │  (clusters escalated, TGN-scored entities into ring records)
        ▼
Component G: Explainability — Attention Reuse (FR05)          [= E8]
        │  (top-5 evidence paths + narrative from TGN attention, no separate backward pass)
        ▼
Component H: Alert/Case Output (FR06) — non-research, build last
```

| Component | Purpose | Concept | Input | Output | Order | Literature support | Validating experiment |
|---|---|---|---|---|---|---|---|
| A | Ingest transactions, resolve entities | Simple schema validation + entity registry | Raw transaction record | Validated event | 1 | FR01/FR02 (standard) | — |
| B | Maintain temporal graph | Event-stream `(src,dst,t,msg)` | Validated events | `TemporalData` object | 2 | Paper #2 (TGN's own input format) | — |
| C | Cheap pre-filter | Velocity/shared-device rules | Event stream | Candidate flags | 3 | Standard rule engine | E10 (ablation: remove this) |
| D | Tabular scoring | Gradient boosting on engineered features | Candidates + features | Escalation decision | 4 | Papers #18, #35 | E2b, E11 (ablation: remove this) |
| E | Temporal graph scoring | TGN memory/message/embedding | Escalated subgraph | Per-entity fraud score + attention | 5 | Paper #2 | E6, E12 (ablation: replace with static GCN) |
| F | **Ring aggregation** | Clustering over attention-weighted escalated subgraph | Scored entities + attention | Ring record | 6 | **Novel — no direct precedent**, informed by paper #20's directed-pattern theory | E7, E13 (ablation: remove this) |
| G | Explainability | Top-k attention-path extraction + template narrative | Ring record + attention | Evidence paths + narrative | 7 | Papers #12 (attention-as-interpretability precedent), #9 (overhead benchmark) | E8 |
| H | Case output | CRUD alert record | Ring + explanation | Stored alert | 8 | FR06 (standard) | — |

**Implementation order rationale:** A→B are plumbing (build once, reuse everywhere). C→D→E must be built in cascade order because each stage's *output* (escalation decision) is the next stage's *input* — you cannot test E in isolation without D's escalation logic already working, but you *can and should* test D and E's underlying models (XGBoost, TGN) independently first (Phases 1–6) before wiring the cascade (Phase 9). F is the piece with zero prior implementation to copy — budget the most exploration time here.

---

## 15. Ablation Study Plan

Only ablations that are meaningful for *this* architecture:

| Ablation | What's removed | Why | Hypothesis | Metric expected to change | Interpretation |
|---|---|---|---|---|---|
| No rule layer | Component C | Tests whether the cheap filter is pulling its weight | Ring-F1 roughly unchanged, but escalation rate to XGBoost rises, hurting latency | Escalation rate, P95 latency | If latency barely changes, the rule layer isn't earning its architectural complexity — consider simplifying |
| No XGBoost layer | Component D | Isolates the tabular layer's precision contribution | Escalation rate to TGN rises sharply (more false candidates reach the expensive layer); Ring-F1 may drop slightly if XGBoost was filtering noise TGN can't | Escalation rate, P95 latency, Ring-Precision | Tests whether the "cost-vs-accuracy trade-off" claim in Ch.4.1.1 is real |
| Static graph instead of temporal (GCN swapped for TGN) | Component E's temporal mechanism | **Sharpest test of the core temporal-modeling claim** | Ring-F1 drops materially — temporal ordering is necessary to detect fan-in/out/cycle/scatter-gather patterns that unfold over time | Ring-F1, Ring-Recall | If Ring-F1 does *not* drop, your central claim ("temporal modeling matters for rings") is not supported by the data — be prepared to report this honestly |
| No ring aggregation (report raw node scores, majority-vote pseudo-rings) | Component F | Proves the aggregation step adds value beyond node-level scoring alone | Ring-Recall drops sharply — individually-plausible nodes without explicit grouping under-recover full ring membership | Ring-Recall, Member-Coverage | Directly validates/refutes G1's core premise |
| No attention-reuse explainability (blank/random top-k) | Component G | Sanity check that explanations are non-trivial | Explanation fidelity score (does the top-5 path actually overlap with the ring's true shared entity) should be far higher for real attention than random | Fidelity (edge-overlap %) | Confirms G3 claim is substantive, not decorative |

Do **not** add ablations for multi-tenancy or drift — neither is implemented (§1, §2), so there is nothing to ablate.

---

## 16. Evaluation Framework

**Classification (node/transaction-level, Elliptic + AMLworld pre-ring stages):**
- **Primary:** Illicit/minority-class F1 (imbalance means accuracy is meaningless — Weber et al. and Blanuša et al. both explicitly avoid accuracy as headline metric; you should too).
- **Secondary:** Precision, Recall, ROC-AUC, Average Precision (AP), confusion matrix.
- **Why F1/AP primary:** class imbalance (illicit ≈2% Elliptic, minority-class laundering ≪5% AMLworld HI) makes accuracy misleadingly high for a trivial "predict all licit" model.

**Ring-level (novel protocol — you must define this; no paper in your corpus provides it, confirming G8):**
- **Ring-Precision** = (# predicted rings matching a true ring, by ≥50% member overlap) / (# predicted rings).
- **Ring-Recall** = (# true rings recovered, by ≥50% member overlap) / (# true rings).
- **Member-Coverage** = mean fraction of a true ring's members correctly included in the matched predicted ring.
- **Time-to-Detection** = median time between a ring's first constituent transaction and the ring alert's generation timestamp.
- These four together directly answer FR04.5's requirement and close gap G8.

**Explainability evaluation:**
- **Fidelity** = % overlap between the top-5 attention-ranked evidence edges and the ring's actual shared-entity edges (ground truth known from AMLworld's pattern generator).
- **Latency** = wall-clock time to generate one explanation (target <2s, NFR01.2).
- These are **secondary but required** metrics — do not skip; FR05/NFR05 depend on them.

**Computational performance:**
- Training time (wall-clock, per model, same hardware).
- Inference latency (P50/P95/P99, per cascade stage and end-to-end).
- Parameter count (per model).
- Memory footprint (peak RSS during training/inference).
- These map directly to NFR01 (§17) and are **primary** for Phase 10, secondary elsewhere.

**System-level (NFR-mapped):** see §17.

---

## 17. FR/NFR Traceability Matrix

| Req ID | Requirement | Architecture Component | Implementation Step | Experiment/Test | Evidence | Status |
|---|---|---|---|---|---|---|
| FR01.1–01.4 | Data ingestion | Component A | Phase 0/6 | Schema validation unit test | `tests/test_ingestion.py` | Buildable but not research-critical |
| FR02.1–02.3 | Entity resolution | Component A | Phase 0/6 | Entity registry unit test | `tests/test_entity_resolution.py` | Buildable, low priority |
| FR03.1–03.5 | Temporal graph builder | Component B | Phase 2, 6 | Graph object inspection (node/edge counts match raw data) | `graph/build_*.py` outputs | **Research-adjacent** — needed for TGN input |
| FR04.1 | Three-layer cascade | C+D+E | Phase 9 | E9 | `pipeline/hybrid_cascade.py`, E9 metrics | Core deliverable |
| FR04.2 | Rule heuristics | Component C | Phase 9 | E10 (ablation) | E10 results | Core deliverable |
| FR04.3 | Tabular ML layer | Component D | Phase 1, 5 | E2b, E5a, E11 (ablation) | E2b/E5a/E11 results | Core deliverable |
| FR04.4 | TGN/TGAT layer | Component E | Phase 6 | E6, E12 (ablation) | E6/E12 results | Core deliverable |
| FR04.5 | Ring alert record | Component F | Phase 7 | E7, E13 (ablation) | E7/E13 results, `evaluation/ring_metrics.py` | **Core research deliverable** |
| FR04.6–04.7 | Thresholds, deduplication | Component F | Phase 7 | Unit test on synthetic overlapping candidates | `tests/test_dedup.py` | Buildable, low research priority |
| FR05.1–05.4 | Explainability | Component G | Phase 8 | E8 | `explainability/*`, E8 fidelity/latency numbers | Core research deliverable |
| FR06.1–06.4 | Case management | Component H | Phase 11 (last) | Manual UI walkthrough | Screenshot/demo | **Not research-critical** — minimal build |
| FR07.1–07.4 | Feedback/retraining | Standard MLOps | Phase 11 (stretch) | Manual re-train trigger + held-out eval | `retrain/retrain_workflow.py` | Stretch, only if time allows |
| FR08.1–08.7 | Dashboard/UI | Component H | Phase 11 (last) | Manual walkthrough | Screenshots | **Not research-critical** |
| NFR01.1 | ≤60s scoring pass @ 100k nodes/500k edges | E/F pipeline | Phase 10 | E14 | `system_eval/latency_bench.py` | Testable — measure directly |
| NFR01.2 | ≤2s explanation generation | Component G | Phase 10 | E8, E14 | Explanation latency log | Testable |
| NFR01.3 | ≤3s dashboard load | Component H | Phase 11 | Manual browser timing | Screenshot/log | Testable but non-research |
| NFR01.4 | ≥100 txn/s ingestion | Component A | Phase 10 | E14 (load test) | Throughput log | Testable |
| NFR02.1 | Up to 1M nodes/5M edges | Graph builder | Phase 2/6 | Scale test (if hardware allows) | Memory/time log | **INSUFFICIENT INFO — dataset scale (AMLworld HI-Small) is smaller than this; either use HI-Medium/Large for a scale test, or explicitly footnote that full-scale testing is future work** |
| NFR02.2 | Single-tenant only | N/A | N/A | N/A | Design decision documented | **Correctly out of implementation scope** — do not build multi-tenancy |
| NFR03.1–03.3 | Reliability/checkpointing | Component B/H | Phase 11 (stretch) | Restart-recovery test | Log | Stretch |
| NFR04.1–04.4 | Security | Component H | Phase 11 (stretch) | Manual review | N/A | Stretch, non-research |
| NFR05.1–05.3 | Explainability/audit logging | Component G/H | Phase 8/11 | E8 | Explanation logs w/ model version | Core, low effort once G is built |
| NFR06.1–06.4 | Maintainability | All | Ongoing | CI pipeline | GitHub Actions logs | Standard engineering hygiene |

---

## 18. Research Traceability Matrix

```
Literature (Weber et al. #18; Altman et al. #19; Blanuša et al. #35; Rossi et al. #2)
   → Research Gap (G1 ring-level output; G3 community explanation; G8 ring evaluation)
      → Proposed Solution (three-layer cascade + ring aggregation + attention-reuse XAI)
         → Architecture (Components A–H, §14)
            → Requirement (FR04.4/04.5/05.1, NFR01.1/01.2)
               → Implementation (Phases 1–10)
                  → Experiment (E1–E14)
                     → Metric (Illicit-F1 → Ring-Precision/Recall/Member-Coverage → Explanation fidelity/latency → P95 latency)
                        → Result (recorded in results/*.json, §21 template)
                           → Research Claim (Claims A–D, §2)
```

Every implementation decision should be traceable to exactly one row of this chain. If a task cannot be traced back to a literature-grounded gap or a requirement, it is out of scope for the research contribution (route it to "system polish," Phase 11, or cut it — §1's over-engineering flags apply).

---

## 19. 3-Person Team Work Breakdown

Given the actual dependency structure (Component B feeds C/D/E; E feeds F; F feeds G), a clean split is by **pipeline layer**, not by arbitrary task category — this avoids the two members working on E and F blocking each other mid-sprint.

**Person 1 — Data, Graph & Baseline-ML (Phases 0–5, Components A–D)**
- Owns: dataset preprocessing, temporal splits, graph construction (Elliptic + AMLworld), LR/RF/XGBoost/GCN/GraphSAGE/EvolveGCN baselines, GFP-style motif-feature engineering.
- Delivers by end of Phase 5: `results/phase1-5_baseline_table.csv` — every non-TGN number in the experiment registry.

**Person 2 — TGNN Backbone & Ring Aggregation (Phases 6–7, Components E–F)**
- Owns: TGN implementation and training (E6), ring-aggregation algorithm design and implementation (E7), and the **novel ring-evaluation protocol** (`evaluation/ring_metrics.py`).
- This is the highest-research-value, highest-risk workstream — starts as soon as Person 1 delivers the AMLworld `TemporalData` object (end of Phase 2/5), can work in parallel with Person 1's Elliptic-track baselines (Phases 3–4) since they use different datasets.

**Person 3 — Explainability, Cascade Integration, System Evaluation, UI/Reporting (Phases 8–11, Components G–H)**
- Owns: attention-reuse explainability (E8), full cascade wiring (E9), all ablations (E10–E13), latency/system evaluation (E14), minimal dashboard (FR06/FR08), and report/figure generation.
- Depends on Person 1's XGBoost model (D) and Person 2's TGN+ring output (E, F) — starts substantive work once those checkpoints exist (roughly Phase 6–7), but can build the explainability *scaffolding* and dashboard *skeleton* in parallel earlier.

**Interfaces every member must agree on before diverging (standardize now):**
- The exact `TemporalData`/event-stream schema (`src, dst, t, amount, currency, msg`) — Person 1 defines it while building the graph, Person 2 and 3 consume it as-is.
- Model checkpoint/metrics file format (§21 template) — every experiment, regardless of owner, writes to the same `experiments/<ID>_<name>/` structure so results are directly comparable.
- The ring ground-truth extraction logic from AMLworld's pattern labels (Decision D1, §23) — this must be written **once**, reviewed by all three, and used identically by Person 1 (E5b), Person 2 (E7), and Person 3 (E13 ablation).

**Integration points:** end of Phase 2 (graph objects ready), end of Phase 5 (baseline table + AMLworld motif baseline complete, unblocking Person 2 fully), end of Phase 7 (TGN+ring output ready, unblocking Person 3 fully), end of Phase 9 (full cascade + ablations — all three review together before Phase 10).

---

## 20. Repository / Folder Structure

```
ringshield/
├── data/
│   ├── raw/                      # untouched downloads (Elliptic CSVs, AMLworld txn logs) — gitignored
│   ├── processed/                # split, cleaned parquet/csv files — checksummed, small enough to version or DVC-tracked
│   └── SPLIT_MANIFEST.md         # exact split boundaries, feature-set decisions, dataset versions
├── preprocessing/
│   ├── elliptic_loader.py
│   ├── amlworld_loader.py
│   └── shared_utils.py           # class-weighting, common feature scaling — used identically by all baselines
├── graph/
│   ├── build_elliptic_graph.py
│   ├── build_amlworld_graph.py
│   └── motif_features.py         # GFP-style cycle/fan-in/out/scatter-gather counters
├── baselines/
│   ├── logistic_regression.py
│   ├── random_forest.py
│   ├── xgboost_baseline.py
│   ├── gfp_xgboost.py
│   ├── gcn.py
│   ├── graphsage.py
│   └── evolvegcn.py
├── models/
│   ├── tgn.py
│   ├── ring_aggregator.py
│   └── rules.py                  # FR04.2 heuristics
├── pipeline/
│   └── hybrid_cascade.py         # wires rules→xgb→tgn→ring_agg→explain
├── explainability/
│   ├── attention_explainer.py
│   └── narrative_templates.py
├── evaluation/
│   ├── classification_metrics.py
│   ├── ring_metrics.py           # Ring-Precision/Recall/Member-Coverage/Time-to-Detection — NOVEL, document thoroughly
│   └── system_metrics.py         # latency/throughput harness
├── experiments/
│   ├── E1_logistic_regression/
│   │   ├── config.yaml
│   │   ├── metrics.json
│   │   ├── predictions.csv
│   │   ├── model.pkl
│   │   ├── training_log.csv
│   │   └── environment.txt
│   ├── E2a_random_forest/ ...
│   └── ... (one folder per experiment ID, §7/§21 template — nothing else lives here)
├── ablation/
│   └── ablation_runner.py        # orchestrates E10–E13, writes results/ablation_table.csv
├── system_eval/
│   └── latency_bench.py
├── results/
│   ├── phase1_summary.md
│   ├── ablation_table.csv
│   ├── nfr_validation.csv
│   └── figures/                  # all report-ready plots, PNG/SVG, named by experiment ID
├── configs/
│   ├── elliptic_features.yaml
│   ├── amlworld_features.yaml
│   └── cascade_thresholds.yaml
├── notebooks/                    # exploratory only — nothing here is a source of truth; promote to scripts once stable
├── scripts/                      # one-off utility scripts (dataset download, checksum verification)
├── tests/                        # unit tests for ingestion, entity resolution, dedup logic
└── docs/
    ├── SPLIT_MANIFEST.md (symlink or copy)
    ├── EXPERIMENT_REGISTRY.md    # human-readable mirror of §7 table, updated as experiments complete
    └── RING_GROUND_TRUTH_DEFINITION.md   # Decision D1 writeup (§23) — must exist before E7
```

**Naming convention:** experiment folders always `E<number>[letter]_<short_name>`, matching the IDs in §7 exactly — never rename after the fact, only add.

**What does NOT belong in `baselines/` or `models/`:** any explainer other than `attention_explainer.py` (§5, do-not-replicate list); any Kafka/Flink/Redis code; any multi-tenant/auth code.

---

## 21. Experiment Reproducibility Standard

Every experiment folder (`experiments/<ID>_<name>/`) must contain:

```yaml
# config.yaml — example
experiment_id: "E6"
name: "tgn_amlworld_hi_small"
dataset: "amlworld_hi_small"
dataset_version_hash: "<sha256 of processed parquet>"
split: "chronological_70_30"
feature_set: "engineered_account_features_v1"
model: "TGN-attn"
hyperparameters:
  memory_dim: 100
  time_dim: 100
  embedding_dim: 100
  n_layers: 1
  lr: 0.0001
  epochs: 50
  batch_size: 200
random_seed: 42
hardware: "1x NVIDIA T4, 16GB VRAM"
software_env: "environment.txt"
git_commit: "<commit hash at run time>"
```

Plus, in the same folder:
- `metrics.json` — every metric from §16 relevant to this experiment.
- `predictions.csv` — per-instance predictions (node/ring ID, score, true label).
- `confusion_matrix.png` (classification stages) or `ring_match_table.csv` (ring stages).
- `training_log.csv` — per-epoch loss/metric curve.
- `model.ckpt` / `model.pkl` — the trained model artifact.
- `environment.txt` — `pip freeze` output + CUDA/driver version.
- `runtime_seconds.txt` — wall-clock training + inference time.

**Never overwrite an experiment folder.** If you re-run E6 with different hyperparameters, it becomes `E6b`, not a silent overwrite — this is what makes the ablation table (§15) and the traceability matrix (§18) trustworthy.

---

## 22. Research Project Master Checklist

**Research**
- [ ] Research gap (G1, G3, G8) restated as testable claims (Claims A–D, §2) and agreed by all 3 team members
- [ ] Literature-to-implementation mapping (§3) reviewed; MUST-REPLICATE list confirmed as minimal and sufficient
- [ ] Contradictions C1–C3 (§23) resolved and documented in report Ch.3/Ch.5

**Dataset**
- [ ] Elliptic downloaded, checksummed, time-based split frozen and documented (`SPLIT_MANIFEST.md`)
- [ ] AMLworld HI-Small downloaded, checksummed, chronological split frozen
- [ ] LF-vs-AF feature-set decision made and documented
- [ ] Ring ground-truth extraction logic (Decision D1) written, reviewed, documented

**Baselines**
- [ ] E1 Logistic Regression complete, logged
- [ ] E2a Random Forest complete, logged
- [ ] E2b XGBoost complete, logged
- [ ] E5a Tabular baselines re-run on AMLworld, logged
- [ ] E5b GFP-style motif+XGBoost complete, logged (critical scientific-caution baseline)

**Graph Construction**
- [ ] Elliptic native graph object built and validated (node/edge counts match published stats)
- [ ] AMLworld temporal event-stream/graph object built and validated
- [ ] Motif feature extraction pipeline (cycles/fan-in/out/scatter-gather) implemented and unit-tested

**Static/Dynamic GNN Baselines**
- [ ] E3a GCN complete, logged
- [ ] E3b GraphSAGE complete, logged
- [ ] E4 EvolveGCN complete, logged

**Proposed Model**
- [ ] E6 TGN trained and evaluated on AMLworld, logged
- [ ] E7 Ring aggregation algorithm implemented, evaluated with novel ring-metrics, logged
- [ ] E8 Explainability (attention reuse) implemented, fidelity/latency logged
- [ ] E9 Full hybrid cascade wired and evaluated end-to-end, logged

**Ablation**
- [ ] E10 no-rule-layer ablation complete
- [ ] E11 no-XGBoost-layer ablation complete
- [ ] E12 static-graph-instead-of-temporal ablation complete
- [ ] E13 no-ring-aggregation ablation complete
- [ ] `results/ablation_table.csv` compiled, all four hypotheses (§15) confirmed/refuted with numbers

**Explainability**
- [ ] Explanation fidelity metric implemented and measured
- [ ] Explanation latency measured against NFR01.2 (<2s)
- [ ] 20–30 example explanations saved for report Ch.4 qualitative discussion

**Evaluation**
- [ ] Ring-Precision/Recall/Member-Coverage/Time-to-Detection protocol documented in `docs/`
- [ ] All classification metrics (F1, AP, ROC-AUC) computed consistently across every baseline
- [ ] Computational-performance metrics (train time, inference latency, params, memory) recorded for every model

**FR/NFR Validation**
- [ ] Traceability matrix (§17) filled in with actual evidence file paths, not "TBD"
- [ ] NFR01.1/01.2/01.4 measured directly via E14
- [ ] NFR02.1 scale-test caveat resolved (footnote or HI-Medium/Large run)
- [ ] NFR02.2 (single-tenant) explicitly confirmed as design-only, not implemented

**System Integration**
- [ ] `pipeline/hybrid_cascade.py` runs end-to-end on a held-out AMLworld sample without manual intervention
- [ ] Minimal dashboard/UI built (non-research, Phase 11, low effort)
- [ ] Latency benchmark (E14) executed under simulated streaming load

**Documentation**
- [ ] `docs/EXPERIMENT_REGISTRY.md` kept current with every completed experiment
- [ ] `docs/RING_GROUND_TRUTH_DEFINITION.md` written before E7 begins
- [ ] Repository README explains how to reproduce every experiment from a clean checkout

**Research Paper / Report**
- [ ] Every number in Chapter 4 (Phase-2 update) traces to a file in `results/`
- [ ] Ablation table included with interpretation paragraph per row
- [ ] Contradictions C1–C3 resolution reflected in updated Ch.1/Ch.3 text
- [ ] Limitations section explicitly states what was scoped out (multi-tenancy, drift, full 7-entity schema) and why

---

## 23. Risks, Gaps & Decisions Required

**Contradictions in the current report that need resolution before Phase-2 work proceeds:**

- **C1 — Drift monitoring.** Abstract and §1.6 describe drift monitoring as a core pillar ("drift-monitoring module... triggers adaptive retraining"), but Ch.3's own capability table (Table 2.1, "RingShield (proposed)" row) self-rates Drift Robustness = **No**, and NFR is silent on any automatic drift trigger — FR07.2 is explicitly *administrator-triggered*, not drift-triggered. **Recommendation:** update Ch.1/Abstract language to "supports manually-triggered retraining; automatic drift detection is future work," matching what FR07 and Table 2.1 actually specify. Do not build drift detection as a system component (§5).
- **C2 — Multi-tenancy.** Title and Abstract describe RingShield as a "multi-tenant SaaS," but NFR02.2 explicitly scopes the *project* to single-tenant, with multi-tenancy as future work, and Table 2.1 rates Multi-Tenancy = **No** for the proposed system as currently specified. **Recommendation:** keep the multi-tenant *architecture* as a design-only discussion (Ch.4) but do not implement tenant isolation, per-tenant auth, or cross-tenant anything in Phase-2 code.
- **C3 — Explainability method.** Ch.2.4/2.10 (G3) frames the field's explainability gap in terms of GNNExplainer/PGExplainer/TempME-style dedicated explainer modules, and Ch.4's own methodology figure (Fig 4.1, "Hybrid Detection Stack... Explainability Module") could be read as implying one of these. But Sub-system 4 (§4.1.2) is explicit: **reuse TGN/TGAT attention weights directly, no separate backward pass, no dedicated explainer network.** This is the correct, right-sized choice (matches NFR01.2's 2-second budget) — **recommendation: state this explicitly and prominently in Ch.2.11/Ch.5 so a reviewer doesn't expect a TempME-style implementation you deliberately did not build.**

**Decisions needed before specific phases can start:**

- **D1 (blocks Phase 7 / E7) — Ring ground-truth extraction.** AMLworld provides transaction-level laundering-pattern labels (Fan-In, Fan-Out, Cycle, Scatter-Gather), but the exact algorithm for converting these into a discrete list of "ground-truth rings" (each with a member-account set and a time window) is not specified anywhere in the report or the dataset paper excerpts you have. **INSUFFICIENT INFORMATION — NEEDS DECISION.** Recommended approach: for each documented pattern instance in the dataset's metadata, take the connected component of accounts participating in that specific pattern instance within its documented time window as one ground-truth ring; write this as `docs/RING_GROUND_TRUTH_DEFINITION.md` and have all 3 team members review it before E7 begins, since E5b, E7, and E13 all depend on using the *same* definition.
- **D2 (blocks Phase 7) — Ring aggregation algorithm choice.** The report specifies *that* ring records must be produced (FR04.5) but not *how* escalated candidates become a ring. Recommended starting point (cheap, explainable, defensible as a first pass): connected-components over the escalated-candidate subgraph, using edges weighted by TGN attention score, with a minimum-edge-weight threshold as a tunable hyperparameter (consistent with FR04.6's "minimum candidate edge density: default 0.4"). Treat more sophisticated community-detection (e.g., Louvain) as a stretch/ablation variant, not the baseline design.
- **D3 (affects NFR02.1 validation) — Scale testing.** AMLworld HI-Small is smaller than the 1M-node/5M-edge scale NFR02.1 references. **INSUFFICIENT INFORMATION — NEEDS DECISION:** either (a) run one scale-focused experiment on HI-Medium/HI-Large with sampling to fit reference hardware, or (b) explicitly footnote NFR02.1 as "validated at HI-Small scale; full-scale validation is Phase-2 stretch/future work" in the report. Given the T4 GPU reference hardware in §3.3, option (b) is the realistic default — confirm with your guide.
- **D4 (affects E16, optional) — IEEE-CIS graph construction method.** If the team decides to pursue the optional generalization check (E16), the exact k-NN graph-construction hyperparameters (k, distance metric, feature subset) used in paper #10 are only partially specified in your literature survey extract. Decide and document before running E16, or drop E16 entirely (it is optional).

**Other risks to actively manage:**
- **Overfitting to AMLworld's synthetic pattern generator.** Because Fan-In/Fan-Out/Cycle/Scatter-Gather are algorithmically generated, a ring-aggregation method could overfit to the generator's specific topology quirks rather than learning generalizable ring structure. Mitigate by holding out one pattern *type* (e.g., train without Scatter-Gather examples, test ring-recall specifically on Scatter-Gather) as a generalization stress-test — a good addition to Phase 9 if time allows.
- **Hyperparameter tuning on the test set.** All threshold tuning (FR04.6 defaults: min ring size 3, min confidence 0.7, min edge density 0.4) must be tuned on a held-out **validation** split carved from the training period, never on the chronological test period — add an explicit validation slice (e.g., last 15% of the training-period timestamps) to the split manifest now, before Phase 6.
- **Random-seed inconsistency across team members.** Enforce `seed=42` via a shared `configs/seed.yaml` imported by every training script — do not let each person hardcode their own seed.
