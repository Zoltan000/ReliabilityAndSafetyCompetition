# Data Integrity Audit — Hidden Tricks, Leaks, and Evaluation Risks

**Source:** `2026-09_compet_Student_Historical_Data_V03.parquet` + this repo's own
evaluation code (`src/conveyor/evaluate.py`), queried with DuckDB.
**Generated:** 2026-09-26.
**Reproduce:**
```
uv run --no-project --with duckdb --with pandas --with numpy --with scikit-learn --with pyarrow \
  python analysis/data_audit/run_integrity_checks.py
```

## Why this exists

Prompted by an explicit ask to check for "tricks that were designed to be overseen by
LLMs too" — not just "what does the data say" (covered in `analysis/failure_interactions/`
and `analysis/reliability_over_time/`) but "what might trip up an LLM-driven analysis
or an LLM-written modeling pipeline specifically." Six independent, previously
unchecked angles, each fast (seconds) against the fleet file. Five came back clean;
one is a real, documented trap — though verified **not** currently exploited by this
repo's own pipeline.

## 1. Example-file consistency — CLEAN

`Example_P02CV27_1Year.parquet` and `Example_P02CV27_6Years.parquet` were claimed
(CLAUDE.md, spec) to be exact cut-off prefixes of `P02CV27`'s rows in the fleet file,
but this was never actually verified. Checked row-for-row, column-for-column, all 36
columns, both files: **zero discrepancies.** This matters because it's a grading-path
risk, not just an understanding one — if the example files had diverged even slightly
from the fleet slice, a forecasting tool validated against them could behave
differently on the hidden evaluation file. Confirmed clean.

## 2. Contactor deep characterization — CLEAN (no second hidden ceiling)

Only 12 fleet-wide failures — small enough to look at every single one directly
rather than statistically, the same way the Speed_Sensor ceiling was originally found
by looking at raw data instead of summary stats. All 12 events pulled with full
context (conveyor, load class, date, cumulative operating hours, cumulative cycles,
operating-hours-since-restart). Cumulative operating hours (31,272–116,784) and
cumulative cycles (657–2,025) are both widely spread with no repeated or
suspiciously-close values — no second ceiling. (Operating-hours-since-restart = 12.0
for all 12 and days-since-last-failure = 0 for all 12 are both already-documented
facts about the restart-cycling wear mechanism, not new.) This is a useful negative
result: it reinforces that the Speed_Sensor ceiling really is a one-off, not one of
several similar tricks scattered through the dataset.

## 3. Leakage timing audit — REAL FINDING, but not currently exploited

Checked two things:

- **Whether `Failed_Component_ID`/`Sensor_Replacement` ever appear on a non-`FAILURE_DAY`
  row** (they should only ever describe the day's own failure) — confirmed they don't;
  always exactly 0 outside `FAILURE_DAY`.
- **Whether `Days_Since_Last_Failure` and `Cumulative_Failure_Count` are "as-of-start-
  of-day" (safe) or already reflect the current day's own failure (a same-day leak)** —
  checked directly against a real failure (P02CV27, 2005-06-06): on the failure day
  itself, `Days_Since_Last_Failure` resets to **0** and `Cumulative_Failure_Count`
  **already includes that day's failure**, not the day after. Both columns are
  end-of-day accounting, not as-of-start-of-day.

**This is exactly the kind of trap the request was asking about.** A naive
feature-engineering pass — by an LLM or otherwise — that reaches for these two
obviously-named, tempting columns as same-day predictors of "will a failure happen
today" would get a severe, silent leak: `Days_Since_Last_Failure == 0` is *already
true* on every single failure day, by definition, before any real prediction has
happened. A model built on it would look outstanding in-sample and be worthless in
deployment.

**Checked whether this repo's own pipeline is exposed:** grepped `src/conveyor/` and
`scripts/` for both column names. Neither is used as a model feature anywhere —
`Cumulative_Failure_Count` appears exactly once, in `io.py`'s calendar-gap
forward-fill list (data hygiene, not a feature), and `Days_Since_Last_Failure` doesn't
appear at all. **The trap is real in the raw data, but not currently triggered.**
Worth keeping this file around specifically so nobody reaches for either column later
without knowing why not to.

## 4. Sealed-conveyor selection bias — CLEAN

`src/conveyor/evaluate.sealed_conveyors()` holds out ~15% of conveyors per plant
(`np.random.default_rng(seed=0)`, stratified by plant, sampling without replacement)
for the one-time final model score already reported (4.1% 3-year downtime error). The
selection code is legitimately random by construction, but a fixed seed with small
per-plant counts could still land on an unlucky, unrepresentative draw by chance —
checked directly rather than trusting the code alone:

- Load-class mix: sealed (Heavy 20.9% / Light 44.2% / Medium 34.9%) vs. non-sealed
  (20.3% / 45.2% / 34.4%) vs. overall (20.4% / 45.1% / 34.5%) — all within ~1
  percentage point.
- Fleet-wide failure rate: sealed 138.6 per 1,000 at-risk days vs. non-sealed 136.1 —
  a ~1.8% difference, ordinary sampling noise for a 43-conveyor hold-out.

The sealed-test numbers already reported are trustworthy; this seed didn't get unlucky.

## 5. Duplicate/near-duplicate conveyor detection — CLEAN

Hashed each of the 284 conveyors' full failure sequence (`day_idx:Failure_Type`,
in order) and, separately, each conveyor's full `Motor_Current_A` daily sequence
(rounded to 3dp). Zero conveyors share an identical hash on either signature — no
copy-paste artifact in the generator, distinct from the already-understood
within-plant homogeneity in static/environment columns (which are *supposed* to be
shared, per plant design, not a red flag).

## 6. Quantization/precision sweep — CLEAN

Checked whether the continuous condition-monitoring signals show genuinely continuous
noise or suspiciously coarse rounding (which might expose a crude/discrete
underlying generator). Distinctness (unique values ÷ total rows) is 65-92% for
`Motor_Current_A`, `Motor_Temperature_C`, `Structure_Vibration_RMS_mm_s`,
`Contact_Voltage_Drop_mV`, `Contactor_Closing_Time_ms`, and `Humidity_pct` — genuine
high-precision floating-point noise, not a discretized/quantized value set.
`Voltage_V`'s lower 22% distinctness is explained by its narrow true operating range
(468-492V, plant-constant ± small noise), not quantization — a narrower range simply
has fewer possible values at a given decimal precision, nothing suspicious.

## Bottom line

**One real finding (§3), everything else clean.** The Speed_Sensor ceiling remains
the one genuine hidden artifact found across this entire session's data audits (this
one plus the earlier column-clipping sweep in
`analysis/reliability_over_time/reliability_over_time_findings.md` §6). The example
files, the sealed hold-out, and the dataset's internal consistency (no duplicates, no
quantization tricks) all check out — the main actionable takeaway is the documented
leakage trap in §3, worth remembering even though it isn't currently a live bug.
