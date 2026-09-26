# Session notes: 2026-09-26 — sealed-holdout leak fix + two remaining Req.1 gaps

## Context

Before this session, an earlier planning pass (see git history on `docs/PLAN.md`) had proposed a list of
correlation analyses to run before ML/Monte Carlo modeling. In the meantime, a teammate had already built
the full pipeline (`src/conveyor/`, `scripts/00-08`) and, along the way, executed most of that analysis
list inside `scripts/02_reliability_analysis.py`. This session (1) audited that pipeline for correctness,
(2) fixed the one real bug found, and (3) filled the two analysis items that were still genuinely missing.

## 1. Bug fixed: sealed-holdout leak

`src/conveyor/features.py` hard-codes two numbers describing bearing wear-out — `BRG_BETA` and
`BRG_ETA_OH` — used as model features (`brg_whaz_next7/30/90/365`). They were fit in
`scripts/02_reliability_analysis.py` on **all 284 conveyors**, including the ~15% sealed holdout
(`evaluate.sealed_conveyors`, always including `P02CV27`) that's supposed to be untouched until the
one-time final test in `scripts/05_fit_final.py`. The same issue affected `fleet_tmax` (temperature
climatology) in `scripts/01_build_tables.py`.

**Fix:**
- `01_build_tables.py` now computes `fleet_tmax` excluding the sealed conveyors.
- `02_reliability_analysis.py` gained a new §A2 that refits the Bearing/op_h Weibull constants
  excluding the sealed conveyors, saved to `outputs/req1/weibull_bearing_ml_constants.csv`. The
  full-fleet Weibull table (§A, `weibull_by_clock.csv`) is untouched on purpose — Req. 1's descriptive
  reporting has no reason to respect an ML train/test split, only the literal constants baked into the
  model's feature code do.
- `features.py`'s `BRG_BETA`/`BRG_ETA_OH` updated to the corrected values: β 2.98→2.97,
  η_Light 45,880→45,886 op-h. The shift is tiny (~0.01%), confirming the leak's practical effect was
  negligible — but the constants must not depend on the sealed set even in principle.
- Rebuilt `outputs/cache/{features,labels}.parquet` and `artifacts/climatology.json`. All of
  `01_build_tables.py`'s truncation- and example-file-parity assertions still pass with zero difference.
- **Not done in this session, by request:** rerunning `scripts/03_cv.py eb:1000 direct --seed 0 --folds 5`
  to confirm the corrected constants don't move the headline numbers already quoted in `CLAUDE.md`
  (downtime error 4.5% for `direct` vs. 9.1% for `eb:1000`). This should be run before trusting those
  numbers again — a partial `eb:1000` rerun already confirmed identical results (that model doesn't use
  the leaked constants at all), but `direct` hasn't been re-verified.
- `artifacts/model_seed*/` still doesn't exist — the one-time sealed test in `05_fit_final.py` remains
  unspent.

## 2. Two analysis gaps filled

Both added as new lettered sections to `scripts/02_reliability_analysis.py`, following its existing
convention (compact printed table + CSV under `outputs/req1/`).

### §F — Speed-sensor spike years (`outputs/req1/speed_sensor_spikes.csv`)

All 284 conveyors share the same EIS date (2005-01-01), so a fleet-wide age cohort would show up as a
calendar-year spike. Checked whether the known spike years (2010/2012/2016/2019/2022) line up with a
common "years since last install/replacement." **Partial explanation only**: spike-year failures skew
~31% older on average (3.11 vs. 2.38 years) than non-spike-year failures, but the age distribution is
smoothly decreasing (mode at 1 year), not a sharp periodic peak. The cohort effect is real but doesn't
fully explain the spikes.

### §G — Bad-actor conveyor frailty (`outputs/req1/frailty_check.csv`)

Split each conveyor's 20-year history in half; compared its failure rate relative to load-class peers in
each half. **Strong, real effect**: r = 0.93 fleet-wide (Heavy 0.98, Medium 0.93, Light 0.93) between the
two halves. Conveyors that run worse than their load class explains in years 1-10 keep running worse in
years 11-20 — this is not noise. The model's own-history rate features (`rate_30/90/365` in
`features.py`) already capture this by construction, which validates that part of the feature design.
This is also a strong, surprising, defensible candidate for the Req. 1 slides.

## 3. Documentation corrections

- `analysis/fleet_kpis_report.md`: added a correction note on the old "replacement belts fail 34% sooner"
  claim, pointing to `CLAUDE.md`'s Simpson's-paradox explanation (already documented there, but the
  original file was never updated, so it still read as wrong if opened directly).
- `CLAUDE.md`: documented the leak fix, and added the §F/§G findings to the "Req. 1 findings" section.

## Files touched this session

- `scripts/01_build_tables.py`, `scripts/02_reliability_analysis.py`, `src/conveyor/features.py`
- `CLAUDE.md`, `analysis/fleet_kpis_report.md`
- Regenerated: `artifacts/climatology.json`, `outputs/req1/weibull_by_clock.csv` (Contactor rows only
  shifted by floating-point noise from re-fitting, not a real change), `outputs/experiments.csv` (one
  confirmatory `eb:1000` row appended)
- New: `outputs/req1/weibull_bearing_ml_constants.csv`, `outputs/req1/speed_sensor_spikes.csv`,
  `outputs/req1/frailty_check.csv`

## Next step

Rerun `python scripts/03_cv.py eb:1000 direct --seed 0 --folds 5` on a faster machine and compare the new
`direct` row in `outputs/experiments.csv` against the one already there (timestamp
`2026-09-26T12:16:32`) to confirm `CLAUDE.md`'s quoted CV numbers still hold after the constant fix.
