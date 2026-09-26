# Results for the Req. 1 slides

This is a handoff for whoever builds the 2 Req. 1 slides. It collects the verified results, where each number comes from, which figures already exist, and what must **not** be claimed. Every number here has been checked against the files in `outputs/` and `analysis/` (2026-09-26).

## 1. Slide rules (spec §7, not negotiable)

- **Exactly 2 slides.** Both carry results. No title slide and no intro slide.
- **Every participant's name on both slides.** The current deck uses `Zoltan Hegyi, Jose Acosta Aldrete`. Confirm the full team list before finalising.
- **Content is Req. 1 only**: component reliability, patterns, operating effects, failure behaviour, differences between components, and uncertainty.
- The slides must read without narration. They also carry a ~3-minute talk, so lead with the clearest and most defensible findings. Skip code and implementation details.

## 2. The existing deck

- **File:** `outputs/Req1_slides.pptx` (16:9, 2 slides, committed).
- **Built by:** `scripts/07_figures.py`, which writes `outputs/figures/{beta,load,cm,accuracy}.png`, then `scripts/08_make_slides.py --names "..."`. Slide text is hard-coded in the `SLIDES` list in `08_make_slides.py`. Edit that list and rerun the script; don't hand-edit the pptx.
- **Layout per slide:** a headline, two captioned figures side by side, 3–4 bullets, and a footer with names.

| Slide | Headline | Figures | Bullets |
|---|---|---|---|
| 1 | "Bearings, belts and motor-reducers wear out, and load (not weather) sets how fast" | `beta.png`, `load.png` | Bearings = 94% of failures; perfect renewal plus the Simpson's-paradox correction; weather ≤ 5% |
| 2 | "Downtime is a failure-count problem, and it is forecastable from the last observed day" | `cm.png`, `accuracy.png` | Downtime = 36 h × failures + planned; young-conveyor ramp-up; bad actors stay bad (r = 0.93); contactor wear-out emerging |

### Two claims in the current deck are wrong and must be fixed

1. **"Bad actors stay bad … a conveyor's failure rate … predicts years 11-20 (r = 0.93)"** (slide 2). The r = 0.93 is real, but it is a **plant** effect, not a conveyor effect. Plant means of the relative rate are identical in both halves (P06 1.52/1.53, P01 0.81/0.81, P09 0.92/0.91). After subtracting each plant's mean, the conveyor-level half-vs-half correlation is **r = −0.19**, and each plant's own r lies between −0.49 and +0.28. Within a plant, conveyors are interchangeable. See finding F6 for the correct claim. `CLAUDE.md` ("Bad-actor conveyors are real and persistent") and `analysis/reliability_over_time/reliability_over_time_findings.md` §4 repeat the same over-claim.
2. **"Weather … change[s] failure rates by ≤ 5% (bearings: 0%)"** (slide 1). This holds for bearings. It does not hold for the motor-reducer, whose failure rate is 7–14% lower in summer (JJA ratio: Heavy 0.857, Medium 0.891, Light 0.928). Use the wording in F4.

### Gaps in the current deck

- **The speed-sensor 50,000 op-h ceiling is not on either slide.** The analysts rate it the strongest "the naive analysis misses this" finding (F3).
- `accuracy.png` shows Req. 2/3 forecast accuracy. It is supporting context, not a Req. 1 finding. It could give way to a Req. 1 figure (e.g. `hazard_vs_age.png` or `frailty_persistence.png`) if space is needed.

## 3. Findings, strongest first

Each finding lists the number to quote, the evidence file, and a ready-made figure where one exists.

### F1. Bearings dominate everything; every failure costs exactly 36 h

- 247,117 failures over 284 conveyors × 20 years (2005–2024, 12 plants). Bearings account for **231,180 (93.6%)**, or **40.7 per conveyor-year**. Belt 3.2%, motor-reducer 1.7%, speed sensor 0.7%, controller PC 0.6%, control software 0.2%, contactor 12 in total.
- **Repair time never varies.** Each of the 247,117 failures is followed by exactly one `CORRECTIVE_DOWNTIME` day, so every failure costs 12 h + 24 h = 36 h. This holds for every component (verified with a gaps-and-islands query).
- **Planned maintenance** runs exactly 3 times a year (15 Mar / 15 Jul / 15 Dec), 24 h each, so 72 h per conveyor-year.
- **Consequence:** downtime = 36 h × failures + 72 h/yr, so forecasting downtime means forecasting the failure count.
- Fleet availability is 81.3%: Light 95.3%, Medium 77.1%, Heavy 57.7%.
- Source: `analysis/fleet_kpis_report.md` §1, §2, §4, §5.

### F2. Three clear failure behaviours (Weibull shape β)

Right-censored Weibull renewal fits, with load class as an AFT covariate on the operating-hours clock. Source: `outputs/req1/weibull_by_clock.csv` (`intervals=all`, `clock=op_h`). Figure: `outputs/figures/beta.png`.

| Component | n failures | β (95% CI) | Behaviour | η Light (op h) | Life on Heavy vs Light |
|---|---|---|---|---|---|
| Bearing (per position) | 231,180 | 2.98 (2.97–2.98) | wear-out | 45,880 | **12.7× shorter** |
| Belt | 7,822 | 2.98 (2.92–3.03) | wear-out | 13,930 | **5.5× shorter** |
| Motor-reducer | 4,265 | 2.33 (2.27–2.38) | wear-out | 19,500 | **3.6× shorter** |
| Speed sensor | 1,838 | 1.19 (1.14–1.23) | near-random, **plus a hard ceiling (F3)** | 22,750 | no effect (1.05) |
| Controller PC | 1,537 | 0.99 (0.95–1.03) | random | 27,120 | no effect (0.96) |
| Control software | 463 | 0.91 (0.85–0.98) | infant mortality | 51,400 | **23.7× longer** (Light fails more) |
| Contactor | 12 | 3.72 (2.16–6.41) | wear-out, but n = 12 | n/a | n/a |

- **Suggested headline:** "Mechanical parts wear out, electronics fail at random, software fails early."
- **Hazard curves:** `analysis/reliability_over_time/hazard_vs_age.png` shows the same thing as actual hazard curves versus age, per load class, with the Weibull fit overlaid. It reads faster for a live audience than a β plot.
- **Distribution shapes:** `analysis/reliability_over_time/bell_curve_*.png`.

### F3. The speed sensor has a hard design-life ceiling at ≈ 50,000 op h (hidden in "β ≈ 1.2, near-random")

- **158 of 1,838 sensor failures (8.6%)** fall within 0.1% of 50,016 op h, the fleet maximum. Every other component: ≤ 0.02% of failures near their own maximum.
- The pattern holds across all load classes and every renewal index. It is the only clipping artifact in the dataset; all 17 numeric columns were swept.
- **Behaviour:** random failures up to the ceiling, then an almost certain failure at ≈ 50,000 op h (≈ 2,084 days of continuous running). The lifetime distribution is visibly bimodal.
- **Why it matters:** a Weibull-only summary misses it completely. The forecasting tool adds an expert rule for it: in backtests, the sensor is in the predicted next 5 failures every time, dated within ±1 day.
- Sources: `analysis/reliability_over_time/data_audit_ceiling_check.csv`, and `reliability_over_time_findings.md` §1, §6, §8.
- Figures: `analysis/reliability_over_time/bell_curve_speed_sensor.png`, `speed_sensor_scatter.png`, `data_audit_ceiling_check.png`.

### F4. Load (plant tier), not weather, sets how fast mechanical parts wear

- **Load acts as a stress multiplier, not just extra hours.** At the same operating hours, Heavy bearings last 12.7× shorter, belts 5.5× and motor-reducers 3.6× shorter than on Light. Sensor and PC life are unaffected, and software is inverted (F2 table).
- **Median bearing life:** Heavy 3,204 op h, Medium 6,492, Light 38,700.
- **Figures:** `outputs/figures/load.png`, and `analysis/throughput/throughput_by_load_class.png`, which shows Light 21.5k / Medium 39.7k / Heavy 50.3k kg/day on running days, as three clean tiers.
- **Weather:** effects are small and have no consistent direction.
  - **Season:** the bearing rate varies by ≤ 3% across seasons (Heavy/Medium ≤ 1%). The belt varies by ≤ 6%. The motor-reducer is **7–14% lower in summer**, a weak effect. Speed-sensor and software season ratios swing widely, but rest on small n.
  - **Same-day noise:** top vs bottom quintile of temperature, humidity and voltage residuals changes failure rates by ≤ 10% for every component, and by ≤ 1% for bearings.
  - Sources: `outputs/req1/season_effect.csv`, and `outputs/req1.log` §C–D.
- **Safe wording:** "Weather doesn't drive failures: bearings (94% of failures) are within ±3% across seasons and weather extremes. The largest effect anywhere is motor-reducers failing ~10% less in summer."
- **Caveat to state if asked:** every plant has exactly one load class, so "load" and "plant" can't be fully separated in this data.

### F5. Every component renews perfectly (repair = as good as new)

- First-life η equals renewed η. For example, belt op h 14,111 vs 13,918 and motor-reducer 20,190 vs 19,419, both within the CIs. Mean life is flat across renewal index 0–5+ within each load class.
- **Two traps were checked and debunked**, and both make good "we checked" material:
  - **Belts:** "Replacement belts last 34% less" (raw data: 7,481 vs 4,931 h) is **Simpson's paradox**. Replacements come mostly from Heavy conveyors. Within each load class, the gap is ≈ 1%.
  - **Light-class bearings:** their apparent decline with renewal index is survivorship bias. Following the same 76 physical bearing positions from renewal 0 to renewal 5 gives 25,095 → 27,885 op h (+11%, p = 0.18), so there is no decline.
- **Condition-monitoring confirmation:** right after a motor-reducer repair, temperature, current and vibration drop *below* the conveyor's own baseline.
- **Belt and motor-reducer almost never fail twice in a row:** the same-type rate in the 90 days after a repair is 0.09× baseline.
- Sources: `weibull_by_clock.csv` (`first` vs `renewed` rows); `analysis/reliability_over_time/reliability_over_time_findings.md` §2–3; `analysis/failure_interactions/failure_interactions_findings.md` §3–4, §7.
- Figures: `analysis/reliability_over_time/renewal_check.png`, `light_bearing_selection_effect.png`, `bell_curve_conveyor_belt_by_load_each_renewal.png`.

### F6. Plants differ persistently beyond load class; individual conveyors don't

- **Across the whole fleet:** each conveyor's failure rate relative to its load-class peers in years 1–10 predicts years 11–20 with **r = 0.935** (Heavy 0.98, Medium 0.93, Light 0.93).
- **Almost all of it is between plants.** Plant means are stable to 2 decimals across the halves. Within a plant, the conveyor-level correlation is **−0.19**.
- **Standout:** **P06 (Light) runs ~52% above other Light plants in both halves**, and all 18 of its conveyors sit in the high cluster. Within the Heavy tier, P04 runs at 1.07 and P09 at 0.91.
- **Failure-proneness is component-specific:** once load is controlled, conveyor failure rates for different components are uncorrelated (|r| ≤ 0.19).
- **Safe wording:** "Some plants are persistently worse than others with the same load class (P06: +52%, stable over 20 years). Within a plant, conveyors behave alike."
- **Implication for uncertainty:** the load class alone leaves a stable plant-level factor of 0.8–1.5×. A new conveyor's own history reveals that factor.
- Sources: `outputs/req1/frailty_check.csv` (plant split recomputed for this file); `failure_interactions_findings.md` §2.
- **Figure:** `analysis/reliability_over_time/frailty_persistence.png`. Caption it as plants, not conveyors.

### F7. Only the motor-reducer (and, weakly, the belt) gives advance warning

Mean within-conveyor shift over the 30 days before a failure, in σ units. Source: `outputs/req1/cm_precursors.csv`. Figure: `outputs/figures/cm.png`, or the all-component heatmap `analysis/failure_interactions/precursor_shift_heatmap.png`.

| Component | Vibration | Current / throughput | Motor temp excess |
|---|---|---|---|
| Motor-reducer | +0.21 | **+0.31** | **+0.38** |
| Belt | **+0.23** | +0.02 | +0.02 |
| Bearing | +0.05 | 0.00 | 0.00 |
| Speed sensor, PC, software | ≤ 0.05 | ≈ 0 | ≈ 0 |

- **Motor-reducer, in real units:** before a failure, motor temperature rises about 3.1–3.9 °C (Cohen's d ≈ 0.65–0.69 in every load class). The signal climbs **steadily over ~60 days**, not as a late spike, so there is a usable lead time.
  - Sources: `failure_interactions_findings.md` §6–7, 9.
  - Figures: `motor_precursor_trajectory.png`, `motor_indicator_distributions.png`.
- **Bearings, 94% of failures, give no warning** from these sensors.
- The raw contactor voltage drop tracks current (r ≈ 0.97). Normalised by current, it shows nothing.
- **Plain-language version:** `analysis/failure_interactions/early_warning_signs_plain_summary.md`.

### F8. Secondary findings (use only if space allows)

- **Contactor:** 12 failures, all from 2011 onward, all on the restart day after a failure + corrective day. That points to cycle-driven wear-out (β ≈ 3.7, CI 2.2–6.4). **Low confidence: n = 12.**
- **Control software:** failures cluster in time. The software→software transition lift is 2.8×, and the 90-day post-failure rate is 1.4× baseline, which fits infant mortality (β = 0.91) rather than clean renewal. Light conveyors have 455 software failures per million at-risk days vs 19.8 for Heavy (exact rate-ratio test, p ≈ 10⁻⁴³).
- **Speed-sensor spike years** (2010/12/16/19/22, ~2× normal) are only partly explained by sensors installed together aging together. There is a residual unexplained pattern.
- **Young conveyors:** failures ramp up through year 1 because every bearing starts new (β ≈ 3). 2005 is the only low year in the fleet; the fleet is in steady state from 2006.

## 4. Do not claim

- ~~"Bad-actor *conveyors*"~~: this is a plant effect (see §2).
- ~~"Weather changes failure rates by ≤ 5%"~~: motor-reducer summer is −7 to −14%.
- ~~"Replacement belts are worse" / "imperfect repair"~~: this is Simpson's paradox (F5). `fleet_kpis_report.md` §3–4 and its "Implications" item 4 still say it; ignore them.
- ~~"Throughput predicts bearing life within a load class"~~: |ρ| ≤ 0.13, inconsistent in sign, and throughput varies only 5–8% within a class (`bearing_lifetime_vs_throughput_findings.md`).
- ~~"Temperature should be a reliability covariate"~~: `analysis/weather/weather_seasonality_findings.md` recommends this, but the failure-rate analysis (F4) shows no meaningful effect. That report only looked at the weather itself, not at failures.
- ~~"Speed-sensor / software failures are preceded by falling temperature"~~: this is seasonal clustering, not a precursor (`failure_interactions_findings.md` §8).
- ~~Cycles as the cause of wear~~: cycles only happen on restarts after failures, so the cycles clock is endogenous.
- ~~Bearing position matters~~: ρ ≈ 0 for every load class.
- Anything about the contactor beyond "emerging, very few events".

## 5. Req. 2/3 numbers (supporting context only, if `accuracy.png` stays)

Final model: `direct-tuned` plus the speed-sensor ceiling rule. Held-out conveyors, grouped by conveyor.

| Metric | Grouped 5-fold CV | Sealed test (43 conveyors, scored once) |
|---|---|---|
| 3-year downtime error (all conveyors) | 4.41% | **4.1%** |
| 3-year downtime error (Light) | 7.69% | 7.2% |
| 3-year downtime error (< 1 year old) | 6.03% | 6.0% |
| Baseline "fleet prior + own rate" (`eb:1000`) | 9.1% | — |
| P10–P90 coverage | — | 0.825 |

- **Next-failure component accuracy** is 0.87, which equals "always Bearing". The *type* of the next failure carries almost no signal beyond the base rate, except for a speed sensor near its ceiling.
- **Unseen plant (leave-one-plant-out):** error rises to ~9–10%. This is consistent with F6: plant identity matters.
- Sources: `outputs/sealed_test.csv`, `outputs/experiments.csv`, and `CLAUDE.md` "Modeling pipeline".

## 6. Suggested structure (a recommendation, not a requirement)

- **Slide 1, "How components fail":**
  - **Figures:** F2 (β or `hazard_vs_age.png`) and F4 (`load.png`).
  - **Bullets:** F1 (bearings 94%, 36 h/failure), F3 (speed-sensor ceiling), F5 (perfect renewal and the Simpson's trap), F4 weather wording.
- **Slide 2, "What drives and predicts failures":**
  - **Figures:** F7 (`cm.png`) and F6 (`frailty_persistence.png`, captioned by plant), or keep `accuracy.png`.
  - **Bullets:** F7 lead time, F6 plant effect (P06), downtime = 36 h × failures, contactor watch item.
- **Talk order:** bearings dominate → three failure behaviours → load not weather → the hidden sensor ceiling → which failures announce themselves → what remains uncertain (plant factor, contactor with n = 12).
