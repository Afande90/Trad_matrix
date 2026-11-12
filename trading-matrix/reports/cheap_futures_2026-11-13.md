This stopped on the years already seen. The 2025 and 2026 holdout was not opened.
Of the six settings, P2 4h had the highest result after a doubled fee.
Even that best setting loses money once the fee is doubled, so the gate stopped the test.
On those same holds the futures price rose about 0.00132239 and the spot price rose about 0.000934746, so most of that rise was the price itself.
Buying the same number of times at random minutes made about -0.001246 after costs.
No further variants. rule_sets_tried stays 3.

Kept variant: P2 4h.
STOPPED AT STEP 1 - holdout untouched

Step 1. Seen period 2020-12-01 to 2022-10-31. November 2020 is warm-up for the 30-day window only.

| variant | trades | days with trades | gross mean | net mean | net mean at cost x2 | share of months with positive net | worst single trade | kept |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P10 1h | 6509 | 575 | 0.000454874 | -0.000751819 | -0.00195182 | 0.174 | -0.0792845 |  |
| P10 4h | 2257 | 572 | 0.000573683 | -0.000662457 | -0.00186246 | 0.435 | -0.10367 |  |
| P5 1h | 4585 | 535 | 0.000680181 | -0.000525114 | -0.00172511 | 0.391 | -0.0792845 |  |
| P5 4h | 1790 | 533 | 0.000993183 | -0.000236271 | -0.00143627 | 0.435 | -0.10367 |  |
| P2 1h | 2782 | 468 | 0.000988351 | -0.000215148 | -0.00141515 | 0.522 | -0.0864015 |  |
| P2 4h | 1231 | 466 | 0.00132239 | 9.7275e-05 | -0.00110272 | 0.522 | -0.097545 | yes |

Train controls for P2 4h: truncation identical: yes; RANDOM LONG net -0.001246 on 1231 of 1231 trades (seed 3558); spot mean over the same holds 0.000934746; PEEK net 0.00538207 on 3213 trades; missing futures minutes 0 of 1008000.
Cost is 0.0012 per trade (taker in, taker out, spread 0.0001, slippage 0.0001). Funding is applied on top and is not doubled when the cost is doubled. Cost x2 is 0.0024.
Share of months uses every calendar month in the seen window. A month with no trades counts as not positive.

DECISION: STOPPED AT STEP 1 - holdout untouched
Checklist Step 4 was not applied. Only a holdout can decide CONTINUE, and this holdout was not loaded.

No further variants. Stop.
