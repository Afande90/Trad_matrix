This looks at old prices only. Nothing was traded, and a profit is not shown.
Four cases stayed positive after the fee was doubled, each with at least 100 trades: the 5% gap held 4 hours at the lowest fee, and the 2% gap held 1 hour at the lowest fee or 4 hours at either of the two lower fees. The ordinary fee did not.
In every setting the limit filled a little more often on trades that would have made money (0.719 to 0.869) than on trades that would have lost (0.691 to 0.865).
Buys at random minutes lost money at the ordinary fee. P10 4h placed 2171 of 2193. Cutting the tape one day earlier changed nothing.
On gold, silver, oil and the currencies, 48 measures showed nothing and 18 were real but smaller than the cost. 12 others only say that a large move tends to be followed by another large move, not which way.
No gold, silver, oil or currency measure was both strong and larger than its cost.
Gold versus silver, after an unusually high or low ratio, did not pay over the next 4 hours. The euro and the pound barely predict each other's next minute, and that sliver is far smaller than the spread.
Binance gold and silver futures were skipped: there is no price history before the sealed window, so they are too short to judge.

Part A. Bitcoin cheap futures, limit entry, seen period 2020-12-01 to 2022-10-31. November 2020 is warm-up only. The holdout was not opened.

| variant | fee | trades | NOT_FILLED | fill rate winners | fill rate losers | gross mean | net mean | net mean at double cost | share of months positive | worst trade | double cost still positive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P10 1h | F1 | 6225 | 1190 | 0.842 | 0.836 | 0.000324959 | -0.000582047 | -0.00148205 | 0.261 | -0.0767283 |  |
| P10 1h | F2 | 6225 | 1190 | 0.842 | 0.836 | 0.000324959 | -0.000282047 | -0.000882047 | 0.391 | -0.0764283 |  |
| P10 1h | F3 | 6225 | 1190 | 0.842 | 0.836 | 0.000324959 | -8.20471e-05 | -0.000482047 | 0.522 | -0.0762283 |  |
| P10 4h | F1 | 2193 | 918 | 0.719 | 0.691 | 0.000419407 | -0.000517527 | -0.00141753 | 0.435 | -0.12803 |  |
| P10 4h | F2 | 2193 | 918 | 0.719 | 0.691 | 0.000419407 | -0.000217527 | -0.000817527 | 0.435 | -0.12773 |  |
| P10 4h | F3 | 2193 | 918 | 0.719 | 0.691 | 0.000419407 | -1.75268e-05 | -0.000417527 | 0.435 | -0.12753 |  |
| P5 1h | F1 | 4368 | 747 | 0.860 | 0.847 | 0.000547949 | -0.00035772 | -0.00125772 | 0.435 | -0.104401 |  |
| P5 1h | F2 | 4368 | 747 | 0.860 | 0.847 | 0.000547949 | -5.77197e-05 | -0.00065772 | 0.522 | -0.104101 |  |
| P5 1h | F3 | 4368 | 747 | 0.860 | 0.847 | 0.000547949 | 0.00014228 | -0.00025772 | 0.565 | -0.103901 |  |
| P5 4h | F1 | 1738 | 563 | 0.772 | 0.738 | 0.00100321 | 7.28956e-05 | -0.000827104 | 0.478 | -0.108794 |  |
| P5 4h | F2 | 1738 | 563 | 0.772 | 0.738 | 0.00100321 | 0.000372896 | -0.000227104 | 0.565 | -0.108494 |  |
| P5 4h | F3 | 1738 | 563 | 0.772 | 0.738 | 0.00100321 | 0.000572896 | 0.000172896 | 0.652 | -0.108294 | yes |
| P2 1h | F1 | 2640 | 405 | 0.869 | 0.865 | 0.000929715 | 2.59071e-05 | -0.000874093 | 0.565 | -0.0767283 |  |
| P2 1h | F2 | 2640 | 405 | 0.869 | 0.865 | 0.000929715 | 0.000325907 | -0.000274093 | 0.652 | -0.0764283 |  |
| P2 1h | F3 | 2640 | 405 | 0.869 | 0.865 | 0.000929715 | 0.000525907 | 0.000125907 | 0.696 | -0.0762283 | yes |
| P2 4h | F1 | 1189 | 300 | 0.820 | 0.778 | 0.00124757 | 0.000321451 | -0.000578549 | 0.565 | -0.0980931 |  |
| P2 4h | F2 | 1189 | 300 | 0.820 | 0.778 | 0.00124757 | 0.000621451 | 2.14507e-05 | 0.609 | -0.0977931 | yes |
| P2 4h | F3 | 1189 | 300 | 0.820 | 0.778 | 0.00124757 | 0.000821451 | 0.000421451 | 0.609 | -0.0975931 | yes |

A row marked yes has a positive average after the fee is doubled and at least 100 counted trades. Funding is charged once and is not doubled. F1 is 0.0009, F2 is 0.0006, F3 is 0.0004, each including spread 0.0001 and slippage 0.0001. Share of months uses all 23 calendar months from December 2020 through October 2022. A month with no trades is not positive.

RANDOM LONG, same number of filled limits per month, seed 3558.

| variant | placed | seed | F1 net | F2 net | F3 net |
| --- | --- | --- | --- | --- | --- |
| P10 1h | 6225 of 6225 | 3558 | -0.000915124 | -0.000615124 | -0.000415124 |
| P10 4h | 2171 of 2193 | 3565 | -0.000839582 | -0.000539582 | -0.000339582 |
| P5 1h | 4368 of 4368 | 3558 | -0.000932546 | -0.000632546 | -0.000432546 |
| P5 4h | 1738 of 1738 | 3565 | -0.000630068 | -0.000330068 | -0.000130068 |
| P2 1h | 2640 of 2640 | 3558 | -0.000913261 | -0.000613261 | -0.000413261 |
| P2 4h | 1189 of 1189 | 3558 | -0.00104226 | -0.000742262 | -0.000542262 |

Truncation test, data cut one day later versus one day earlier: identical: yes. Signal mismatches 0, fill mismatches 0 on 41758 minutes whose three-minute window ends before 2022-10-30.

Part B. Gold, silver, light crude and three currencies, 2022-01-01 to 2023-12-31. One row per measure.

| instrument | measure | n | gross effect per trade | cost | effect / cost | t-stat on daily totals | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gold | 5m, follow the last bar, held one bar | 141203 | -4.4958e-06 | 0.000260991 | -0.0172258 | -3.09088 | real but smaller than the cost |
| Gold | 5m, fade the last bar, held one bar | 141203 | 4.4958e-06 | 0.000260991 | 0.0172258 | 3.09088 | real but smaller than the cost |
| Gold | 15m, follow the last bar, held one bar | 47037 | -2.10567e-06 | 0.000260991 | -0.00806797 | -0.495083 | nothing |
| Gold | 15m, fade the last bar, held one bar | 47037 | 2.10567e-06 | 0.000260991 | 0.00806797 | 0.495083 | nothing |
| Gold | 15m correlation of the size of one move with the size of the next 0.2665 | 47037 | — | — | — | 20.086 | not an up-or-down trade |
| Gold | after a top-10% 15m move, follow it, next 1h | 5672 | -9.35454e-07 | 0.000260991 | -0.00358423 | -0.0247217 | nothing |
| Gold | after a top-10% 15m move, fade it, next 1h | 5672 | 9.35454e-07 | 0.000260991 | 0.00358423 | 0.0247217 | nothing |
| Gold | 60m, follow the last bar, held one bar | 11683 | 2.25233e-07 | 0.000260991 | 0.00086299 | 0.0141928 | nothing |
| Gold | 60m, fade the last bar, held one bar | 11683 | -2.25233e-07 | 0.000260991 | -0.00086299 | -0.0141928 | nothing |
| Gold | 60m correlation of the size of one move with the size of the next 0.2523 | 11683 | — | — | — | 13.6572 | not an up-or-down trade |
| Gold | follow the first 15m after 07:00 UTC, next 4h | 514 | 0.000157711 | 0.000260991 | 0.604278 | 1.0938 | nothing |
| Gold | follow the first 15m after 13:30 UTC, next 4h | 513 | -0.000175263 | 0.000260991 | -0.671527 | -0.766058 | nothing |
| Silver | 5m, follow the last bar, held one bar | 136198 | -1.02525e-05 | 0.00139211 | -0.00736474 | -3.38727 | real but smaller than the cost |
| Silver | 5m, fade the last bar, held one bar | 136198 | 1.02525e-05 | 0.00139211 | 0.00736474 | 3.38727 | real but smaller than the cost |
| Silver | 15m, follow the last bar, held one bar | 46145 | -1.56253e-05 | 0.00139211 | -0.0112242 | -1.76014 | nothing |
| Silver | 15m, fade the last bar, held one bar | 46145 | 1.56253e-05 | 0.00139211 | 0.0112242 | 1.76014 | nothing |
| Silver | 15m correlation of the size of one move with the size of the next 0.2631 | 46145 | — | — | — | 20.6066 | not an up-or-down trade |
| Silver | after a top-10% 15m move, follow it, next 1h | 5573 | 2.16362e-05 | 0.00139211 | 0.0155421 | 0.27386 | nothing |
| Silver | after a top-10% 15m move, fade it, next 1h | 5573 | -2.16362e-05 | 0.00139211 | -0.0155421 | -0.27386 | nothing |
| Silver | 60m, follow the last bar, held one bar | 11574 | -4.4362e-05 | 0.00139211 | -0.0318667 | -1.31357 | nothing |
| Silver | 60m, fade the last bar, held one bar | 11574 | 4.4362e-05 | 0.00139211 | 0.0318667 | 1.31357 | nothing |
| Silver | 60m correlation of the size of one move with the size of the next 0.2254 | 11574 | — | — | — | 12.553 | not an up-or-down trade |
| Silver | follow the first 15m after 07:00 UTC, next 4h | 510 | 0.000508712 | 0.00139211 | 0.365425 | 1.77665 | nothing |
| Silver | follow the first 15m after 13:30 UTC, next 4h | 512 | 0.000118583 | 0.00139211 | 0.0851819 | 0.258565 | nothing |
| Light crude | 5m, follow the last bar, held one bar | 137720 | -1.59557e-05 | 0.000680971 | -0.0234309 | -3.82265 | real but smaller than the cost |
| Light crude | 5m, fade the last bar, held one bar | 137720 | 1.59557e-05 | 0.000680971 | 0.0234309 | 3.82265 | real but smaller than the cost |
| Light crude | 15m, follow the last bar, held one bar | 46412 | -9.97853e-06 | 0.000680971 | -0.0146534 | -0.822667 | nothing |
| Light crude | 15m, fade the last bar, held one bar | 46412 | 9.97853e-06 | 0.000680971 | 0.0146534 | 0.822667 | nothing |
| Light crude | 15m correlation of the size of one move with the size of the next 0.2884 | 46412 | — | — | — | 22.4063 | not an up-or-down trade |
| Light crude | after a top-10% 15m move, follow it, next 1h | 5706 | 0.000134312 | 0.000680971 | 0.197236 | 1.2421 | nothing |
| Light crude | after a top-10% 15m move, fade it, next 1h | 5706 | -0.000134312 | 0.000680971 | -0.197236 | -1.2421 | nothing |
| Light crude | 60m, follow the last bar, held one bar | 11593 | 3.47509e-06 | 0.000680971 | 0.00510314 | 0.0655726 | nothing |
| Light crude | 60m, fade the last bar, held one bar | 11593 | -3.47509e-06 | 0.000680971 | -0.00510314 | -0.0655726 | nothing |
| Light crude | 60m correlation of the size of one move with the size of the next 0.2744 | 11593 | — | — | — | 14.9745 | not an up-or-down trade |
| Light crude | follow the first 15m after 07:00 UTC, next 4h | 512 | 0.000128338 | 0.000680971 | 0.188464 | 0.261761 | nothing |
| Light crude | follow the first 15m after 13:30 UTC, next 4h | 512 | -0.00022973 | 0.000680971 | -0.337357 | -0.33366 | nothing |
| EURUSD | 5m, follow the last bar, held one bar | 147614 | -3.19036e-06 | 0.000107883 | -0.0295723 | -3.63385 | real but smaller than the cost |
| EURUSD | 5m, fade the last bar, held one bar | 147614 | 3.19036e-06 | 0.000107883 | 0.0295723 | 3.63385 | real but smaller than the cost |
| EURUSD | 15m, follow the last bar, held one bar | 49463 | -1.06614e-05 | 0.000107883 | -0.0988235 | -3.99666 | real but smaller than the cost |
| EURUSD | 15m, fade the last bar, held one bar | 49463 | 1.06614e-05 | 0.000107883 | 0.0988235 | 3.99666 | real but smaller than the cost |
| EURUSD | 15m correlation of the size of one move with the size of the next 0.2637 | 49463 | — | — | — | 20.264 | not an up-or-down trade |
| EURUSD | after a top-10% 15m move, follow it, next 1h | 5702 | -3.61416e-05 | 0.000107883 | -0.335006 | -1.74557 | nothing |
| EURUSD | after a top-10% 15m move, fade it, next 1h | 5702 | 3.61416e-05 | 0.000107883 | 0.335006 | 1.74557 | nothing |
| EURUSD | 60m, follow the last bar, held one bar | 12316 | -1.87853e-05 | 0.000107883 | -0.174126 | -1.6998 | nothing |
| EURUSD | 60m, fade the last bar, held one bar | 12316 | 1.87853e-05 | 0.000107883 | 0.174126 | 1.6998 | nothing |
| EURUSD | 60m correlation of the size of one move with the size of the next 0.2444 | 12316 | — | — | — | 15.8239 | not an up-or-down trade |
| EURUSD | follow the first 15m after 07:00 UTC, next 4h | 520 | 2.53809e-05 | 0.000107883 | 0.235262 | 0.215774 | nothing |
| EURUSD | follow the first 15m after 13:30 UTC, next 4h | 518 | 1.04688e-05 | 0.000107883 | 0.0970382 | 0.0776293 | nothing |
| GBPUSD | 5m, follow the last bar, held one bar | 147951 | -3.85962e-06 | 0.000158842 | -0.0242984 | -3.71537 | real but smaller than the cost |
| GBPUSD | 5m, fade the last bar, held one bar | 147951 | 3.85962e-06 | 0.000158842 | 0.0242984 | 3.71537 | real but smaller than the cost |
| GBPUSD | 15m, follow the last bar, held one bar | 49503 | -1.30858e-05 | 0.000158842 | -0.0823822 | -4.30408 | real but smaller than the cost |
| GBPUSD | 15m, fade the last bar, held one bar | 49503 | 1.30858e-05 | 0.000158842 | 0.0823822 | 4.30408 | real but smaller than the cost |
| GBPUSD | 15m correlation of the size of one move with the size of the next 0.2998 | 49503 | — | — | — | 21.2771 | not an up-or-down trade |
| GBPUSD | after a top-10% 15m move, follow it, next 1h | 5776 | -2.62684e-05 | 0.000158842 | -0.165374 | -1.12365 | nothing |
| GBPUSD | after a top-10% 15m move, fade it, next 1h | 5776 | 2.62684e-05 | 0.000158842 | 0.165374 | 1.12365 | nothing |
| GBPUSD | 60m, follow the last bar, held one bar | 12326 | -7.17168e-07 | 0.000158842 | -0.00451497 | -0.0560133 | nothing |
| GBPUSD | 60m, fade the last bar, held one bar | 12326 | 7.17168e-07 | 0.000158842 | 0.00451497 | 0.0560133 | nothing |
| GBPUSD | 60m correlation of the size of one move with the size of the next 0.2944 | 12326 | — | — | — | 17.0691 | not an up-or-down trade |
| GBPUSD | follow the first 15m after 07:00 UTC, next 4h | 519 | 3.09932e-05 | 0.000158842 | 0.195119 | 0.235008 | nothing |
| GBPUSD | follow the first 15m after 13:30 UTC, next 4h | 518 | -6.80577e-05 | 0.000158842 | -0.42846 | -0.438752 | nothing |
| USDJPY | 5m, follow the last bar, held one bar | 148024 | -1.13974e-07 | 0.000122157 | -0.000933015 | -0.120036 | nothing |
| USDJPY | 5m, fade the last bar, held one bar | 148024 | 1.13974e-07 | 0.000122157 | 0.000933015 | 0.120036 | nothing |
| USDJPY | 15m, follow the last bar, held one bar | 49513 | 2.78669e-06 | 0.000122157 | 0.0228124 | 0.933978 | nothing |
| USDJPY | 15m, fade the last bar, held one bar | 49513 | -2.78669e-06 | 0.000122157 | -0.0228124 | -0.933978 | nothing |
| USDJPY | 15m correlation of the size of one move with the size of the next 0.2672 | 49513 | — | — | — | 17.2089 | not an up-or-down trade |
| USDJPY | after a top-10% 15m move, follow it, next 1h | 5845 | 2.12254e-05 | 0.000122157 | 0.173755 | 0.837565 | nothing |
| USDJPY | after a top-10% 15m move, fade it, next 1h | 5845 | -2.12254e-05 | 0.000122157 | -0.173755 | -0.837565 | nothing |
| USDJPY | 60m, follow the last bar, held one bar | 12327 | 2.68454e-05 | 0.000122157 | 0.219762 | 2.16869 | real but smaller than the cost |
| USDJPY | 60m, fade the last bar, held one bar | 12327 | -2.68454e-05 | 0.000122157 | -0.219762 | -2.16869 | real but smaller than the cost |
| USDJPY | 60m correlation of the size of one move with the size of the next 0.2461 | 12327 | — | — | — | 9.98574 | not an up-or-down trade |
| USDJPY | follow the first 15m after 07:00 UTC, next 4h | 517 | -0.00014915 | 0.000122157 | -1.22097 | -1.24488 | nothing |
| USDJPY | follow the first 15m after 13:30 UTC, next 4h | 519 | 0.000209337 | 0.000122157 | 1.71367 | 1.46349 | nothing |
| Gold/Silver | ratio in the bottom 10%, gold minus silver over the next 4h | 114583 | 8.57172e-05 | 0.0016531 | 0.0518524 | 0.404584 | nothing |
| Gold/Silver | ratio in the top 10%, gold minus silver over the next 4h | 144288 | -5.93841e-05 | 0.0016531 | -0.0359229 | -0.298984 | nothing |
| EURUSD/GBPUSD | EURUSD last minute, GBPUSD next minute correlation 0.0052 | 880343 | — | — | — | 1.9538 | nothing |
| EURUSD/GBPUSD | EURUSD last minute, follow it in GBPUSD, held one minute | 716566 | 7.61363e-07 | 0.000158842 | 0.0047932 | 3.15765 | real but smaller than the cost |
| GBPUSD/EURUSD | GBPUSD last minute, EURUSD next minute correlation -0.0001 | 880342 | — | — | — | 0.280413 | nothing |
| GBPUSD/EURUSD | GBPUSD last minute, follow it in EURUSD, held one minute | 724418 | 4.16999e-07 | 0.000107883 | 0.00386527 | 2.20977 | real but smaller than the cost |

78 rows were measured. With this many rows a few will look good by luck. That is why the bar is |t| >= 3.5.

Measured on seen periods. Shows where to look. Not evidence of profit. Anything promising must be frozen and tested once on 2025 onward.

Instruments skipped because the file was missing: none.
The 0.00007 commission added to each instrument is an assumption, not a measured fee. Cost = measured median spread (ask close minus bid close, divided by the mid) plus that commission.
A pair costs the sum of the two instruments. Correlation rows are not a fee test: their gross and cost cells are left blank, and they are never labelled bigger than the cost.
A hold that would cross a missing minute or the weekend close (Friday 22:00 UTC through Sunday 22:00 UTC) was dropped.
Measured costs: Gold median spread 0.000190991 plus 0.00007 commission, cost 0.000260991; Silver median spread 0.00132211 plus 0.00007 commission, cost 0.00139211; Light crude median spread 0.000610971 plus 0.00007 commission, cost 0.000680971; EURUSD median spread 3.78835e-05 plus 0.00007 commission, cost 0.000107883; GBPUSD median spread 8.88424e-05 plus 0.00007 commission, cost 0.000158842; USDJPY median spread 5.2157e-05 plus 0.00007 commission, cost 0.000122157.
Binance XAUUSDT and XAGUSDT perpetuals were not measured. The December 2024 archive is not there, and the contracts start in 2026, inside the sealed window. No file from 2025 onward was downloaded, so there is no pre-seal history and the sample is too short to judge. Archive checks: {"XAUUSDT kline 2024-12": 404, "XAGUSDT kline 2024-12": 404, "XAUUSDT index 2024-12": 404}. Usable days: 0.
rule_sets_tried is 4. This set is the measurement above. No variant was frozen and the holdout was not opened. Written 2026-11-13 04:00 Asia/Dubai.
