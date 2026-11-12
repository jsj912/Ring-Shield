# Instructions for reviewers (DRAFT)

Thank you for taking part. This page is read with you at the start of the session.

## What you will do

You will look at **40 suspected money-laundering cases**, one at a time, in a web dashboard. Each
case is a small group of accounts and the transfers between them that a detection system flagged.

For each case, decide what you would do as an investigator:

- **Confirm:** this looks like a laundering ring; you would open an investigation on these accounts.
- **Reject:** this does not look like laundering, or the evidence is not enough to act on.
- **Partial:** part of it looks like a ring, but some accounts do not belong. Untick the accounts
  you would leave out, and add a short note.

Then fill in your answer sheet for the same case:

| Column | What to write |
|---|---|
| `shape` | The pattern you think it is: fan-out, fan-in, scatter-gather, gather-scatter, cycle, bipartite, stack, random, or `cant_tell` |
| `confidence` | 1 (a guess) to 5 (certain) |
| `misleading` | Only if the case shows a written summary sentence: 1 if anything in it is not supported by the transactions shown, else 0. Leave it blank if there is no sentence. |
| `comment` | Optional |

## Things to know

- **The data are synthetic.** They come from a public simulated banking dataset, not from real
  customers. Some cases may look less messy than real alerts. That is expected, so please judge
  them as you would a real alert.
- **Not every case is laundering.** Some were flagged wrongly. We will not tell you how many.
- **Presentation varies.** Some cases show a written summary sentence and some do not. Judge each
  case from what is on the screen.
- **Take the time you need.** We record how long each case takes, but there is no target. Please
  do not leave a case open while you take a break. Submit it or don't open the next one.
- **Do not look anything up** outside the dashboard, and do not discuss cases with other reviewers
  until everyone has finished.
- You can stop at any time without giving a reason.

## What happens to your answers

Your verdicts and answer sheet are stored under a code (for example `ext-03`), not your name. The
results are reported only in aggregate across reviewers.
