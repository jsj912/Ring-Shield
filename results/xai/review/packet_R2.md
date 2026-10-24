# RingShield explanation review — reviewer R2

30 suspected laundering rings, one per section. For each, read the narrative, the top evidence transactions and the account roles, then answer four questions with **1 (yes)** or **0 (no)** in your answer sheet (`answers_R2.csv`, one row per item):

1. **q1_topology_plausible** — Is the stated topology (shape) plausible from the evidence shown?
2. **q2_named_accounts_matter** — Are the named accounts the ones that matter in the shown evidence?
3. **q3_evidence_enough** — Would the evidence transactions be enough to start an investigation?
4. **q4_misleading** — Is anything in the sentence misleading or unsupported by the evidence shown? (1 = yes)

Judge only from what is shown here; do not look anything up in other files. Your items are in your own order; the item number (R-01 …) is what links a section to its row.

---
## R-06

> Fan-in ring (most likely shape, p = 0.28): 5 accounts, 6 transactions over 21.8 h. Account 137509 was paid by 2 different accounts. Total moved: 28,800 (US Dollar). 97% of the money sent by the sources reached the sinks. Strongest evidence: 210231→137509 (8,460, weight 0.68); 33496→213191 (7,450, weight 0.66); 33496→213191 (760, weight 0.57). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 5 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 210231 → 137509 | 7,217.43 Euro | 8,457.27 | ACH | Australia Bank #3 → Italy Bank #587 | 0.68 |
| 2 | 33496 → 213191 | 9,825.28 Canadian Dollar | 7,447.34 | ACH | Savings Bank of Danbury → Canada Bank #37 | 0.66 |
| 3 | 33496 → 213191 | 1,002.64 Canadian Dollar | 759.98 | ACH | Savings Bank of Danbury → Canada Bank #37 | 0.57 |
| 4 | 210231 → 137509 | 122.71 Euro | 143.79 | ACH | Australia Bank #3 → Italy Bank #587 | 0.56 |
| 5 | 213191 → 210231 | 11,157.67 Canadian Dollar | 8,457.26 | ACH | Canada Bank #37 → Australia Bank #3 | 0.16 |

**Account roles** (5 accounts, strongest first):

- **source** (2): 33496, 373406
- **mule** (2): 210231, 213191
- **sink** (1): 137509

Your answers for this item go in the row **R-06** of your answer sheet.

---

## R-01

> Fan-out ring (most likely shape, p = 0.60): 5 accounts, 5 transactions over 29.4 h. Account 508502 paid 4 different accounts. Total moved: 1,010,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 508502→64105 (917,000, weight 0.96); 508502→64105 (81,600, weight 0.63); 508502→389499 (8,000, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH); that lowered it: the amount sent, the amount received. The accounts span 5 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 508502 → 64105 | 916,645.83 US Dollar | 916,645.83 | ACH | National Bank of the East → First Bank of Helena | 0.96 |
| 2 | 508502 → 64105 | 81,592.54 US Dollar | 81,592.54 | ACH | National Bank of the East → First Bank of Helena | 0.63 |
| 3 | 508502 → 389499 | 6,828.41 Euro | 8,001.42 | ACH | National Bank of the East → Netherlands Bank #195 | 0.60 |
| 4 | 508502 → 108227 | 4,773.42 Euro | 5,593.41 | ACH | National Bank of the East → Germany Bank #65 | 0.60 |
| 5 | 508502 → 235443 | 1,380.75 Swiss Franc | 1,509.02 | ACH | National Bank of the East → Switzerland Bank #20 | 0.60 |

**Account roles** (5 accounts, strongest first):

- **source** (1): 508502
- **sink** (4): 389499, 108227, 64105, 235443

Your answers for this item go in the row **R-01** of your answer sheet.

---

## R-15

> Layered chain ring (most likely shape, p = 0.70): 3 accounts, 2 transactions over 3.35 h. Funds moved 2 hops from 112157 to 238336 through 307838. Total moved: 13,000 (US Dollar). 99% of the money sent by the sources reached the sinks. Strongest evidence: 112157→307838 (6,550, weight 0.64); 307838→238336 (6,490, weight 0.63). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: how many payments the receiver makes. The accounts span 3 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 112157 → 307838 | 690,837.53 Yen | 6,554.44 | ACH | Spain Bank #37 → Japan Bank #179 | 0.64 |
| 2 | 307838 → 238336 | 5,940.74 Swiss Franc | 6,492.61 | ACH | Japan Bank #179 → Switzerland Bank #20 | 0.63 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 112157
- **mule** (1): 307838
- **sink** (1): 238336

Your answers for this item go in the row **R-15** of your answer sheet.

---

## R-03

> Gather-scatter ring (most likely shape, p = 0.39): 7 accounts, 7 transactions over 41.2 h. Total moved: 56,500 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 99051→267860 (16,100, weight 0.67); 274972→267860 (5,690, weight 0.60); 337905→267860 (16,400, weight 0.58). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the receiver being paid by many accounts. The accounts span 5 banks (Finland Bank #0, National Bank of the East, China Bank #6 +2 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 99051 → 267860 | 13,714.11 Euro | 16,069.97 | ACH | Germany Bank #18 → Finland Bank #0 | 0.67 |
| 2 | 274972 → 267860 | 4,852.08 Euro | 5,685.59 | ACH | China Bank #6 → Finland Bank #0 | 0.60 |
| 3 | 337905 → 267860 | 13,988.55 Euro | 16,391.55 | ACH | National Bank of the East → Finland Bank #0 | 0.58 |
| 4 | 99186 → 267860 | 3,837.07 Euro | 4,496.22 | ACH | Germany Bank #65 → Finland Bank #0 | 0.53 |
| 5 | 337905 → 267860 | 10.35 Euro | 12.13 | ACH | National Bank of the East → Finland Bank #0 | 0.49 |

**Account roles** (7 accounts, strongest first):

- **source** (6): 100229, 337905, 274972, 99186, 99051, 358235
- **sink** (1): 267860

Your answers for this item go in the row **R-03** of your answer sheet.

---

## R-17

> Layered chain ring (most likely shape, p = 0.62): 3 accounts, 2 transactions over 9.15 h. Funds moved 2 hops from 246668 to 18175 through 108402. Total moved: 36,300 (US Dollar). 96% of the money sent by the sources reached the sinks. Strongest evidence: 108402→18175 (17,700, weight 0.71); 246668→108402 (18,500, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 108402 → 18175 | 17,746.73 US Dollar | 17,746.73 | ACH | France Bank #28 → National Bank of Pittsburgh | 0.71 |
| 2 | 246668 → 108402 | 15,810.55 Euro | 18,526.54 | ACH | Israel Bank #5 → France Bank #28 | 0.52 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 246668
- **mule** (1): 108402
- **sink** (1): 18175

Your answers for this item go in the row **R-17** of your answer sheet.

---

## R-11

> Scatter-gather ring (most likely shape, p = 0.64): 11 accounts, 12 transactions over 25.1 h. Total moved: 115,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 425012→84086 (17,000, weight 0.64); 165499→84086 (16,300, weight 0.57); 270966→84086 (5,810, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver receives. The accounts span 11 banks (National Bank of Laramie (10), Acme Federal Bank, Spruce Trust Bank +8 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 425012 → 84086 | 17,049.76 US Dollar | 17,049.76 | ACH | UK Bank #52 → National Bank of Laramie | 0.64 |
| 2 | 165499 → 84086 | 16,280.79 US Dollar | 16,280.79 | ACH | China Bank #340 → National Bank of Laramie | 0.57 |
| 3 | 270966 → 84086 | 5,814.03 US Dollar | 5,814.03 | ACH | Australia Bank #23 → National Bank of Laramie | 0.52 |
| 4 | 309749 → 84086 | 498.75 US Dollar | 498.75 | ACH | National Bank of Laramie → National Bank of Laramie | 0.51 |
| 5 | 61323 → 84086 | 9,719.50 US Dollar | 9,719.50 | ACH | Hilltop Community Bank → National Bank of Laramie | 0.44 |

**Account roles** (11 accounts, strongest first):

- **source** (10): 311407, 309749, 63500, 270966, 165499, 351884, 425012, 61323, 292387, 10437
- **sink** (1): 84086

Your answers for this item go in the row **R-11** of your answer sheet.

---

## R-22

> Cycle ring (most likely shape, p = 0.80): 8 accounts, 10 transactions over 44.4 h. Total moved: 40,600 (US Dollar). 98% of the money sent by the sources reached the sinks. Strongest evidence: 306715→353064 (6,060, weight 0.62); 376861→421565 (5,840, weight 0.61); 127330→414802 (5,370, weight 0.61). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 8 banks (Germany Bank #65, Savings Bank of Los Angeles, Italy Bank #1106 +5 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 306715 → 353064 | 6,058.07 US Dollar | 6,058.07 | ACH | Germany Bank #65 → First Bank of Houston | 0.62 |
| 2 | 376861 → 421565 | 5,840.05 US Dollar | 5,840.05 | ACH | Italy Bank #1106 → Savings Bank of Newport | 0.61 |
| 3 | 127330 → 414802 | 5,372.23 US Dollar | 5,372.23 | ACH | Italy Bank #215 → Bank of Laramie | 0.61 |
| 4 | 118234 → 127330 | 4,584.66 Euro | 5,372.23 | ACH | Belgium Bank #26 → Italy Bank #215 | 0.61 |
| 5 | 2556 → 118234 | 4,584.66 Euro | 5,372.23 | ACH | Savings Bank of Los Angeles → Belgium Bank #26 | 0.51 |

**Account roles** (8 accounts, strongest first):

- **source** (1): 306715
- **mule** (6): 127330, 118234, 421565, 2556, 376861, 353064
- **sink** (1): 414802

Your answers for this item go in the row **R-22** of your answer sheet.

---

## R-28

> Fan-in ring (most likely shape, p = 0.39): 5 accounts, 6 transactions over 28.8 h. Account 317176 was paid by 3 different accounts. Total moved: 33,900 (US Dollar). 99% of the money sent by the sources reached the sinks. Strongest evidence: 384222→412261 (2,280, weight 0.62); 31627→317176 (8,610, weight 0.61); 31627→317176 (247, weight 0.51). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 5 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 384222 → 412261 | 2,284.16 US Dollar | 2,284.16 | ACH | UK Bank #0 → First Bank of Springfield | 0.62 |
| 2 | 31627 → 317176 | 7,348.32 Euro | 8,610.64 | ACH | First Bank of New Orleans → Italy Bank #49 | 0.61 |
| 3 | 31627 → 317176 | 211.12 Euro | 247.39 | ACH | First Bank of New Orleans → Italy Bank #49 | 0.51 |
| 4 | 286427 → 317176 | 15,037.10 Euro | 17,620.22 | ACH | National Bank of Omaha → Italy Bank #49 | 0.44 |
| 5 | 412261 → 317176 | 1,577.86 Euro | 1,848.91 | ACH | First Bank of Springfield → Italy Bank #49 | 0.34 |

**Account roles** (5 accounts, strongest first):

- **source** (3): 31627, 286427, 384222
- **mule** (1): 412261
- **sink** (1): 317176

Your answers for this item go in the row **R-28** of your answer sheet.

---

## R-10

> Scatter-gather ring (most likely shape, p = 0.56): 6 accounts, 5 transactions over 12.8 h. Total moved: 53,200 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 176079→44567 (8,390, weight 0.50); 176079→10376 (4,280, weight 0.40); 176079→333657 (10,600, weight 0.30). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 6 banks (Russia Bank #16, Japan Bank #8, First Bank of Arkadelphia +3 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 176079 → 44567 | 8,386.88 US Dollar | 8,386.88 | ACH | Japan Bank #8 → Hearthstone Savings Bank | 0.50 |
| 2 | 176079 → 10376 | 4,284.50 US Dollar | 4,284.50 | ACH | Japan Bank #8 → First Bank of Arkadelphia | 0.40 |
| 3 | 176079 → 333657 | 823,911.24 Ruble | 10,589.57 | ACH | Japan Bank #8 → Russia Bank #16 | 0.30 |
| 4 | 176079 → 341597 | 15,777.54 Euro | 18,487.86 | ACH | Japan Bank #8 → Belgium Bank #886 | 0.14 |
| 5 | 176079 → 435643 | 11,427.94 US Dollar | 11,427.94 | ACH | Japan Bank #8 → Savings Bank of Seattle | 0.09 |

**Account roles** (6 accounts, strongest first):

- **source** (1): 176079
- **sink** (5): 44567, 10376, 333657, 341597, 435643

Your answers for this item go in the row **R-10** of your answer sheet.

---

## R-20

> Fan-out ring (most likely shape, p = 0.67): 16 accounts, 15 transactions over 2.95 days. Account 138280 paid 15 different accounts. Total moved: 107,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 138280→3257 (17,000, weight 0.56); 138280→67641 (15,200, weight 0.56); 138280→228248 (501, weight 0.54). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the sender receives. The accounts span 16 banks (India Bank #0, Brazil Bank #7, Brazil Bank #6 +13 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 138280 → 3257 | 16,974.64 US Dollar | 16,974.64 | ACH | Netherlands Bank #500 → Flagstone Federal Bank | 0.56 |
| 2 | 138280 → 67641 | 15,168.56 US Dollar | 15,168.56 | ACH | Netherlands Bank #500 → Spruce Trust Bank | 0.56 |
| 3 | 138280 → 228248 | 2,829.41 Brazil Real | 501.09 | ACH | Netherlands Bank #500 → Brazil Bank #6 | 0.54 |
| 4 | 138280 → 10648 | 7,901.37 US Dollar | 7,901.37 | ACH | Netherlands Bank #500 → Arbor Thrift | 0.53 |
| 5 | 138280 → 404504 | 37,127.49 Brazil Real | 6,575.32 | ACH | Netherlands Bank #500 → Brazil Bank #7 | 0.53 |

**Account roles** (16 accounts, strongest first):

- **source** (1): 138280
- **sink** (15): 10648, 404504, 167038, 247734, 67641, 359461, 239957, 411711, 77852, 312060, 229106, 228248, 321058, 3257, 4955

Your answers for this item go in the row **R-20** of your answer sheet.

---

## R-18

> Fan-out ring (most likely shape, p = 0.89): 6 accounts, 5 transactions over 36.8 h. Account 26856 paid 5 different accounts. Total moved: 47,200 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 26856→236729 (18,500, weight 0.69); 26856→67164 (6,650, weight 0.56); 26856→121842 (6,450, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 6 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 26856 → 236729 | 16,926.06 Swiss Franc | 18,498.43 | ACH | Acme Community Bank → Switzerland Bank #51 | 0.69 |
| 2 | 26856 → 67164 | 6,645.85 US Dollar | 6,645.85 | ACH | Acme Community Bank → Bank of Watertown | 0.56 |
| 3 | 26856 → 121842 | 5,500.84 Euro | 6,445.79 | ACH | Acme Community Bank → Germany Bank #543 | 0.56 |
| 4 | 26856 → 143709 | 9,558.55 Euro | 11,200.55 | ACH | Acme Community Bank → Spain Bank #1392 | 0.18 |
| 5 | 26856 → 236883 | 4,047.19 Swiss Franc | 4,423.16 | ACH | Acme Community Bank → Switzerland Bank #31 | 0.11 |

**Account roles** (6 accounts, strongest first):

- **source** (1): 26856
- **sink** (5): 236729, 67164, 121842, 143709, 236883

Your answers for this item go in the row **R-18** of your answer sheet.

---

## R-21

> Fan-in ring (most likely shape, p = 0.68): 5 accounts, 4 transactions over 20.1 h. Account 98998 was paid by 4 different accounts. Total moved: 34,100 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 21429→98998 (9,830, weight 0.64); 99331→98998 (5,210, weight 0.50); 300474→98998 (14,100, weight 0.23). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 4 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 21429 → 98998 | 8,392.45 Euro | 9,834.13 | ACH | National Bank of the East → Germany Bank #65 | 0.64 |
| 2 | 99331 → 98998 | 4,443.22 Euro | 5,206.49 | ACH | Germany Bank #65 → Germany Bank #65 | 0.50 |
| 3 | 300474 → 98998 | 12,030.97 Euro | 14,097.69 | ACH | Portugal Bank #43 → Germany Bank #65 | 0.23 |
| 4 | 99567 → 98998 | 4,197.12 Euro | 4,918.12 | ACH | Germany Bank #18 → Germany Bank #65 | 0.22 |

**Account roles** (5 accounts, strongest first):

- **source** (4): 21429, 99331, 300474, 99567
- **sink** (1): 98998

Your answers for this item go in the row **R-21** of your answer sheet.

---

## R-07

> Gather-scatter ring (most likely shape, p = 0.22): 3 accounts, 19 transactions over 4.67 days. Total moved: 426,000 (US Dollar). Conservation cannot be measured: no account only sends or only receives. Strongest evidence: 111451→109645 (17,400, weight 0.56); 109645→111451 (16,800, weight 0.56); 109645→111451 (14,000, weight 0.56). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH); that lowered it: how many payments the sender makes. The accounts span 3 banks (Sea Bank, Finland Bank #109, Spain Bank #81).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 111451 → 109645 | 14,840.19 Euro | 17,389.49 | ACH | Finland Bank #109 → Spain Bank #81 | 0.56 |
| 2 | 109645 → 111451 | 14,368.04 Euro | 16,836.23 | ACH | Spain Bank #81 → Finland Bank #109 | 0.56 |
| 3 | 109645 → 111451 | 11,931.69 Euro | 13,981.36 | ACH | Spain Bank #81 → Finland Bank #109 | 0.56 |
| 4 | 109645 → 111451 | 9,136.15 Euro | 10,705.59 | ACH | Spain Bank #81 → Finland Bank #109 | 0.56 |
| 5 | 111451 → 109645 | 1,549.19 Euro | 1,815.32 | ACH | Finland Bank #109 → Spain Bank #81 | 0.55 |

**Account roles** (3 accounts, strongest first):

- **sink** (1): 17870
- **peripheral** (2): 111451, 109645

Your answers for this item go in the row **R-07** of your answer sheet.

---

## R-23

> Fan-out ring (most likely shape, p = 0.42): 3 accounts, 2 transactions over 10.4 h. Account 269684 paid 2 different accounts. Total moved: 27,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 269684→319423 (11,500, weight 0.71); 269684→358035 (15,500, weight 0.61). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks (Mexico Bank #8, China Bank #204, National Bank of Montpelier).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 269684 → 319423 | 243,832.19 Mexican Peso | 11,532.47 | ACH | China Bank #204 → Mexico Bank #8 | 0.71 |
| 2 | 269684 → 358035 | 15,475.69 US Dollar | 15,475.69 | ACH | China Bank #204 → National Bank of Montpelier | 0.61 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 269684
- **sink** (2): 319423, 358035

Your answers for this item go in the row **R-23** of your answer sheet.

---

## R-26

> Fan-out ring (most likely shape, p = 0.91): 9 accounts, 8 transactions over 3.76 days. Account 140096 paid 8 different accounts. Total moved: 1,340,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 140096→69698 (1,250,000, weight 0.85); 140096→423591 (9,290, weight 0.60); 140096→322566 (2,980, weight 0.57). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 9 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 140096 → 69698 | 1,247,008.84 US Dollar | 1,247,008.84 | ACH | Slovenia Bank #460 → Brownstone Community Bank | 0.85 |
| 2 | 140096 → 423591 | 9,291.80 US Dollar | 9,291.80 | ACH | Slovenia Bank #460 → Bank of Arkadelphia | 0.60 |
| 3 | 140096 → 322566 | 2,539.57 Euro | 2,975.83 | ACH | Slovenia Bank #460 → Greece Bank #1330 | 0.57 |
| 4 | 140096 → 381579 | 16,114.69 Swiss Franc | 17,611.68 | ACH | Slovenia Bank #460 → Switzerland Bank #170 | 0.51 |
| 5 | 140096 → 389240 | 11,666.56 Euro | 13,670.68 | ACH | Slovenia Bank #460 → Spain Bank #23 | 0.50 |

**Account roles** (9 accounts, strongest first):

- **source** (1): 140096
- **sink** (8): 69698, 423591, 322566, 389240, 275055, 331536, 381579, 354892

Your answers for this item go in the row **R-26** of your answer sheet.

---

## R-08

> Cycle ring (most likely shape, p = 0.49): 4 accounts, 4 transactions over 46 h. Total moved: 51,100 (US Dollar). 97% of the money sent by the sources reached the sinks. Strongest evidence: 127076→67303 (17,500, weight 0.69); 67303→208963 (16,700, weight 0.69); 208963→110683 (16,700, weight 0.62). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 4 banks (France Bank #28, Italy Bank #73, National Bank of Laramie +1 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 127076 → 67303 | 17,509.45 US Dollar | 17,509.45 | ACH | Italy Bank #73 → National Bank of Laramie | 0.69 |
| 2 | 67303 → 208963 | 21,986.64 Canadian Dollar | 16,665.38 | ACH | National Bank of Laramie → Canada Bank #4 | 0.69 |
| 3 | 208963 → 110683 | 14,222.24 Euro | 16,665.39 | ACH | Canada Bank #4 → France Bank #28 | 0.62 |
| 4 | 208963 → 110683 | 209.51 Euro | 245.50 | ACH | Canada Bank #4 → France Bank #28 | 0.46 |

**Account roles** (4 accounts, strongest first):

- **source** (1): 127076
- **mule** (2): 208963, 67303
- **sink** (1): 110683

Your answers for this item go in the row **R-08** of your answer sheet.

---

## R-13

> Scatter-gather ring (most likely shape, p = 0.62): 9 accounts, 10 transactions over 38.9 h. Total moved: 99,500 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 211499→347162 (16,900, weight 0.67); 429461→347162 (15,900, weight 0.65); 404935→347162 (13,900, weight 0.64). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 9 banks (Arbor Savings Bank, First Bank of Springfield, Italy Bank #304 +6 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 211499 → 347162 | 1,781,903.40 Yen | 16,906.11 | ACH | Canada Bank #4 → Japan Bank #44 | 0.67 |
| 2 | 429461 → 347162 | 1,671,193.57 Yen | 15,855.73 | ACH | Arbor Savings Bank → Japan Bank #44 | 0.65 |
| 3 | 404935 → 347162 | 1,461,046.77 Yen | 13,861.92 | ACH | Spruce Cooperative Bank → Japan Bank #44 | 0.64 |
| 4 | 367050 → 347162 | 1,552,912.19 Yen | 14,733.51 | ACH | India Bank #58 → Japan Bank #44 | 0.62 |
| 5 | 301338 → 347162 | 1,357,453.18 Yen | 12,879.06 | ACH | Italy Bank #304 → Japan Bank #44 | 0.61 |

**Account roles** (9 accounts, strongest first):

- **source** (8): 211499, 404935, 429461, 44637, 367050, 5610, 68182, 301338
- **sink** (1): 347162

Your answers for this item go in the row **R-13** of your answer sheet.

---

## R-16

> Scatter-gather ring (most likely shape, p = 0.63): 6 accounts, 5 transactions over 20.9 h. Total moved: 72,600 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 329697→410512 (19,800, weight 0.71); 329697→436143 (18,500, weight 0.70); 329697→149377 (17,100, weight 0.69). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the sender receives. The accounts span 6 banks (Italy Bank #49, Italy Bank #17, Oasis Community Bank +3 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 329697 → 410512 | 19,845.21 US Dollar | 19,845.21 | ACH | Switzerland Bank #51 → Oasis Community Bank | 0.71 |
| 2 | 329697 → 436143 | 15,757.84 Euro | 18,464.78 | ACH | Switzerland Bank #51 → Italy Bank #17 | 0.70 |
| 3 | 329697 → 149377 | 14,635.16 Euro | 17,149.24 | ACH | Switzerland Bank #51 → Spain Bank #439 | 0.69 |
| 4 | 329697 → 365250 | 7,433.54 UK Pound | 9,601.58 | ACH | Switzerland Bank #51 → UK Bank #61 | 0.65 |
| 5 | 329697 → 99882 | 6,398.44 Euro | 7,497.59 | ACH | Switzerland Bank #51 → Italy Bank #49 | 0.64 |

**Account roles** (6 accounts, strongest first):

- **source** (1): 329697
- **sink** (5): 436143, 149377, 99882, 410512, 365250

Your answers for this item go in the row **R-16** of your answer sheet.

---

## R-27

> Gather-scatter ring (most likely shape, p = 0.32): 3 accounts, 4 transactions over 6.32 days. Total moved: 19,700 (US Dollar). 50% of the money sent by the sources reached the sinks. Strongest evidence: 254055→367905 (1,700, weight 0.58); 254935→367905 (5,180, weight 0.54); 254935→254055 (3,430, weight 0.50). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), money gathered and then scattered by one account; that lowered it: how many payments the sender makes. The accounts span 3 banks (Switzerland Bank #8, Israel Bank #6, Saudi Arabia Bank #5).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 254055 → 367905 | 6,379.01 Saudi Riyal | 1,700.57 | ACH | Switzerland Bank #8 → Saudi Arabia Bank #5 | 0.58 |
| 2 | 254935 → 367905 | 19,428.85 Saudi Riyal | 5,179.51 | ACH | Israel Bank #6 → Saudi Arabia Bank #5 | 0.54 |
| 3 | 254935 → 254055 | 12,859.38 Saudi Riyal | 3,428.16 | ACH | Israel Bank #6 → Switzerland Bank #8 | 0.50 |
| 4 | 367905 → 254055 | 35,150.22 Saudi Riyal | 9,370.64 | ACH | Saudi Arabia Bank #5 → Switzerland Bank #8 | 0.46 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 254935
- **sink** (1): 367905
- **peripheral** (1): 254055

Your answers for this item go in the row **R-27** of your answer sheet.

---

## R-12

> Gather-scatter ring (most likely shape, p = 0.80): 7 accounts, 6 transactions over 4.14 days. Account 432249 gathered money from 2 accounts and passed it on to 4. Total moved: 11,400,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 432249→494201 (11,300,000, weight 0.83); 14332→432249 (17,700, weight 0.56); 364532→432249 (16,300, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 7 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 432249 → 494201 | 9,667,383.73 Euro | 11,328,080.28 | ACH | Spain Bank #9 → Portugal Bank #43 | 0.83 |
| 2 | 14332 → 432249 | 15,146.20 Euro | 17,748.07 | ACH | Hearthstone Savings Bank → Spain Bank #9 | 0.56 |
| 3 | 364532 → 432249 | 13,930.60 Euro | 16,323.65 | ACH | Arbor Savings Bank → Spain Bank #9 | 0.56 |
| 4 | 432249 → 387 | 12,104.04 US Dollar | 12,104.04 | ACH | Spain Bank #9 → National Bank of Laramie | 0.56 |
| 5 | 432249 → 12208 | 3,676.61 US Dollar | 3,676.61 | ACH | Spain Bank #9 → First Bank of Tampa | 0.56 |

**Account roles** (7 accounts, strongest first):

- **source** (3): 432249, 14332, 364532
- **sink** (4): 494201, 107564, 12208, 387

Your answers for this item go in the row **R-12** of your answer sheet.

---

## R-19

> Gather-scatter ring (most likely shape, p = 0.38): 4 accounts, 3 transactions over 47.3 h. Total moved: 41,300 (US Dollar). 78% of the money sent by the sources reached the sinks. Strongest evidence: 429603→223158 (15,900, weight 0.73); 413165→429603 (18,100, weight 0.68); 429603→145009 (7,270, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 4 banks (Bank of the East, Germany Bank #99, Ireland Bank #358 +1 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 429603 → 223158 | 336,915.71 Mexican Peso | 15,935.02 | ACH | Bank of the East → Sunrise Federal Bank | 0.73 |
| 2 | 413165 → 429603 | 18,102.46 US Dollar | 18,102.46 | ACH | Germany Bank #99 → Bank of the East | 0.68 |
| 3 | 429603 → 145009 | 6,206.76 Euro | 7,272.98 | ACH | Bank of the East → Ireland Bank #358 | 0.52 |

**Account roles** (4 accounts, strongest first):

- **source** (1): 413165
- **mule** (1): 429603
- **sink** (2): 223158, 145009

Your answers for this item go in the row **R-19** of your answer sheet.

---

## R-29

> Gather-scatter ring (most likely shape, p = 0.48): 5 accounts, 4 transactions over 35.7 h. Total moved: 35,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 103710→335245 (14,200, weight 0.72); 322225→335245 (9,510, weight 0.66); 161501→335245 (6,620, weight 0.63). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver receives. The accounts span 5 banks (China Bank #2, Spain Bank #23, Italy Bank #73 +2 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 103710 → 335245 | 14,246.13 US Dollar | 14,246.13 | ACH | Spain Bank #23 → National Bank of Huron | 0.72 |
| 2 | 322225 → 335245 | 9,511.58 US Dollar | 9,511.58 | ACH | Italy Bank #97 → National Bank of Huron | 0.66 |
| 3 | 161501 → 335245 | 6,620.88 US Dollar | 6,620.88 | ACH | China Bank #2 → National Bank of Huron | 0.63 |
| 4 | 354270 → 335245 | 4,663.00 US Dollar | 4,663.00 | ACH | Italy Bank #73 → National Bank of Huron | 0.25 |

**Account roles** (5 accounts, strongest first):

- **source** (4): 103710, 322225, 161501, 354270
- **sink** (1): 335245

Your answers for this item go in the row **R-29** of your answer sheet.

---

## R-05

> Scatter-gather ring (most likely shape, p = 0.90): 16 accounts, 33 transactions over 3.88 days. Money spread out from 160150, passed through 351843, 514985, 33128 +11 more and came together at 238203. Total moved: 20,800,000 (US Dollar). 87% of the money sent by the sources reached the sinks. Strongest evidence: 160150→811 (9,560,000, weight 0.77); 811→238203 (11,000,000, weight 0.77); 160150→33128 (16,000, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the receiver being paid by many accounts.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 160150 → 811 | 9,558,773.45 US Dollar | 9,558,773.45 | ACH | China Bank #2 → Bank of Laramie | 0.77 |
| 2 | 811 → 238203 | 10,075,910.88 Swiss Franc | 11,011,924.46 | ACH | Bank of Laramie → Switzerland Bank #10 | 0.77 |
| 3 | 160150 → 33128 | 16,005.33 US Dollar | 16,005.33 | ACH | China Bank #2 → Plandor Savings Bank | 0.60 |
| 4 | 160150 → 218401 | 22,143.08 Australian Dollar | 15,673.19 | ACH | China Bank #2 → Australia Bank #20 | 0.60 |
| 5 | 160150 → 134135 | 10,149.63 Euro | 11,893.17 | ACH | China Bank #2 → Germany Bank #32 | 0.60 |

**Account roles** (16 accounts, strongest first):

- **source** (1): 160150
- **mule** (14): 351843, 514985, 33128, 173224, 134135, 490086, 218401, 52164, 58309, 228377, 811, 144946, 233141, 298415
- **sink** (1): 238203

Your answers for this item go in the row **R-05** of your answer sheet.

---

## R-25

> Scatter-gather ring (most likely shape, p = 0.87): 11 accounts, 11 transactions over 40.2 h. Money spread out from 392207, 12518, 462161 +3 more, passed through 5016, 327494 and came together at 462162, 315018, 101783. Total moved: 113,000 (US Dollar). 97% of the money sent by the sources reached the sinks. Strongest evidence: 392207→5016 (18,900, weight 0.66); 392207→315018 (17,800, weight 0.66); 108368→462162 (15,500, weight 0.64). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 392207 → 5016 | 18,888.26 US Dollar | 18,888.26 | ACH | France Bank #8 → First Bank of Springfield | 0.66 |
| 2 | 392207 → 315018 | 17,840.31 US Dollar | 17,840.31 | ACH | France Bank #8 → National Bank of Pittsburgh | 0.66 |
| 3 | 108368 → 462162 | 15,480.79 US Dollar | 15,480.79 | ACH | France Bank #40 → Plandor Savings Bank | 0.64 |
| 4 | 392207 → 101783 | 3,959.45 Euro | 4,639.62 | ACH | France Bank #8 → China Bank #6 | 0.61 |
| 5 | 8140 → 462162 | 4,352.24 US Dollar | 4,352.24 | ACH | Savings Bank of Miami → Plandor Savings Bank | 0.60 |

**Account roles** (11 accounts, strongest first):

- **source** (6): 392207, 12518, 462161, 108368, 348707, 8140
- **mule** (2): 5016, 327494
- **sink** (3): 462162, 315018, 101783

Your answers for this item go in the row **R-25** of your answer sheet.

---

## R-14

> Gather-scatter ring (most likely shape, p = 0.38): 3 accounts, 2 transactions over 2.03 h. Money starts at 28508 and ends at 3451. Total moved: 11,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 324564→3451 (5,520, weight 0.71); 28508→324564 (5,520, weight 0.43). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the day of the week. The accounts span 3 banks (First Bank of Houston, Bank of the West, Mexico Bank #43).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 324564 → 3451 | 5,517.96 US Dollar | 5,517.96 | ACH | Mexico Bank #43 → Bank of the West | 0.71 |
| 2 | 28508 → 324564 | 116,810.80 Mexican Peso | 5,524.77 | ACH | First Bank of Houston → Mexico Bank #43 | 0.43 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 28508
- **mule** (1): 324564
- **sink** (1): 3451

Your answers for this item go in the row **R-14** of your answer sheet.

---

## R-24

> Layered chain ring (most likely shape, p = 0.83): 3 accounts, 2 transactions over 6.77 h. Funds moved 2 hops from 357666 to 331537 through 222219. Total moved: 2,180 (US Dollar). 96% of the money sent by the sources reached the sinks. Strongest evidence: 357666→222219 (1,110, weight 0.78); 222219→331537 (1,070, weight 0.50). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH); that lowered it: the amount sent, the amount received. The accounts span 3 banks (Desert Bancorp, Bank of Providence, Mexico Bank #15).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 357666 → 222219 | 23,554.37 Mexican Peso | 1,114.05 | ACH | Desert Bancorp → Mexico Bank #15 | 0.78 |
| 2 | 222219 → 331537 | 1,065.19 US Dollar | 1,065.19 | ACH | Mexico Bank #15 → Bank of Providence | 0.50 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 357666
- **mule** (1): 222219
- **sink** (1): 331537

Your answers for this item go in the row **R-24** of your answer sheet.

---

## R-09

> Cycle ring (most likely shape, p = 0.67): 6 accounts, 6 transactions over 37.2 h. Total moved: 74,400 (US Dollar). 87% of the money sent by the sources reached the sinks. Strongest evidence: 150726→3783 (14,700, weight 0.63); 3783→416247 (14,100, weight 0.63); 416247→285818 (14,100, weight 0.54). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver makes. The accounts span 6 banks (First Bank of Indianapolis, Plandor Trust Bank, Italy Bank #293 +3 more).

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 150726 → 3783 | 14,655.44 US Dollar | 14,655.44 | ACH | Italy Bank #293 → Plandor Trust Bank | 0.63 |
| 2 | 3783 → 416247 | 10,911.78 UK Pound | 14,094.27 | ACH | Plandor Trust Bank → UK Bank #1 | 0.63 |
| 3 | 416247 → 285818 | 14,094.27 US Dollar | 14,094.27 | ACH | UK Bank #1 → First Bank of Indianapolis | 0.54 |
| 4 | 215901 → 287169 | 16,409.59 US Dollar | 16,409.59 | ACH | Australia Bank #18 → First Bank of New Orleans | 0.52 |
| 5 | 287169 → 150726 | 12,715.37 Euro | 14,899.66 | ACH | First Bank of New Orleans → Italy Bank #293 | 0.39 |

**Account roles** (6 accounts, strongest first):

- **source** (1): 215901
- **mule** (4): 416247, 287169, 150726, 3783
- **sink** (1): 285818

Your answers for this item go in the row **R-09** of your answer sheet.

---

## R-02

> Fan-out ring (most likely shape, p = 0.33): 3 accounts, 9 transactions over 2.48 days. Account 257831 paid 2 different accounts. Total moved: 65,500 (US Dollar). 38% of the money sent by the sources reached the sinks. Strongest evidence: 309496→257831 (5,270, weight 0.62); 309496→309497 (16,900, weight 0.61); 309496→309497 (8,370, weight 0.56). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH), the currency it was sent in (Saudi Riyal). The accounts span 2 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 309496 → 257831 | 19,776.22 Saudi Riyal | 5,272.11 | ACH | Saudi Arabia Bank #10 → Saudi Arabia Bank #10 | 0.62 |
| 2 | 309496 → 309497 | 63,212.42 Saudi Riyal | 16,851.70 | ACH | Saudi Arabia Bank #10 → Saudi Arabia Bank #37 | 0.61 |
| 3 | 309496 → 309497 | 31,405.92 Saudi Riyal | 8,372.46 | ACH | Saudi Arabia Bank #10 → Saudi Arabia Bank #37 | 0.56 |
| 4 | 309497 → 257831 | 14,744.79 Saudi Riyal | 3,930.79 | ACH | Saudi Arabia Bank #37 → Saudi Arabia Bank #10 | 0.53 |
| 5 | 257831 → 309497 | 17,973.58 Saudi Riyal | 4,791.55 | ACH | Saudi Arabia Bank #10 → Saudi Arabia Bank #37 | 0.53 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 257831
- **sink** (1): 309497
- **peripheral** (1): 309496

Your answers for this item go in the row **R-02** of your answer sheet.

---

## R-04

> Fan-out ring (most likely shape, p = 0.70): 3 accounts, 4 transactions over 34.4 h. Account 257870 paid 2 different accounts. Total moved: 3,790,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 257871→257871 (3,770,000, weight 0.99); 257871→255084 (8,350, weight 0.59); 257870→257871 (7,210, weight 0.59). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH), the currency it was sent in (Saudi Riyal). The accounts span 3 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 257871 → 257871 | 14,144,807.18 Saudi Riyal | 3,770,842.47 | ACH | Israel Bank #6 → Israel Bank #6 | 0.99 |
| 2 | 257871 → 255084 | 31,324.25 Saudi Riyal | 8,350.68 | ACH | Israel Bank #6 → Saudi Arabia Bank #5 | 0.59 |
| 3 | 257870 → 257871 | 27,043.63 Saudi Riyal | 7,209.52 | ACH | Saudi Arabia Bank #68 → Israel Bank #6 | 0.59 |
| 4 | 257870 → 255084 | 28,341.71 Saudi Riyal | 7,555.57 | ACH | Saudi Arabia Bank #68 → Saudi Arabia Bank #5 | 0.56 |

**Account roles** (3 accounts, strongest first):

- **source** (1): 257870
- **sink** (2): 257871, 255084

Your answers for this item go in the row **R-04** of your answer sheet.

---

## R-30

> Scatter-gather ring (most likely shape, p = 0.67): 5 accounts, 7 transactions over 3.14 days. Money spread out from 103618, passed through 10978 and came together at 311675, 3061, 397884. Total moved: 51,800 (US Dollar). 98% of the money sent by the sources reached the sinks. Strongest evidence: 103618→10978 (15,000, weight 0.67); 10978→311675 (14,400, weight 0.60); 103618→3061 (3,820, weight 0.59). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 5 banks.

**Top 5 evidence transactions** (strongest first):

| # | from → to | amount received | ≈ US Dollar | payment | from bank → to bank | weight |
|---|---|---|---|---|---|---|
| 1 | 103618 → 10978 | 14,983.77 US Dollar | 14,983.77 | ACH | China Bank #6 → Arbor Savings Bank | 0.67 |
| 2 | 10978 → 311675 | 12,249.73 Euro | 14,354.03 | ACH | Arbor Savings Bank → Italy Bank #95 | 0.60 |
| 3 | 103618 → 3061 | 3,816.20 US Dollar | 3,816.20 | ACH | China Bank #6 → Savings Bank of Seattle | 0.59 |
| 4 | 103618 → 397884 | 6,312.29 Euro | 7,396.64 | ACH | China Bank #6 → Austria Bank #20 | 0.52 |
| 5 | 3061 → 311675 | 2,907.58 Euro | 3,407.05 | ACH | Savings Bank of Seattle → Italy Bank #95 | 0.33 |

**Account roles** (5 accounts, strongest first):

- **source** (1): 103618
- **mule** (1): 10978
- **sink** (3): 311675, 3061, 397884

Your answers for this item go in the row **R-30** of your answer sheet.

---
