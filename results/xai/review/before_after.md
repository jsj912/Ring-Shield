# The 30 reviewed narratives, before and after the review fixes (Week 8)

Before = exactly as the reviewers read it (their packet). After = the current explanation (explainer 0.5.0-review). Weights, evidence ranking and fidelity are unchanged; only the wording moved.

30 of 30 narratives changed (the scope words reach almost every narrative). Per fix — A1 shape stated as a guess: 14 of 19 flagged items, 14 of 30 overall; scope words: 18 of 19 flagged items, 29 of 30 overall; self-payment not cited: 1 of 19 flagged items, 1 of 30 overall.

## R-01

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-out ring (most likely shape, p = 0.60): 5 accounts, 5 transactions over 29.4 h. Account 508502 paid 4 different accounts. Total moved: 1,010,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 508502→64105 (917,000, weight 0.96); 508502→64105 (81,600, weight 0.63); 508502→389499 (8,000, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH); that lowered it: the amount sent, the amount received. The accounts span 5 banks.

**After:** Fan-out ring (most likely shape, p = 0.60): 5 accounts, 5 transactions over 29.4 h. Across the ring's 5 transactions, account 508502 paid 4 different accounts. Total moved: 1,010,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 508502→64105 (917,000, weight 0.96); 508502→64105 (81,600, weight 0.63); 508502→389499 (8,000, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH); that lowered it: the amount sent, the amount received. The accounts span 5 banks.

## R-02

Reviewers (majority): misleading, shape implausible. Fixes applied: scope words.

**Before:** Fan-out ring (most likely shape, p = 0.33): 3 accounts, 9 transactions over 2.48 days. Account 257831 paid 2 different accounts. Total moved: 65,500 (US Dollar). 38% of the money sent by the sources reached the sinks. Strongest evidence: 309496→257831 (5,270, weight 0.62); 309496→309497 (16,900, weight 0.61); 309496→309497 (8,370, weight 0.56). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH), the currency it was sent in (Saudi Riyal). The accounts span 2 banks.

**After:** Fan-out ring (most likely shape, p = 0.33): 3 accounts, 9 transactions over 2.48 days. Across the ring's 9 transactions, account 257831 paid 2 different accounts. Total moved: 65,500 (US Dollar). Across the ring, 38% of the sources' money reached the sinks. Strongest evidence: 309496→257831 (5,270, weight 0.62); 309496→309497 (16,900, weight 0.61); 309496→309497 (8,370, weight 0.56). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH), the currency it was sent in (Saudi Riyal). The accounts span 2 banks.

## R-03

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Gather-scatter ring (most likely shape, p = 0.39): 7 accounts, 7 transactions over 41.2 h. Total moved: 56,500 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 99051→267860 (16,100, weight 0.67); 274972→267860 (5,690, weight 0.60); 337905→267860 (16,400, weight 0.58). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the receiver being paid by many accounts. The accounts span 5 banks (Finland Bank #0, National Bank of the East, China Bank #6 +2 more).

**After:** Suspected ring: 7 accounts, 7 transactions over 41.2 h. The typing model's most likely shape is gather-scatter (p = 0.39), but the ring's transactions do not show that shape. Total moved: 56,500 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 99051→267860 (16,100, weight 0.67); 274972→267860 (5,690, weight 0.60); 337905→267860 (16,400, weight 0.58). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the receiver being paid by many accounts. The accounts span 5 banks.

## R-04

Reviewers (majority): misleading, shape implausible. Fixes applied: scope words, self-payment not cited.

**Before:** Fan-out ring (most likely shape, p = 0.70): 3 accounts, 4 transactions over 34.4 h. Account 257870 paid 2 different accounts. Total moved: 3,790,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 257871→257871 (3,770,000, weight 0.99); 257871→255084 (8,350, weight 0.59); 257870→257871 (7,210, weight 0.59). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH), the currency it was sent in (Saudi Riyal). The accounts span 3 banks.

**After:** Fan-out ring (most likely shape, p = 0.70): 3 accounts, 4 transactions over 34.4 h. Across the ring's 4 transactions, account 257870 paid 2 different accounts. Total moved: 3,790,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 257871→255084 (8,350, weight 0.59); 257870→257871 (7,210, weight 0.59); 257870→255084 (7,560, weight 0.56). One stronger-ranked payment from an account to itself is not cited.

## R-05

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.90): 16 accounts, 33 transactions over 3.88 days. Money spread out from 160150, passed through 351843, 514985, 33128 +11 more and came together at 238203. Total moved: 20,800,000 (US Dollar). 87% of the money sent by the sources reached the sinks. Strongest evidence: 160150→811 (9,560,000, weight 0.77); 811→238203 (11,000,000, weight 0.77); 160150→33128 (16,000, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the receiver being paid by many accounts.

**After:** Scatter-gather ring (most likely shape, p = 0.90): 16 accounts, 33 transactions over 3.88 days. Across the ring's 33 transactions, money spread from account 160150 to 14 accounts and gathered at account 238203. Total moved: 20,800,000 (US Dollar). Across the ring, 87% of the sources' money reached the sinks. Strongest evidence: 160150→811 (9,560,000, weight 0.77); 811→238203 (11,000,000, weight 0.77); 160150→33128 (16,000, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the receiver being paid by many accounts.

## R-06

Reviewers (majority): misleading, shape implausible. Fixes applied: scope words.

**Before:** Fan-in ring (most likely shape, p = 0.28): 5 accounts, 6 transactions over 21.8 h. Account 137509 was paid by 2 different accounts. Total moved: 28,800 (US Dollar). 97% of the money sent by the sources reached the sinks. Strongest evidence: 210231→137509 (8,460, weight 0.68); 33496→213191 (7,450, weight 0.66); 33496→213191 (760, weight 0.57). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 5 banks.

**After:** Fan-in ring (most likely shape, p = 0.28): 5 accounts, 6 transactions over 21.8 h. Across the ring's 6 transactions, account 137509 was paid by 2 different accounts. Total moved: 28,800 (US Dollar). Across the ring, 97% of the sources' money reached the sinks. Strongest evidence: 210231→137509 (8,460, weight 0.68); 33496→213191 (7,450, weight 0.66); 33496→213191 (760, weight 0.57). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 5 banks.

## R-07

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess.

**Before:** Gather-scatter ring (most likely shape, p = 0.22): 3 accounts, 19 transactions over 4.67 days. Total moved: 426,000 (US Dollar). Conservation cannot be measured: no account only sends or only receives. Strongest evidence: 111451→109645 (17,400, weight 0.56); 109645→111451 (16,800, weight 0.56); 109645→111451 (14,000, weight 0.56). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH); that lowered it: how many payments the sender makes. The accounts span 3 banks (Sea Bank, Finland Bank #109, Spain Bank #81).

**After:** Suspected ring: 3 accounts, 19 transactions over 4.67 days. The typing model's most likely shape is gather-scatter (p = 0.22), but the ring's transactions do not show that shape. Total moved: 426,000 (US Dollar). Conservation cannot be measured: no account only sends or only receives. Strongest evidence: 111451→109645 (17,400, weight 0.56); 109645→111451 (16,800, weight 0.56); 109645→111451 (14,000, weight 0.56). Signals from a reference transaction-level model that raised suspicion: money gathered and then scattered by one account, the payment method (ACH); that lowered it: how many payments the sender makes.

## R-08

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Cycle ring (most likely shape, p = 0.49): 4 accounts, 4 transactions over 46 h. Total moved: 51,100 (US Dollar). 97% of the money sent by the sources reached the sinks. Strongest evidence: 127076→67303 (17,500, weight 0.69); 67303→208963 (16,700, weight 0.69); 208963→110683 (16,700, weight 0.62). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 4 banks (France Bank #28, Italy Bank #73, National Bank of Laramie +1 more).

**After:** Suspected ring: 4 accounts, 4 transactions over 46 h. The typing model's most likely shape is cycle (p = 0.49), but the ring's transactions do not show that shape. Total moved: 51,100 (US Dollar). Across the ring, 97% of the sources' money reached the sinks. Strongest evidence: 127076→67303 (17,500, weight 0.69); 67303→208963 (16,700, weight 0.69); 208963→110683 (16,700, weight 0.62). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 4 banks.

## R-09

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Cycle ring (most likely shape, p = 0.67): 6 accounts, 6 transactions over 37.2 h. Total moved: 74,400 (US Dollar). 87% of the money sent by the sources reached the sinks. Strongest evidence: 150726→3783 (14,700, weight 0.63); 3783→416247 (14,100, weight 0.63); 416247→285818 (14,100, weight 0.54). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver makes. The accounts span 6 banks (First Bank of Indianapolis, Plandor Trust Bank, Italy Bank #293 +3 more).

**After:** Suspected ring: 6 accounts, 6 transactions over 37.2 h. The typing model's most likely shape is cycle (p = 0.67), but the ring's transactions do not show that shape. Total moved: 74,400 (US Dollar). Across the ring, 87% of the sources' money reached the sinks. Strongest evidence: 150726→3783 (14,700, weight 0.63); 3783→416247 (14,100, weight 0.63); 416247→285818 (14,100, weight 0.54). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver makes. The accounts span 6 banks.

## R-10

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.56): 6 accounts, 5 transactions over 12.8 h. Total moved: 53,200 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 176079→44567 (8,390, weight 0.50); 176079→10376 (4,280, weight 0.40); 176079→333657 (10,600, weight 0.30). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 6 banks (Russia Bank #16, Japan Bank #8, First Bank of Arkadelphia +3 more).

**After:** Suspected ring: 6 accounts, 5 transactions over 12.8 h. The typing model's most likely shape is scatter-gather (p = 0.56), but the ring's transactions do not show that shape. Total moved: 53,200 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 176079→44567 (8,390, weight 0.50); 176079→10376 (4,280, weight 0.40); 176079→333657 (10,600, weight 0.30). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 6 banks.

## R-11

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.64): 11 accounts, 12 transactions over 25.1 h. Total moved: 115,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 425012→84086 (17,000, weight 0.64); 165499→84086 (16,300, weight 0.57); 270966→84086 (5,810, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver receives. The accounts span 11 banks (National Bank of Laramie (10), Acme Federal Bank, Spruce Trust Bank +8 more).

**After:** Suspected ring: 11 accounts, 12 transactions over 25.1 h. The typing model's most likely shape is scatter-gather (p = 0.64), but the ring's transactions do not show that shape. Total moved: 115,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 425012→84086 (17,000, weight 0.64); 165499→84086 (16,300, weight 0.57); 270966→84086 (5,810, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver receives. The accounts span 11 banks.

## R-12

Reviewers (majority): misleading. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Gather-scatter ring (most likely shape, p = 0.80): 7 accounts, 6 transactions over 4.14 days. Account 432249 gathered money from 2 accounts and passed it on to 4. Total moved: 11,400,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 432249→494201 (11,300,000, weight 0.83); 14332→432249 (17,700, weight 0.56); 364532→432249 (16,300, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 7 banks.

**After:** Suspected ring: 7 accounts, 6 transactions over 4.14 days. The typing model's most likely shape is gather-scatter (p = 0.80), but the ring's transactions do not show that shape. Total moved: 11,400,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 432249→494201 (11,300,000, weight 0.83); 14332→432249 (17,700, weight 0.56); 364532→432249 (16,300, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 7 banks.

## R-13

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.62): 9 accounts, 10 transactions over 38.9 h. Total moved: 99,500 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 211499→347162 (16,900, weight 0.67); 429461→347162 (15,900, weight 0.65); 404935→347162 (13,900, weight 0.64). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 9 banks (Arbor Savings Bank, First Bank of Springfield, Italy Bank #304 +6 more).

**After:** Suspected ring: 9 accounts, 10 transactions over 38.9 h. The typing model's most likely shape is scatter-gather (p = 0.62), but the ring's transactions do not show that shape. Total moved: 99,500 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 211499→347162 (16,900, weight 0.67); 429461→347162 (15,900, weight 0.65); 404935→347162 (13,900, weight 0.64). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 9 banks.

## R-14

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Gather-scatter ring (most likely shape, p = 0.38): 3 accounts, 2 transactions over 2.03 h. Money starts at 28508 and ends at 3451. Total moved: 11,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 324564→3451 (5,520, weight 0.71); 28508→324564 (5,520, weight 0.43). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the day of the week. The accounts span 3 banks (First Bank of Houston, Bank of the West, Mexico Bank #43).

**After:** Suspected ring: 3 accounts, 2 transactions over 2.03 h. The typing model's most likely shape is gather-scatter (p = 0.38), but the ring's transactions do not show that shape. Total moved: 11,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 324564→3451 (5,520, weight 0.71); 28508→324564 (5,520, weight 0.43). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the day of the week. The accounts span 3 banks.

## R-15

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Layered chain ring (most likely shape, p = 0.70): 3 accounts, 2 transactions over 3.35 h. Funds moved 2 hops from 112157 to 238336 through 307838. Total moved: 13,000 (US Dollar). 99% of the money sent by the sources reached the sinks. Strongest evidence: 112157→307838 (6,550, weight 0.64); 307838→238336 (6,490, weight 0.63). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: how many payments the receiver makes. The accounts span 3 banks.

**After:** Layered chain ring (most likely shape, p = 0.70): 3 accounts, 2 transactions over 3.35 h. Across the ring's 2 transactions, funds moved along a chain of 2 hops. Total moved: 13,000 (US Dollar). Across the ring, 99% of the sources' money reached the sinks. Strongest evidence: 112157→307838 (6,550, weight 0.64); 307838→238336 (6,490, weight 0.63). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: how many payments the receiver makes. The accounts span 3 banks.

## R-16

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.63): 6 accounts, 5 transactions over 20.9 h. Total moved: 72,600 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 329697→410512 (19,800, weight 0.71); 329697→436143 (18,500, weight 0.70); 329697→149377 (17,100, weight 0.69). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the sender receives. The accounts span 6 banks (Italy Bank #49, Italy Bank #17, Oasis Community Bank +3 more).

**After:** Suspected ring: 6 accounts, 5 transactions over 20.9 h. The typing model's most likely shape is scatter-gather (p = 0.63), but the ring's transactions do not show that shape. Total moved: 72,600 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 329697→410512 (19,800, weight 0.71); 329697→436143 (18,500, weight 0.70); 329697→149377 (17,100, weight 0.69). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the sender receives. The accounts span 6 banks.

## R-17

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Layered chain ring (most likely shape, p = 0.62): 3 accounts, 2 transactions over 9.15 h. Funds moved 2 hops from 246668 to 18175 through 108402. Total moved: 36,300 (US Dollar). 96% of the money sent by the sources reached the sinks. Strongest evidence: 108402→18175 (17,700, weight 0.71); 246668→108402 (18,500, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks.

**After:** Layered chain ring (most likely shape, p = 0.62): 3 accounts, 2 transactions over 9.15 h. Across the ring's 2 transactions, funds moved along a chain of 2 hops. Total moved: 36,300 (US Dollar). Across the ring, 96% of the sources' money reached the sinks. Strongest evidence: 108402→18175 (17,700, weight 0.71); 246668→108402 (18,500, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks.

## R-18

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-out ring (most likely shape, p = 0.89): 6 accounts, 5 transactions over 36.8 h. Account 26856 paid 5 different accounts. Total moved: 47,200 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 26856→236729 (18,500, weight 0.69); 26856→67164 (6,650, weight 0.56); 26856→121842 (6,450, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 6 banks.

**After:** Fan-out ring (most likely shape, p = 0.89): 6 accounts, 5 transactions over 36.8 h. Across the ring's 5 transactions, account 26856 paid 5 different accounts. Total moved: 47,200 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 26856→236729 (18,500, weight 0.69); 26856→67164 (6,650, weight 0.56); 26856→121842 (6,450, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 6 banks.

## R-19

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Gather-scatter ring (most likely shape, p = 0.38): 4 accounts, 3 transactions over 47.3 h. Total moved: 41,300 (US Dollar). 78% of the money sent by the sources reached the sinks. Strongest evidence: 429603→223158 (15,900, weight 0.73); 413165→429603 (18,100, weight 0.68); 429603→145009 (7,270, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 4 banks (Bank of the East, Germany Bank #99, Ireland Bank #358 +1 more).

**After:** Suspected ring: 4 accounts, 3 transactions over 47.3 h. The typing model's most likely shape is gather-scatter (p = 0.38), but the ring's transactions do not show that shape. Total moved: 41,300 (US Dollar). Across the ring, 78% of the sources' money reached the sinks. Strongest evidence: 429603→223158 (15,900, weight 0.73); 413165→429603 (18,100, weight 0.68); 429603→145009 (7,270, weight 0.52). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 4 banks.

## R-20

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-out ring (most likely shape, p = 0.67): 16 accounts, 15 transactions over 2.95 days. Account 138280 paid 15 different accounts. Total moved: 107,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 138280→3257 (17,000, weight 0.56); 138280→67641 (15,200, weight 0.56); 138280→228248 (501, weight 0.54). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the sender receives. The accounts span 16 banks (India Bank #0, Brazil Bank #7, Brazil Bank #6 +13 more).

**After:** Fan-out ring (most likely shape, p = 0.67): 16 accounts, 15 transactions over 2.95 days. Across the ring's 15 transactions, account 138280 paid 15 different accounts. Total moved: 107,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 138280→3257 (17,000, weight 0.56); 138280→67641 (15,200, weight 0.56); 138280→228248 (501, weight 0.54). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the sender receives. The accounts span 16 banks.

## R-21

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-in ring (most likely shape, p = 0.68): 5 accounts, 4 transactions over 20.1 h. Account 98998 was paid by 4 different accounts. Total moved: 34,100 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 21429→98998 (9,830, weight 0.64); 99331→98998 (5,210, weight 0.50); 300474→98998 (14,100, weight 0.23). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 4 banks.

**After:** Fan-in ring (most likely shape, p = 0.68): 5 accounts, 4 transactions over 20.1 h. Across the ring's 4 transactions, account 98998 was paid by 4 different accounts. Total moved: 34,100 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 21429→98998 (9,830, weight 0.64); 99331→98998 (5,210, weight 0.50); 300474→98998 (14,100, weight 0.23). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 4 banks.

## R-22

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Cycle ring (most likely shape, p = 0.80): 8 accounts, 10 transactions over 44.4 h. Total moved: 40,600 (US Dollar). 98% of the money sent by the sources reached the sinks. Strongest evidence: 306715→353064 (6,060, weight 0.62); 376861→421565 (5,840, weight 0.61); 127330→414802 (5,370, weight 0.61). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 8 banks (Germany Bank #65, Savings Bank of Los Angeles, Italy Bank #1106 +5 more).

**After:** Suspected ring: 8 accounts, 10 transactions over 44.4 h. The typing model's most likely shape is cycle (p = 0.80), but the ring's transactions do not show that shape. Total moved: 40,600 (US Dollar). Across the ring, 98% of the sources' money reached the sinks. Strongest evidence: 306715→353064 (6,060, weight 0.62); 376861→421565 (5,840, weight 0.61); 127330→414802 (5,370, weight 0.61). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 8 banks.

## R-23

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-out ring (most likely shape, p = 0.42): 3 accounts, 2 transactions over 10.4 h. Account 269684 paid 2 different accounts. Total moved: 27,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 269684→319423 (11,500, weight 0.71); 269684→358035 (15,500, weight 0.61). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks (Mexico Bank #8, China Bank #204, National Bank of Montpelier).

**After:** Fan-out ring (most likely shape, p = 0.42): 3 accounts, 2 transactions over 10.4 h. Across the ring's 2 transactions, account 269684 paid 2 different accounts. Total moved: 27,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 269684→319423 (11,500, weight 0.71); 269684→358035 (15,500, weight 0.61). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks.

## R-24

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Layered chain ring (most likely shape, p = 0.83): 3 accounts, 2 transactions over 6.77 h. Funds moved 2 hops from 357666 to 331537 through 222219. Total moved: 2,180 (US Dollar). 96% of the money sent by the sources reached the sinks. Strongest evidence: 357666→222219 (1,110, weight 0.78); 222219→331537 (1,070, weight 0.50). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH); that lowered it: the amount sent, the amount received. The accounts span 3 banks (Desert Bancorp, Bank of Providence, Mexico Bank #15).

**After:** Layered chain ring (most likely shape, p = 0.83): 3 accounts, 2 transactions over 6.77 h. Across the ring's 2 transactions, funds moved along a chain of 2 hops. Total moved: 2,180 (US Dollar). Across the ring, 96% of the sources' money reached the sinks. Strongest evidence: 357666→222219 (1,110, weight 0.78); 222219→331537 (1,070, weight 0.50). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH); that lowered it: the amount sent, the amount received. The accounts span 3 banks (Desert Bancorp, Bank of Providence, Mexico Bank #15).

## R-25

Reviewers (majority): misleading. Fixes applied: scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.87): 11 accounts, 11 transactions over 40.2 h. Money spread out from 392207, 12518, 462161 +3 more, passed through 5016, 327494 and came together at 462162, 315018, 101783. Total moved: 113,000 (US Dollar). 97% of the money sent by the sources reached the sinks. Strongest evidence: 392207→5016 (18,900, weight 0.66); 392207→315018 (17,800, weight 0.66); 108368→462162 (15,500, weight 0.64). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day.

**After:** Scatter-gather ring (most likely shape, p = 0.87): 11 accounts, 11 transactions over 40.2 h. Across the ring's 11 transactions, money spread from account 392207 to 4 accounts and gathered at account 462162. Total moved: 113,000 (US Dollar). Across the ring, 97% of the sources' money reached the sinks. Strongest evidence: 392207→5016 (18,900, weight 0.66); 392207→315018 (17,800, weight 0.66); 108368→462162 (15,500, weight 0.64). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day.

## R-26

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-out ring (most likely shape, p = 0.91): 9 accounts, 8 transactions over 3.76 days. Account 140096 paid 8 different accounts. Total moved: 1,340,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 140096→69698 (1,250,000, weight 0.85); 140096→423591 (9,290, weight 0.60); 140096→322566 (2,980, weight 0.57). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 9 banks.

**After:** Fan-out ring (most likely shape, p = 0.91): 9 accounts, 8 transactions over 3.76 days. Across the ring's 8 transactions, account 140096 paid 8 different accounts. Total moved: 1,340,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 140096→69698 (1,250,000, weight 0.85); 140096→423591 (9,290, weight 0.60); 140096→322566 (2,980, weight 0.57). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 9 banks.

## R-27

Reviewers (majority): misleading. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Gather-scatter ring (most likely shape, p = 0.32): 3 accounts, 4 transactions over 6.32 days. Total moved: 19,700 (US Dollar). 50% of the money sent by the sources reached the sinks. Strongest evidence: 254055→367905 (1,700, weight 0.58); 254935→367905 (5,180, weight 0.54); 254935→254055 (3,430, weight 0.50). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), money gathered and then scattered by one account; that lowered it: how many payments the sender makes. The accounts span 3 banks (Switzerland Bank #8, Israel Bank #6, Saudi Arabia Bank #5).

**After:** Suspected ring: 3 accounts, 4 transactions over 6.32 days. The typing model's most likely shape is gather-scatter (p = 0.32), but the ring's transactions do not show that shape. Total moved: 19,700 (US Dollar). Across the ring, 50% of the sources' money reached the sinks. Strongest evidence: 254055→367905 (1,700, weight 0.58); 254935→367905 (5,180, weight 0.54); 254935→254055 (3,430, weight 0.50). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), money gathered and then scattered by one account; that lowered it: how many payments the sender makes.

## R-28

Reviewers (majority): not flagged. Fixes applied: scope words.

**Before:** Fan-in ring (most likely shape, p = 0.39): 5 accounts, 6 transactions over 28.8 h. Account 317176 was paid by 3 different accounts. Total moved: 33,900 (US Dollar). 99% of the money sent by the sources reached the sinks. Strongest evidence: 384222→412261 (2,280, weight 0.62); 31627→317176 (8,610, weight 0.61); 31627→317176 (247, weight 0.51). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 5 banks.

**After:** Fan-in ring (most likely shape, p = 0.39): 5 accounts, 6 transactions over 28.8 h. Across the ring's 6 transactions, account 317176 was paid by 3 different accounts. Total moved: 33,900 (US Dollar). Across the ring, 99% of the sources' money reached the sinks. Strongest evidence: 384222→412261 (2,280, weight 0.62); 31627→317176 (8,610, weight 0.61); 31627→317176 (247, weight 0.51). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the amount sent. The accounts span 5 banks.

## R-29

Reviewers (majority): misleading, shape implausible. Fixes applied: A1 shape stated as a guess, scope words.

**Before:** Gather-scatter ring (most likely shape, p = 0.48): 5 accounts, 4 transactions over 35.7 h. Total moved: 35,000 (US Dollar). 100% of the money sent by the sources reached the sinks. Strongest evidence: 103710→335245 (14,200, weight 0.72); 322225→335245 (9,510, weight 0.66); 161501→335245 (6,620, weight 0.63). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver receives. The accounts span 5 banks (China Bank #2, Spain Bank #23, Italy Bank #73 +2 more).

**After:** Suspected ring: 5 accounts, 4 transactions over 35.7 h. The typing model's most likely shape is gather-scatter (p = 0.48), but the ring's transactions do not show that shape. Total moved: 35,000 (US Dollar). Across the ring, 100% of the sources' money reached the sinks. Strongest evidence: 103710→335245 (14,200, weight 0.72); 322225→335245 (9,510, weight 0.66); 161501→335245 (6,620, weight 0.63). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths, how many payments the receiver receives. The accounts span 5 banks.

## R-30

Reviewers (majority): misleading. Fixes applied: scope words.

**Before:** Scatter-gather ring (most likely shape, p = 0.67): 5 accounts, 7 transactions over 3.14 days. Money spread out from 103618, passed through 10978 and came together at 311675, 3061, 397884. Total moved: 51,800 (US Dollar). 98% of the money sent by the sources reached the sinks. Strongest evidence: 103618→10978 (15,000, weight 0.67); 10978→311675 (14,400, weight 0.60); 103618→3061 (3,820, weight 0.59). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 5 banks.

**After:** Scatter-gather ring (most likely shape, p = 0.67): 5 accounts, 7 transactions over 3.14 days. Across the ring's 7 transactions, money spread from account 103618 to 3 accounts and gathered at account 311675. Total moved: 51,800 (US Dollar). Across the ring, 98% of the sources' money reached the sinks. Strongest evidence: 103618→10978 (15,000, weight 0.67); 10978→311675 (14,400, weight 0.60); 103618→3061 (3,820, weight 0.59). Signals from a reference transaction-level model that raised suspicion: the payment method (ACH), two-hop scatter-gather paths; that lowered it: the hour of the day.
