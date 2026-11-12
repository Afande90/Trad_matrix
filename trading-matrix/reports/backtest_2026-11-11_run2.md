Holdout verdicts are mixed: STOP as built x 2, STOP this track x 2, TOO EARLY x 2.

K = 6. z = 3.09. rule_sets_tried = 2.
Reported K is the six tracks. z is z_for_k(6) = 3.09. rule_sets_tried = 2 is printed so the second try is visible.

## CEILING

track | oracle gross | cost | oracle net | break-even hit rate
| T1 MOMENTUM 1h | 0.003087 | 0.001200 | 0.001887 | 0.694364
| T2 MOMENTUM 4h | 0.006267 | 0.001200 | 0.005067 | 0.595744
| T3 REVERSION 1h | 0.003087 | 0.001200 | 0.001887 | 0.694364
| T4 REVERSION 4h | 0.006267 | 0.001200 | 0.005067 | 0.595744
| X1 BTC EXTENDED | 0.003087 | 0.000900 | 0.002187 | 0.645773
| X2 GOLD EXTENDED | 0.001402 | 0.000900 | 0.000502 | 0.820914

## Step 1

- RANDOM control: net -0.001155196811992527 vs cost target -0.0012 (n=2000)
- WINDOW ORACLE: wiring ok
- Truncation test: identical: yes
- Entry price: next candle open
- Costs applied: cost_pct > 0 on counted calls
- Holdout ledger: registered before the holdout was read
- Rule sets tried (K): rule_sets_tried = 2. Reported K = 6. z = 3.09.
- Same-candle cases: count shown; resolved by aggTrades or counted as loss
- Data gaps: missing minutes 0.0000% of the spanned minutes

## One-line summary

track | counted | days | K | gross mean | net mean | net_lb (daily) | net mean cost x2 | RANDOM net | verdict
T1 MOMENTUM 1h | 4521 | 729 | 6 | -0.000105 | -0.001307 | -0.009521 | -0.002507 | -0.001241 | STOP this track
T2 MOMENTUM 4h | 1170 | 611 | 6 | 0.000074 | -0.001130 | -0.003269 | -0.002330 | -0.000641 | STOP as built
T3 REVERSION 1h | 917 | 529 | 6 | 0.000371 | -0.000827 | -0.001967 | -0.002027 | -0.001602 | STOP as built
T4 REVERSION 4h | 266 | 228 | 6 | -0.000143 | -0.001342 | -0.001266 | -0.002542 | -0.000736 | TOO EARLY
X1 BTC EXTENDED | 13394 | 600 | 6 | -0.000015 | -0.000808 | -0.017564 | -0.001601 | -0.000866 | STOP this track
X2 GOLD EXTENDED | 59 | 13 | 6 | 0.000375 | -0.000401 | -0.001731 | -0.001179 | -0.000899 | TOO EARLY

## T1 MOMENTUM 1h

Step 4 verdict: **STOP this track**
- Holdout dates: 2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.
- Counted calls: 4521
- Days containing calls: 729
- Gross mean per call: -0.000105
- Net mean per call: -0.001307
- net_lb on daily totals: -0.009521
- VALIDATE net mean: n/a. HOLDOUT net mean: -0.001307
- Net by month: 2022-11 -0.238853, 2022-12 -0.202109, 2023-01 -0.192609, 2023-02 -0.236668, 2023-03 -0.271010, 2023-04 -0.212111, 2023-05 -0.186633, 2023-06 -0.274666, 2023-07 -0.175376, 2023-08 -0.130887, 2023-09 -0.246049, 2023-10 -0.348840, 2023-11 -0.352697, 2023-12 -0.260394, 2024-01 -0.264234, 2024-02 -0.272616, 2024-03 -0.218761, 2024-04 -0.205128, 2024-05 -0.211323, 2024-06 -0.215642, 2024-07 -0.305947, 2024-08 -0.209468, 2024-09 -0.326415, 2024-10 -0.349493
- Flags: spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Baselines: ALWAYS_UP=0.4990, ALWAYS_DOWN=0.5006, PERSISTENCE=0.4884, COIN=0.5000, baseline_hit=0.5006
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 1910 / 2611 / 0 / 0 / 0
- Maker fill rate, would-be winners vs losers: n/a vs n/a
- Same-candle: aggTrades 0, counted as loss 0
- Hit rate: 0.4225  hit_lb: 0.4000
- Net mean at COST x2: -0.002507  x3: -0.003707
- VALIDATE net mean: n/a  HOLDOUT net mean: -0.001307
- Max drawdown of cumulative net: 592.8776%  longest losing streak: 12
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Observer
- RANDOM net mean: -0.001241
- Oracle gross / cost / net: 0.003087 / 0.001200 / 0.001887
- Break-even hit rate: 0.6944
- Strategy ran: True
- Net by month:
  - 2022-11: -0.238853
  - 2022-12: -0.202109
  - 2023-01: -0.192609
  - 2023-02: -0.236668
  - 2023-03: -0.271010
  - 2023-04: -0.212111
  - 2023-05: -0.186633
  - 2023-06: -0.274666
  - 2023-07: -0.175376
  - 2023-08: -0.130887
  - 2023-09: -0.246049
  - 2023-10: -0.348840
  - 2023-11: -0.352697
  - 2023-12: -0.260394
  - 2024-01: -0.264234
  - 2024-02: -0.272616
  - 2024-03: -0.218761
  - 2024-04: -0.205128
  - 2024-05: -0.211323
  - 2024-06: -0.215642
  - 2024-07: -0.305947
  - 2024-08: -0.209468
  - 2024-09: -0.326415
  - 2024-10: -0.349493
- Net by symbol: BTCUSDT -0.001307
- Step 3 flags:
  - spread_assumed is true on every call (bookTicker archive 404); COST x2 is required

## T2 MOMENTUM 4h

Step 4 verdict: **STOP as built**
- Holdout dates: 2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.
- Counted calls: 1170
- Days containing calls: 611
- Gross mean per call: 0.000074
- Net mean per call: -0.001130
- net_lb on daily totals: -0.003269
- VALIDATE net mean: n/a. HOLDOUT net mean: -0.001130
- Net by month: 2022-11 -0.027244, 2022-12 -0.062413, 2023-01 0.011659, 2023-02 0.018944, 2023-03 -0.175713, 2023-04 -0.086850, 2023-05 -0.053381, 2023-06 -0.093157, 2023-07 -0.146351, 2023-08 -0.005320, 2023-09 -0.001257, 2023-10 -0.050858, 2023-11 -0.077117, 2023-12 -0.020507, 2024-01 -0.099927, 2024-02 0.011574, 2024-03 -0.055446, 2024-04 0.080650, 2024-05 -0.027866, 2024-06 -0.068001, 2024-07 -0.083391, 2024-08 -0.181383, 2024-09 -0.088869, 2024-10 -0.040217
- Flags: spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Baselines: ALWAYS_UP=0.5197, ALWAYS_DOWN=0.4803, PERSISTENCE=0.4752, COIN=0.5000, baseline_hit=0.5197
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 494 / 676 / 0 / 0 / 0
- Maker fill rate, would-be winners vs losers: n/a vs n/a
- Same-candle: aggTrades 0, counted as loss 0
- Hit rate: 0.4222  hit_lb: 0.3784
- Net mean at COST x2: -0.002330  x3: -0.003530
- VALIDATE net mean: n/a  HOLDOUT net mean: -0.001130
- Max drawdown of cumulative net: 141.8327%  longest losing streak: 14
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Observer
- RANDOM net mean: -0.000641
- Oracle gross / cost / net: 0.006267 / 0.001200 / 0.005067
- Break-even hit rate: 0.5957
- Strategy ran: True
- Net by month:
  - 2022-11: -0.027244
  - 2022-12: -0.062413
  - 2023-01: 0.011659
  - 2023-02: 0.018944
  - 2023-03: -0.175713
  - 2023-04: -0.086850
  - 2023-05: -0.053381
  - 2023-06: -0.093157
  - 2023-07: -0.146351
  - 2023-08: -0.005320
  - 2023-09: -0.001257
  - 2023-10: -0.050858
  - 2023-11: -0.077117
  - 2023-12: -0.020507
  - 2024-01: -0.099927
  - 2024-02: 0.011574
  - 2024-03: -0.055446
  - 2024-04: 0.080650
  - 2024-05: -0.027866
  - 2024-06: -0.068001
  - 2024-07: -0.083391
  - 2024-08: -0.181383
  - 2024-09: -0.088869
  - 2024-10: -0.040217
- Net by symbol: BTCUSDT -0.001130
- Step 3 flags:
  - spread_assumed is true on every call (bookTicker archive 404); COST x2 is required

## T3 REVERSION 1h

Step 4 verdict: **STOP as built**
- Holdout dates: 2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.
- Counted calls: 917
- Days containing calls: 529
- Gross mean per call: 0.000371
- Net mean per call: -0.000827
- net_lb on daily totals: -0.001967
- VALIDATE net mean: n/a. HOLDOUT net mean: -0.000827
- Net by month: 2022-11 -0.045263, 2022-12 -0.040854, 2023-01 0.064769, 2023-02 -0.030046, 2023-03 -0.017559, 2023-04 0.012689, 2023-05 -0.028267, 2023-06 -0.070616, 2023-07 -0.042931, 2023-08 -0.029240, 2023-09 -0.012715, 2023-10 0.007582, 2023-11 -0.004505, 2023-12 -0.013929, 2024-01 -0.123113, 2024-02 -0.067405, 2024-03 -0.004922, 2024-04 -0.067630, 2024-05 -0.115546, 2024-06 -0.049427, 2024-07 -0.049337, 2024-08 -0.035106, 2024-09 0.005480, 2024-10 -0.000847
- Flags: hit rate 0.648 is above the suspicion line; spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Baselines: ALWAYS_UP=0.5082, ALWAYS_DOWN=0.4907, PERSISTENCE=0.4515, COIN=0.5000, baseline_hit=0.5082
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 594 / 323 / 0 / 0 / 0
- Maker fill rate, would-be winners vs losers: n/a vs n/a
- Same-candle: aggTrades 0, counted as loss 0
- Hit rate: 0.6478  hit_lb: 0.5977
- Net mean at COST x2: -0.002027  x3: -0.003227
- VALIDATE net mean: n/a  HOLDOUT net mean: -0.000827
- Max drawdown of cumulative net: 82.4597%  longest losing streak: 6
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Learner
- RANDOM net mean: -0.001602
- Oracle gross / cost / net: 0.003087 / 0.001200 / 0.001887
- Break-even hit rate: 0.6944
- Strategy ran: True
- Net by month:
  - 2022-11: -0.045263
  - 2022-12: -0.040854
  - 2023-01: 0.064769
  - 2023-02: -0.030046
  - 2023-03: -0.017559
  - 2023-04: 0.012689
  - 2023-05: -0.028267
  - 2023-06: -0.070616
  - 2023-07: -0.042931
  - 2023-08: -0.029240
  - 2023-09: -0.012715
  - 2023-10: 0.007582
  - 2023-11: -0.004505
  - 2023-12: -0.013929
  - 2024-01: -0.123113
  - 2024-02: -0.067405
  - 2024-03: -0.004922
  - 2024-04: -0.067630
  - 2024-05: -0.115546
  - 2024-06: -0.049427
  - 2024-07: -0.049337
  - 2024-08: -0.035106
  - 2024-09: 0.005480
  - 2024-10: -0.000847
- Net by symbol: BTCUSDT -0.000827
- Step 3 flags:
  - hit rate 0.648 is above the suspicion line
  - spread_assumed is true on every call (bookTicker archive 404); COST x2 is required

## T4 REVERSION 4h

Step 4 verdict: **TOO EARLY**
- Holdout dates: 2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.
- Counted calls: 266
- Days containing calls: 228
- Gross mean per call: -0.000143
- Net mean per call: -0.001342
- net_lb on daily totals: -0.001266
- VALIDATE net mean: n/a. HOLDOUT net mean: -0.001342
- Net by month: 2022-11 -0.019738, 2022-12 0.024862, 2023-01 -0.086743, 2023-02 -0.066977, 2023-03 0.040389, 2023-04 -0.005827, 2023-05 -0.016454, 2023-06 -0.043659, 2023-07 0.015633, 2023-08 -0.040643, 2023-09 0.001688, 2023-10 -0.010738, 2023-11 -0.004943, 2023-12 -0.015940, 2024-01 -0.073627, 2024-02 -0.031435, 2024-03 0.052474, 2024-04 -0.029745, 2024-05 -0.035601, 2024-06 0.022368, 2024-07 -0.056799, 2024-08 0.032679, 2024-09 0.009264, 2024-10 -0.017405
- Flags: spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Baselines: ALWAYS_UP=0.5752, ALWAYS_DOWN=0.4248, PERSISTENCE=0.5150, COIN=0.5000, baseline_hit=0.5752
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 148 / 118 / 0 / 0 / 0
- Maker fill rate, would-be winners vs losers: n/a vs n/a
- Same-candle: aggTrades 0, counted as loss 0
- Hit rate: 0.5564  hit_lb: 0.4619
- Net mean at COST x2: -0.002542  x3: -0.003742
- VALIDATE net mean: n/a  HOLDOUT net mean: -0.001342
- Max drawdown of cumulative net: 40.4522%  longest losing streak: 6
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Observer
- RANDOM net mean: -0.000736
- Oracle gross / cost / net: 0.006267 / 0.001200 / 0.005067
- Break-even hit rate: 0.5957
- Strategy ran: True
- Net by month:
  - 2022-11: -0.019738
  - 2022-12: 0.024862
  - 2023-01: -0.086743
  - 2023-02: -0.066977
  - 2023-03: 0.040389
  - 2023-04: -0.005827
  - 2023-05: -0.016454
  - 2023-06: -0.043659
  - 2023-07: 0.015633
  - 2023-08: -0.040643
  - 2023-09: 0.001688
  - 2023-10: -0.010738
  - 2023-11: -0.004943
  - 2023-12: -0.015940
  - 2024-01: -0.073627
  - 2024-02: -0.031435
  - 2024-03: 0.052474
  - 2024-04: -0.029745
  - 2024-05: -0.035601
  - 2024-06: 0.022368
  - 2024-07: -0.056799
  - 2024-08: 0.032679
  - 2024-09: 0.009264
  - 2024-10: -0.017405
- Net by symbol: BTCUSDT -0.001342
- Step 3 flags:
  - spread_assumed is true on every call (bookTicker archive 404); COST x2 is required

## X1 BTC EXTENDED

Step 4 verdict: **STOP this track**
- Holdout dates: 2022-11-01 → 2024-11-01. Validate: n/a. 2024-11 to 2026-05 was a sanity check only.
- Counted calls: 13394
- Days containing calls: 600
- Gross mean per call: -0.000015
- Net mean per call: -0.000808
- net_lb on daily totals: -0.017564
- VALIDATE net mean: n/a. HOLDOUT net mean: -0.000808
- Net by month: 2022-11 -0.510057, 2022-12 -0.038489, 2023-01 -0.426917, 2023-02 -0.210290, 2023-03 -0.941347, 2023-04 -0.415528, 2023-05 -0.308004, 2023-06 -0.324310, 2023-07 -0.145299, 2023-08 -0.148501, 2023-09 -0.196677, 2023-10 -0.281536, 2023-11 -0.391836, 2023-12 -0.392836, 2024-01 -0.586675, 2024-02 -0.502017, 2024-03 -1.090117, 2024-04 -0.614565, 2024-05 -0.446732, 2024-06 -0.345034, 2024-07 -0.684076, 2024-08 -0.934813, 2024-09 -0.524211, 2024-10 -0.360767
- Flags: spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Baselines: break-even win rate=n/a, ALWAYS_UP=n/a, ALWAYS_DOWN=n/a, PERSISTENCE=n/a, COIN=n/a
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 4762 / 7397 / 1235 / 781633 / 451
- Maker fill rate, would-be winners vs losers: 0.9449 vs 0.9817
- Same-candle: aggTrades 14, counted as loss 1
- Hit rate: 0.3555  hit_lb: 0.3429
- Net mean at COST x2: -0.001601  x3: -0.002395
- VALIDATE net mean: n/a  HOLDOUT net mean: -0.000808
- Max drawdown in R: 3306.129  longest losing streak: 16
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Observer
- RANDOM net mean: -0.000866
- Oracle gross / cost / net: 0.003087 / 0.000900 / 0.002187
- Break-even hit rate: 0.6458
- Strategy ran: True
- Net by month:
  - 2022-11: -0.510057
  - 2022-12: -0.038489
  - 2023-01: -0.426917
  - 2023-02: -0.210290
  - 2023-03: -0.941347
  - 2023-04: -0.415528
  - 2023-05: -0.308004
  - 2023-06: -0.324310
  - 2023-07: -0.145299
  - 2023-08: -0.148501
  - 2023-09: -0.196677
  - 2023-10: -0.281536
  - 2023-11: -0.391836
  - 2023-12: -0.392836
  - 2024-01: -0.586675
  - 2024-02: -0.502017
  - 2024-03: -1.090117
  - 2024-04: -0.614565
  - 2024-05: -0.446732
  - 2024-06: -0.345034
  - 2024-07: -0.684076
  - 2024-08: -0.934813
  - 2024-09: -0.524211
  - 2024-10: -0.360767
- Net by symbol: BTCUSDT -0.000808
- Step 3 flags:
  - spread_assumed is true on every call (bookTicker archive 404); COST x2 is required

## X2 GOLD EXTENDED

Step 4 verdict: **TOO EARLY**
- Holdout dates: Gold archive 2025-12 → 2026-11-01, split 60/20/20. Holdout 2026-08-26 → 2026-11-01. The archive is short, so TOO EARLY is the expected honest result. This is not a quiet pass.
- Counted calls: 59
- Days containing calls: 13
- Gross mean per call: 0.000375
- Net mean per call: -0.000401
- net_lb on daily totals: -0.001731
- VALIDATE net mean: -0.001091. HOLDOUT net mean: -0.000401
- Net by month: 2026-08 0.009668, 2026-09 -0.016154, 2026-10 -0.017155
- Flags: spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Baselines: break-even win rate=n/a, ALWAYS_UP=n/a, ALWAYS_DOWN=n/a, PERSISTENCE=n/a, COIN=n/a
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 24 / 27 / 8 / 438596 / 53
- Maker fill rate, would-be winners vs losers: 0.9470 vs 0.9778
- Same-candle: aggTrades 2, counted as loss 1
- Hit rate: 0.4068  hit_lb: 0.2360
- Net mean at COST x2: -0.001179  x3: -0.001957
- VALIDATE net mean: -0.001091  HOLDOUT net mean: -0.000401
- Max drawdown in R: 15.203  longest losing streak: 8
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Observer
- RANDOM net mean: -0.000899
- Oracle gross / cost / net: 0.001402 / 0.000900 / 0.000502
- Break-even hit rate: 0.8209
- Strategy ran: True
- Net by month:
  - 2026-08: 0.009668
  - 2026-09: -0.016154
  - 2026-10: -0.017155
- Net by symbol: XAUUSDT -0.000401
- Step 3 flags:
  - spread_assumed is true on every call (bookTicker archive 404); COST x2 is required
- Note: Gold archive starts 2025-12. The 20% holdout is a short sample. TOO EARLY is expected when the count or the days fall short. XAUUSDT fee was not confirmed; using FEE_FUT_MAKER and FEE_FUT_TAKER.

## Retired tracks

These tracks are STOP as built. The figures are quoted from reports/backtest_2026-11-11.md.

- BTC trend 15m. The published window oracle cannot beat costs: window-oracle net -0.000946. PEEK line: gross 0.000387 net -0.001813. Counted directional calls: 0.
- BTC quick scalps and gold quick scalps. The cost gate blocked every bar: blocked 210160, passed 0.
- The both-voters trend rule. It made 0 directional calls. Published holdout decisions: ABSTAIN 4527, SIDEWAYS 9489. The two voters are opposite by design.

## SEEN PERIOD - not evidence

2026-06-08 to 2026-11-01. These numbers never feed a verdict.
- T1 MOMENTUM 1h: counted 1015 net mean -0.001111 (not evidence)
- T2 MOMENTUM 4h: counted 230 net mean -0.001132 (not evidence)
- T3 REVERSION 1h: counted 169 net mean -0.001456 (not evidence)
- T4 REVERSION 4h: counted 52 net mean 0.000219 (not evidence)
- X1 BTC EXTENDED: oracle windows 3503 oracle net 0.001605. This is the window oracle, not a strategy result, and it is not evidence.
- X2 GOLD EXTENDED: oracle windows 3503 oracle net 0.000601. This is the window oracle, not a strategy result, and it is not evidence.

## Scope

- Rule set 2. K = 6. z = 3.09. rule_sets_tried = 2. The second try is this pre-registered set, not a search.
- Develop months 2024-11 to 2026-05 were a sanity check. The engine finished. Those numbers are not a verdict.
- The new holdout is 2022-11-01 to 2024-11-01 (end exclusive). The ledger row was written before that sample was read. It was run once.
- 2026-06-08 to 2026-11-01 is the seen period. It is not evidence and it is not in the ledger.
- Trend is BTCUSDT USD-M perpetual, taker in and taker out, entry at the next 1m open, exit at the window end, funding applied.
- Lens input is 500 closed bars resampled from closed 1m candles: 5m for the 1h window, 15m for the 4h window. SIDEWAYS is stored and not counted.
- Markov window 20, MARKOV_K 1.0, RSI 14, MACD 12/26/9, Bollinger 20/2. One voter. No weight modulation.
- X1 BTC EXTENDED and X2 GOLD EXTENDED are the maker EXTENDED tracks. Trigger is the cost gate, then the setup score, then the ensemble voter or the aggTrade delta over the last 3 closed 1m candles. No bookTicker. QUICK is not mixed in.
- WIN pays maker + maker. LOSS and TIMEOUT pay maker + taker. Spread 0.0001 is assumed because the bookTicker archive returns 404. Slippage is 0.0001.
- fapi.binance.com exchangeInfo returned HTTP 451. The ticks that were frozen are BTCUSDT 0.10 and XAUUSDT 0.01 from https://testnet.binancefuture.com/fapi/v1/exchangeInfo. They were not tuned.
- The metal fee was not confirmed. Gold uses FEE_FUT_MAKER and FEE_FUT_TAKER.
- Gold missing minutes in the loaded archive: 0. No news calendar, so blackout is false. AI and visual lenses stay excluded.
- Gold's blocked-by-cost count is the whole 2025-12 to 2026-10 archive, because the walk is continuous. The counted calls, the net, and the verdict use only the last 20%.
- Trend tracks have no stop. Their drawdown is the peak-to-trough of cumulative net return, recovered as the stored R path times the constant taker cost 0.0012. Scalp ALWAYS_UP and ALWAYS_DOWN in the first draft were the win/loss split. They are withdrawn. The mean gate break-even was not stored with that summary, so the scalp baseline is n/a rather than a reconstructed number.

## DECISION

- T1 MOMENTUM 1h: STOP this track
- T2 MOMENTUM 4h: STOP as built
- T3 REVERSION 1h: STOP as built
- T4 REVERSION 4h: TOO EARLY
- X1 BTC EXTENDED: STOP this track
- X2 GOLD EXTENDED: TOO EARLY

Tracks that are STOP or NOT PROVEN stop for good.
Tracks that are TOO EARLY are not rerun. They continue only as live paper tracking.
No track reached CONTINUE. This is the final rerun. Wait for the operator.
