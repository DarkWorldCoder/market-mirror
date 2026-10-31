# MarketMirror-Bench

Scores MarketMirror's simulated answers against what real people did, next to simpler comparators, on open human data. The goal is an honest public record, misses included. A method that does not beat the comparators is reported as such.

| Suite | Human data | Task | Methods |
|---|---|---|---|
| `upworthy` | [Upworthy Research Archive](https://upworthy.natematias.com) (Matias et al. 2021, CC BY 4.0): real headline A/B tests with clicks | Pick the headline that got the most clicks | `chance`, `generic_reader` (no persona), `persona_panel` (people from a prepared run vote) |
| `twin2k` | [Twin-2K-500](https://huggingface.co/datasets/LLM-Digital-Twin/Twin-2K-500) (Toubia et al. 2025, CC BY 4.0) | Predict each person's wave-4 answers from waves 1-3. The default slice is the 40 "would you buy this product at this price" questions | `majority` (leave-one-out), `no_persona`, `twin` |

The two suites report these metrics:

- **Upworthy:** top-choice accuracy and the Spearman correlation with the real click rates.
- **Twin-2K-500:**
  - accuracy;
  - accuracy normalised by each person's own test-retest agreement (the same questions in waves 1-3 against wave 4);
  - Brier score on buy / don't buy;
  - predicted against real purchase share.
- **Both:** calls and tokens per method.

## Run

A dry run is the default. It prints the number of calls and a cost estimate and spends nothing.

```bash
python backend/claude_cli/mirofish.py bench --suite upworthy --data upworthy-archive-confirmatory-packages.csv --n 50
python backend/claude_cli/mirofish.py bench --suite twin2k --fetch --n 20
```

Add `--approve-spend` to call the configured model (`LLM_MODEL_NAME`); no backend server is needed. `persona_panel` needs `--run-dir` of a prepared run, whose people vote. Download the Upworthy packages CSV from [OSF](https://osf.io/jd64p/). `--fetch` downloads Twin-2K-500 rows from Hugging Face into `benchmarks/bench/cache/`, which is gitignored.

The sample is fixed: ids are hashed with a salt. The same command picks the same tests and people, so runs are reproducible without committing the data. Results are written to `benchmarks/bench/results/bench_<suite>.json` and `.md`.

## Caveats

- Both datasets predate current models' training data, so memorisation is possible. In particular, Upworthy headlines were public, so a model may recall which headline won.
- A good score here is evidence for these tasks only, not for a particular market.
- No results are published yet. The first paid run waits for the maintainer's approval of the budget and the model.
