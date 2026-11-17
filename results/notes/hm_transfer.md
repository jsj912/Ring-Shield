# HI-Medium transfer (trained on HI-Small, zero-shot on HI-Medium): notes

## 2026-11-17: proposal (not paper text)

**Proposed wording:** "A detector trained only on HI-Small, applied without retraining to HI-Medium, gives seeds-only ring-F1 X on days 6–14." X is the five-seed B0 mean (global rule) once seeds 2–5 are in; the seed-1 value is 0.4087.

**Labels**
- The transfer result is B0 (primary, global rule), with B1b beside it.
- Proposed and Full on HI-Medium are "not evaluated under transfer: policy trained on HI-Medium on the old detector, two of its features missing". They stay out of any paper table.
- Full's partition used the affinity model `experiments_hi_medium/R4_partition/affinity_no_embedding`, trained on HI-Medium pairs from the old GINe scores. Its cut 0.3 was chosen on HI-Medium validation with the old detector.
- The comparison with the old detector differs in both architecture (GINe vs GenAgg) and training data (HI-Medium vs HI-Small). The old side has two seeds. This note does not claim that transfer beats in-domain training.

**Jump decomposition (as reported; update with the five-seed mean)**
- Under the per-day rule, the old detector scores 0.1475 (two seeds) and the new one 0.3883 (one seed).
- Budget allocation across days explains at most about 0.06 of the 0.32 gap between 0.0898 and 0.4087.
