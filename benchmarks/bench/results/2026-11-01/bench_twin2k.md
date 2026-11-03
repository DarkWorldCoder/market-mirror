# MarketMirror-Bench: twin2k

| method | accuracy | brier_purchase | calls | ci95 | input_tokens | n | normalized_accuracy | output_tokens | predicted_purchase_share | real_purchase_share | test_retest | usd_at_haiku |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| majority | 0.49 | 0.51 | 0 | [0.44, 0.532] |  | 400 | 0.585 |  | 0.32 | 0.43 | 0.838 |  |
| no_persona | 0.613 | 0.388 | 20 | [0.548, 0.673] | 74168 | 400 | 0.731 | 1360 | 0.657 | 0.43 | 0.838 | 0.08 |
| twin | 0.598 | 0.403 | 40 | [0.52, 0.667] | 926279 | 400 | 0.713 | 36644 | 0.698 | 0.43 | 0.838 | 1.11 |
| twin_affect | 0.61 | 0.39 | 20 | [0.535, 0.68] | 107523 | 400 | 0.728 | 2868 | 0.64 | 0.43 | 0.838 | 0.12 |

Human data: CC BY 4.0. Simulated answers are compared with what real people did; a method that does not beat the simpler comparators is reported as such.