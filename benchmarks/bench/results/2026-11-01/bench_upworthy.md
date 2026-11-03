# MarketMirror-Bench: upworthy

| method | calls | ci95 | input_tokens | missing | n | output_tokens | spearman | top_choice_accuracy | unanimity | usd_at_haiku |
|---|---|---|---|---|---|---|---|---|---|---|
| chance | 0 |  |  |  | 50 |  |  | 0.34 |  |  |
| generic_reader | 50 | [0.5, 0.78] | 48528 | 0 | 50 | 889 | 0.47 | 0.64 |  | 0.05 |
| persona_panel | 500 | [0.3, 0.58] | 646350 | 0 | 50 | 4500 | 0.202 | 0.44 | 0.659 | 0.67 |
| persona_panel_feel | 500 | [0.22, 0.5] | 735924 | 0 | 50 | 91965 | 0.178 | 0.36 | 0.75 | 1.2 |
| persona_panel_mood | 500 | [0.36, 0.64] | 534939 | 0 | 50 | 3600 | 0.205 | 0.5 | 0.745 | 0.55 |

Human data: CC BY 4.0. Simulated answers are compared with what real people did; a method that does not beat the simpler comparators is reported as such.