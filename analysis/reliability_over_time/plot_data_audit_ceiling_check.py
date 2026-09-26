"""Data audit: is the Speed_Sensor hard ceiling (found via hazard_vs_age.png /
speed_sensor_scatter.png) the only hidden ceiling-type artifact among the 7 failure
components? For each, checks what fraction of intervals sit within 0.1% of that
component's max recorded operating-hours duration, and whether those near-max
intervals are actual failures (a real ceiling) or just censored/still-running units
(normal -- some conveyor always has the longest history).

Reuses outputs/req1/intervals_<component>.parquet -- no fleet-file re-query needed.

Usage (repo root):
  uv run --no-project --with matplotlib --with pandas --with numpy --with pyarrow \
    python analysis/reliability_over_time/plot_data_audit_ceiling_check.py
"""
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

IN = Path("outputs/req1")
OUT = Path(__file__).parent
COMPONENTS = ["Bearing", "Conveyor_Belt", "Motor_Reducer", "Speed_Sensor",
              "Controller_PC", "Control_Software", "Contactor"]
ORANGE, GREY = "#eb6834", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def main():
    rows = []
    for comp in COMPONENTS:
        iv = pd.read_parquet(IN / f"intervals_{comp}.parquet")
        mx = iv.op_h.max()
        near = iv[iv.op_h >= mx * 0.999]
        rows.append({"component": comp, "n_intervals": len(iv), "max_op_h": mx,
                     "n_near_max": len(near), "n_near_max_failures": int((near.event == 1).sum()),
                     "n_near_max_censored": int((near.event == 0).sum()),
                     "pct_failures_near_max": round(100 * (near.event == 1).sum() / max((iv.event == 1).sum(), 1), 2)})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "data_audit_ceiling_check.csv", index=False)
    print(df.to_string(index=False))

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = [ORANGE if c == "Speed_Sensor" else GREY for c in df.component]
    ax.bar(df.component, df.pct_failures_near_max, color=colors)
    for i, v in enumerate(df.pct_failures_near_max):
        ax.text(i, v + 0.15, f"{v:.1f}%", ha="center", fontsize=9)
    ax.set_ylabel("% of that component's failures landing within 0.1% of its own max lifetime")
    ax.set_title("Only Speed_Sensor shows a real ceiling -- every other component's\n"
                  "\"near-max\" cases are just normal censoring, not failures piling up",
                  fontsize=12, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, axis="x", rotation=30)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(OUT / "data_audit_ceiling_check.png", dpi=170, bbox_inches="tight")
    print(f"\nSaved: {OUT / 'data_audit_ceiling_check.png'}")


if __name__ == "__main__":
    main()
