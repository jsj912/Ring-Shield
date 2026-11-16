# RingShield — senior-reviewer assessment (2026-11-13)

Reviewed against the current draft in `paper_draft/latex/` (base commit `aa4d233`).
Literature searched on the web today; anything I could not confirm is marked **[unverified]**.

**One-line verdict.** As a method paper this is a reject at KDD/NeurIPS: the method's one
robust gain is matched by a two-line rule. As an evaluation-and-benchmark paper it is a
plausible accept, *if* you fix the related work (your "not aware of prior work" sentence is
now wrong), add one external baseline family, and confirm the artefacts on a second release.

---

## 1. Novelty check

| Work | What it does | Data | Metric | Relation to your claims |
|---|---|---|---|---|
| **Chai et al., AAAI 2023** (AMAP) | Neural sub-network proposer + contrastive loss; first deep "ML sub-network discovery" | Private Alipay | Transaction detection + sub-network discovery | **Overlaps the task.** Not on AMLworld, not reproducible. Must be cited as the origin of the learned sub-network framing. |
| **Rico et al., IJCAI 2026** (TAML) | Joint account classification + sub-network discovery in one latent space; BFS over learned translations in a K-hop ego-net | **AMLworld HI-Small**, Elliptic++, SAML-D | Node-wise precision/recall of the predicted sub-network around each account; AUPRC/AUROC | **Directly contradicts "not aware of prior work".** Sub-network discovery on HI-Small exists, with baselines AMAP, Diga, DenseFlow. But the unit is an ego sub-network per account, not a laundering attempt matched one-to-one, and it uses a 70/15/15 temporal split with no stated tail/scope treatment. How its ground truth is built from the pattern file is in its supplement **[unverified]**. |
| **Tian et al., WWW 2025** (CSGM) | Privacy-preserving collaborative scatter-gather mining across banks; finds laundering groups | AMLworld HI (+ synthetic) | Group-level detection | **Overlaps, and you already ran it**: `r4_partition.csv` has a `b5` CSGM row (ring-F1 0.122, recall 0.069, 1 seed). The draft omits it. That is your external ring-level baseline, sitting unused. |
| **SMURF** (TU Delft thesis) | Multi-party extension of CSGM | AMLworld HI-Small | F1 82.44 % (its own group definition) **[unverified metric definition]** | Shows group-level numbers on HI-Small are being published under incompatible definitions — evidence *for* your comparability argument. |
| **FlowScope, AAAI 2020** (Li, Liu, Li, Han, Shi, Hooi, Huang, Cheng) | Dense multipartite flow subgraphs, unsupervised | Real bank data + injected | Detection of injected groups | Classic unsupervised group baseline. Not on AMLworld. A reviewer will ask for it or a descendant (DenseFlow). |
| **Elliptic2, Bellei et al. 2024**; **RevTrack/RevClassify** (arXiv 2410.08394) | Subgraph *classification* (given subgraphs) and discovery (RevFilter) | Elliptic2, 122K labelled subgraphs | Subgraph classification PR-AUC/F1 | Adjacent. Subgraphs are given, not recovered from edge scores; no temporal split issue. Cite as the real-data counterpart; no contradiction. |
| **Tariq, Kaja, Hassani 2026** (ReDiRect, arXiv 2604.01315) | Fuzzy partitioning + "refined evaluation metric" for exposed laundering patterns | Libra + IBM synthetic | Its own pattern-level metric | **Overlaps your protocol contribution.** Someone else has proposed a pattern-level metric on IBM data this year. You must compare definitions. |
| **ExSTraQt** (Tariq & Hassani, SAC 2026) | XGBoost on quasi-temporal graph features | IBM AML HI/LI, Ethereum | Minority F1 (≈ 80.9 on HI-Small **[unverified]**) | Edge-level only. Relevant to C6: if a tree model reaches ~0.81 edge F1, your 0.596 detector looks weak and "edge F1 buys no rings" needs testing at that level. |
| **FraudGT, ICAIF 2024** | Graph transformer, edge gates + attention bias | AMLworld | Minority F1 (+7.8–17.8 % over prior) | Edge-level only. The stronger detector a reviewer will name. |
| **MEGA-GNN** (Bilgi, Chen, Atasu; arXiv 2412.00241) | Two-stage multi-edge aggregation | AMLworld | Minority F1 | Already your swap. Fix the author list; venue beyond arXiv **[unverified]**. |
| **SALT-GNN** (arXiv 2607.10131 **[unverified id]**) | Statistics-aware attention; recipient-degree-stratified evaluation | HI-Small, HI-Medium, AMLSim | Stratified F1 | Edge-level. Its stratified evaluation is a precedent for "one number hides structure" — cite as kindred. |
| **Practitioner repos** (e.g. Kluey/AML-Transaction-Detection) | Note the last ~8 days sit at 56–73 % laundering and inflate PR-AUC ~40 % | HI-Small | — | **Your tail finding is known informally.** I found no peer-reviewed statement of it. Say "observed informally by practitioners; we quantify it, reproduce it across releases and measure its ring-level and budget consequences." |

### Verdict per contribution

| Contribution | Status | Why |
|---|---|---|
| Ring recovery as a task on AMLworld | **Already done** (TAML, CSGM) | Rewrite the claim: you are first to score *attempt-level* recovery with one-to-one matching, a stated scope rule and intervals — not first to do group-level AML on HI-Small. |
| Scope convention worth 0.35–0.38 ring-F1; component scope; 44 % unobservable | **Novel** | Nobody states the scope rule. Strongest single result. TAML and SMURF numbers become evidence that the field needs it. |
| Test tail, quantified, across HI/LI, with budget consequence (463 of 864 seeds) | **Novel as a formal result**, known informally | The seed-budget consequence and cross-release reproduction are new. |
| Day-0 warm-up; quantile budget capture (87.5 % on HI-Medium day 15) | **Novel** | No prior found. |
| Edge F1 is not a proxy for ring recovery | **Novel but conditional** | Holds at one budget, two GNNs, one dataset. Needs a third, stronger detector. |
| In-window disconnection (81.5 %; STACK 100 %) | **Novel** | Explains why any windowed group metric on this split has a hidden ceiling. |
| Precision-blindness of matched-ring tests + paired unit bootstrap | **Incremental** | Useful, standard statistics applied carefully. |
| Expansion policy | **Incremental / weak** | Rule matches recall; purity gain is real (p 0.0008) but the test was post hoc. |
| Partition, typing, L4, platform | **Not contributions** | Null, modest, unvalidated, engineering. |

---

## 2. Positioning

**What it is:** an evaluation-methodology and benchmark-audit paper with a reference pipeline
and honest negative results. Not a method paper. Every strong result is about measurement.

**Title.** *Rings, Not Edges: What AMLworld Can and Cannot Tell Us About Recovering
Money-Laundering Attempts*

**Abstract (rewrite, ~170 words).**
> Money-laundering detection on AMLworld is reported as per-transaction F1, while group-level
> results are appearing under incompatible definitions. We audit what the benchmark supports
> when the unit is the laundering attempt. We define attempt-level recovery with one-to-one
> matching, an explicit scope rule and bootstrap intervals, and show that three unstated
> choices dominate reported numbers: the day split's tail (40.7 % of test positives in 0.13 %
> of edges) inflates edge metrics and absorbs half of a global seed budget; the scope
> convention moves ring-F1 by 0.35–0.38, five times our method's effect; and 44 % of in-scope
> rings have no connected in-window piece any method could match. With a reference pipeline
> (causal GNN, seed expansion, partition) we find that a 9.4-point edge-F1 gain buys no rings
> at a fixed budget, that expansion recovers undetected members (0.5 % → 21 %) but a two-line
> rule matches its recall, and that partitioning is a null. We release the protocol, tables
> and code, and recommend reporting rules for ring-level AML.

**Contributions (rewrite).**
1. An attempt-level evaluation protocol for AMLworld: scope rule, matching with threshold
   sweep, windows, validation-only selection, ring-level intervals and a precision-aware
   paired test.
2. A benchmark audit: tail, day-0 warm-up, budget capture, scope sensitivity, in-window
   disconnection — reproduced on HI-Small, LI-Small and (where run) HI-Medium.
3. A reference pipeline and a decomposition of where ring recovery is lost, including
   negative results reported against our own method.
4. Reporting recommendations (a checklist box) for group-level AML.

**Venues** (deadlines not confirmed from official calls; check before planning):

| Venue | Deadline | Fit |
|---|---|---|
| **KDD 2027 Datasets & Benchmarks, cycle 2** | expected Feb 2027 **[unverified]** (cycle 1 was 26 Jul 2026) | Best fit. Audits of popular benchmarks are in scope; 12 weeks is enough for the experiments below. |
| **NeurIPS 2027 Datasets & Benchmarks** | historically May–June **[unverified]** | AMLworld was published there, so a rigorous audit of it is on-topic. Needs the second dataset and a released evaluation package. |
| **ICAIF 2027** | historically late July/Aug **[unverified]** | Friendliest audience (FraudGT, GFP, LAS-GNN published there); lower bar on generality, practitioners value the platform. |
| Fallback: **TMLR** | rolling | Rewards correctness and negative results; no novelty bar. Good if cycle 2 fails. |

PAKDD 2027 (20 Nov 2026) is too soon to do this properly.

---

## 3. Experiments that would most change a reviewer's mind

| # | Run | Why a reviewer asks | A5000 effort | Strengthens if… | Hurts if… |
|---|---|---|---|---|---|
| 1 | **External ring baselines under your protocol**: report the existing CSGM row (5 seeds), add Louvain/Leiden on top-k flagged edges, and TAML's BFS extractor (code public) or DenseFlow | "No external baseline" is the first objection; you already have one row | CSGM 5 seeds ≈ 3 h; Leiden ≈ 1 h; TAML ≈ 15–25 h | They score well below B1b/full, and their rank changes with scope rule (proves the protocol point) | TAML beats your pipeline — still publishable as an audit, but drop method claims |
| 2 | **Finish HI-Medium close-out** (already registered, #7) and present it as the second dataset | "One dataset" | detector exists; ≈ 10–15 h | Tail, scope gap and budget capture reproduce | Method ordering flips — report it; audit claims survive |
| 3 | **Stronger detector for the C6 claim**: FraudGT (public code) under your causal sampler, B0 + full | "0.596 is a weak detector; of course it doesn't matter" | ≈ 20–30 h for 3–5 seeds | Ring-F1 flat at +15 edge points → C6 becomes the headline | Ring-F1 rises clearly → C6 becomes "plateau between 0.60 and 0.69 only" |
| 4 | **Ring-folded cross-scores** (#8, registered, code ready) | Any leak in a paper about leaks is fatal | ≈ 8 h | \|Δ\| ≤ 0.008: closes B17 as a measurement | Larger: disclose, re-ship; cheap either way |
| 5 | **Budget sweep with all detectors** at 0.05/0.1/0.15/0.2 % in-window | C6 and C7 are single-budget claims | ≈ 4 h (scores exist) | Curves coincide across detectors | They separate at larger budgets — narrows the claim |
| 6 | **Re-score a published group-level number under both scope rules** (TAML or SMURF outputs) | Shows the protocol matters for *others'* results | ≈ 6–10 h | Their ranking or headline moves materially | Robust — then say so |
| 7 | **AMLGenteX or Tide** as a non-IBM generator | External validity of artefacts | 20–40 h, uncertain labels for attempts | Artefacts absent → "IBM-generator specific", still useful | — (low risk, high cost; do only for NeurIPS) |
| 8 | **External analyst study** (drafted) | Only matters if L4 stays in the paper | weeks, people-bound | — | — **Recommendation: cut L4 from this paper instead.** |

---

## 4. Method improvements

| Idea | Targets | Realistic? |
|---|---|---|
| **Make the rule the method.** Ship B1b + a learned *precision filter* and frame the policy as a purity re-ranker with a tested gain (+0.408, p 0.0008). | "Rule matches policy" | **Days.** A framing change; no new training. |
| **Account-level ring-membership model**: score accounts (not candidate edges) for membership in a seed's ring using aggregated flow features; removes the endpoint-adjacency requirement | BIPARTITE (0 of 51 quiet edges adjacent), hub noise | **3–4 weeks**, plausible. Risk: precision collapse without adjacency. |
| **Per-day budget with a per-day validation-chosen cut** (not the same quantile per day) | Budget capture, half-budget window | **1 week.** Your own row shows naive per-day loses precision; needs a per-day floor on score, chosen on val. |
| **Two-stage budget**: global seeds, then a second, lower cut only inside the 1-hop neighbourhood of existing rings | Unreached rings without the purity loss of a flat larger budget | **1–2 weeks.** Cheap to test with existing scores. |
| **Cross-window linking by non-path signals** (shared counterparties over history, amount fingerprints, bank/currency routing) | STACK disconnection | **Research bet.** Your own B16 (0 of 140 at 2–3 hops) and the ring-identity head (AUC 0.62 vs 0.75 bar) say the generator may not encode it. Do not promise this. |
| **End-to-end ring-identity fine-tuning** of the detector | Same | **Research bet**, ≥ 3 GPU-h/seed, weak prior from the frozen-head result. |
| **Change the question for STACK**: evaluate split-severed patterns under the component convention and say so | Unmatchable targets | **Days.** This is an evaluation fix, and it is the honest one. |

Blunt advice: spend the four weeks on Section 3, not here. No method fix on this list moves
the paper's acceptance odds as much as experiments 1–3.

---

## 5. Writing and presentation

**Cut or translate**
- All internal codes in prose: B7/B9/B13/B17, C1–C11, R6/R10/R11/R12b, E7, "V3.2b",
  "Step 6 amendment b", "11b/11c". Keep them only in `% source` comments.
- Lab-log voice: "corrected 2026-10-26", "retracted", "found by Ruhani", "registered and
  closed the same day". One short "Corrections" appendix paragraph is enough. A reviewer reads
  a paper with four retractions in the body as unstable.
- The `[CITATION NEEDED]` marker and the "Affiliation" placeholder.
- L4 numbers and the R10/R11/R12 material from the body. They violate your own FINDINGS scope
  rule and dilute the paper. Platform → 5 lines + 1 screenshot in the appendix, or a demo paper.
- Typing section → 3 sentences.

**Move to appendix:** robustness table, windows table, per-pattern table, held-out BIPARTITE
arms (keep CYCLE in one paragraph), reallocation detail, R12b, B17 detail (keep 4 lines + bound
in the body).

**Missing figures (the paper currently has no figure that carries an argument)**
1. Per-day base rate and volume, HI vs LI (the tail and day 0 in one picture). Figure 1.
2. Edge F1 vs ring-F1 scatter for all detectors × seeds — the flat line is the paper.
3. Scope-convention bar chart: three conventions × methods.
4. Waterfall of the 174 rings: matched / <3 visible / untouched / over-merged / under-covered,
   with the "no matchable piece" overlay.
5. One drawn example of a STACK ring severed by the split.

**References:** 11 entries is far too few; target 35–45. Add TAML, AMAP, CSGM, SMURF,
DenseFlow, Diga, ReDiRect, ExSTraQt, FraudGT, SALT-GNN, LAS-GNN, Elliptic++, Elliptic2/RevTrack,
SAML-D, Tide, AMLSim, GARG-AML, plus Holm (1979), bootstrap (Efron), SupCon (Khosla 2020),
LightGBM, isotonic calibration. Fix `bilgi2024` (Bilgi, Chen, Atasu) and `li2020flowscope`
(eight authors, listed above).

**Section order:** Intro → Related → Protocol → **Benchmark audit** → Reference pipeline (1.5
pages) → Results → Where recovery stops → Recommendations box → Limitations.

**Authorship.** If L4 and the platform are cut to an appendix mention, sole authorship with
acknowledgements is defensible but thin: the typing bug was found by Ruhani and corrected a
reported number, which is an intellectual contribution to a result in the paper. Under ACM and
ICMJE-style criteria that plus drafting/approval would qualify. Recommendation: offer
co-authorship to Ruhani (and to Kashish only if R10/platform results stay in the body), with a
contribution statement; also confirm with your supervisor, who is conspicuously absent. Settle
this before submission — authorship disputes after acceptance are far worse.

---

## 6. Reviewer simulation

**R1 — harsh. Score 3/10 (reject), confidence 4.**
The method is a pipeline of standard parts whose learned component is matched by a two-line
rule; partition is a null; four of five pre-registered tests fail. Related work omits TAML
(IJCAI 2026) and CSGM (WWW 2025), which do sub-network discovery on the same dataset, so the
novelty claim is false. One synthetic dataset, a detector 20 points below reported SOTA, and
the only significant precision test was added post hoc. The manuscript reads as a lab notebook
with dated retractions. The benchmark observations are interesting but belong in a different
paper.

**R2 — neutral. Score 5/10 (borderline), confidence 3.**
Careful and unusually honest. The scope-convention and tail analyses are valuable and I have
not seen them stated. But the paper cannot decide whether it is a method or an audit; the
audit findings are shown on one generator family; no external group-level baseline is scored
under the proposed protocol, so I cannot tell whether the protocol changes any conclusion in
the literature. Would move to accept with (a) baselines under the protocol, (b) HI-Medium,
(c) a restructure around the audit.

**R3 — supportive. Score 7/10 (accept), confidence 4.**
The field needs this. Showing that an unstated scope rule is worth five times a method effect,
that the test tail halves the effective seed budget, and that 44 % of targets are unobservable
as objects will change how I review AML papers. Negative results are reported with intervals
and against the authors' own method. Requests: figures, a reporting checklist, a stronger
detector for the edge-vs-ring claim, and trimming of the platform material.

### Rebuttal plan

| # | Criticism | Response | Needs |
|---|---|---|---|
| 1 | Prior work exists (TAML, CSGM, AMAP) | Concede; reposition as attempt-level protocol. Show their numbers move under scope rule / tail | Exp. 1, 6 |
| 2 | Rule matches the method | Agree; it is our stated result. Reframe policy as purity re-ranker; paper's claim is the audit | Reframing only |
| 3 | One synthetic dataset | HI-Medium + LI-Small reproduction of artefacts; state generator-family limit | Exp. 2 |
| 4 | Weak detector undermines "edge F1 is no proxy" | FraudGT row + budget sweep | Exp. 3, 5 |
| 5 | Post-hoc tests, cross-score leak | Label exploratory tests as such; report ring-folded re-run | Exp. 4 |

---

## Prioritised 2-week plan

| Day | Task | Output |
|---|---|---|
| 1 | Decide framing (audit paper) and authorship; cut L4/platform/R10–R12 from body | Agreed outline |
| 1–2 | Related work rewrite with TAML, AMAP, CSGM, SMURF, ReDiRect, FlowScope/DenseFlow, FraudGT, ExSTraQt, SALT-GNN; delete "not aware of prior work" | `related.tex`, ~40 refs |
| 2–3 | CSGM to 5 seeds; Leiden/Louvain on flagged edges; put all in the main table | Baseline rows (Exp. 1a) |
| 3–4 | Ring-folded cross-score run (already registered) | B17 closed (Exp. 4) |
| 3–6 | HI-Medium close-out | Second-dataset section (Exp. 2) |
| 5–9 | FraudGT under causal sampling, 3 seeds, B0 + full; budget sweep for all detectors | Edge-vs-ring figure (Exp. 3, 5) |
| 7–10 | TAML extractor scored under your protocol, both scope rules | Exp. 1b, 6 |
| 8–11 | Five figures; strip internal codes and dated-correction prose | New Figures 1–5 |
| 11–13 | Rewrite title, abstract, intro, contributions, recommendations box; move tables to appendix | Full draft v3 |
| 14 | Compile on Overleaf, page-fit to venue template, internal read by a non-author | Submission candidate |

If only three things get done: **(1) related work + reframing, (2) external baselines under
your protocol, (3) HI-Medium.** Those convert R2 to accept and blunt R1's main points.

---

## Sources

- Chai et al., AAAI 2023: https://ojs.aaai.org/index.php/AAAI/article/view/26656
- Rico et al., IJCAI 2026 (TAML): https://ijcai.org/proceedings/2026/723
- Tian et al., WWW 2025 (CSGM): https://arxiv.org/abs/2502.19952
- SMURF: https://repository.tudelft.nl/record/uuid:8e53ccf5-3cfa-4907-adc2-775846021e90
- FlowScope, AAAI 2020: https://ojs.aaai.org/index.php/AAAI/article/view/5906
- Elliptic2: https://arxiv.org/abs/2404.19109 ; RevTrack: https://arxiv.org/abs/2410.08394
- ReDiRect: https://arxiv.org/abs/2604.01315 ; ExSTraQt: https://arxiv.org/abs/2604.02899
- FraudGT: https://dspace.mit.edu/handle/1721.1/157762
- MEGA-GNN: https://arxiv.org/abs/2412.00241
- SALT-GNN: https://www.alphaxiv.org/abs/2607.10131.md
- Tide: https://arxiv.org/abs/2603.01863
- Practitioner note on the tail: https://github.com/Kluey/AML-Transaction-Detection
- KDD 2027 dates: https://kdd2027.kdd.org/research-track-call-for-papers/
