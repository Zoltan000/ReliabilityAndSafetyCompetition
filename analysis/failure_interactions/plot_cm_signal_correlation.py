"""Correlation matrix across condition-monitoring, exposure, and environment signals.

Raw signals (Motor_Current_A, Motor_Temperature_C, Structure_Vibration_RMS_mm_s,
Contact_Voltage_Drop_mV, Contactor_Closing_Time_ms) mix load/ambient effects with
equipment condition (per the spec's own caveat on these columns). Alongside them we
compute the same load/ambient-normalized ratios already used as CM precursors in
scripts/02_reliability_analysis.py SS E, to show how much of the raw correlation is
just shared exposure vs. a signal-to-signal relationship.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_cm_signal_correlation.py
"""
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent

RAW_COLS = ["Motor_Current_A", "Motor_Temperature_C", "Structure_Vibration_RMS_mm_s",
            "Contact_Voltage_Drop_mV", "Contactor_Closing_Time_ms", "Operating_Hours_Day",
            "Throughput_kg_per_h", "Temperature_Max_C", "Humidity_pct", "Voltage_V"]
LABELS = {"Motor_Current_A": "Motor current (A)", "Motor_Temperature_C": "Motor temp (C)",
          "Structure_Vibration_RMS_mm_s": "Vibration RMS", "Contact_Voltage_Drop_mV": "Contact V-drop",
          "Contactor_Closing_Time_ms": "Closing time", "Operating_Hours_Day": "Op hours/day",
          "Throughput_kg_per_h": "Throughput", "Temperature_Max_C": "Ambient temp max",
          "Humidity_pct": "Humidity", "Voltage_V": "Supply voltage",
          "Current_per_Throughput": "Current / throughput", "VDrop_per_Current": "V-drop / current",
          "MotorTemp_Excess": "Motor temp - ambient"}


def plot_heatmap(corr, title, path):
    cols = list(corr.columns)
    n = len(cols)
    fig, ax = plt.subplots(figsize=(0.62 * n + 3, 0.62 * n + 2))
    im = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels([LABELS.get(c, c) for c in cols], rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels([LABELS.get(c, c) for c in cols], fontsize=8)
    for i in range(n):
        for j in range(n):
            v = corr.iat[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                    color="white" if abs(v) > 0.6 else "#222222")
    ax.set_title(title, fontsize=12, fontweight="bold")
    cb = fig.colorbar(im, ax=ax, shrink=0.8)
    cb.set_label("Pearson r")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved: {path}")


def main():
    con = duckdb.connect()
    cols_sql = ", ".join(RAW_COLS)
    print("Fetching at-risk-day CM/exposure/environment signals...")
    df = con.sql(f"""
        SELECT {cols_sql}
        FROM read_parquet('{FLEET}')
        WHERE Daily_State IN ('RUNNING', 'FAILURE_DAY')
    """).df()
    print(f"  {len(df):,} rows")

    df["Current_per_Throughput"] = df["Motor_Current_A"] / df["Throughput_kg_per_h"]
    df["VDrop_per_Current"] = df["Contact_Voltage_Drop_mV"] / df["Motor_Current_A"]
    df["MotorTemp_Excess"] = df["Motor_Temperature_C"] - df["Temperature_Max_C"]

    raw_corr = df[RAW_COLS].corr()
    derived_cols = RAW_COLS + ["Current_per_Throughput", "VDrop_per_Current", "MotorTemp_Excess"]
    full_corr = df[derived_cols].corr()

    raw_corr.to_csv(OUT / "cm_signal_correlation_raw.csv")
    full_corr.to_csv(OUT / "cm_signal_correlation.csv")
    print("\nRaw-signal correlation matrix:")
    print(raw_corr.round(3).to_string())
    print("\nWith normalized ratios added:")
    print(full_corr.round(3).to_string())

    plot_heatmap(raw_corr, "CM / exposure / environment signal correlation (raw)",
                 OUT / "cm_signal_correlation_raw_heatmap.png")
    plot_heatmap(full_corr, "CM signal correlation, incl. load/ambient-normalized ratios",
                 OUT / "cm_signal_correlation_heatmap.png")


if __name__ == "__main__":
    main()
