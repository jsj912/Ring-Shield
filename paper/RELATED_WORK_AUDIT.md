# Related-work audit (T-P6, 2026-11-14)

How verified: full texts read via arXiv HTML, publisher HTML, or PDFs converted locally with
`pdftotext` (IJCAI paper and TAML supplement, Wang & Cao, FraudGT, Tian, Tariq–Kaja–Hassani).
Quotes are kept under 15 words. "n.v." = could not be verified; it is never filled from memory.

## 1. Characterising sentences in `paper/sections/related.tex`

| # | Sentence (short) | Paper | Where verified | Evidence |
|---|---|---|---|---|
| 1 | AMLworld: synthetic, labels on transactions, temporal 60/20/20 split | Altman et al. 2023 | arXiv 2306.16424 §3.4, §4 (§4 read via summary) | "60-20-20 temporal train-validation-test split"; laundering tag "transitive" on transfers (§3.4, verbatim) |
| 2 | Detectors compared by minority-class F1 per transaction | Egressy 2024; Altman 2023 | Egressy §6 "Scoring" | "we use the minority class F1 score" |
| 3 | Multi-GNN adapts message passing to directed multigraphs | Egressy et al. 2024 | arXiv 2306.11586 title/abstract and §3 | title; abstract "directed multigraphs" |
| 4 | GFP feeds streaming subgraph-pattern features to boosted trees | Blanuša et al. 2024 | arXiv 2402.08593 abstract, §3 | title "Real-time Subgraph-based Feature Extraction"; GFP+XGBoost rows |
| 5 | FraudGT is a graph transformer | Lin et al. 2024 | FraudGT PDF (jshun.csail.mit.edu), title, §1, Tables 1–3 (re-read 2026-11-15 with `pdftotext -raw`) | title; **HI-Small ("AML Small-HI") vanilla FraudGT 69.68 ± 1.58** (Table 2; repeated in Table 3 and §4.2.1: "average F1 score of 69.68%"). **Correction:** the earlier 68.19 ± 2.03 is the Multi-PNA row of Table 2, misread because `pdftotext -layout` shifts the labels one row down in that table. |
| 6 | MEGA-GNN adds two-stage multi-edge aggregation | Bilgi & Atasu (TMLR 2026) | arXiv 2412.00241v3 App. C.5 | MEGA-GIN / MEGA-GenAgg defined with aggregation "in both stages" |
| 7 | ExSTraQt: highest HI-Small F1 we found, trees on quasi-temporal features | Tariq & Hassani 2026 | arXiv 2604.02899 Table 2 | 78.90 ± 0.23 (GFP splits), 80.89 ± 0.32 (FraudGT splits) |
| 8 | HI-Small F1 for these detectors runs from 0.57 (Multi-GIN) to 0.81 (ExSTraQt, FraudGT split ratios), slightly different splits | Egressy Table 2; FraudGT Table 2; MEGA Table 16; SALT-GNN Table 2; ExSTraQt Table 2 | verbatim, 2026-11-15 | Egressy T2: Multi-GIN 57.15 ± 4.99, Multi-GIN+EU 64.79 ± 1.22, Multi-PNA+EU 68.16 ± 2.65, XGBoost+GFs 63.23 ± 0.17. FraudGT T2: FraudGT 69.68 ± 1.58, PE-FraudGT 76.41 ± 1.45. MEGA T16: MEGA-GIN 70.83 ± 2.19. SALT-GNN T2: SALT-Trans 0.716 ± 0.018. ExSTraQt T2: 80.89 ± 0.32. Splits: 60/20/20 temporal (Egressy, ExSTraQt GFP splits); 64/19/17 temporal (FraudGT T1, MEGA T13); SALT-GNN "strictly temporal", ratio not stated in the main text. **Correction:** the earlier low end, "Multi-GIN 61.06 (FraudGT T2)", is PNA's row (same row-shift misread); FraudGT T2 has Multi-GIN at 47.42 ± 2.93, its own rerun. The old "about 0.61–0.81" sentence did not hold and was rewritten in related.tex. |
| 8a | FraudGT numbers: which configuration, split and table | FraudGT; ExSTraQt; SALT-GNN | verbatim | (i) **69.68 ± 1.58**: vanilla FraudGT, FraudGT Table 2 (and Table 3), 64/19/17 temporal split (FraudGT Table 1), 5 seeds, best-validation checkpoint. (ii) **76.41 ± 1.45**: PE-FraudGT = FraudGT + port numbering + ego IDs, FraudGT Table 2, same split. ExSTraQt Table 2 row "FraudGT (Best) [19]" takes the best FraudGT variant per column: HI-Small 76.41 is PE-FraudGT, while HI-Medium 75.93 and HI-Large 73.34 are Multi-FraudGT (+RMP+Ports+Ego ID) in FraudGT T2. So "FraudGT (Best)" is not one configuration. (iii) **0.679 ± 0.018**: SALT-GNN's own rerun, SALT-GNN Table 2 "overall" column (5 seeds, their strictly temporal split, best-validation-F1 configuration from prior work). Which FraudGT variant they ran is not named in Table 2; the "182k" parameter count is in Table 3/§ efficiency. (iv) **68.19 ± 2.03** (our old audit): not a FraudGT number (Multi-PNA). Paper rule: a FraudGT number is quoted only with its configuration named. |
| 8b | SALT-GNN HI-Small overall F1 | Losavio et al. 2026 | arXiv 2607.10131v1 (11 Jul 2026) Table 2, verbatim | SALT-Trans **0.716 ± 0.018**, SALT-GAT **0.694 ± 0.007** ("HI-Small F1 by recipient degree (mean ± std, 5 seeds)", column "overall"). Also in Table 6 (SALT-Trans full 0.716 ± 0.018) and Table 8 (SALT-GAT vs FraudGT overall F1 0.694 vs 0.679). Verified; cited in the edge-level paragraph. Code: the paper says "We release code to reproduce the stratified protocol, baselines, and ablations", but v1 gives no URL (the only github link is IBM/AMLSim). Recorded as not released. |
| 8c | ExSTraQt: scope of communities, flow features and anomaly scores | Tariq & Hassani; github.com/mhaseebtariq/exstraqt at dd1586244a572565802d816e522c3ca75ddb6b10 | ibm/features.py, ibm/communities.py, ibm/common.py, ibm/2_model.ipynb, ibm/node_level_features.ipynb, ibm/1_prepare_input_small.ipynb, read 2026-11-15 | **Expanding windows, not training-only and not whole-graph-at-once.** 2_model splits transactions by sorted id 60/20/20 (env-configurable) and runs node_level_features three times: on `train`; on `train ∪ validation` (for validation features); on `train ∪ validation ∪ test` (for test features). Each run recomputes from that data: Leiden communities (leidenalg, modularity, amount-weighted), 2-hop personalised-PageRank communities (communities.py `get_top_n`, damping 0.95, undirected, threshold on rank/max), temporal flow features (dispense→passthrough→sink joins with `left.ts ≤ right.ts`), and edge/node aggregates. **Test-period features therefore use all test-period transactions, including those after the edge being scored** (label-free, transductive within the period). **Fitted objects are training-only:** `get_or_fit_object` pickles the scalers, PCA and IsolationForest(n_estimators=1000) on the first (train) run and reloads them for validation and test, so anomaly *models* are fit on train and anomaly *scores* are computed on the expanding data. Running balances in prepare-input are cumulative sums in timestamp order (causal). `is_laundering` does not enter these feature notebooks (grep). No licence file (GitHub API `license: null`): nothing copied into this repository. |
| 9 | All evaluated per transaction | rows 1–7 | each paper's metric section | minority-class F1 throughout; no group metric in any |
| 10 | Chai: proposes the laundering sub-network behind a transaction; private AliPay data | Chai et al. 2023 | AAAI article page (abstract) only; PDF blocked (anti-bot, also in browser) | "discover money laundering sub-network behind a particular money laundering transaction"; "real-word datasets in AliPay". **Full text n.v.** — only the abstract-level facts are used; table cells for ground truth / metric / split are n.v. |
| 11 | Rico: joint classification + sub-network discovery; unit = sub-network around target account; node-wise P/R; no matching | Rico et al. 2026 | IJCAI-26 proceedings §3, §4.2, §5.1 Metrics; code `utils/evaluation_utils.py` | P_v = \|Ĝ∩G\|/\|Ĝ\|, R_v = \|Ĝ∩G\|/\|G\| per target node (§5.1) |
| 12 | Tian: collaborative group mining; account-level metrics on AMLworld | Tian et al. 2025 | arXiv 2502.19952 §4, §5.1–5.3, Table 1 | AMLWorld_HI / _LI; ACC/P/R/F1/AUC; Sim-CSGM HI F1 0.7995 |
| 13 | Tariq–Kaja–Hassani: turnover-weighted recall over injected patterns of large IBM releases | Tariq, Kaja, Hassani 2026 | arXiv 2604.01315 §III, §V-A1, Alg. 2 | "F^r are the injected patterns"; context-weighted recall; "large versions"; applied to HI only |
| 14 | Wang & Cao: group from analyst's clue on HI-Small/HI-Medium; groups = connected components of laundering accounts | Wang & Cao 2026 | arXiv 2606.26189 PDF (pdftotext), "Datasets" and Q2 paragraphs | "identify each connected component within that subgraph as a distinct money laundering group"; AUC, AP; recall of LIC |
| 15 | GARG-AML: smurfing account scores on HI-Small, account labels from transaction labels; FlowScope as baseline | Deprez et al. 2025 | arXiv 2506.04292v4 §4.1.2, §4.2, Table 12 | "labels … provided at the edge level"; node positive above a cut-off share; FlowScope rows in Table 12 |
| 16 | Elliptic2: labelled subgraphs, subgraph classification, random split | Bellei et al. 2024 | arXiv 2404.19109v3 §2, §3.2, §4 | "binary classification of suspicious subgraphs"; "random 80:10:10 split" |
| 17 | RevTrack on Elliptic2, same random split | Song et al. 2024 | arXiv 2410.08394 §4–§6 | "randomly (80:10:10)"; Elliptic2 only |
| 18 | None of the papers states how a group crossing the evaluation window is scored | rows 10–17 | each paper's evaluation section | "not stated" in every full-text read; Chai n.v. (full text unavailable) |
| 19 | Tail noted by practitioners (footnote, Kluey repo) | github.com/Kluey/AML-Transaction-Detection | README | "last ~8 days (Sept 11-18) … 56-73% laundering rate"; restricts to Sept 1–10 |
| 20 | TAML's released code keeps only the first ten days of HI-Small | Rico et al. 2026 (code) | `dataset_scripts/build_ibm_graph_dataset.py` | keeps transactions with day ≤ 10; test = days 9–10. The paper text does not state this. |
| 21 | No published quantification of the tail effect, cross-release reproduction, or ring/seed-budget consequence | searches (§3 below) | — | none found in peer-reviewed or arXiv work |

## 2. `paper/tables/related_comparison.tex` — cells that are n.v. or code-derived

- Chai et al. 2023: ground truth, metric/matching, split, scope rule — **n.v.** (PDF unobtainable; AAAI blocks automated and in-app-browser access). Recorded as n.v. in the table.
- Rico et al. 2026: ground truth "code: 2-hop ball within one day", split "code: days 1–6 / 7–8 / 9–10", tail "code: days > 10 dropped" are from the released code, labelled "code" in the table. The paper says 70/15/15 temporal; the supplement does not describe the ground-truth construction.
- Wang & Cao 2026: split "not stated" in the text read (PDF converted with pdftotext; layout-mangled two-column text — a careful re-read of the experimental setup is advised before submission).

## 3. Search for prior statements (runbook T-P6 step 3)

| Topic | Found | Verdict |
|---|---|---|
| (a) Laundering base-rate jump in the last test days | Practitioner repos only: Kluey/AML-Transaction-Detection (56–73 % from 11 Sept); hecmeynell-debug/aml-project ("Licit activity almost stops after 10 September"; 58–73 %). No peer-reviewed or arXiv statement. TAML code drops days > 10 without comment. | Not published. Footnote stands; consider adding the second repo to the footnote. |
| (b) Day-0 volume burst | nothing found | not published |
| (c) Scope-convention sensitivity of group-level scores | GARG-AML studies Louvain pre-partitioning and a "limited transaction view" on **account** scores (§5.3, App. D) — not group scores. Gr-GAD (arXiv 2308.01063) penalises missing/redundant members, no AMLworld. | not published for group scores |
| (d) Edge-level vs group-level metrics disagreeing | Malik, arXiv 2604.23494: transaction- vs actor-level review queues diverge on **Elliptic++** (Jaccard@K 0.051), not AMLworld, no groups, no detector swap. | Closest prior work; does not make our claim. **Cited** (2026-11-14, author round 3) in related.tex §Group-level as `malik2026queues`; sentence states only: transaction- vs actor-level queues overlap only partly at equal budget (mean Jaccard 0.374, 1 % budget, temporal); Elliptic++ Bitcoin data; random forests; unit is the actor address, not a group; no rings, no AMLworld (all from the arXiv abstract page, v1). |
| Count of unobservable targets | nothing found | not published |

Other papers read in the sweep (edge-level, no group evaluation, no artefact statement):
SALT-GNN (arXiv 2607.10131; HI-Small, HI-Medium), TransXion (KDD 2026, arXiv 2604.17420),
BlazingAML (arXiv 2604.12241), AMLworld-Compact (arXiv 2610.13627, dataset card only).

## 4. Facts in the runbook / repository that the papers contradict

- **MEGA-GenAgg HI-Small F1 is 74.48 ± 0.84** (arXiv 2412.00241v3, Table 16), not 74.88 ± 0.38 as recorded in `docs/FUTURE_IMPLEMENTATIONS.md` F4. MEGA-GIN is 70.83 ± 2.19 (repository: 0.7083 ± 0.0218 — rounding only).
- MEGA-GNN's latest version is titled "MEGA: Message Passing Neural Networks for Multigraphs with EdGe Attributes", has **two authors** (Bilgi, Atasu — no Chen), and is accepted at **TMLR 2026**. Published AML batch size 8192, 2 hops × 100 neighbours (App. C.3, Table 11).
- Rico et al.: paper says 70/15/15 temporal split; code uses days 1–6/7–8/9–10. Paper says test accounts were "deleted" from train/val; code assigns overlapping rows at random. Account features are aggregated over all ten days (a temporal leak in their code, not mentioned in the paper). These matter for T-P9.
- Tian et al. use AMLWorld HI and LI (not named HI-Small); thresholds τ = 0.3 on AMLworld.
- Tariq–Kaja–Hassani do not use HI-Small at all (large IBM releases and Libra).
- Egressy et al.: HI-Small Multi-GIN+EU 64.79 ± 1.22 is from a model summary of Table 2, **n.v. verbatim**.

## 5. Bibliography — source of each entry

| Key | Verified fields and source | Not verified |
|---|---|---|
| altman2023 | authors (arXiv header); NeurIPS 36 pages 29851–29874, DOI 10.52202/075280-1300 (Crossref) | — |
| egressy2024 | all fields (Crossref DOI record) | — |
| blanusa2024 | all fields (Crossref DOI record) | — |
| lin2024fraudgt | authors, venue, DOI (MIT DSpace; PDF header "9 pages") | page range 292–300 (Crossref 429; consistent with 9 pages) |
| bilgi2024 | title, two authors, TMLR 2026 (arXiv 2412.00241v3 abs/HTML) | TMLR volume/number |
| tariq2026exstraqt | authors, related DOI (arXiv abs) | venue name "SAC 2026" (not on arXiv page; Crossref 429) |
| chai2023 | all fields (Crossref DOI record + AAAI page) | — |
| rico2026 | authors, venue, pages, DOI (IJCAI proceedings page) | — |
| tian2025 | authors (arXiv), venue WWW '25 and DOI (arXiv HTML header) | page range (ACM 403, Crossref 429) |
| tariq2026redirect | title, authors, arXiv id (arXiv HTML) | venue (none stated) |
| deprez2025garg | title, authors, arXiv id (arXiv HTML v4) | venue (none stated) |
| wang2026clue | title, authors, arXiv id (arXiv abs; second author also on ResearchGate) | venue (none stated) |
| li2020flowscope | authors, title, venue, vol/num/pages, DOI carried from the repository; DOI resolves to AAAI 34(04) | not re-checked field by field (Crossref 429; AAAI blocks fetches) |
| bellei2024 | authors, KDD MLF '24 (arXiv HTML header) | — |
| song2024revtrack | authors, ICAIF '24, DOI 10.1145/3677052.3698635 (arXiv HTML header) | pages |
| khosla2020 | full author list (arXiv 2004.11362) | NeurIPS 33 venue not shown on arXiv page |
| ke2017, holm1979, lundberg2017, lundberg2020, fleiss1971, landis1977 | carried from the repository (standard references; not characterised in the text beyond naming the tool) | not re-checked this session |

Removed: `weber2019` (no longer cited after the rewrite). Entries count: 22, all cited. The
runbook's target of about 35 is not reached because the rule "none uncited" wins; Louvain,
Leiden, XGBoost and LAS-GNN records are verified (Crossref) and ready to add when T-P3/T-P5
cite them:
- Traag, Waltman, van Eck, Sci. Rep. 9:5233 (2019), DOI 10.1038/s41598-019-41695-z.
- Chen & Guestrin, KDD '16, pp. 785–794, DOI 10.1145/2939672.2939785.
- Verlaan, Hulpuș, van Leeuwen, ICAIF '25, pp. 256–264, DOI 10.1145/3768292.3770410 (content n.v.: ACM 403).
- Blondel et al., J. Stat. Mech. P10008 (2008), DOI 10.1088/1742-5468/2008/10/P10008 (from Traag's Crossref reference list; record itself n.v.).
- DenseFlow (WWW 2024) and Diga (KDD 2023): DOIs **n.v.**; not cited.
- SALT-GNN: Losavio, Sovrano, Fenoglio, Gjoreski, Langheinrich, arXiv 2607.10131 (verified).

## 6. Accessibility

Group-level papers (§8.3 A, 12 items): read in full — Rico (+supplement, code), Tian, Tariq–Kaja–Hassani,
Bellei, Song (RevTrack), Deprez (GARG-AML), Wang & Cao. Partly — Chai (abstract page only).
Not read — FlowScope (AAAI blocks; not characterised beyond "used as a baseline by GARG-AML"),
DenseFlow and Diga (not characterised; not cited), SMURF thesis (not cited).
Edge-level (§8.3 B): Altman, Egressy, Blanuša, FraudGT, MEGA, ExSTraQt, SALT-GNN read; LAS-GNN n.v. (ACM 403; not cited).
Inaccessible share of papers we characterise: 1 of 17 partly (Chai) — under the one-third limit.
