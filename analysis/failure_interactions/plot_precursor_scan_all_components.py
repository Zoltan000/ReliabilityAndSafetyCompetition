"""Generalizes plot_motor_precursor_field_scan.py from Motor_Reducer to all 7 failure
types: which of 16 daily-varying fields moves before a failure, and what shape does
the ramp-up/repair-recovery actually take, per component.

Same methodology throughout (within-conveyor z-score per field; -30..-1 days
pre-failure vs. -61..-120 baseline for the ranked shift; day-by-day trajectory
-60..+10 for the top movers; day_idx >= 120 so every failure used has a full window).

Efficiency: the fleet fetch and the 16-field z-score matrix are the expensive parts
and are computed ONCE, not once per component -- only "which day_idx values are this
component's failures" differs per component, which is a cheap numpy index lookup into
the already-computed z matrix. Components with too few qualifying failures (day_idx >=
120) get flagged "insufficient data" instead of a fabricated/noisy result. Per-component
detail goes to CSV; stdout prints only a condensed top-3-movers leaderboard.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_precursor_scan_all_components.py
"""
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from conveyor.io import COMPONENTS  # noqa: E402

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

RAW_FIELDS = ["Temperature_Max_C", "Temperature_Min_C", "Humidity_pct", "Voltage_V",
              "Throughput_kg_per_h", "Total_kg_Day", "Estimated_Roller_Revolutions_Day",
              "Start_Stop_Cycles_Day", "Motor_Current_A", "Motor_Temperature_C",
              "Structure_Vibration_RMS_mm_s", "Contact_Voltage_Drop_mV", "Contactor_Closing_Time_ms"]
DERIVED = ["Current_per_Throughput", "VDrop_per_Current", "MotorTemp_Excess"]
ALL_FIELDS = RAW_FIELDS + DERIVED
LABELS = {"Temperature_Max_C": "Ambient temp max", "Temperature_Min_C": "Ambient temp min",
          "Humidity_pct": "Humidity", "Voltage_V": "Supply voltage",
          "Throughput_kg_per_h": "Throughput", "Total_kg_Day": "Total kg/day",
          "Estimated_Roller_Revolutions_Day": "Roller revolutions/day",
          "Start_Stop_Cycles_Day": "Start/stop cycles", "Motor_Current_A": "Motor current",
          "Motor_Temperature_C": "Motor temperature", "Structure_Vibration_RMS_mm_s": "Vibration RMS",
          "Contact_Voltage_Drop_mV": "Contactor V-drop", "Contactor_Closing_Time_ms": "Contactor closing time",
          "Current_per_Throughput": "Current / throughput", "VDrop_per_Current": "V-drop / current",
          "MotorTemp_Excess": "Motor temp − ambient"}
MIN_EVENTS = 20  # minimum qualifying failures (day_idx >= 120) to trust a component's result
BASELINE_MIN, BASELINE_MAX = 61, 120
PRE_MIN, PRE_MAX = 1, 30
TRAJ_RANGE = range(-60, 11)
TOP_N_TRAJECTORY = 6
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def fetch_and_zscore():
    """The expensive, shared step: one fleet fetch, one 16-field z-score matrix."""
    con = duckdb.connect()
    cols_sql = ", ".join(RAW_FIELDS)
    print("Fetching fleet signals (once, shared across all 7 components)...")
    f = con.sql(f"""
        SELECT Conveyor_ID, Date, Daily_State, Failure_Type, {cols_sql}
        FROM read_parquet('{FLEET}')
        ORDER BY Conveyor_ID, Date
    """).df()
    f["day_idx"] = f.groupby("Conveyor_ID").cumcount().astype(float)
    f["Current_per_Throughput"] = f["Motor_Current_A"] / f["Throughput_kg_per_h"]
    f["VDrop_per_Current"] = f["Contact_Voltage_Drop_mV"] / f["Motor_Current_A"]
    f["MotorTemp_Excess"] = f["Motor_Temperature_C"] - f["Temperature_Max_C"]

    print("Z-scoring all 16 fields within each conveyor (once)...")
    z = pd.DataFrame({c: (f[c] - f.groupby(f.Conveyor_ID)[c].transform("mean"))
                          / f.groupby(f.Conveyor_ID)[c].transform("std") for c in ALL_FIELDS})
    return f, z


def component_indices(f, comp):
    fail_mask = (f.Daily_State == "FAILURE_DAY") & (f.Failure_Type == comp)
    idx = np.flatnonzero(fail_mask.to_numpy())
    return idx[f.day_idx.to_numpy()[idx] >= 120]


def ranked_shift(z, idx):
    pre = np.concatenate([idx - d for d in range(PRE_MIN, PRE_MAX + 1)])
    base = np.concatenate([idx - d for d in range(BASELINE_MIN, BASELINE_MAX + 1)])
    rows = []
    for c in ALL_FIELDS:
        vals = z[c].to_numpy()
        rows.append({"field": c, "shift_z": np.nanmean(vals[pre]) - np.nanmean(vals[base])})
    return pd.DataFrame(rows).sort_values("shift_z", key=np.abs, ascending=False)


def trajectory(z, idx, fields, n_total):
    offsets = np.array(list(TRAJ_RANGE))
    rows = []
    for c in fields:
        vals = z[c].to_numpy()
        means = [np.nanmean(vals[(pts := idx + d)[(pts >= 0) & (pts < n_total)]]) for d in offsets]
        rows.append(pd.DataFrame({"field": c, "day_offset": offsets, "mean_z": means}))
    return pd.concat(rows, ignore_index=True)


def plot_trajectory(traj_df, comp, n_events, path):
    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = plt.get_cmap("tab10")
    for i, c in enumerate(traj_df.field.unique()):
        d = traj_df[traj_df.field == c]
        ax.plot(d.day_offset, d.mean_z, lw=2, color=cmap(i), label=LABELS[c])
    ax.axvline(0, color=INK, ls="--", lw=1.2)
    ax.set_xlabel("Days relative to failure (0 = failure day)")
    ax.set_ylabel("Mean within-conveyor z-score")
    ax.legend(fontsize=8.5, frameon=False, loc="best")
    ax.set_title(f"{comp}: top-moving signals, 60 days before to 10 days after (n={n_events:,} failures)",
                 fontsize=11.5, fontweight="bold")
    style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def plot_heatmap(shift_wide, path):
    fig, ax = plt.subplots(figsize=(13, 5.5))
    vmax = np.nanmax(np.abs(shift_wide.to_numpy()))
    im = ax.imshow(shift_wide.to_numpy(), cmap="RdBu_r", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(shift_wide.columns)))
    ax.set_xticklabels([LABELS[c] for c in shift_wide.columns], rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(shift_wide.index)))
    ax.set_yticklabels(shift_wide.index, fontsize=9)
    for i in range(shift_wide.shape[0]):
        for j in range(shift_wide.shape[1]):
            v = shift_wide.iat[i, j]
            if np.isnan(v):
                continue
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=7,
                    color="white" if abs(v) > vmax * 0.6 else "#222222")
    ax.set_title("Precursor z-shift (30 days before failure vs. baseline), every component × every field",
                 fontsize=12.5, fontweight="bold")
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("z-shift")
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def main():
    f, z = fetch_and_zscore()
    n_total = len(f)

    shift_rows, traj_rows, leaderboard = [], [], []
    for comp in COMPONENTS:
        idx = component_indices(f, comp)
        if len(idx) < MIN_EVENTS:
            print(f"{comp:18s}  insufficient data (n={len(idx)} < {MIN_EVENTS}) -- skipped")
            continue
        shift = ranked_shift(z, idx)
        shift["component"] = comp
        shift["n_events"] = len(idx)
        shift_rows.append(shift)

        top = shift.head(3)
        leaderboard.append(f"{comp:18s} n={len(idx):6,}  " +
                           ", ".join(f"{LABELS[r.field]} {r.shift_z:+.2f}" for r in top.itertuples()))

        top_fields = shift.head(TOP_N_TRAJECTORY).field.tolist()
        traj = trajectory(z, idx, top_fields, n_total)
        traj["component"] = comp
        traj_rows.append(traj)
        plot_trajectory(traj, comp, len(idx), OUT / f"precursor_trajectory_{comp.lower()}.png")

    print("\nTop-3 precursor movers per component:")
    print("\n".join(leaderboard))

    shift_all = pd.concat(shift_rows, ignore_index=True)
    shift_all.to_csv(OUT / "precursor_shift_all_components.csv", index=False)
    traj_all = pd.concat(traj_rows, ignore_index=True)
    traj_all.to_csv(OUT / "precursor_trajectory_all_components.csv", index=False)

    shift_wide = shift_all.pivot(index="component", columns="field", values="shift_z").reindex(
        index=[c for c in COMPONENTS if c in shift_all.component.unique()], columns=ALL_FIELDS)
    plot_heatmap(shift_wide, OUT / "precursor_shift_heatmap.png")
    print(f"\nSaved: {OUT / 'precursor_shift_heatmap.png'}")
    print(f"Saved: {OUT / 'precursor_shift_all_components.csv'}")
    print(f"Saved: {OUT / 'precursor_trajectory_all_components.csv'}")
    print(f"Saved per-component trajectory PNGs for: {', '.join(shift_all.component.unique())}")


if __name__ == "__main__":
    main()
