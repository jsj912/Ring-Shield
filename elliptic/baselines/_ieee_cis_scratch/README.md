# IEEE-CIS Scratch Work

This folder holds exploratory Logistic Regression work done on the IEEE-CIS
Fraud Detection dataset (Kaggle) before the project's baseline registry was
standardized on Elliptic (which has a directly reproducible literature
protocol via Weber et al. 2019).

Two variants are kept:
- `logistic_regression_full.py` — full feature set, 50k-row sample
- `logistic_regression_reduced.py` — TransactionAmt/TransactionDT + first 60
  V-columns only, 20k-row sample

**Important differences from the E1-E3b Elliptic experiments — do not directly
compare F1 scores across the two:**
- Random 80/20 stratified split here, vs. chronological split on Elliptic
- Different dataset entirely (no literature-published baseline target)
- LabelEncoder used for categoricals here (ordinal-izes unordered categories,
  a known simplification)

