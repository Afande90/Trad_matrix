Language replication on an already-seen period. Not evidence about the rule. rule_sets_tried stays 3.

Same result

BTC COMPLETE SENTENCE, WITH variant, as frozen in `backtest/frozen_rules.json`. Holdout 2020-11-01 through 2022-10-31, BTCUSDT USD-M perpetual. The OCaml program is `ocaml/`. No Python file was changed.

| | Python | OCaml |
| --- | ---: | ---: |
| counted calls | 1868 | 1868 |
| wins | 680 | 680 |
| losses | 1040 | 1040 |
| timeouts | 148 | 148 |
| NOT_FILLED | 60 | 60 |
| blocked-by-cost | 399309 | 399309 |
| hit rate | 0.36402569593147749 | 0.36402569593147749 |
| gross mean | 2.4032601977189314e-05 | 2.4032601977189331e-05 |
| net mean | -0.00076731909502495191 | -0.00076731909502495007 |
| net mean at cost x2 | -0.0015581113862455087 | -0.0015581113862455063 |

All 1,928 records (the counted calls and the NOT_FILLED calls) match on entry time, side, and outcome. Gross, net, cost, and funding on those records also match. The three means differ only in the last bits of the sum, by less than 3e-18.

Run time of one WITH pass over the cached month files:

| engine | seconds |
| --- | ---: |
| Python | 2311.201 |
| OCaml | 824.786 |

The aggTrade archives had been removed after run 3. They were downloaded once, before either clock started. Klines and funding were already on disk.
