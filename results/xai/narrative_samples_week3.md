# Week 3 narrative review -- PILOT (7 rings; not the spec's 30-ring review, no kappa)

One matched ring per predicted pattern type (highest type probability; all five seeds). For each, read
the narrative against the evidence and roles shown, and answer the four questions of spec section 7 (0/1).
The true pattern types are at the very end: do not read them before answering.

## FAN-OUT — `full-gine_causal-1-4` (detector seed 1, p = 0.92)

> Fan-out ring (most likely shape, p = 0.92): 10 accounts, 9 transactions over 2.57 days. Account 513343 paid 9 different accounts. Total moved: 433,000 in currency 0. 100% of the money sent by the sources reached the sinks. Strongest evidence: 513343→33859 (296,000, weight 0.87); 513343→178251 (59,200, weight 0.65); 513343→142719 (18,100, weight 0.62). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths; that lowered it: the sender paying many accounts. The accounts span 10 banks (8, 6625, 10709 +7 more).

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 513343→33859 (edge 4625172) | 295,519.18 | 0 | 0.873 | 1.000 | 1.000 | 0.682 |
| 2 | 513343→178251 (edge 5077306) | 6,242,980.34 | 6 | 0.655 | 1.000 | 1.000 | 0.137 |
| 3 | 513343→142719 (edge 4976577) | 15,470.19 | 2 | 0.617 | 1.000 | 1.000 | 0.042 |
| 4 | 513343→130209 (edge 5077438) | 15,177.78 | 2 | 0.616 | 1.000 | 1.000 | 0.041 |
| 5 | 513343→213067 (edge 4942163) | 22,190.66 | 10 | 0.616 | 1.000 | 1.000 | 0.039 |

Roles: **sink** 33859, 178251, 142719, 130209, 255560, 162696, 445862, 183077, 213067; **source** 513343

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

## FAN-IN — `full-gine_causal-2-33` (detector seed 2, p = 0.80)

> Fan-in ring (most likely shape, p = 0.80): 14 accounts, 13 transactions over 3.3 days. Account 424000 was paid by 13 different accounts. Total moved: 136,000 in currency 0. 100% of the money sent by the sources reached the sinks. Strongest evidence: 150728→424000 (9,360, weight 0.63); 201321→424000 (18,600, weight 0.62); 318762→424000 (959, weight 0.60). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths; that lowered it: the amount received. The accounts span 14 banks (210, 1688, 9571 +11 more).

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 150728→424000 (edge 5078052) | 9,356.44 | 0 | 0.627 | 1.000 | 1.000 | 0.069 |
| 2 | 201321→424000 (edge 5077787) | 18,630.53 | 0 | 0.623 | 0.947 | 0.985 | 0.137 |
| 3 | 318762→424000 (edge 5078012) | 958.79 | 0 | 0.603 | 1.000 | 1.000 | 0.007 |
| 4 | 212805→424000 (edge 4985969) | 17,176.41 | 0 | 0.596 | 0.909 | 0.975 | 0.126 |
| 5 | 295990→424000 (edge 5077558) | 12,588.20 | 0 | 0.582 | 0.909 | 0.975 | 0.092 |

Roles: **sink** 424000; **source** 201321, 295990, 150728, 404330, 297531, 318762, 212805, 365244, 40620, 349872, 274010, 11122, 162930

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

## GATHER-SCATTER — `full-gine_causal-4-113` (detector seed 4, p = 0.91)

> Gather-scatter ring (most likely shape, p = 0.91): 11 accounts, 10 transactions over 44 h. Account 101027 gathered money from 7 accounts and passed it on to 3. Total moved: 96,200 in currency 0. 47% of the money sent by the sources reached the sinks. Strongest evidence: 359250→101027 (19,200, weight 0.67); 55735→101027 (11,800, weight 0.64); 396301→101027 (6,120, weight 0.62). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths, how many payments the receiver makes. The accounts span 11 banks (11, 110, 795 +8 more).

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 359250→101027 (edge 4971451) | 16,418.79 | 2 | 0.666 | 0.976 | 0.672 | 0.200 |
| 2 | 55735→101027 (edge 4792993) | 10,054.02 | 2 | 0.645 | 0.993 | 0.672 | 0.123 |
| 3 | 396301→101027 (edge 4565636) | 5,223.87 | 2 | 0.621 | 0.993 | 0.672 | 0.064 |
| 4 | 419269→101027 (edge 4964197) | 1,209.80 | 2 | 0.591 | 0.976 | 0.672 | 0.015 |
| 5 | 19779→101027 (edge 4528310) | 1,099.53 | 2 | 0.591 | 0.976 | 0.672 | 0.013 |

Roles: **peripheral** 101027; **sink** 267067, 435225, 345491; **source** 396301, 419269, 478429, 19779, 359250, 55735, 435926

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

## SCATTER-GATHER — `full-gine_causal-3-64` (detector seed 3, p = 0.93)

> Scatter-gather ring (most likely shape, p = 0.93): 14 accounts, 21 transactions over 3.07 days. Money spread out from 1744, 160789, 378724 +5 more, passed through 315197, 184170, 124947 +2 more and came together at 18018. Total moved: 173,000 in currency 0. 100% of the money sent by the sources reached the sinks. Strongest evidence: 378724→124947 (19,300, weight 0.64); 124947→18018 (20,200, weight 0.64); 161906→18018 (15,300, weight 0.62). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths; that lowered it: the hour of the day.

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 378724→124947 (edge 4544669) | 16,497.64 | 2 | 0.645 | 1.000 | 0.000 | 0.112 |
| 2 | 124947→18018 (edge 5077571) | 20,182.57 | 0 | 0.635 | 0.981 | 0.000 | 0.116 |
| 3 | 161906→18018 (edge 5077318) | 15,291.64 | 0 | 0.624 | 0.981 | 1.000 | 0.088 |
| 4 | 378724→315197 (edge 4558455) | 6,593.51 | 0 | 0.615 | 1.000 | 0.013 | 0.038 |
| 5 | 378724→318443 (edge 4483495) | 41,375.79 | 4 | 0.614 | 1.000 | 0.000 | 0.036 |

Roles: **mule** 315197, 184170, 124947, 198316, 318443; **sink** 18018; **source** 1744, 160789, 378724, 103022, 292683, 161906, 30276, 3216

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

## CYCLE — `full-gine_causal-4-89` (detector seed 4, p = 0.86)

> Cycle ring (most likely shape, p = 0.86): 8 accounts, 10 transactions over 41.9 h. Money starts at 434804 and ends at 362002. Total moved: 89,900,000 in currency 0. 94% of the money sent by the sources reached the sinks. Strongest evidence: 109599→29819 (13,100,000, weight 0.64); 434804→26743 (12,700,000, weight 0.57); 26743→111131 (12,700,000, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 8 banks (1299, 1522, 2439 +5 more).

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 109599→29819 (edge 5077427) | 13,144,322.64 | 0 | 0.644 | 0.976 | 0.093 | 0.146 |
| 2 | 434804→26743 (edge 5015846) | 12,650,338.17 | 0 | 0.567 | 0.851 | 0.906 | 0.141 |
| 3 | 26743→111131 (edge 5024892) | 10,795,798.60 | 2 | 0.561 | 0.841 | 0.043 | 0.141 |
| 4 | 26743→111131 (edge 5024891) | 450,510.99 | 2 | 0.410 | 0.680 | 0.000 | 0.006 |
| 5 | 35113→187255 (edge 5077604) | 876,934,779.34 | 5 | 0.367 | 0.523 | 0.859 | 0.133 |

Roles: **mule** 29819, 187255, 35113, 26743, 111131, 109599; **sink** 362002; **source** 434804

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

## RANDOM — `full-gine_causal-1-74` (detector seed 1, p = 0.62)

> Irregular ring (most likely shape, p = 0.62): 6 accounts, 7 transactions over 42.1 h. Money starts at 142289 and ends at 382858. Total moved: 36,200 in currency 0. 98% of the money sent by the sources reached the sinks. Strongest evidence: 254465→25691 (7,080, weight 0.64); 267241→254465 (7,080, weight 0.60); 254465→25691 (121, weight 0.56). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 6 banks (10, 223, 1601 +3 more).

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 254465→25691 (edge 5027488) | 7,079.07 | 0 | 0.638 | 0.933 | 0.439 | 0.196 |
| 2 | 267241→254465 (edge 4436061) | 26,554.30 | 13 | 0.602 | 0.873 | 0.514 | 0.196 |
| 3 | 254465→25691 (edge 5027487) | 120.57 | 0 | 0.561 | 0.933 | 0.017 | 0.003 |
| 4 | 142289→315151 (edge 4249914) | 7,225.51 | 0 | 0.544 | 0.773 | 0.451 | 0.200 |
| 5 | 25691→382858 (edge 5036055) | 7,104.28 | 0 | 0.542 | 0.773 | 0.451 | 0.196 |

Roles: **mule** 254465, 267241, 25691, 315151; **sink** 382858; **source** 142289

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

## BIPARTITE

_No matched ring of this predicted type in any seed._

## STACK — `full-gine_causal-4-31` (detector seed 4, p = 0.86)

> Layered chain ring (most likely shape, p = 0.86): 3 accounts, 3 transactions over 2.1 days. Funds moved 2 hops from 345917 to 338513 through 388928. Total moved: 20,900 in currency 0. 99% of the money sent by the sources reached the sinks. Strongest evidence: 345917→388928 (10,400, weight 0.78); 388928→338513 (10,400, weight 0.70); 388928→338513 (103, weight 0.23). Signals from a reference transaction-level model that raised suspicion: the payment method, two-hop scatter-gather paths; that lowered it: the hour of the day. The accounts span 3 banks (10, 1547, 1686).

| # | transaction | amount (received) | currency | w_total | w_score | w_loo | w_flow |
|---|---|---|---|---|---|---|---|
| 1 | 345917→388928 (edge 4910252) | 10,388.14 | 0 | 0.785 | 0.976 | 1.000 | 0.498 |
| 2 | 388928→338513 (edge 5077673) | 808,238.64 | 9 | 0.704 | 0.841 | 0.105 | 0.498 |
| 3 | 388928→338513 (edge 5077672) | 7,980.31 | 9 | 0.235 | 0.388 | 0.000 | 0.005 |

Roles: **mule** 388928; **sink** 338513; **source** 345917

Reviewer answers (0/1): topology plausible __ · named accounts matter __ · evidence enough to start __ · anything misleading __

---

## Answer key (read after reviewing)

| predicted type | ring | true pattern type | Jaccard with the truth ring |
|---|---|---|---|
| FAN-OUT | `full-gine_causal-1-4` | FAN-OUT | 1.00 |
| FAN-IN | `full-gine_causal-2-33` | FAN-IN | 1.00 |
| GATHER-SCATTER | `full-gine_causal-4-113` | GATHER-SCATTER | 0.91 |
| SCATTER-GATHER | `full-gine_causal-3-64` | SCATTER-GATHER | 0.92 |
| CYCLE | `full-gine_causal-4-89` | CYCLE | 1.00 |
| RANDOM | `full-gine_causal-1-74` | CYCLE | 1.00 |
| STACK | `full-gine_causal-4-31` | CYCLE | 1.00 |
