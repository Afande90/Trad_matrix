Stop building trading features. The complete-sentence rule is STOP as built.

K = 2. z = 2.88. rule_sets_tried = 3.
K is the two train variants. z is z_for_k(2) = 2.88. rule_sets_tried = 3 counts this rule set after run 1 and run 2.

## CEILING

track | oracle gross | cost | oracle net | break-even hit rate
| BTC COMPLETE SENTENCE | 0.005380 | 0.000900 | 0.004480 | 0.583642

## Step 1

- RANDOM control: net -0.0011264301275881667 vs cost target -0.0008999999999999998 (n=2000)
- WINDOW ORACLE: wiring ok
- Truncation test: identical: yes
- Entry price: maker limit at the setup price; later aggTrades must trade through by one tick
- Costs applied: cost_pct > 0 on counted calls
- Holdout ledger: registered before the holdout was read
- Rule sets tried (K): rule_sets_tried = 3. Reported K = 2. z = 2.88.
- Same-candle cases: count shown; resolved by aggTrades or counted as loss
- Data gaps: missing minutes 0.0000% of the spanned minutes

## TRAIN

Kept variant: WITH. WITH train net mean -0.000806 was higher than AGAINST -0.000855.

variant | counted | days | gross mean | net mean
WITH | 593 | 283 | -0.000012 | -0.000806
AGAINST | 681 | 304 | -0.000054 | -0.000855

## HOLDOUT

track | counted | days | K | gross mean | net mean | net_lb (daily) | net mean cost x2 | RANDOM net | verdict
BTC COMPLETE SENTENCE | 1868 | 549 | 2 | 0.000024 | -0.000767 | -0.002849 | -0.001558 | -0.001126 | STOP as built

### BTC COMPLETE SENTENCE

Step 4 verdict: **STOP as built**
- Holdout dates: 2020-11-01 → 2022-10-31
- Counted calls: 1868
- Days containing calls: 549
- Gross mean per call: 0.000024
- Net mean per call: -0.000767
- net_lb on daily totals: -0.002849
- TRAIN net mean: -0.000806. VALIDATE net mean: n/a. HOLDOUT net mean: -0.000767
- Net by month: 2020-11 -0.025110, 2020-12 -0.122171, 2021-01 -0.024382, 2021-02 -0.192070, 2021-03 0.008148, 2021-04 -0.069251, 2021-05 0.031035, 2021-06 -0.040896, 2021-07 -0.042330, 2021-08 -0.143076, 2021-09 -0.064230, 2021-10 -0.016466, 2021-11 -0.054849, 2021-12 -0.034841, 2022-01 -0.022140, 2022-02 -0.026654, 2022-03 -0.073531, 2022-04 -0.077257, 2022-05 -0.089780, 2022-06 -0.124077, 2022-07 -0.139835, 2022-08 -0.041191, 2022-09 -0.031382, 2022-10 -0.017016
- Baselines: break-even win rate=0.4674, ALWAYS_UP=n/a, ALWAYS_DOWN=n/a, PERSISTENCE=n/a, COIN=n/a
- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: 680 / 1040 / 148 / 399309 / 60
- Maker fill rate, would-be winners vs losers: 0.9392 vs 0.9877
- Same-candle: aggTrades 1, counted as loss 0
- Hit rate: 0.3640  hit_lb: 0.3326
- Net mean at COST x2: -0.001558  x3: -0.002349
- Max drawdown in R: 416.427  longest losing streak: 14
- spread_assumed share: 1.000  funding_ignored share: 0.000
- Ladder level the holdout would have reached: Observer
- RANDOM net mean: -0.001126
- Oracle gross / cost / net: 0.005380 / 0.000900 / 0.004480
- Break-even hit rate: 0.5836
- Note: No news calendar is bundled. The exception is the 1m range versus ATR(1m) only.
- Flag: spread_assumed is true on every call. COST x2 net mean is -0.001558.
- HOLDOUT net mean -0.000767 is slightly above the TRAIN net mean -0.000806. Both are below zero, so the verdict stays STOP as built.

## Scope

- Rule set 3. K = 2 because WITH and AGAINST were both run on TRAIN. z = 2.88. rule_sets_tried = 3.
- The kept variant was chosen on TRAIN net mean per call only. Nothing else was changed.
- Holdout 2020-11-01 to 2022-10-31 was registered before it was read, and the kept variant was run once.
- No news calendar is bundled. The exception role is the last closed 1m range versus 3 x ATR(1m).
- Governor: closed 15m EMA20 and EMA50. Doer: aggTrade buy share over the last 3 closed 1m candles.
- Target: previous UTC day high, low, or volume point of control from profile.py, within 0.25 x ATR(5m).
- State: maker EXTENDED cost gate and the dead-market filter (1m ATR below 0.6 of its 10-bar average).
- Bracket, fill, and costs match X1. WIN is maker+maker. LOSS and TIMEOUT are maker+taker. Spread 0.0001 is assumed.
- BTCUSDT tick 0.10 was carried from run 2 and was not tuned.
- Diagnostic rows switch one role off on the holdout. They are not evidence and they do not choose a variant.
- Run 1 and run 2 ledger rows are unchanged.

## DIAGNOSTIC - not evidence

Holdout calls and net mean with one role switched off. These rows do not feed the verdict.

role switched off | counted | net mean
| governor | 3539 | -0.000826
| doer | 3785 | -0.000718
| target | 20497 | -0.000923
| exception | 1890 | -0.000766

## DECISION

- BTC COMPLETE SENTENCE: STOP as built

Stop building trading features. The measuring engine and Trader School still stand. This is the only test of this rule. Do not try other variants. Wait for the operator.
