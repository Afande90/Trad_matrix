Short clock bars and volume bars: fading the last bar earns a little, and that little is smaller than the fee. The fifteen-minute and one-hour clock bars, and the one-hour volume bar, show nothing.
Futures versus spot: when futures are unusually cheap, the next hour's rise is a little bigger than the 0.0009 fee, and bigger than the 0.0006 fee too. The other gap readings are smaller than the fee, or show nothing.
Bitcoin and ether a minute apart: a tiny link, smaller than the fee.
A big move tends to be followed by another big move. That is calm or violent, not up or down, so it is not a fee test.
The first ten seconds of each quarter hour: a small link, smaller than the fee.
Extreme funding can move more than the fee, but the evidence is too weak, so it counts as smaller than the fee. A sharp change in open interest shows a link, and it is smaller than the fee.

| frame | measure | n | gross effect per trade | fee 0.0009 | effect / fee | t-stat on daily totals | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 5m clock correlation, this bar's return with the next -0.0383 | 210238 | — | — | — | -11 | not an up-or-down trade |
| 0 | 5m clock, follow the last bar, held one bar | 210073 | -3.83105e-05 | 0.0009 | -0.0426 | -6.9 | real but smaller than the fee |
| 0 | 5m clock, fade the last bar, held one bar | 210073 | 3.83105e-05 | 0.0009 | 0.0426 | 6.9 | real but smaller than the fee |
| 0 | 15m clock correlation, this bar's return with the next 0.0012 | 70078 | — | — | — | -3.8 | not an up-or-down trade |
| 0 | 15m clock, follow the last bar, held one bar | 70041 | 3.06591e-06 | 0.0009 | 0.00341 | 0.21 | nothing |
| 0 | 15m clock, fade the last bar, held one bar | 70041 | -3.06591e-06 | 0.0009 | -0.00341 | -0.21 | nothing |
| 3 | 15m clock correlation of the size of one move with the size of the next 0.3102 | 70078 | — | — | — | 23 | not an up-or-down trade |
| 0 | 60m clock correlation, this bar's return with the next 0.0040 | 17518 | — | — | — | -6.2 | not an up-or-down trade |
| 0 | 60m clock, follow the last bar, held one bar | 17513 | 3.75255e-05 | 0.0009 | 0.0417 | 0.66 | nothing |
| 0 | 60m clock, fade the last bar, held one bar | 17513 | -3.75255e-05 | 0.0009 | -0.0417 | -0.66 | nothing |
| 3 | 60m clock correlation of the size of one move with the size of the next 0.2257 | 17518 | — | — | — | 3.7 | not an up-or-down trade |
| 1 | volume bar aimed at 5m (average 5.0m) correlation, this bar's return with the next -0.0193 | 210237 | — | — | — | -11 | not an up-or-down trade |
| 1 | volume bar aimed at 5m (average 5.0m), follow the last bar, held one bar | 210096 | -4.96132e-05 | 0.0009 | -0.0551 | -8.8 | real but smaller than the fee |
| 1 | volume bar aimed at 5m (average 5.0m), fade the last bar, held one bar | 210096 | 4.96132e-05 | 0.0009 | 0.0551 | 8.8 | real but smaller than the fee |
| 1 | volume bar aimed at 15m (average 15.0m) correlation, this bar's return with the next -0.0216 | 70077 | — | — | — | -9.3 | not an up-or-down trade |
| 1 | volume bar aimed at 15m (average 15.0m), follow the last bar, held one bar | 70049 | -8.08256e-05 | 0.0009 | -0.0898 | -5.2 | real but smaller than the fee |
| 1 | volume bar aimed at 15m (average 15.0m), fade the last bar, held one bar | 70049 | 8.08256e-05 | 0.0009 | 0.0898 | 5.2 | real but smaller than the fee |
| 1 | volume bar aimed at 60m (average 60.0m) correlation, this bar's return with the next -0.0224 | 17517 | — | — | — | -8.6 | not an up-or-down trade |
| 1 | volume bar aimed at 60m (average 60.0m), follow the last bar, held one bar | 17515 | -2.81644e-06 | 0.0009 | -0.00313 | -0.048 | nothing |
| 1 | volume bar aimed at 60m (average 60.0m), fade the last bar, held one bar | 17515 | 2.81644e-06 | 0.0009 | 0.00313 | 0.048 | nothing |
| 2 | futures-spot gap in the top 10%, long the next 15m | 104985 | -0.000110749 | 0.0009 | -0.123 | -1.9 | nothing |
| 2 | futures-spot gap in the top 10%, short the next 15m | 104985 | 0.000110749 | 0.0009 | 0.123 | 1.9 | nothing |
| 2 | futures-spot gap in the bottom 10%, long the next 15m | 104985 | 0.000301935 | 0.0009 | 0.335 | 6.3 | real but smaller than the fee |
| 2 | futures-spot gap in the bottom 10%, short the next 15m | 104985 | -0.000301935 | 0.0009 | -0.335 | -6.3 | real but smaller than the fee |
| 2 | futures-spot gap in the top 10%, long the next 60m | 104980 | -0.0004746 | 0.0009 | -0.527 | -2.3 | real but smaller than the fee |
| 2 | futures-spot gap in the top 10%, short the next 60m | 104980 | 0.0004746 | 0.0009 | 0.527 | 2.3 | real but smaller than the fee |
| 2 | futures-spot gap in the bottom 10%, long the next 60m | 104980 | 0.000987689 | 0.0009 | 1.1 | 5.6 | bigger than the fee - worth ONE strategy test |
| 2 | futures-spot gap in the bottom 10%, short the next 60m | 104980 | -0.000987689 | 0.0009 | -1.1 | -5.6 | real but smaller than the fee |
| 2 | ETH last minute, BTC next minute correlation 0.0110 | 1051198 | — | — | — | -0.77 | nothing |
| 2 | ETH last minute, BTC next minute, follow it, held one minute | 1046922 | 5.46257e-06 | 0.0009 | 0.00607 | 3.8 | real but smaller than the fee |
| 2 | BTC last minute, ETH next minute correlation 0.0233 | 1051198 | — | — | — | -0.93 | nothing |
| 2 | BTC last minute, ETH next minute, follow it, held one minute | 1047955 | 5.67272e-06 | 0.0009 | 0.0063 | 2.8 | real but smaller than the fee |
| 4 | quarter-hour buy share and the next 1h correlation 0.0152 | 68664 | — | — | — | 0.54 | nothing |
| 4 | quarter-hour buy share, follow it, next 1h | 68664 | 0.000115333 | 0.0009 | 0.128 | 3.3 | real but smaller than the fee |
| 4 | quarter-hour buy share and the next 4h correlation 0.0175 | 68652 | — | — | — | -2.6 | not an up-or-down trade |
| 4 | quarter-hour buy share, follow it, next 4h | 68652 | 0.000288964 | 0.0009 | 0.321 | 3.7 | real but smaller than the fee |
| 4 | funding rate in the top 10%, long the next 8h | 219 | 0.00125962 | 0.0009 | 1.4 | 0.71 | nothing |
| 4 | funding rate in the top 10%, short the next 8h | 219 | -0.00125962 | 0.0009 | -1.4 | -0.71 | nothing |
| 4 | funding rate in the bottom 10%, long the next 8h | 219 | 0.00394083 | 0.0009 | 4.38 | 2.2 | real but smaller than the fee |
| 4 | funding rate in the bottom 10%, short the next 8h | 219 | -0.00394083 | 0.0009 | -4.38 | -2.2 | real but smaller than the fee |
| 4 | open interest 1h rise in the top 10%, long the next 1h | 20930 | 0.000520693 | 0.0009 | 0.579 | 2.6 | real but smaller than the fee |
| 4 | open interest 1h rise in the top 10%, short the next 1h | 20930 | -0.000520693 | 0.0009 | -0.579 | -2.6 | real but smaller than the fee |
| 4 | open interest 1h fall in the bottom 10%, long the next 1h | 20930 | 0.000427608 | 0.0009 | 0.475 | 2.2 | real but smaller than the fee |
| 4 | open interest 1h fall in the bottom 10%, short the next 1h | 20930 | -0.000427608 | 0.0009 | -0.475 | -2.2 | real but smaller than the fee |

44 rows were measured. With this many rows, one or two will look good by luck. That is why the bar is |t| >= 3.5.

Diagnostic on a seen period. Shows where to look. Not evidence of profit. Any idea from this table must be frozen and tested once on 2025-01 to 2026-10.

The monthly open-interest zip returns 404. The daily metrics archive for this period was used instead.
