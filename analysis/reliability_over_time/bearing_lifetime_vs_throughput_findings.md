# Bearing Lifetime vs. Daily Throughput — 3D Distribution Findings

**Source data:** [`bearing_position_intervals_all_loads.csv`](bearing_position_intervals_all_loads.csv)
— 245,118 renewal intervals (231,180 of them actual failures) across 13,938 distinct
physical bearing positions, the whole fleet, built by
[`plot_bearing_lifetime_vs_load_3d.py`](plot_bearing_lifetime_vs_load_3d.py) directly
from the fleet Parquet (one row per bearing position per renewal, so `Bearing_Count`
is handled by construction — a conveyor with 50 bearings contributes 50 lifetimes, not
one).

**Figures:** [`bearing_lifetime_vs_kgday_raw_3d.png`](bearing_lifetime_vs_kgday_raw_3d.png),
[`bearing_lifetime_vs_kgday_per_bearing_3d.png`](bearing_lifetime_vs_kgday_per_bearing_3d.png)

**Reproduce:**
```
uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with scipy --with pyarrow \
  python analysis/reliability_over_time/plot_bearing_lifetime_vs_load_3d.py
```

This doc corrects an overstated claim made in conversation before this file was
written — a first read of the 3D plot said throughput shifts the bell curve left
*within* every load class. On checking the actual numbers in the CSV, that claim
doesn't hold up. The real findings are below.

## 1. The bell shape itself is real and meaningful

Each curve in the 3D plots is a Gaussian KDE of bearing lifetime (hours until
failure), and it's genuinely bell-shaped — peaked away from zero, not tallest at
zero and decaying (which is what a random/exponential failure process would look
like). This is the visual signature of wear-out: bearings have a typical expected
life, and most fail close to it. It's consistent with, and a direct visualization of,
the Weibull shape already fit in `outputs/req1/weibull_by_clock.csv`
(β=2.98 for Bearing, op-h clock) — a Weibull with β≈3 is close to the range where the
distribution starts to resemble a normal curve.

## 2. Between-load-class differences are large and well-established

From [`bearing_position_intervals_all_loads.csv`](bearing_position_intervals_all_loads.csv)
(failures only, `event==1`):

| Load class | n failures | median life (op-h) | p10–p90 range (op-h) |
|---|---:|---:|---:|
| Heavy | 112,965 | 3,204 | 1,692 – 4,788 |
| Medium | 98,853 | 6,492 | 3,456 – 9,792 |
| Light | 19,362 | 38,700 | 20,388 – 58,884 |

Heavy bearings live roughly 12x shorter than Light bearings (median-to-median).
This is the dominant, well-supported effect — already known from the Weibull
η-by-load-class fit, now visible directly as three clearly separated bell curves.

## 3. Within a load class, the throughput "dose-response" is weak and inconsistent — not a robust finding

This is the corrected part. Checked with Spearman rank correlation between bearing
life (`op_h`) and daily throughput (`kg_day`), by load class, on the same CSV:

| Load class | ρ(life, raw kg/day) | ρ(life, kg/day ÷ Bearing_Count) | Direction |
|---|---:|---:|---|
| Heavy | +0.054 (p=1.1×10⁻⁷²) | +0.054 | **more throughput → slightly *longer* life** |
| Medium | −0.086 (p=1.8×10⁻¹⁶²) | −0.069 | more throughput → slightly shorter life |
| Light | −0.130 (p=4.5×10⁻⁷⁴) | **+0.052** (flips sign) | inconsistent between the two Z-axis definitions |

Two reasons to not trust this as a real effect:

- **The p-values look extreme only because n is huge** (13,000–113,000 events per
  class). At that sample size, even a practically meaningless correlation of 0.05–0.13
  becomes "significant" at p<10⁻⁷⁰. Statistical significance here is not the same as
  a meaningful effect size.
- **Throughput barely varies within a load class to begin with**: Heavy conveyors span
  28,014–30,307 kg/day (an 8% range), Medium 29,607–31,817 (7%), Light 19,959–20,959
  (5%). `Load_Class` already sorts conveyors into narrow throughput bands (consistent
  with `analysis/throughput/throughput_findings.md`'s plant-tier finding), so there
  isn't much of a "dial" left to turn within one class — and Heavy going the *wrong*
  direction, plus Light flipping sign between the two Z-axis definitions, is what
  noise around a near-zero true effect looks like, not a real signal.

**Conclusion:** load class itself (Heavy/Medium/Light) is the real, strong,
already-documented driver of bearing life. Finer-grained daily-throughput differences
*within* a load class do not show a reliable additional effect in this data — the
apparent leftward shift in the 3D plot is not something to present as a finding.

## 4. Bearing count doesn't vary enough within a class to matter here

| Load class | Bearing_Count range | mean |
|---|---:|---:|
| Heavy | 58–68 | 63.8 |
| Medium | 44–56 | 50.7 |
| Light | 32–62 | 44.0 |

This is why the raw (`kg_day`) and per-bearing (`kg_day ÷ Bearing_Count`) versions of
the 3D plot look similar — there isn't enough within-class spread in `Bearing_Count`
for the two Z-axis definitions to diverge much. This also matches §3's finding: since
`kg_day_per_bearing` is just `kg_day` divided by a nearly-constant number per class,
it can't behave very differently from raw `kg_day`.

## Implication

Don't use "throughput predicts bearing life within a load class" as a Req. 1 claim —
it doesn't survive a proper check. The defensible, citable claims from this file are
(1) the bell-curve shape itself confirms wear-out behavior, and (2) load class remains
the dominant, large, real driver of bearing life (§2), consistent with
`outputs/req1/weibull_by_clock.csv`.
