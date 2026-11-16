# OPEN_QUESTIONS — what you must decide or supply

## Must decide before submission

1. **Venue and page style.** The draft uses the plain `article` class at ~11–12 pages of body
   text plus appendix. Name a venue and I (or you) switch `main.tex` to `IEEEtran` or `acmart`
   and cut to the page limit. Candidate cuts, in order of least damage:
   - the per-pattern table (Table per_pattern) → appendix;
   - the windows table (Table windows) → one sentence plus appendix;
   - Section 7.5 (LI-Small) → fold into 4.3;
   - the three platform screenshots → one;
   - the R10 table → cite the repository.
2. **Author affiliation(s) and email.** Not recorded in the repository — the title block has a
   `[NO SOURCE]` placeholder.
3. **Authorship vs acknowledgements.** Per your instruction, Joan Sara Joe is sole author and
   Ruhani Kumar, Kashish Mittal and Lakshmishree are acknowledged (as CONTRIBUTORS.md credits
   them). If any venue's authorship norms would treat L4 or the platform as authorship-level
   contributions, that is your call to revisit.
4. **Anonymisation.** If the venue is double-blind, the acknowledgements section, the GitHub
   path and the contributor names must come out of the submitted version.

## Citations to complete or decide

5. **bilgi2024 (MEGA-GNN).** The repo cites it only as "Bilgi et al., arXiv:2412.00241". I
   filled in a title from the arXiv number but left the author list as "and others" — verify
   both against the arXiv record before submission.
6. **li2020flowscope.** Cited in the repo only via the archived survey
   (`docs/archive/compass_artifact…md`) as "Li et al. (2020), FlowScope, AAAI 2020"; the author
   list is incomplete in the .bib. Decide whether to keep it (it is the classic unsupervised
   group baseline) or drop the sentence.
7. **weber2019.** The repo references "Weber et al. 2019" by name without full bibliographic
   data; I used the standard arXiv:1908.02591 record. Verify.
8. **Related work is thin by design.** The brief said to cite only what the repo references.
   One `[CITATION NEEDED]` stands in `sections/related.tex` for the broader ring/group-level
   AML literature (the archived survey lists candidates: Elliptic2/RevClassify, Chai et al.
   AAAI 2023, GARG-AML, Clue2Group, LAS-GNN, FraudGT…). A reviewer will expect 4–8 more
   citations here; they are all in `docs/archive/compass_artifact…md` with verification notes.

## Figures

9. **Figures are the repository's matplotlib PNGs** (f2, f3, f4, r4_val_ringf1_vs_seedfrac,
   r9_quiet_vs_precision) plus three dashboard screenshots. For camera-ready you may want to
   redraw f3/r9_quiet_vs_precision in a consistent style and as vector graphics; the CSVs
   behind them are in `results/figures/` and `results/tables/`.
10. **The pipeline diagram** is a TikZ redraw of the Mermaid architecture in `docs/report.md`
    §3.2 — check it renders to your taste (it is deliberately minimal).

## Small factual items to confirm

11. **FINDINGS rounding vs CSV.** FINDINGS A1 writes proposed quiet recall as 0.2098 where
    `r9_quiet_members.csv` holds 0.20915 (both round to 0.210, which the paper uses in tables;
    the abstract follows FINDINGS' 21 %). No action needed unless you want the fifth decimal.
12. **xai_chapter's two populations.** Its fidelity note says "343 of the 395 matched
    ring-instances with any true ranked transaction"; the README and its own earlier sentence
    say "343 of 401". The paper says "343 of 401 matched ring-instances" — confirm with Ruhani
    which denominator the camera-ready should use.
13. **The added-member precision 0.926 appears under two sources** (FINDINGS A5 / proposed =
    0.9263; r6_detector_swap full = 0.9257). Both round to 0.926; the paper's Table
    detector_swap uses the r6 value, the expansion section uses A5. Consistent, but stated here
    so nobody "fixes" one against the other.
14. **Compile check.** No LaTeX compiler exists on this machine (pdflatex/bibtex/tectonic/
    latexmk all absent, no MiKTeX/TeX Live install found), so the project is statically checked
    (environments balanced, all \input/figure paths exist, all \ref and \cite keys resolve) but
    **not compiled**. First Overleaf compile may surface float-placement warnings.

## Content you may want that was deliberately left out

15. **Elliptic baselines (E1–E3)** — excluded from the paper body per the brief and README
    ("not part of the ring pipeline"); mentioned in one sentence of the introduction only.
16. **HI-Medium V3 results beyond C10/C11/B17** — the findings file treats HI-Medium as
    context for specific rows; a full second-dataset section would need the V3 pre-registration
    to land first.
17. **R11/R12 detail** — one appendix sentence each. The full defect table (D-1…D-10) and test
    matrix stay in `docs/report.md`.

## Added 2026-11-12, after commit aa4d233

18. **FINDINGS scope rule vs this paper.** FINDINGS now states that R10, R11, R12 and L4
    numbers "stay out of the report until they enter this file". The paper keeps them, but only
    in Limitations, the L4 method paragraph and the appendix, each labelled as outside FINDINGS.
    If you want the paper to obey the rule literally, cut: the R10 paragraph and Table r10, the
    L4 numbers in Section 5.5, and the R11/R12 appendix sentences.
19. **Three follow-ups are in the paper but not in FINDINGS section G** (G covers #1–#6 only):
    the HI-Small day-0 exclusion (#9), the ring-identity head (#10) and the L4 mixed-ring
    evaluation (#11). Each is cited to `docs/deep-analysis.md` and marked "not yet a FINDINGS
    row" in the .tex comments. Either add dated notes for them to FINDINGS or tell me to drop
    them. In particular **FINDINGS C10 still says the HI-Small exclusion "has not been run"**,
    which #9 contradicts.
20. **FINDINGS rows A1, B1 and E3 still print 0.2098** although the new note above table A says
    every value is the 0.2092 point estimate. The paper uses 0.2092 / 0.209 everywhere.
21. **B14's row text still carries the as-run 0.4455** in FINDINGS; only the G note corrects
    it. The paper uses the corrected forced-budget figures and does not print 0.4455.
22. **Pending results that will change the paper when they land:** the ring-folded cross-score
    re-run (#8, B17; `experiments/R3_ringfold/` exists locally but is untracked) and the
    HI-Medium close-out (#7). The Limitations section says the first result "is not in this
    draft"; the second is not mentioned.
23. **Length.** The update adds three tables and about one page of text. For an 8-page limit,
    Table window_budget and Table precision_paired are the first candidates to move to the
    appendix (Table component_scope is already there).
24. **Overleaf.** I have no access to your Overleaf project, so updating it means re-uploading:
    either upload the new zip as a fresh project, or replace the changed files inside the
    existing project (three new tables, three edited tables, eight edited sections).
25. **The first draft's item 11 is resolved** by the repository's own correction (0.2098 was a
    bootstrap mean; the point estimate 0.2092 is now the convention).

## Added 2026-11-13, draft v3 (audit framing)

26. **Title and framing changed.** The paper is now "Rings, Not Edges: What AMLworld Can and
    Cannot Tell Us About Recovering Money-Laundering Attempts", with no method-novelty claim and
    the name "RingShield" no longer in the title or body. Say so if you want the name kept.
27. **Related work now cites papers the repository does not reference** (Chai 2023, Rico 2026,
    Tian 2025, Tariq 2026 ×2, FraudGT, Holm, LightGBM, SupCon). This departs from your original
    "cite only what the repo references" rule, on the strength of the review. Three entries
    still have "and others" author lists (chai2023, tian2025, khosla2020). Verify every
    sentence that characterises another paper against its PDF, above all Rico et al.
28. **Authorship is still open.** The acknowledgements now state that Ruhani found the typing
    evaluation defect. If she becomes a co-author, move that sentence out.
29. **Experiments the new framing promises implicitly.** The Limitations section states
    plainly that learned sub-network baselines, a stronger detector and the ring-folded re-run
    are missing. Those are the experiments in REVIEW.md §3; the paper is honest without them
    but much stronger with them.
30. **Figures.** Two of the four new figures use hand-transcribed numbers (see CLAIMS_CHECK).
    A drawn example of a split-severed STACK ring (REVIEW.md, figure 5) is not made: it needs
    the transaction data, which I did not open.
31. **FINDINGS scope rule.** L4, platform and tenant numbers are now confined to one appendix
    section that says they are outside the findings file. Cut that section if you want strict
    compliance.
32. **"We release the protocol, tables and code"** is asserted in the abstract and conclusion.
    Confirm the repository will be public (or anonymised) at submission.
