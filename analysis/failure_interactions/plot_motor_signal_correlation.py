"""Correlation between motor-related signals: Voltage_V (supply), Motor_Temperature_C,
and Motor_Current_A -- a focused scatter-matrix (pairplot) instead of digging these 3
out of the full 10x10 cm_signal_correlation_heatmap.png.

Colored by Load_Class throughout: Motor_Current_A and Motor_Temperature_C are both
already known to be load-driven (cm_signal_correlation_heatmap.png: current correlates
~0.98 with throughput), while Voltage_V is a plant-level constant with no real load
dependence -- so a naive pooled correlation involving current or temperature risks the
same load confound already found and corrected elsewhere in this analysis. Also marks
each point as inside/outside the 30-day window before a Motor_Reducer failure (the
window CM precursors z-shift analysis, outputs/req1/cm_precursors.csv, already flags
current and temperature as real precursors: cur_per_tp +0.311, mtemp_excess +0.382).

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_motor_signal_correlation.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
ORANGE, AQUA, GREY, RED = "#eb6834", "#1baf7a", "#8a8a86", "#c0392b"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
COLS = ["Voltage_V", "Motor_Temperature_C", "Motor_Current_A"]
LABELS = {"Voltage_V": "Supply voltage (V)", "Motor_Temperature_C": "Motor temp (°C)",
          "Motor_Current_A": "Motor current (A)"}
PRECURSOR_WINDOW = 30
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def main():
    con = duckdb.connect()
    print("Fetching at-risk-day signals + Motor_Reducer failure markers...")
    df = con.sql(f"""
        WITH f AS (
            SELECT Conveyor_ID, Date, Daily_State, Failure_Type, Load_Class,
                   Voltage_V, Motor_Temperature_C, Motor_Current_A,
                   ROW_NUMBER() OVER (PARTITION BY Conveyor_ID ORDER BY Date) AS rn
            FROM read_parquet('{FLEET}')
        ),
        fails AS (
            SELECT Conveyor_ID, rn AS fail_rn FROM f
            WHERE Daily_State = 'FAILURE_DAY' AND Failure_Type = 'Motor_Reducer'
        )
        SELECT f.Conveyor_ID, f.Load_Class, f.Voltage_V, f.Motor_Temperature_C, f.Motor_Current_A,
               MAX(CASE WHEN fl.fail_rn - f.rn BETWEEN 1 AND {PRECURSOR_WINDOW} THEN 1 ELSE 0 END) AS pre_failure
        FROM f
        LEFT JOIN fails fl ON fl.Conveyor_ID = f.Conveyor_ID AND fl.fail_rn - f.rn BETWEEN 1 AND {PRECURSOR_WINDOW}
        WHERE f.Motor_Current_A IS NOT NULL
        GROUP BY f.Conveyor_ID, f.Load_Class, f.Voltage_V, f.Motor_Temperature_C, f.Motor_Current_A, f.rn
    """).df()
    print(f"  {len(df):,} at-risk rows, {df.pre_failure.sum():,} in the {PRECURSOR_WINDOW}-day pre-failure window")

    corr_overall = df[COLS].corr()
    corr_overall.to_csv(OUT / "motor_signal_correlation.csv")
    print("\nOverall Pearson correlation:")
    print(corr_overall.round(3).to_string())
    print("\nBy load class:")
    for load in ["Light", "Medium", "Heavy"]:
        print(f"{load}:")
        print(df[df.Load_Class == load][COLS].corr().round(3).to_string())

    rng = np.random.default_rng(0)
    sample = df.sample(min(60000, len(df)), random_state=0)

    n = len(COLS)
    fig, axes = plt.subplots(n, n, figsize=(11, 10))
    for i, yc in enumerate(COLS):
        for j, xc in enumerate(COLS):
            ax = axes[i, j]
            if i == j:
                for load in ["Light", "Medium", "Heavy"]:
                    vals = df.loc[df.Load_Class == load, xc]
                    ax.hist(vals, bins=40, color=LOAD_COLOR[load], alpha=0.55, density=True, histtype="stepfilled")
                ax.set_yticks([])
            elif i > j:
                base = sample[sample.pre_failure == 0]
                pre = sample[sample.pre_failure == 1]
                for load in ["Light", "Medium", "Heavy"]:
                    b = base[base.Load_Class == load]
                    ax.scatter(b[xc], b[yc], s=4, color=LOAD_COLOR[load], alpha=0.15, linewidths=0)
                ax.scatter(pre[xc], pre[yc], s=8, color=RED, alpha=0.6, linewidths=0,
                          label=f"≤30d before Motor_Reducer failure (n={len(pre):,} sampled)" if (i, j) == (n - 1, 0) else None)
            else:
                r = corr_overall.loc[yc, xc]
                ax.text(0.5, 0.5, f"r = {r:+.3f}", ha="center", va="center", fontsize=15,
                        fontweight="bold", color=INK, transform=ax.transAxes)
                ax.set_xticks([])
                ax.set_yticks([])
            if i == n - 1:
                ax.set_xlabel(LABELS[xc], fontsize=9)
            if j == 0:
                ax.set_ylabel(LABELS[yc], fontsize=9)
            style(ax)

    handles = [plt.Line2D([], [], marker="o", ls="", color=LOAD_COLOR[l], label=l) for l in ["Light", "Medium", "Heavy"]]
    handles.append(plt.Line2D([], [], marker="o", ls="", color=RED,
                              label=f"≤30d before a Motor_Reducer failure"))
    fig.legend(handles=handles, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.04), fontsize=9.5)
    fig.suptitle("Motor signals: voltage, temperature, current -- correlation matrix, colored by Load_Class",
                 fontsize=13, fontweight="bold", y=1.09)
    fig.tight_layout()
    fig.savefig(OUT / "motor_signal_correlation.png", dpi=170, bbox_inches="tight")
    print(f"\nSaved: {OUT / 'motor_signal_correlation.png'}")


if __name__ == "__main__":
    main()
