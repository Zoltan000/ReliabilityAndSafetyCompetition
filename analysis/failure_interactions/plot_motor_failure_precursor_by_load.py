"""Does motor temperature/current actually rise before a Motor_Reducer failure, and
does that hold up WITHIN each load class -- not just because failures cluster on
already-hot, already-high-current (i.e. Heavy) conveyor-days?

motor_signal_correlation.png (SS5 in failure_interactions_findings.md) showed
pre-failure points skewed toward the upper-right of the temp/current band, and
Heavy's raw distribution has a longer hot-side tail than Light/Medium's -- this checks
directly whether that tail is driven by proximity to failure, load class, or both, by
splitting baseline vs. pre-failure histograms out per load class instead of mixing
both groupings into one figure.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with scipy \
    python analysis/failure_interactions/plot_motor_failure_precursor_by_load.py
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
SIGNALS = {"Motor_Temperature_C": "Motor temperature (°C)", "Motor_Current_A": "Motor current (A)"}
LOADS = ["Light", "Medium", "Heavy"]
PRECURSOR_WINDOW = 30
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def main():
    con = duckdb.connect()
    df = con.sql(f"""
        WITH f AS (
            SELECT Conveyor_ID, Date, Daily_State, Failure_Type, Load_Class,
                   Motor_Temperature_C, Motor_Current_A,
                   ROW_NUMBER() OVER (PARTITION BY Conveyor_ID ORDER BY Date) AS rn
            FROM read_parquet('{FLEET}')
        ),
        fails AS (
            SELECT Conveyor_ID, rn AS fail_rn FROM f
            WHERE Daily_State = 'FAILURE_DAY' AND Failure_Type = 'Motor_Reducer'
        )
        SELECT f.Conveyor_ID, f.Load_Class, f.Motor_Temperature_C, f.Motor_Current_A,
               MAX(CASE WHEN fl.fail_rn - f.rn BETWEEN 1 AND {PRECURSOR_WINDOW} THEN 1 ELSE 0 END) AS pre_failure
        FROM f
        LEFT JOIN fails fl ON fl.Conveyor_ID = f.Conveyor_ID AND fl.fail_rn - f.rn BETWEEN 1 AND {PRECURSOR_WINDOW}
        WHERE f.Motor_Current_A IS NOT NULL
        GROUP BY f.Conveyor_ID, f.Load_Class, f.Motor_Temperature_C, f.Motor_Current_A, f.rn
    """).df()

    rows = []
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for i, (col, label) in enumerate(SIGNALS.items()):
        for j, load in enumerate(LOADS):
            ax = axes[i, j]
            g = df[df.Load_Class == load]
            base = g.loc[g.pre_failure == 0, col].dropna()
            pre = g.loc[g.pre_failure == 1, col].dropna()
            ax.hist(base, bins=60, density=True, color=BLUE, alpha=0.55, label=f"baseline (n={len(base):,})")
            ax.hist(pre, bins=60, density=True, color=RED, alpha=0.55,
                    label=f"≤30d pre-failure (n={len(pre):,})")
            t, p = stats.ttest_ind(pre, base, equal_var=False)
            pooled_sd = np.sqrt((base.var() + pre.var()) / 2)
            cohens_d = (pre.mean() - base.mean()) / pooled_sd
            ax.axvline(base.mean(), color=BLUE, ls="--", lw=1.3)
            ax.axvline(pre.mean(), color=RED, ls="--", lw=1.3)
            ax.set_title(f"{load}: +{pre.mean() - base.mean():.2f} ({label.split('(')[0].strip()}), "
                         f"d={cohens_d:.2f}, p={p:.1e}", fontsize=9.5)
            if i == 1:
                ax.set_xlabel(label)
            if j == 0:
                ax.set_ylabel("Density")
            ax.legend(fontsize=7.5, frameon=False)
            style(ax)
            rows.append({"signal": col, "load": load, "baseline_mean": base.mean(), "prefailure_mean": pre.mean(),
                        "diff": pre.mean() - base.mean(), "cohens_d": cohens_d, "p_value": p,
                        "n_baseline": len(base), "n_prefailure": len(pre)})

    fig.suptitle(f"Motor temperature and current, baseline vs. {PRECURSOR_WINDOW} days before a Motor-Reducer "
                 f"failure -- split by Load_Class\n(dashed lines = group means; d = Cohen's d effect size)",
                 fontsize=13, fontweight="bold", y=1.04)
    fig.tight_layout()
    fig.savefig(OUT / "motor_failure_precursor_by_load.png", dpi=170, bbox_inches="tight")
    print(f"Saved: {OUT / 'motor_failure_precursor_by_load.png'}")

    stats_df = pd.DataFrame(rows)
    stats_df.to_csv(OUT / "motor_failure_precursor_by_load.csv", index=False)
    print(stats_df.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
