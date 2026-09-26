# Fleet KPI Report

**Source:** `2026-09_compet_Student_Historical_Data_V03.parquet`, queried with DuckDB.
**Generated:** 2026-09-26.
**Reproduce:** from the repo root, run `uv run --no-project --with duckdb python analysis/run_sql.py analysis/fleet_kpis.sql`.

Every figure below comes from `analysis/fleet_kpis.sql`.

## 1. Data overview

| Metric | Value |
|---|---|
| Rows | 2,074,620 |
| Conveyors | 284 |
| Plants | 12 |
| Period | 2005-01-01 to 2024-12-31 (20 years) |
| Missing condition-monitoring readings on running days | 0 |

| Daily_State | Days | % of days | Operating h | Downtime h |
|---|---|---|---|---|
| RUNNING | 1,563,380 | 75.36 | 37,521,120 | 0 |
| FAILURE_DAY | 247,117 | 11.91 | 2,965,404 | 2,965,404 |
| CORRECTIVE_DOWNTIME | 247,083 | 11.91 | 0 | 5,929,992 |
| PLANNED_MAINTENANCE | 17,040 | 0.82 | 0 | 408,960 |

**Consistency checks (all pass):**
- There are 247,117 failure rows, which equals the sum of each conveyor's final `Cumulative_Failure_Count`.
- Adding up the downtime of each failure (the 12 h failure day plus the corrective days that follow) gives 8,895,396 h. That matches the total downtime on `FAILURE_DAY` and `CORRECTIVE_DOWNTIME` days.

## 2. Failures per type

| Component | Failures | % of failures | Per conveyor-year |
|---|---|---|---|
| Bearing | 231,180 | 93.55 | 40.70 |
| Conveyor_Belt | 7,822 | 3.17 | 1.38 |
| Motor_Reducer | 4,265 | 1.73 | 0.75 |
| Speed_Sensor | 1,838 | 0.74 | 0.32 |
| Controller_PC | 1,537 | 0.62 | 0.27 |
| Control_Software | 463 | 0.19 | 0.08 |
| Contactor | 12 | 0.00 | 0.00 |
| **Total** | **247,117** | 100 | 43.51 |

## 3. Conveyor belt operating hours

`Cumulative_Operating_Hours` is a counter for the whole conveyor, not for the belt. The table therefore reports three different measures.

| Measure | n | Mean (h) | Std dev (h) | Min (h) | Median (h) | Max (h) |
|---|---|---|---|---|---|---|
| a. Conveyor cumulative hours on the day of each belt failure | 7,822 | 66,566.2 | 39,774.2 | 564 | 64,086 | 168,048 |
| **b. Belt life: operating hours between belt failures (all)** | 7,822 | **5,023.3** | **4,473.0** | 156 | 3,372 | 30,192 |
| b1. First belt (counted from start of service) | 284 | 7,481.4 | 5,659.7 | 564 | 5,298 | 23,208 |
| b2. Replacement belts | 7,538 | 4,930.6 | 4,395.8 | 156 | 3,348 | 30,192 |
| c. Conveyor cumulative hours at the end of 2024 | 284 | 142,558.2 | 25,445.1 | 96,756 | n/a | 168,660 |

**How to read these:**
- Measure **b** is the reliability-relevant belt life.
- Measure **a** mostly reflects conveyor age at the time of failure.
- Replacement belts last about 34% fewer hours than the original belt. This points to imperfect repair, or to replacement belts being different from the originals.
  - **Correction (see `CLAUDE.md`, "Req. 1 findings"):** this is a Simpson's-paradox artifact, not imperfect repair. Belt replacements are dominated by Heavy conveyors (which fail faster from load, not from being repaired worse); once load class is controlled for (`scripts/02_reliability_analysis.py`, `outputs/req1/weibull_by_clock.csv`), first-life and renewed-life η are within ~1.4% of each other. Renewal is effectively perfect.

## 4. Per-component reliability

MTBF is measured between consecutive failures of the same component on the same conveyor. The first failure after the start of service is excluded.

| Component | Failures | MTBF (op h) | Std (op h) | MTBF (days) | Std (days) | Mean repair (h) | Total downtime (h) | % of corrective downtime |
|---|---|---|---|---|---|---|---|---|
| Bearing | 231,180 | 167 | 429 | 9 | 18 | 36.0 | 8,321,664 | 93.6 |
| Conveyor_Belt | 7,822 | 4,931 | 4,396 | 255 | 179 | 36.0 | 281,592 | 3.2 |
| Motor_Reducer | 4,265 | 8,886 | 6,708 | 461 | 279 | 36.0 | 153,540 | 1.7 |
| Speed_Sensor | 1,838 | 18,424 | 14,567 | 932 | 753 | 36.0 | 66,168 | 0.7 |
| Controller_PC | 1,537 | 20,564 | 19,805 | 1,046 | 1,012 | 36.0 | 55,332 | 0.6 |
| Control_Software | 463 | 33,973 | 29,320 | 1,515 | 1,330 | 36.0 | 16,668 | 0.2 |
| Contactor | 12 | n/a | n/a | n/a | n/a | 36.0 | 432 | 0.0 |

**What the table shows:**
- **Repair time never varies.** Every failure costs exactly 36 h (12 h on the failure day plus one 24 h corrective day), whatever the component. Downtime is therefore 36 h × the number of failures, so it doesn't need its own model.
- **Bearing MTBF is per conveyor, not per bearing.** It covers a population of about 49 bearings on each conveyor.
- **The contactor has no MTBF.** No conveyor had two contactor failures, so there is no interval to measure. All 12 of its failures happened between 2011 and 2024.

## 5. Availability and downtime

Availability here means operating hours divided by calendar hours.

| Group | Availability % | Corrective downtime h / conveyor-year | Planned downtime h / conveyor-year |
|---|---|---|---|
| **Fleet** | **81.31** | **1,566.1** | **72.0** |
| Load Light | 95.27 | 342.7 | 72.0 |
| Load Medium | 77.07 | 1,937.8 | 72.0 |
| Load Heavy | 57.68 | 3,637.8 | 72.0 |
| Plant P01 | 95.98 | 280.5 | 72.0 |
| Plant P02 | 76.56 | 1,982.5 | 72.0 |
| Plant P03 | 95.84 | 292.6 | 72.0 |
| Plant P04 | 55.58 | 3,821.8 | 72.0 |
| Plant P05 | 78.51 | 1,812.0 | 72.0 |
| Plant P06 | 93.30 | 515.7 | 72.0 |
| Plant P07 | 77.38 | 1,911.2 | 72.0 |
| Plant P08 | 95.48 | 324.0 | 72.0 |
| Plant P09 | 60.26 | 3,411.4 | 72.0 |
| Plant P10 | 95.64 | 309.8 | 72.0 |
| Plant P11 | 75.32 | 2,091.7 | 72.0 |
| Plant P12 | 95.18 | 350.2 | 72.0 |

**Planned maintenance is completely regular:** 17,040 episodes, which is exactly 3 per conveyor per year, and each lasts 1 day.

## 6. Failure rates by load class

Failures per 10,000 operating hours:

| Component | Light (128 conv.) | Medium (98) | Heavy (58) | Heavy / Light |
|---|---|---|---|---|
| Bearing | 9.056 | 74.651 | 192.602 | 21.3× |
| Conveyor_Belt | 0.774 | 2.708 | 4.402 | 5.7× |
| Motor_Reducer | 0.556 | 1.424 | 2.029 | 3.6× |
| Speed_Sensor | 0.456 | 0.462 | 0.430 | ~1× |
| Controller_PC | 0.368 | 0.398 | 0.382 | ~1× |
| Control_Software | 0.192 | 0.035 | 0.010 | 0.05× |
| Contactor | 0 | 0.001 | 0.019 | n/a |

**Components fall into three groups:**
- **Load-driven:** bearings, belt and motor-reducer. For these, operating hours are the wrong exposure clock unless load is also accounted for.
- **Load-independent:** speed sensor and controller PC. Their failures are probably driven by calendar time.
- **Inverted:** control software fails more often on Light conveyors. Heavy conveyors spend more time down, so this may be a calendar-time effect or a confounder.

Failures per conveyor-year by plant:

| Plant | Conveyors | Failures / conveyor-year |
|---|---|---|
| P04 | 32 | 106.17 |
| P09 | 26 | 94.77 |
| P11 | 17 | 58.11 |
| P02 | 27 | 55.07 |
| P07 | 30 | 53.09 |
| P05 | 24 | 50.33 |
| P06 | 18 | 14.33 |
| P12 | 29 | 9.73 |
| P08 | 13 | 9.00 |
| P10 | 33 | 8.60 |
| P03 | 15 | 8.13 |
| P01 | 20 | 7.79 |

The plants split into a high-failure cluster and a low-failure cluster. This is probably their mix of load classes; confirm by cross-tabulating plant against load class.

## 7. Trends

Failures per year:

| Year | Bearing | Contactor | Control_Software | Controller_PC | Conveyor_Belt | Motor_Reducer | Speed_Sensor |
|---|---|---|---|---|---|---|---|
| 2005 | 8,150 | 0 | 47 | 79 | 295 | 126 | 66 |
| 2006 | 10,933 | 0 | 31 | 84 | 400 | 217 | 74 |
| 2007 | 11,274 | 0 | 30 | 91 | 404 | 229 | 67 |
| 2008 | 11,706 | 0 | 24 | 66 | 395 | 210 | 52 |
| 2009 | 11,887 | 0 | 22 | 87 | 380 | 218 | 55 |
| 2010 | 12,003 | 0 | 21 | 75 | 409 | 215 | **173** |
| 2011 | 11,828 | 1 | 16 | 74 | 390 | 236 | 82 |
| 2012 | 11,801 | 0 | 27 | 91 | 392 | 196 | **147** |
| 2013 | 11,718 | 0 | 26 | 90 | 397 | 219 | 46 |
| 2014 | 11,866 | 1 | 16 | 72 | 401 | 224 | 81 |
| 2015 | 11,782 | 0 | 23 | 76 | 389 | 225 | 89 |
| 2016 | 11,829 | 0 | 20 | 68 | 404 | 208 | **170** |
| 2017 | 11,758 | 0 | 20 | 83 | 401 | 227 | 80 |
| 2018 | 11,860 | 0 | 15 | 67 | 386 | 198 | 63 |
| 2019 | 11,734 | 1 | 22 | 72 | 395 | 221 | **137** |
| 2020 | 11,900 | 2 | 20 | 77 | 383 | 218 | 70 |
| 2021 | 11,739 | 1 | 23 | 63 | 408 | 222 | 70 |
| 2022 | 11,756 | 1 | 20 | 61 | 399 | 226 | **168** |
| 2023 | 11,773 | 4 | 24 | 79 | 396 | 208 | 86 |
| 2024 | 11,883 | 1 | 16 | 82 | 398 | 222 | 62 |

**Year-by-year patterns:**
- **The fleet is in steady state from 2006 onwards.** 2005 is lower because every conveyor starts its first life then, with no renewals yet.
- **Control_Software failures are highest in 2005 (47) and fall over time.** This is consistent with early-life failures that get fixed.
- **Speed_Sensor failures spike in 2010, 2012, 2016, 2019 and 2022.** They run at about 2× the usual level in those years, which suggests a replacement cohort or a batch effect. Every speed-sensor failure matches exactly one `Sensor_Replacement` (1,838 of each).
- **Contactor failures only appear from 2011 onwards.** They may be the start of wear-out.

## 8. Conveyor extremes

| Rank | Conveyor | Plant | Load | Failures (20 y) |
|---|---|---|---|---|
| Most | P04CV32 | P04 | Heavy | 2,143 |
| | P04CV13 | P04 | Heavy | 2,137 |
| | P04CV28 | P04 | Heavy | 2,136 |
| | P04CV20 | P04 | Heavy | 2,135 |
| | P04CV06 | P04 | Heavy | 2,131 |
| Fewest | P01CV03 | P01 | Light | 145 |
| | P01CV19 | P01 | Light | 148 |
| | P01CV01 | P01 | Light | 149 |
| | P03CV12 | P03 | Light | 151 |
| | P01CV15 | P01 | Light | 151 |

## 9. Bearings

| Metric | Value |
|---|---|
| Average bearings per conveyor | 49.1 |
| Bearing failures | 231,180 |
| Failures per bearing over 20 years | 16.6 |
| Distinct bearing positions that failed at least once | 13,938 (≈ every bearing in the fleet) |

## Implications for modeling

1. **Model bearings first.** They cause 94% of failures and downtime, so they decide most of the 3-year downtime forecast (Req. 3).
2. **Forecast downtime as 36 h × the expected number of failures**, plus 72 h of planned maintenance per year. Report corrective and planned downtime separately.
3. **Use load class as a covariate** for the bearing, belt and motor-reducer models. Treat speed sensor and controller PC as calendar-time processes.
4. **Treat the belt as a renewal process with imperfect repair.** The first belt lasts longer than its replacements (7,481 h vs 4,931 h).
5. **Look into the speed-sensor cohort spikes.** They may make the next-5 failure order predictable in certain years.
