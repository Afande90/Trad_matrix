This is the one holdout of the frozen cheap-futures rule. Nothing was traded.
All three fee levels are STOP as built.
No fee case is cleared for paper tracking.
The futures were a bit cheap, and the next four hours rose on average, but that rise was smaller than every fee.
Buying the same number of times at random minutes lost more. Ending the data one day earlier changed nothing.
Nothing from 2026 was loaded.

Holdout 2025-01-01 to 2025-12-31. December 2024 is warm-up for the 30-day window only. K = 1 frozen rule × 5 rule sets = 5. z = 3.09. The same trades are shown at three fees. Funding is charged once and is not doubled.

| fee | trades | days | NOT_FILLED | fill winners | fill losers | gross mean | net mean | net_lb | net at double cost | net at triple cost | RANDOM net | RANDOM placed | cumulative net % | largest drop from a peak % | worst trade | longest losing streak | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | 952 | 322 | 107 | 0.902 | 0.896 | 0.000348348 | -0.000569422 | -0.0044686 | -0.00146942 | -0.00236942 | -0.0013979 | 952 of 952 | -54.209 | 66.477 | -0.0493704 | 10 | STOP as built |
| F2 | 952 | 322 | 107 | 0.902 | 0.896 | 0.000348348 | -0.000269422 | -0.0036856 | -0.000869422 | -0.00146942 | -0.0010979 | 952 of 952 | -25.649 | 43.227 | -0.0490704 | 10 | STOP as built |
| F3 | 952 | 322 | 107 | 0.902 | 0.896 | 0.000348348 | -6.94222e-05 | -0.00316467 | -0.000469422 | -0.000869422 | -0.0008979 | 952 of 952 | -6.609 | 27.727 | -0.0488704 | 10 | STOP as built |

Net by month. A month with no trades is 0.

| month | F1 | F2 | F3 |
| --- | --- | --- | --- |
| 2025-01 | -0.0162723 | 0.0107277 | 0.0287277 |
| 2025-02 | -0.206643 | -0.176943 | -0.157143 |
| 2025-03 | -0.0443404 | -0.0179404 | -0.000340381 |
| 2025-04 | 0.0934952 | 0.120495 | 0.138495 |
| 2025-05 | 0.0117405 | 0.0246405 | 0.0332405 |
| 2025-06 | -0.0765363 | -0.0465363 | -0.0265363 |
| 2025-07 | -0.00335099 | 0.00504901 | 0.010649 |
| 2025-08 | -0.10744 | -0.0774405 | -0.0574405 |
| 2025-09 | 0.00277785 | 0.0315778 | 0.0507778 |
| 2025-10 | -0.215217 | -0.189717 | -0.172717 |
| 2025-11 | -0.0444015 | -0.0243015 | -0.0109015 |
| 2025-12 | 0.0640982 | 0.0838982 | 0.0970982 |

Truncation test: identical: yes. Signal mismatches 0, fill mismatches 0 on 41758 minutes whose three-minute window ends before 2025-12-30.
RANDOM LONG uses the same number of filled limits per month, seed 3558. Clearly better means the rule's net is higher and the daily difference stays positive after z = 3.09.
F1 versus random: higher=True, difference net_lb=-0.00037147, matched=True, clearly better=False.
F1 flags: more than half the positive net sits in one month.
F1 peek net 0.00304204 on 1602 oracle trades.
F2 versus random: higher=True, difference net_lb=-0.000366228, matched=True, clearly better=False.
F2 flags: none.
F2 peek net 0.00311887 on 1642 oracle trades.
F3 versus random: higher=True, difference net_lb=-0.000364079, matched=True, clearly better=False.
F3 flags: none.
F3 peek net 0.00319226 on 1672 oracle trades.
Missing futures minutes 0 of 525600 (0). Futures minutes without a spot close: 0.
Entry is a limit at the signal close. It counts only when a later trade prints at least one tick through that price within 3 minutes. Same-candle cases: 0. The exit is the open four hours after the fill.
Costs are above zero on every counted trade. F1 is 0.0009, F2 is 0.0006, F3 is 0.0004, each including spread 0.0001 and slippage 0.0001. Ledger row written 2026-11-13 04:23 Asia/Dubai before any 2025 price was read. Rules hash 8ad10eceed1e.
Step 4 is read from the top. CONTINUE needs at least 300 trades over 60 days, net_lb > 0, a positive average after the fee is doubled, and a clear win over buying at random minutes, with no unexplained flag and the profit not piled in one month. CONTINUE is paper tracking only, never real money.
rule_sets_tried is 5. Written 2026-11-13 04:33 Asia/Dubai.
