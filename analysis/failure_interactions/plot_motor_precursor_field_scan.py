"""Deeper dive on the Motor-Reducer precursor signal: which fields move before a
failure (a full scan across every relevant daily-varying column, not just motor
current/temperature), and what shape does the ramp-up actually take (a day-by-day
trajectory, not just a single before/after mean comparison)?

Extends outputs/req1/cm_precursors.csv's methodology (within-conveyor z-score,
-30..-1 days before failure vs. -120..-61 baseline) from 5 derived signals to every
daily-varying numeric column in the dataset, plus adds an event-aligned trajectory
(mean z-score at each single day offset from -60 to +10) for the top movers -- this
doesn't have the shrinking-risk-set problem hazard curves do, since every failure
used has a full -60..+10 window by construction (day_idx >= 120 filter), so every
offset is averaged over the same set of failures.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_motor_precursor_field_scan.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
BLUE, ORANGE, GREY, RED = "#2a78d6", "#eb6834", "#8a8a86", "#c0392b"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

RAW_FIELDS = ["Temperature_Max_C", "Temperature_Min_C", "Humidity_pct", "Voltage_V",
              "Throughput_kg_per_h", "Total_kg_Day", "Estimated_Roller_Revolutions_Day",
              "Start_Stop_Cycles_Day", "Motor_Current_A", "Motor_Temperature_C",
              "Structure_Vibration_RMS_mm_s", "Contact_Voltage_Drop_mV", "Contactor_Closing_Time_ms"]
LABELS = {"Temperature_Max_C": "Ambient temp max", "Temperature_Min_C": "Ambient temp min",
          "Humidity_pct": "Humidity", "Voltage_V": "Supply voltage",
          "Throughput_kg_per_h": "Throughput", "Total_kg_Day": "Total kg/day",
          "Estimated_Roller_Revolutions_Day": "Roller revolutions/day",
          "Start_Stop_Cycles_Day": "Start/stop cycles", "Motor_Current_A": "Motor current",
          "Motor_Temperature_C": "Motor temperature", "Structure_Vibration_RMS_mm_s": "Vibration RMS",
          "Contact_Voltage_Drop_mV": "Contactor V-drop", "Contactor_Closing_Time_ms": "Contactor closing time",
          "Current_per_Throughput": "Current / throughput", "VDrop_per_Current": "V-drop / current",
          "MotorTemp_Excess": "Motor temp − ambient"}
DERIVED = ["Current_per_Throughput", "VDrop_per_Current", "MotorTemp_Excess"]
ALL_FIELDS = RAW_FIELDS + DERIVED
FAIL_TYPE = "Motor_Reducer"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def main():
    con = duckdb.connect()
    cols_sql = ", ".join(RAW_FIELDS)
    print("Fetching fleet signals...")
    f = con.sql(f"""
        SELECT Conveyor_ID, Date, Daily_State, Failure_Type, {cols_sql}
        FROM read_parquet('{FLEET}')
        ORDER BY Conveyor_ID, Date
    """).df()
    f["day_idx"] = f.groupby("Conveyor_ID").cumcount().astype(float)

    f["Current_per_Throughput"] = f["Motor_Current_A"] / f["Throughput_kg_per_h"]
    f["VDrop_per_Current"] = f["Contact_Voltage_Drop_mV"] / f["Motor_Current_A"]
    f["MotorTemp_Excess"] = f["Motor_Temperature_C"] - f["Temperature_Max_C"]

    print("Z-scoring every field within each conveyor...")
    z = pd.DataFrame({c: (f[c] - f.groupby(f.Conveyor_ID)[c].transform("mean"))
                          / f.groupby(f.Conveyor_ID)[c].transform("std") for c in ALL_FIELDS})
    z["cid"] = f["Conveyor_ID"].to_numpy()

    fail_mask = (f.Daily_State == "FAILURE_DAY") & (f.Failure_Type == FAIL_TYPE)
    idx = np.flatnonzero(fail_mask.to_numpy())
    idx = idx[f.day_idx.to_numpy()[idx] >= 120]
    print(f"{len(idx):,} {FAIL_TYPE} failures with a full baseline window")

    # --- Ranked shift (bar chart): mean z at -30..-1 minus mean z at -120..-61, per field
    pre = np.concatenate([idx - d for d in range(1, 31)])
    base = np.concatenate([idx - d for d in range(61, 121)])
    shift_rows = []
    for c in ALL_FIELDS:
        vals = z[c].to_numpy()
        shift_rows.append({"field": c, "shift_z": np.nanmean(vals[pre]) - np.nanmean(vals[base]),
                           "pre_n": np.sum(~np.isnan(vals[pre])), "base_n": np.sum(~np.isnan(vals[base]))})
    shift_df = pd.DataFrame(shift_rows).sort_values("shift_z", key=np.abs, ascending=False)
    shift_df.to_csv(OUT / "motor_precursor_field_scan.csv", index=False)
    print(shift_df.round(3).to_string(index=False))

    fig, ax = plt.subplots(figsize=(9, 7))
    order = shift_df.sort_values("shift_z")
    colors = [ORANGE if v > 0 else BLUE for v in order.shift_z]
    ax.barh([LABELS[c] for c in order.field], order.shift_z, color=colors)
    ax.axvline(0, color=INK2, lw=1)
    for y, v in enumerate(order.shift_z):
        ax.text(v + (0.02 if v >= 0 else -0.02), y, f"{v:+.2f}", va="center",
                ha="left" if v >= 0 else "right", fontsize=8)
    ax.set_xlabel("Within-conveyor z-shift, 30 days before a Motor-Reducer failure vs. baseline")
    ax.set_title(f"Every field scanned for a Motor-Reducer precursor signal (n={len(idx):,} failures)",
                 fontsize=12.5, fontweight="bold")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "motor_precursor_field_scan.png", dpi=170, bbox_inches="tight")
    print(f"\nSaved: {OUT / 'motor_precursor_field_scan.png'}")

    # --- Trajectory (line chart): mean z at each single day offset, top movers by |shift|
    top = shift_df.head(6)["field"].tolist()
    offsets = np.arange(-60, 11)
    traj_rows = []
    fig, ax = plt.subplots(figsize=(11, 6.5))
    cmap = plt.get_cmap("tab10")
    for i, c in enumerate(top):
        vals = z[c].to_numpy()
        means = []
        for d in offsets:
            pts = idx + d
            pts = pts[(pts >= 0) & (pts < len(vals))]
            means.append(np.nanmean(vals[pts]))
        traj_rows.append(pd.DataFrame({"field": c, "day_offset": offsets, "mean_z": means}))
        ax.plot(offsets, means, lw=2, color=cmap(i), label=LABELS[c])
    ax.axvline(0, color=INK, ls="--", lw=1.2)
    ax.text(0.3, ax.get_ylim()[1] * 0.95, "failure day", fontsize=8, color=INK2)
    ax.set_xlabel("Days relative to Motor-Reducer failure (0 = failure day)")
    ax.set_ylabel("Mean within-conveyor z-score")
    ax.legend(fontsize=9, frameon=False, loc="upper left")
    ax.set_title("What the top-moving signals actually do in the 60 days before a Motor-Reducer failure",
                 fontsize=12.5, fontweight="bold")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "motor_precursor_trajectory.png", dpi=170, bbox_inches="tight")
    print(f"Saved: {OUT / 'motor_precursor_trajectory.png'}")

    pd.concat(traj_rows, ignore_index=True).to_csv(OUT / "motor_precursor_trajectory.csv", index=False)
    print(f"Saved: {OUT / 'motor_precursor_trajectory.csv'}")


if __name__ == "__main__":
    main()
