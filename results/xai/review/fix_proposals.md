# Narrative fixes proposed from the review (Week 7, for sign-off; applied in Week 8)

Every proposal below comes from a rule in `analysis_plan.md` that fired on the scored review (`review_summary.md`).
Exploratory findings, i.e. analysis that was not in the plan, are labelled as such. Nothing here has been changed
yet. The narratives stay exactly as reviewed until Ruhani and Joan sign off.

## Fix A — do not headline a shape the transactions don't show

**Triggers (pre-registered):**
- q1 within `bank_list`: yes-rate 0.35;
- q4 within `bank_list`: 13 of 16 items flagged;
- q4 within `narrated_shape_correct`: 9 of 15 flagged.

**What is behind them (exploratory, not in the plan):**
- All 13 narratives that state a shape **without a shape sentence** were flagged misleading by the majority (13 of
  13), and 12 of 13 were called implausible.
- Of the 17 narratives with a shape sentence, 6 were flagged.
- `bank_list` only stands in for this: every narrative without a shape sentence had room for the bank list.
- It is not about the shape being wrong: 6 of those 13 shapes were the true pattern type, and reviewers still found
  them unsupported. That is exactly what q4 asks ("unsupported by what is shown").

**Proposal A1 (recommended).** When no shape sentence holds on the ring's transactions, open with the untyped head and
state the typing model's guess as a guess:

> Suspected ring: 6 accounts, 5 transactions over 20.9 h. … The typing model's most likely shape is Scatter-gather
> (p = 0.63), but the transactions shown do not display that shape.

When a shape sentence holds, the headline stays as it is.

**Alternative A2.** Leave the shape out of the narrative entirely when no shape sentence holds; it stays in the
`topology_type` field and the dashboard.

**Effect:**
- Wording only: no weight and no fidelity number changes.
- It changes the narrative of every ring that has no shape sentence (about a third).
- `evidence_summary` gains one clause id, and regeneration still matches character for character.

## Fix B — find out what was misleading in the 6 shape-sentence narratives

**Trigger (pre-registered):** q4 within `shape_sentence`, 6 of 17 flagged: R-02, R-04, R-06, R-12, R-25, R-30.

**What the data shows:**
- In all 6, the shape sentence agrees with the headline shape.
- 3 of the 6 are the true pattern type, 3 are not.
- No reviewer left a comment.
- So the cause can't be read from the answers, and a wording change now would be a guess.

**Proposal B1 (recommended).** One short follow-up question to all three reviewers, for those 6 items only: "what in
the sentence was misleading?" (free text). The fix is decided from the answers in Week 8. If nothing actionable comes
back, the finding is reported as it is.

## Not changed

- **Bank list:** its trigger is explained by Fix A (see above). Changing the bank clause alone would not address it.
- **Same-currency self-payment among the top-3 evidence:** 1 item, flagged by the majority. Below the plan's
  thresholds (at least 3 items, or 20 % with at least 2), so not a fix under the plan. It is passed to Joan as an
  evidence question, as decided earlier.
- **q3 ("enough to start an investigation"):** yes for every item from every reviewer, so it can't discriminate.
  Reported as such.

## Reported as findings, not fixes

- **Agreement:**
  - q2 almost perfect (κ 0.86);
  - q4 substantial (κ 0.72);
  - q1 moderate (κ 0.60);
  - q3 undefined (unanimous yes).
- **The reveal:**
  - the narrated shape was the true type for 50 % of these 30 items (the typing model is right about 60 % overall);
  - the reviewers' "plausible" answer matched the truth 63 % of the time (majority 67 %).

  So the reviewers could tell right shapes from wrong ones only modestly better than chance. Together with Fix A,
  this supports showing shapes as guesses.
