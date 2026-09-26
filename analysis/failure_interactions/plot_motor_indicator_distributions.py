"""One PNG, one panel per indicator, showing the real-unit distribution (Amps, deg C,
mm/s, etc.) of each Motor_Reducer precursor signal on ordinary days vs. the 30 days
right before a failure -- the "what does the motor actually do before it breaks"
picture, in physical units instead of the abstract z-scores used in
plot_precursor_scan_all_components.py / plot_motor_precursor_field_scan.py.

Uses the 6 fields that scan already identified as Motor_Reducer's real precursors
(precursor_shift_all_components.csv), pooled across load class (see
plot_motor_failure_precursor_by_load.py for the load-class-split version of
temperature/current specifically).

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with scipy \
    python analysis/failure_interactions/plot_motor_indicator_distributions.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
BLUE, RED, GRID, SURF, INK, INK2 = "#2a78d6", "#c0392b", "#e4e3df", "#fcfcfb", "#0b0b0b", "#52514e"
PRECURSOR_WINDOW = 30

# field -> (raw SQL expression, axis label, display units)
FIELDS = {
    "Motor_Current_A": ("Motor_Current_A", "Motor current", "A"),
    "Motor_Temperature_C": ("Motor_Temperature_C", "Motor temperature", "°C"),
    "Structure_Vibration_RMS_mm_s": ("Structure_Vibration_RMS_mm_s", "Vibration RMS", "mm/s"),
    "Contact_Voltage_Drop_mV": ("Contact_Voltage_Drop_mV", "Contactor voltage drop", "mV"),
    "Current_per_Throughput": ("Motor_Current_A / NULLIF(Throughput_kg_per_h, 0)",
                               "Current / throughput", "A per kg/h"),
    "MotorTemp_Excess": ("Motor_Temperature_C - Temperature_Max_C", "Motor temp − ambient", "°C"),
}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def main():
    con = duckdb.connect()
    select_exprs = ",\n           ".join(f"{expr} AS {name}" for name, (expr, _, _) in FIELDS.items())
    print("Fetching motor signals + pre-failure marker...")
    df = con.sql(f"""
        WITH f AS (
            SELECT Conveyor_ID, Date, Daily_State, Failure_Type,
                   {select_exprs},
                   ROW_NUMBER() OVER (PARTITION BY Conveyor_ID ORDER BY Date) AS rn
            FROM read_parquet('{FLEET}')
        ),
        fails AS (
            SELECT Conveyor_ID, rn AS fail_rn FROM f
            WHERE Daily_State = 'FAILURE_DAY' AND Failure_Type = 'Motor_Reducer'
        )
        SELECT f.*,
               MAX(CASE WHEN fl.fail_rn - f.rn BETWEEN 1 AND {PRECURSOR_WINDOW} THEN 1 ELSE 0 END) AS pre_failure
        FROM f
        LEFT JOIN fails fl ON fl.Conveyor_ID = f.Conveyor_ID AND fl.fail_rn - f.rn BETWEEN 1 AND {PRECURSOR_WINDOW}
        GROUP BY f.Conveyor_ID, f.Date, f.Daily_State, f.Failure_Type, f.rn,
                 {", ".join(FIELDS.keys())}
    """).df()
    print(f"  {len(df):,} rows, {df.pre_failure.sum():,} in the {PRECURSOR_WINDOW}-day pre-failure window")

    # Pooling raw values across conveyors is confounded by WHICH conveyors show up in
    # each sample: Heavy/Medium conveyors fail by Motor_Reducer far more often, so the
    # pre-failure sample is more Heavy/Medium-weighted (68%) than the normal-days sample
    # (49%) -- and since throughput (and things scaled by it) vary a lot by load, that
    # alone can move a pooled average even with zero real day-to-day change. Caught this
    # on Current_per_Throughput, which flipped sign vs. the within-conveyor z-score
    # result. Fix: center each conveyor on its own mean first, then re-add the
    # fleet-wide mean -- removes the between-conveyor mixing, keeps real units.
    for name in FIELDS:
        conv_mean = df.groupby("Conveyor_ID")[name].transform("mean")
        df[name] = df[name] - conv_mean + df[name].mean()

    fig, axes = plt.subplots(2, 3, figsize=(16, 9.5))
    rows = []
    for ax, (name, (_, label, unit)) in zip(axes.flat, FIELDS.items()):
        base = df.loc[df.pre_failure == 0, name].dropna()
        pre = df.loc[df.pre_failure == 1, name].dropna()
        ax.hist(base, bins=70, density=True, color=BLUE, alpha=0.55, label=f"normal days (n={len(base):,})")
        ax.hist(pre, bins=70, density=True, color=RED, alpha=0.55,
                label=f"≤30d before failure (n={len(pre):,})")
        ax.axvline(base.mean(), color=BLUE, ls="--", lw=1.4)
        ax.axvline(pre.mean(), color=RED, ls="--", lw=1.4)
        t, p = stats.ttest_ind(pre, base, equal_var=False)
        pct = (pre.mean() / base.mean() - 1) * 100 if base.mean() != 0 else np.nan
        ax.set_title(f"{label}\nnormal: {base.mean():.2f}{unit}  →  pre-failure: {pre.mean():.2f}{unit}  "
                     f"({pct:+.0f}%)", fontsize=10.5)
        ax.set_xlabel(f"{label} ({unit})")
        ax.set_ylabel("Density")
        ax.legend(fontsize=7.5, frameon=False)
        style(ax)
        rows.append({"field": name, "normal_mean": base.mean(), "prefailure_mean": pre.mean(),
                    "pct_change": pct, "p_value": p, "n_normal": len(base), "n_prefailure": len(pre)})

    fig.suptitle(f"What the motor actually does before a Motor-Reducer failure\n"
                 f"(real units, load-composition-adjusted, {PRECURSOR_WINDOW}-day pre-failure window vs. "
                 f"all other days, dashed = mean)",
                 fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "motor_indicator_distributions.png", dpi=180, bbox_inches="tight")
    print(f"Saved: {OUT / 'motor_indicator_distributions.png'}")

    pd.DataFrame(rows).to_csv(OUT / "motor_indicator_distributions.csv", index=False)
    print(pd.DataFrame(rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
