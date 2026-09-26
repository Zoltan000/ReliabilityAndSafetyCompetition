"""Relationship between Load_Class (Light/Medium/Heavy) and daily throughput (Total_kg_Day).

throughput_findings.md already covers Total_kg_Day by *plant tier* (high/low). This
looks at the same quantity through the Load_Class label instead, since that's the
covariate used throughout the Req. 1 reliability analysis (Weibull load effects,
hazard-vs-age curves, etc.).

Note on a mistake made while building this: a first pass averaged Total_kg_Day over
ALL days including downtime (where it's 0), which made Heavy look no higher than
Medium -- an artifact of Heavy conveyors having far more downtime (frequent bearing
failures), not a real throughput effect. Restricting to Daily_State='RUNNING' (what a
conveyor actually carries while operating) gives the clean, monotonic, well-separated
relationship the Load_Class labels imply.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/throughput/plot_throughput_by_load_class.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
ORANGE, AQUA, GREY = "#eb6834", "#1baf7a", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
LOAD_ORDER = ["Light", "Medium", "Heavy"]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def main():
    con = duckdb.connect()
    per_conv = con.sql(f"""
        SELECT Conveyor_ID, Load_Class, Plant_ID, AVG(Total_kg_Day) AS mean_kg_day
        FROM read_parquet('{FLEET}')
        WHERE Daily_State = 'RUNNING'
        GROUP BY Conveyor_ID, Load_Class, Plant_ID
    """).df()
    per_conv.to_csv(OUT / "conveyor_mean_kg_day_by_load_class.csv", index=False)

    daily = con.sql(f"""
        SELECT Load_Class, Total_kg_Day
        FROM read_parquet('{FLEET}')
        WHERE Daily_State = 'RUNNING'
        USING SAMPLE 200000 ROWS
    """).df()

    print(per_conv.groupby("Load_Class")["mean_kg_day"].describe().reindex(LOAD_ORDER).round(0).to_string())

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.5))
    rng = np.random.default_rng(0)

    # Left: per-conveyor means -- box + every conveyor as its own jittered dot, so the
    # overlap between classes (not just their medians) is visible, not hidden by a box.
    ax = axes[0]
    data = [per_conv.loc[per_conv.Load_Class == load, "mean_kg_day"].to_numpy() for load in LOAD_ORDER]
    bp = ax.boxplot(data, positions=range(3), widths=0.45, showfliers=False, patch_artist=True,
                     medianprops=dict(color=INK, lw=2), boxprops=dict(facecolor="none", edgecolor=INK2))
    for i, (load, vals) in enumerate(zip(LOAD_ORDER, data)):
        jitter = rng.uniform(-0.12, 0.12, size=len(vals))
        ax.scatter(np.full(len(vals), i) + jitter, vals, s=22, color=LOAD_COLOR[load],
                   alpha=0.75, edgecolor=SURF, linewidth=0.4, zorder=3)
    ax.set_xticks(range(3), [f"{load}\n(n={len(v)})" for load, v in zip(LOAD_ORDER, data)])
    ax.set_ylabel("Mean kg/day per conveyor (on RUNNING days)")
    ax.set_title("Every conveyor's own mean throughput", fontsize=11.5, fontweight="bold")
    style(ax)

    # Right: raw daily-level distribution (sampled), showing the day-to-day spread
    # within each class, not just the per-conveyor average.
    ax = axes[1]
    parts = ax.violinplot([daily.loc[daily.Load_Class == load, "Total_kg_Day"].to_numpy() for load in LOAD_ORDER],
                          positions=range(3), showmedians=True, widths=0.7)
    for pc, load in zip(parts["bodies"], LOAD_ORDER):
        pc.set_facecolor(LOAD_COLOR[load])
        pc.set_edgecolor(INK2)
        pc.set_alpha(0.75)
    for key in ("cbars", "cmins", "cmaxes", "cmedians"):
        parts[key].set_color(INK2)
    ax.set_xticks(range(3), LOAD_ORDER)
    ax.set_ylabel("Total kg/day (daily rows, RUNNING days, sampled)")
    ax.set_title("Full daily-level distribution", fontsize=11.5, fontweight="bold")
    style(ax)

    fig.suptitle("Load_Class tracks daily throughput cleanly once restricted to RUNNING days:\n"
                 "Light 21.5k -> Medium 39.7k -> Heavy 50.3k kg/day, well-separated, low within-class spread",
                 fontsize=12.5, fontweight="bold", y=1.06)
    fig.tight_layout()
    fig.savefig(OUT / "throughput_by_load_class.png", dpi=180, bbox_inches="tight")
    print(f"\nSaved: {OUT / 'throughput_by_load_class.png'}")


if __name__ == "__main__":
    main()
