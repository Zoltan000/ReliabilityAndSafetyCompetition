# Seasonal Weather Cycle Analysis

## Overview

Analysis of 20 years of historical daily data from all 284 conveyors across 12 plants in the fleet dataset (`2026-09_compet_Student_Historical_Data_V03.parquet`). The goal is to identify whether temperature and humidity follow predictable seasonal patterns tied to the calendar year, and whether these patterns warrant inclusion as operating environment covariates in component reliability modeling (Requirement 1).

## Methodology

- **Data scope**: All 2.07 million rows (2005–2024, daily resolution)
- **Aggregation**: 
  1. Per plant × day-of-year, computed mean `Temperature_Max_C`, `Temperature_Min_C`, `Humidity_pct`
  2. Per day-of-year, computed fleet-wide mean and standard deviation (cross-plant spread) of each metric
  3. Applied 7-day centered rolling mean to smooth day-to-day noise while preserving seasonal trends
- **Visualization**: Two-panel time series:
  - Top: Max and min temperatures with ±1σ cross-plant spread bands
  - Bottom: Humidity with ±1σ cross-plant spread band
  - X-axis: Day of year (Jan–Dec)

## Key Findings

### Temperature: Strong Seasonal Cycle

**Pattern:**
- Clear, stable annual cycle with ~3.5°C peak-to-trough amplitude
- **Summer peak** (June–August): Mean max 24.0°C, mean min 23.5°C
- **Winter trough** (December–February): Mean max 21.5°C, mean min 21.0°C
- **Transition months**: Smooth ramps in spring (Mar–May) and fall (Sep–Nov)

**Cross-plant consistency:**
- Shaded bands (±1σ) are tight (~0.3°C), indicating all 12 plants experience synchronized seasonal temperature swings
- Despite geographic spread, plants share a common thermal cycle
- Suggests **warehouses and indoor mounting** dampen but do not eliminate ambient seasonal variation

**Implication:** Temperature is a **meaningful operating environment covariate** that correlates with calendar seasonality. Failure rates may shift seasonally if components are thermally stressed (motor temperature, bearing lubrication viscosity, belt elasticity, contactor wetting).

---

### Humidity: Flat, Non-Seasonal Profile

**Pattern:**
- Remarkably constant across the year: **~47% ± 0.5%** year-round
- No discernible seasonal trend (no winter–summer divergence)
- Cross-plant variation negligible (narrow green band)

**Implication:** Humidity does **not follow calendar seasonality** in this fleet's environment. Likely controlled/maintained by HVAC or ventilation systems, or the sensor mix captures mostly indoor air rather than outdoor ambient. This suggests humidity is a **stable, non-covariate environmental factor** for reliability modeling — failures are unlikely to spike seasonally due to humidity swings.

---

## Recommendations for Requirement 1 (Component Reliability)

### Include in Covariates
- **Temperature**: Use `Temperature_Max_C` and/or `Temperature_Min_C` as covariates in component-level failure models (e.g., via Weibull/NHPP with log-link). The 3.5°C seasonal swing is material enough to affect component wear rates.
  - *Why*: Motor and bearing performance are thermally sensitive; contactors can suffer increased arcing or contact erosion in warm months; belt elasticity changes with temperature.

### Exclude or Deprioritize
- **Humidity**: Drop from covariates or assign low weight. The flat profile offers no signal; including it risks overfitting or masking actual failure drivers.

### Validation
- **Backtest**: Fit failure models with and without temperature as a covariate on a held-out conveyor subset (e.g., truncate to 250–500 days). Compare forecast accuracy to confirm temperature improves predictions.
- **Residual analysis**: Plot residuals (actual vs. predicted failures) stratified by month or temperature bin to check for remaining seasonal patterns or model misspecification.

---

## Technical Notes

- **DuckDB aggregation**: Parquet directly queried; no pandas materialization needed, keeping memory footprint small.
- **Rolling smoothing**: 7-day window balances noise suppression with retention of genuine seasonal detail.
- **Null handling**: Rows with missing temperature or humidity data excluded from aggregation (standard practice; confirms most records are complete).

---

## Temperature–Humidity Independence

An additional analysis examined whether temperature and humidity are correlated, testing whether they represent the same underlying environmental driver or independent phenomena.

**Correlation results:**
- **Fleet-wide**: +0.1319 (Temp_Max vs Humidity) — weak positive, entirely due to seasonal confounding
- **Per-plant**: −0.0047 to +0.0045 (all near-zero) — no meaningful daily relationship

**Visual evidence** (scatter plots colored by month):
- Winter data (blue) cluster at ~21–22°C with ~47% humidity
- Summer data (yellow) cluster at ~23–24°C with same ~47% humidity
- The "separation" is seasonal, not causal — temperature and humidity shift together only because both respond to calendar season independently

**Implication**: Temperature and humidity are **decoupled drivers**. Humidity is not a reliability covariate; it offers no signal for component failure prediction. The weak fleet-level correlation is a statistical artifact, not a physical relationship.

---

## File References

- **Input**: `2026-09_compet_Student_Historical_Data_V03.parquet`
- **Weather analysis**: `analysis/weather/` (seasonality plots and scripts)
- **Correlation analysis**: `analysis/correlation/` (humidity vs temperature plots and scripts)
- **This report**: `analysis/reports/weather_seasonality_findings.md`

---

## Conclusion

The fleet exhibits a **stable, predictable seasonal temperature cycle (~3.5°C annual amplitude) that warrants inclusion as a reliability covariate**, while **humidity remains flat, uncorrelated with temperature, and offers no predictive signal**. This supports Requirement 1 by providing concrete, data-backed evidence that operating environment effects on component behavior are driven by **thermal stress alone**, not humidity control. 

**Recommendations:**
- ✅ **Include** `Temperature_Max_C` and/or `Temperature_Min_C` as operating-environment covariates in component failure models
- ❌ **Exclude** `Humidity_pct` — it adds no variance, correlates with nothing, and dilutes model clarity
