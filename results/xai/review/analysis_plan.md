# Review analysis plan (written before scoring)

**Written 2026-10-18.** At this point reviewer R1's sheet is filled. R2's and R3's are not back. **No sheet has been
read for its answers or scored**; R1's was only checked for format: 30 rows, 0/1 everywhere.

This file fixes in advance how the 30-explanation review (L4 spec section 7, XR-29) will be read. Deciding the rules
first means nobody can pick the rules after seeing the answers. It is committed to git before R2 and R3 return their
sheets; the commit date is the proof.

## 1. What is measured

The three reviewers (R1, R2, R3) each answer four questions with 1 = yes, 0 = no, for each of 30 items:

| question | 1 means |
|---|---|
| q1_topology_plausible | the stated shape is plausible from the evidence shown |
| q2_named_accounts_matter | the accounts the narrative names are the ones that matter |
| q3_evidence_enough | the evidence transactions would be enough to start an investigation |
| q4_misleading | something in the sentence is misleading or unsupported (**1 = a problem**) |

Per question:
- **yes-rate:** the share of all 90 answers that are 1;
- **all-agree rate:** the share of items on which all three gave the same answer;
- **Fleiss' κ:** agreement beyond what chance alone would produce. Read with the Landis & Koch (1977) bands:
  below 0 poor, up to 0.20 slight, up to 0.40 fair, up to 0.60 moderate, up to 0.80 substantial, above 0.80 almost
  perfect.

A low κ is reported as "the reviewers read this question differently". It is a property of the question and the
reviewers, **not a reason to change a narrative**.

**The reveal**, after scoring:
- for each item, whether the narrated shape is the true pattern type;
- whether each reviewer's q1 matched that (plausible when right, implausible when wrong).

## 2. Narrative features used for the breakdowns

Each item is tagged from its own explanation (`evidence_summary`), never from the answers:

| feature | the item has it when |
|---|---|
| `shape_sentence` | the narrative states a shape sentence ("Account X paid N different accounts", …) |
| `self_payment_top3` | one of the narrative's three strongest transactions is an account paying itself |
| `partial_currency` | the money total is partial (Bitcoin has no exchange rate) |
| `bank_list` | the narrative lists bank names (rather than only a count, or nothing) |
| `undetermined_named` | the narrative names an account whose role cannot be checked |
| `narrated_shape_correct` | the narrated shape is the true pattern type (from the answer key, after scoring) |

Every question is also broken down by true pattern type.

## 3. When the review says "fix this"

**Flagged item:** at least `flag_majority` of the 3 reviewers answered q4 = 1 (misleading), or answered 0 to q1, q2
or q3.

**A fix is triggered by:**
1. **q1–q3 overall:** a question's yes-rate is below `low_yes_rate`.
2. **q1–q3 within a feature:** a question's yes-rate is below `low_yes_rate` on the items that have a feature, when
   at least `min_group_items` items have it.
3. **q4 within a feature:** at least `q4_pattern_min_items` of the feature's items are flagged misleading; or at
   least `q4_pattern_min_share` of them are, with at least `q4_share_min_items` flagged.

Each trigger becomes one proposed fix, with the items and comments that caused it. **No fix is proposed without a
trigger.**

The numbers, exactly as `explainability/config.yaml` (`review.rules`) holds them; a test checks the two are identical:

```yaml
flag_majority: 2
low_yes_rate: 0.5
min_group_items: 5
q4_pattern_min_items: 3
q4_pattern_min_share: 0.2
q4_share_min_items: 2
kappa_bands: [[0.0, "poor"], [0.2, "slight"], [0.4, "fair"], [0.6, "moderate"], [0.8, "substantial"], [1.0, "almost perfect"]]
```

## 4. What a fix may change

- **Allowed in Week 8, with Joan's and Ruhani's sign-off:** wording, templates, which clauses appear, captions. These
  change no weight and no fidelity number.
- **A separate decision with Joan:** anything that changes the evidence itself (for example removing same-currency
  self-payments from the ranked transactions). It changes the weights and the fidelity tables, so it is not a
  "narrative fix".
- **No second review round.** For the 30 items, Week 8 shows each narrative before and after the fixes.

## 5. What the report will say

The review is a structured check by the three team members, **not an analyst study**. R1 also built the
explanations, so R1's answers are not blind to how they work. The reveal uses the true pattern types only after all
three sheets are in.
