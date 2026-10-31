---
name: market-mirror-evidence-review
description: Validate actual marketing exports and assess whether simulated predictions beat a simple baseline.
---

# Evidence review

Call `actuals_import` for CSV/JSON ads, email, website, CRM or survey exports. Map source columns explicitly, give a date and market where missing, and resolve every validation error before comparing outcomes. Use `backtest` or `holdout_backtest` with independent real experiments: training observations set calibration, held-out observations evaluate it against a no-persona training-mean baseline. State the split and sample size. An uncalibrated output is directional; if held-out persona error does not beat the baseline, keep the conclusion exploratory. Only report a probability or interval with its real calibration basis. With 10+ real survey answers, `calibrate` adds a PPI++ interval for the audience rate (valid whatever the panel's quality, assuming the real answers are a random sample of that audience), the panel's worth in real answers, and how many more real answers a target precision needs. Quote that interval and its assumption, not the raw simulated rate.
