# Improvement backlog (agent B)

You implement model and feature improvements, in parallel with agent A, who runs and finalizes the
pipeline from `docs/HANDOFF_gaming_pc.md`. Read `CLAUDE.md` first: data facts, findings, pipeline order.

## Working agreement

- Work on the branch `improvements` (`git checkout -b improvements`, rebased on `main` regularly). A owns `main`.
- **Every change has to earn its place in grouped CV.** After a change:
  1. Rebuild with `scripts/01_build_tables.py` (the parity asserts must still print 0).
  2. Run `scripts/03_cv.py <spec> --seed 0` against the current best row in `outputs/experiments.csv`.
  3. Keep the change only if it improves the target metric without hurting `all:dt_tot_pct`.
  4. Merge winners into `main` in small PRs or fast-forwards, and tell the user what changed and by how much.
- Metric names come from `src/conveyor/evaluate.py`. Every metric is averaged per conveyor. Report
  `all`, `Light` and `age<1y`, because they are the weak spots.
- Never read the sealed conveyors (`evaluate.sealed_conveyors`) for anything, including fitting constants.
- Add a new model variant as a spec in `scripts/03_cv.py::make()` (e.g. `direct-v2`) rather than
  changing `direct` in place, so old and new stay comparable.
- Keep `features.daily_features()` causal: row i may use only rows 0..i. Only `labels.py` looks forward.

## Baseline to beat (grouped CV, 5 folds, seed 0; agent A is re-verifying after the leak fix)

| Metric | `eb:1000` | `direct` |
|---|---|---|
| 3-year downtime error `dt_tot_pct` | 0.091 | 0.045 |
| … conveyors < 1 year old | 0.211 | 0.059 |
| next-failure timing `t1_logerr` | 0.649 | 0.645 |
| 5th-failure timing `t5_logerr` | 0.302 | 0.270 |
| next-component accuracy `c1_acc` (all / Light) | 0.864 / 0.764 | 0.859 / 0.754 |

## Backlog, in priority order

### 1. Fix the component classifier (Req. 2) — high
It's slightly worse than always predicting "Bearing", so it currently adds nothing.
- Add age-based Weibull risk features for belt, motor-reducer, speed sensor and PC, like the existing
  `brg_whaz_next*` in `features.py`. That gives the expected failures of component c in the next 7/30/90
  days from its op-hour age since its last renewal (`<comp>_since_oh`), load-class η and β.
  - Get the fits from `outputs/req1/weibull_by_clock.csv`, but **refit them excluding the sealed conveyors**, as
    `02_reliability_analysis.py` §A2 does for bearings.
  - Store the constants in one table, e.g. `artifacts/weibull_constants.json` written by `02`, rather than
    as more hard-coded numbers.
- Add a feature for P(next failure is not a bearing): the ratio of the other components' hazards to the bearing hazard.
- Decision rule: predict a non-bearing component only if its calibrated probability beats Bearing. Check
  calibration of the LightGBM multiclass output: it's trained with conveyor weights, which may distort it.
  Try training without weights, and try an isotonic recalibration on OOF.
- Target: `c1_acc` > 0.864 overall and > 0.764 on Light.

### 2. More training origins for young conveyors — high
The hidden file may have as few as 200 days of history, and year 1 is where bearing failures ramp up.
- In `01_build_tables.py`, use a cut-off every day from day 199 to day 730, then weekly after that.
- Down-weight the dense rows, so each conveyor keeps equal total weight and the young regime gets its own weight.
- Watch memory: `DirectML._long` stacks origins × 36 blocks. Use `count_stride`, or subsample within the dense region.
- Target: the `age<1y` metrics.

### 3. Optuna tuning — high (needs the gaming PC)
- New `scripts/04_tune.py`: an Optuna study per sub-model:
  - count model: `all:dt_tot_pct` on grouped CV;
  - AFT: `t5_logerr` plus `t1_logerr`;
  - component classifier: multiclass log-loss.
- Search `num_leaves`, `min_data_in_leaf`, `learning_rate` × rounds (with early stopping on an inner
  grouped split), `feature_fraction`, `lambda_l2`, AFT `aft_loss_distribution` and its scale, and XGBoost `max_depth`.
- Use 3 folds during search, then confirm the best configuration with the 5-fold harness.
- Save the best parameters to `artifacts/params.json` and make `DirectML` read them (its constructor already
  accepts `lgb_count`, `xgb_aft` and `lgb_comp`).

### 4. Unseen-plant robustness — medium (do it if agent A's leave-one-plant-out run is much worse than grouped CV)
- `Bearing_Count`, `Length_m`, the rating fields, and the plant humidity/voltage/temperature levels each identify the plant.
- Try a variant without the plant-identifying static features. Keep `load_class`. Replace the dropped
  ones with physical per-conveyor quantities: `tp_90`, and the conveyor's own rates, which already carry the frailty
  signal (r = 0.93, see `CLAUDE.md`).
- Compare grouped CV and `--lopo` for both variants. Choose by the worse of the two, since we don't know
  whether the hidden conveyor's plant is in the fleet.

### 5. Forward-chaining leakage check — medium
- Add a `--forward <YYYY-MM-DD>` mode to `03_cv.py`: train only on origins whose 3-year label window ends
  before the cut date; test on held-out conveyors' origins at or after that date.
- If it's much worse than plain grouped CV, the model leans on calendar information from other
  conveyors (e.g. the speed-sensor spike years). Report that and remove calendar-identifying features.

### 6. Inputs that don't start at the conveyor's entry into service — medium
- `features.py` assumes the file starts at EIS. A never-failed component (or bearing position) gets age = conveyor age.
  If the file starts mid-life, bearing ages are unknown.
- Add training rows built from left-truncated histories: drop the first N days before computing features.
- Add a `history_starts_at_eis` flag feature. Keep the parity asserts meaningful: they should compare like with like.

### 7. Monte Carlo challenger for next-5 timing — medium or low
- Build a per-bearing Weibull renewal simulation plus the other components, using the current ages from the
  features, 1 corrective day after each failure, and planned-maintenance days.
- Output the median time to each of the next 5 failures and the component shares. Add it as spec `mc` and
  compare `t1..t5_logerr` and `c*_acc`. Use it for Req. 2 only if it wins; also test a blend (geometric mean with `direct`).

### 8. Small, cheap features — low
- **Restart day:** failure risk is higher on the first day after a stop (Heavy 0.40 vs 0.27). The feature is
  "origin is a failure day / tomorrow is a restart", partly covered by `state_code`.
- **Contactor wear:** `contactor_since_cyc` exists already. Add cycles since EIS × load.
- **Explicit frailty:** the conveyor's rate relative to its load-class prior, shrunk (empirical Bayes), as one feature.

### 9. Req. 3 output detail — low
- Planned maintenance is postponed when the conveyor is down on the nominal date (03-15, 07-15, 12-15).
  A failure on the last day of a block pushes its 24 h corrective day into the next block. Both are small biases:
  measure them with the `m{j}_dt` and `m{j}_pm` labels before fixing.

### 10. Point-estimate choice — blocked on the organizers
The dates for Req. 2 are AFT medians. If the organizers score with MAE in days or a similar metric,
compare median, mean and a CV-optimal quantile per k on OOF. The ensemble uses geometric means of the
seed models' predictions (`forecast.ensemble_predict`).

## Don't

- Don't touch `notebooks/`, `artifacts/model_seed*` or the sealed test. Those belong to agent A.
- Don't add features that read a post-origin value (future weather, future CM). Weather enters only
  through the climatology levels, which are known in advance.
