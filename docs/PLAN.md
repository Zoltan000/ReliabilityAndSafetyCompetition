# Plan: winning entry for the Industrial Conveyor Reliability Data Challenge

## Context

We must deliver three technical results (spec §5–6) and four submission items (§7):
- **Req. 1**: reliability understanding per component, as 2 slides plus a ~3-minute talk.
- **Req. 2**: the next 5 failures (component + date) for one unseen conveyor.
- **Req. 3**: 3-year downtime (monthly + cumulative + total).

Req. 2 and 3 come from one frozen Colab. It takes a Parquet path with ≥200 days, detects the last day, and hard-codes no length. The user's direction:
- supervised ML, with each row labelled by the known future (days until failure);
- cross-validation whose test folds are whole conveyors;
- the fitted model stored at a pinned GitHub commit.

Compute is free; Claude-side tokens should stay low. Every decision gets challenged.

### Facts that drive the design (`analysis/fleet_kpis_report.md`, `analysis/weather_seasonality_findings.md`, the 1-year example)

- 284 conveyors, 12 plants, 2005–2024, all at EIS on 2005-01-01. The fleet is in steady state from 2006.
- **Every failure costs exactly 36 h. Planned maintenance is exactly 3 one-day stops per year.**
  - So **downtime = 36 h × failures + 24 h × maintenance days**: Req. 3 is a *failure-count* forecast, and the planned part is deterministic.
- **Bearings are 94% of failures and downtime**, at ~40.7 per conveyor-year; bearing positions renew. Load matters hugely: bearings 21×, belt 5.7×, and motor-reducer 3.6× from Light to Heavy. Speed sensor and PC are load-independent. Control software is inverted and declining.
- Event counts: contactor has only 12 failures, and software has 463.
- **Temperature is a deterministic step function of meteorological season**: DJF ≈ 21.5, MAM ≈ 23.0, JJA ≈ 24.1, SON ≈ 22.7 °C (max). Plants differ by a stable offset (±~0.5 °C), and daily noise is small (~0.3 °C).
  - **Correction to the findings doc:** humidity is flat *over the year* but differs *between plants*. The ±1σ band spans ~42.5–51%, so humidity is a **plant-level constant**, not "no signal." It's a static covariate, confounded with plant.
- For Medium/Heavy conveyors, the next 5 failures are almost surely all bearings a few days apart, so *timing* is what gets scored. For Light conveyors the *component order* matters too.

## Your proposal: append a "days until failure" (Y) column and learn X → Y

**Verdict: adopt it as the primary approach, with 5 fixes.** Once repair and maintenance are constant, a direct supervised model is the cleanest fit. It predicts from the origin only, so it never needs future covariates or a simulator. Its CV backtest is also just out-of-fold prediction on held-out conveyors' rows. Without the fixes, it would be biased or unable to answer Req. 2/3:

1. **Censoring.** Near 2024-12-31, many rows have no next failure observed yet (software MTBF ~1,500 days, PC ~1,000, sensor ~930).
   - Dropping those rows biases Y low; filling them with "days to end of data" is also wrong.
   - → Store **Y plus an `event_observed` flag** and train with a censoring-aware loss: **XGBoost `survival:aft`**, with `y_lower = y`, and `y_upper = y` if observed or `+inf` if censored. It predicts log-days, so errors are relative, which is the right scale for heavy-tailed gaps.
2. **Which failure, and next 1 vs. next 5.** A single "days to next failure of any type" only gives failure #1, with no component. Add label columns for **k = 1..5**:
   - **gap_k** = days from failure k−1 (or the origin) to failure k, with a censor flag. Predicting gaps rather than cumulative days guarantees order.
   - **comp_k** = component of the k-th failure. A multiclass LightGBM predicts it; bearing vs. the rest is the key split for Light conveyors.
   - Also **days_to_next_c** per component *c* (7 AFT models). This is for Req. 1 insight and a consistency check: P(component c first) should agree with comp_1.
3. **Req. 3 needs counts, not days-to-failure.** Add label columns **failures in future month m = 1..36**, masked where the window passes 2024-12-31. Train one stacked **LightGBM Poisson** model on (origin features + m + calendar month of m + expected temperature of month m) → expected count.
   - Downtime per month = 36 h × count (a failure on a month's last day spills 24 h into the next; allocate at daily level) + the known maintenance days.
   - The total gets P10/P90 from LightGBM **quantile** models on the 36-month total.
4. **Leakage.** Labels look into the future by construction.
   - They go in a **separate label table**, keyed by (Conveyor_ID, origin Date).
   - Features are computed strictly "as of" the origin, using expanding or rolling windows over rows ≤ origin, exactly what the tool sees in a file ending that day.
   - Assertion tests enforce this. The original Parquet is never modified.
5. **Overlapping rows.** The label on day t is almost the label on day t−1 minus one, so consecutive days are near-duplicates.
   - Use origins **every 7 days**, from day 200 on (≥200 days of history, matching the spec).
   - Weight each conveyor equally, so Heavy conveyors don't dominate.
   - Grouped CV already stops the overlap leaking across folds.

## Challenges to the other decisions

- **ML at all.** Constant repair makes Req. 3 ≈ E[failure count], driven by load, plant, and the bearing population. An **empirical-Bayes rate baseline** is strong: a fleet prior by plant × load, shrunk to the conveyor's own as-of rate, with the season profile applied. ML is kept only where it beats it. A **parametric renewal simulation** (per-bearing Weibull + other components) is the second baseline, and becomes the Req. 2 method only if it beats the direct model on next-5 timing. Contactor (12 events) and software (463) enter the ML as ordinary classes, but their Req. 1 story uses parametric fits with CIs.
- **Test folds = whole conveyors.** Correct, since a conveyor is the unit of generalization. Not sufficient on its own:
  - **Calendar leakage.** Other conveyors' rows from after the origin carry calendar information (e.g. the speed-sensor spike years). Add a **forward-chaining check**: train only on label windows that end before the test origin's date. A large drop means we rely on calendar leakage.
  - **Unseen plant.** Add **leave-one-plant-out** as a stress test.
  - **Stability.** 5 folds × 3 seeds, stratified by plant.
  - **Sealed holdout.** ~15% of conveyors, P02CV27 included, scored once at the end.
  - **Weighting.** Metrics are averaged per conveyor, and reported by load class and by origin age (the year-1 ramp-up is its own regime).
- **The earlier hybrid-hazard + Monte Carlo design is demoted.** It needed a simulator for every future covariate, and the direct design avoids that. It stays only as the parametric baseline above.
- **Downtime definition.** Report corrective, planned, and total.
- **Point estimates.** The scoring metric is unknown, so report the median (headline), mean, and P10–P90. Backtest mean vs. median, and **ask the organizers how scoring works**.
- **Pinned public GitHub.** Colab needs a public URL, but publishing the working repo exposes our work early. → At submission, create a separate **public submission repo** holding only `artifacts/` and the notebook, pinned by commit SHA.

## Weather: extrapolate the seasonal pattern (known future ≠ unknown future)

Temperature's *expected* future is known exactly: it's the plant's seasonal step level. Daily noise is ~0.3 °C against a ~2.5 °C seasonal swing, so plugging in the expected value loses almost nothing. We verify that by checking within-plant-season residual SD and autocorrelation; if residuals are autocorrelated, a frozen origin anomaly is added as a feature.

- **Climatology table.**
  - Built from the fleet: plant × season mean of Temperature_Max/Min, a plant humidity constant, and a plant voltage mean. Voltage gets checked for seasonality the same way.
  - Unknown plant: plant offset = the input's own observed mean minus the fleet season profile, over the seasons it covers. ≥200 days always covers ≥2 seasons.
- **Features.** Built from climatology, not realized weather, in both training and inference (so train equals serve):
  - expected temperature for each target month (count model);
  - expected mean temperature over the next 30/90/365 days, and the origin's season and day-of-year (AFT and component models);
  - plant humidity as a static feature.
- **Other unknown-future columns.**
  - Throughput and daily kg: the as-of recent level (the conveyor is stable).
  - CM signals (vibration, current/throughput, voltage-drop/current, motor-temp minus ambient, closing time): **as-of origin** 7/30-day means and slopes. That's legitimate in a direct model because they describe the state at the origin. Each is kept only if the ablation shows a gain.
- **Req. 1 use of weather.** Season steps are a natural experiment. Compare failure rates just before vs. just after each step date (Mar 1, Jun 1, Sep 1, Dec 1) per component, plus realized-temperature Cox/SHAP effects. This is a clean slide finding if it's real.
- **Maintenance days in the future.** Taken from the conveyor's own pattern (EDA: fixed calendar dates per plant or conveyor?). Fallback: 3/yr evenly spaced from the last maintenance.

## Features (all as-of origin, one function for training and inference)

- **Static:** plant, load class, length, bearing count, rated throughput, speed, roller diameter, plant humidity.
- **Age/exposure:** calendar age, cumulative op-h, cycles, kg, revolutions.
- **Per component:** time/op-h/kg/cycles since last failure (NaN if never failed, plus a flag), failure count, and own failure rate over the last 90/365 days/all history.
- **Bearing population:** count of never-failed bearings; age quantiles (min/median/max) over positions; number of bearings older than the fleet-median bearing life; days since the last bearing failure; bearing failures in the last 30/90 days.
- **Belt:** "original belt" flag (imperfect repair), belt age on the op-h and kg clocks.
- **Restart and maintenance:** days/hours since restart, days since maintenance, days to next maintenance.
- **Climatology:** as described in the weather section.
- **CM:** as-of origin statistics, as described in the weather section.

## CV, metrics, selection

- **Level A = the direct models' out-of-fold scores.** Grouped folds; Optuna tunes LightGBM/XGBoost per target.
  - AFT: C-index, log-days MAE, and interval coverage.
  - comp_k: log-loss and accuracy.
  - Counts: Poisson deviance, total 3-year absolute/% error, monthly RMSE, P10–P90 coverage (~80%).
- **Level B = end-to-end parity.** Run the real `forecast(path)` on truncated Parquet files of held-out conveyors (200 days, 1, 2, 4, 6, 10, 14, and 17 years) to prove the tool gives the same numbers as the out-of-fold pipeline.
- **Ablations**, each logged as one row in `outputs/experiments.csv`: CM on/off, climatology on/off, bearing-population features on/off, the AFT distribution (normal/logistic/extreme), and median vs. mean. Plus the two baselines and the forward-chaining and leave-one-plant-out checks.
- **Final model.** Refit on all 284 conveyors with the CV-chosen settings, bagged over 5 seeds. Score the sealed test once.

## Req. 1 (the 2 slides)

- **Per component:** best exposure clock (Weibull AIC across clocks), β with bootstrap CIs resampled by conveyor, and a renewal vs. trend test.
- **Load/plant effects:** with the plant × load cross-tab.
- **Temperature:** the season-step effect.
- **Humidity/voltage:** plant-level effects.
- **CM precursors** before each failure type.
- **Imperfect belt repair.**
- **Speed-sensor cohort waves:** does time since replacement explain the spike years?
- **Contactor:** emerging wear-out (n = 12, with uncertainty).
- **Downtime share**, and SHAP from the direct models.

Slide 1: "What fails, how, and why." Slide 2: "What drives downtime, and how accurately we forecast it." All names go on both slides.

## Repository layout (new files)

- `pyproject.toml`: uv, as the team already uses. Dependencies: pandas, pyarrow, duckdb, numpy, scipy, scikit-learn, lightgbm, xgboost, optuna, lifelines, shap, matplotlib, nbformat, python-pptx.
- `src/conveyor/`:
  - `io.py`: load, validate, sort, dedupe; detect the last day.
  - `climatology.py`
  - `features.py`: `features_asof(df)`, a single source for training and inference.
  - `labels.py`: builds the future labels with censor flags; training only.
  - `models.py`
  - `baselines.py`
  - `forecast.py`: `forecast(path) -> Next5, Downtime`.
  - `evaluate.py`
- `scripts/`:
  - `01_build_tables.py`: fleet → `outputs/cache/{features,labels,climatology}.parquet`, with heavy aggregation in DuckDB.
  - `02_reliability_analysis.py`
  - `03_cv_tune.py`
  - `04_backtest.py`
  - `05_fit_final.py`: writes `artifacts/`, with models as text/JSON and SHA-256 hashes.
  - `06_build_notebook.py`: generates the notebook from `src/`.
  - `07_make_slides.py`
- `notebooks/Conveyor_Forecast.ipynb`:
  - A `#@param INPUT_PATH` cell.
  - Pinned pip install.
  - Artifacts fetched from the pinned SHA of the public submission repo.
  - Prints the Req. 2 table and the Req. 3 monthly/cumulative table and plot.
- Update CLAUDE.md with the confirmed EDA facts, including the humidity correction.

## Execution order

1. Set up the uv env and run EDA checks:
   - maintenance date pattern;
   - load class nested in plant;
   - within-plant-season temperature residuals, and voltage seasonality;
   - conveyor-ID gaps (does the hidden conveyor come from a known plant?);
   - failures only on at-risk days.
2. `01_build_tables`: climatology + as-of features + label table, with leakage assertions.
3. Baselines first (empirical-Bayes rate, parametric renewal) → score them in the CV harness.
4. Direct models (AFT gaps, comp_k, Poisson monthly counts, quantile totals) → Optuna → ablations → forward-chaining and leave-one-plant-out checks.
5. Req. 1 analysis and figures (can run in parallel with step 4).
6. Final refit → sealed test → artifacts → public submission repo at a pinned SHA → notebook → Level-B parity run.
7. Slides, then the CLAUDE.md submission checklist: fresh Colab run on both examples → PDF → 7-day freeze.

## Working conventions (token efficiency)

- Scripts print ≤ ~40 summary lines. Full outputs go to `outputs/`, and raw frames are never printed.
- The fleet is parsed once into the cache, with aggregation in DuckDB.
- One `experiments.csv` row per run.
- Long runs go in the background. No subagents unless needed. `src/` is the single source of truth, and the notebook is generated from it.

## Verification

- **Parity.** `features_asof` on fleet-truncated P02CV27 equals features from the example files.
- **Leakage tests.**
  - Features computed on a file truncated at date d are identical to fleet features at origin d.
  - No test `Conveyor_ID` appears in training.
  - Label windows past 2024-12-31 are flagged as censored or masked.
- **Robustness.** `forecast()` runs on the 1-year file, the 6-year file, a 200-day cut, shuffled rows, and string dates.
- **Accuracy.**
  - The direct models beat both baselines on CV and on the sealed test.
  - P10–P90 coverage is ≈80%.
  - Forward-chaining shows no large drop.
- **End-to-end.** A fresh Colab run on both example files matches local `forecast()`.
- **Slides.** Exactly 2, all names on each, no title slide.

## Open items for the organizers

- The scoring metric for Req. 2 and 3.
- The email address and deadline.
- Whether the hidden conveyor comes from a fleet plant, and whether its window falls within 2005–2024.
