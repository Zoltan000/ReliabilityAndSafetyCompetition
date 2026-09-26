"""Failure rate vs. component age (operating hours since restart) -- the concrete,
visual counterpart to outputs/figures/beta.png's abstract Weibull shape (beta) plot.

Reuses outputs/req1/intervals_<component>.parquet (one row per renewal interval:
cid, load, renewal, event, days, op_h, cycles, kg -- see scripts/02_reliability_analysis.py
`intervals()`). Fits a Nelson-Aalen smoothed hazard on op_h per component, split by
Load_Class for the 3 load-driven wear-out components (Bearing, Conveyor_Belt,
Motor_Reducer -- same set outputs/figures/07_figures.py's load_plot() covers), pooled
for the rest. Contactor is excluded (n=12 events, too sparse for a curve -- same
exclusion load_plot() already makes).

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with lifelines \
    python analysis/reliability_over_time/plot_hazard_vs_age.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import NelsonAalenFitter
import matplotlib.pyplot as plt

IN = Path("outputs/req1")
OUT = Path(__file__).parent
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
NAMES = {"Bearing": "Bearings", "Conveyor_Belt": "Belt", "Motor_Reducer": "Motor-reducer",
         "Speed_Sensor": "Speed sensor", "Controller_PC": "Controller PC",
         "Control_Software": "Control software"}
LOAD_SPLIT = {"Bearing", "Conveyor_Belt", "Motor_Reducer"}
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def smoothed_curve(df, cap):
    # Kernel-smoothed hazard estimates are boundary-biased near the edge of the observed
    # timeline; compute over a wider range and only return the inner (visible) part so the
    # artifact falls outside the plotted window.
    naf = NelsonAalenFitter()
    naf.fit(df["op_h"].clip(lower=0.01), event_observed=df["event"])
    bw = max(cap * 0.1, 200.0)
    extended = np.linspace(0, cap * 1.25, 250)
    haz = naf.smoothed_hazard_(bandwidth=bw)
    y_ext = np.interp(extended, haz.index.to_numpy(), haz.iloc[:, 0].to_numpy())
    timeline = np.linspace(0, cap, 200)
    return np.interp(timeline, extended, y_ext), timeline


def main():
    fig, axes = plt.subplots(2, 4, figsize=(17, 7.5))
    axes = axes.flatten()
    rows_out = []

    for ax, comp in zip(axes, NAMES):
        iv = pd.read_parquet(IN / f"intervals_{comp}.parquet")
        if comp in LOAD_SPLIT:
            # Each load class gets its OWN cap from its OWN data. A shared/pooled cap
            # (e.g. Light's 97th percentile, ~45k op-h for Bearing) would force Heavy
            # and Medium curves to extrapolate far past their real range -- Heavy
            # bearings never exceed 8,028 op-h fleet-wide, Medium never exceed 18,300 --
            # producing a flat tail that reflects "no data left," not a real hazard
            # plateau. Caught when asked what the flat Heavy/Medium tail meant.
            for load in ["Light", "Medium", "Heavy"]:
                d = iv[iv.load == load]
                if d.event.sum() < 20:
                    continue
                cap = float(d["op_h"].quantile(0.97))
                y, x = smoothed_curve(d, cap)
                ax.plot(x / 1000, y * 1000, color=LOAD_COLOR[load], lw=2.2, label=load)
                rows_out.append(pd.DataFrame({"component": comp, "load": load, "op_h": x, "hazard_per_op_h": y}))
        else:
            cap = float(iv["op_h"].quantile(0.97))
            y, x = smoothed_curve(iv, cap)
            ax.plot(x / 1000, y * 1000, color=BLUE, lw=2.2, label="all loads")
            rows_out.append(pd.DataFrame({"component": comp, "load": "all", "op_h": x, "hazard_per_op_h": y}))
        ax.set_title(f"{NAMES[comp]}  (n={int(iv.event.sum()):,} failures)", fontsize=11, fontweight="bold")
        ax.set_xlabel("Operating hours since restart (thousands)")
        ax.set_ylabel("Hazard / 1,000 op-h")
        ax.legend(fontsize=8, frameon=False)
        style(ax)

        if comp == "Speed_Sensor":
            # Real, data-backed hard ceiling (not a smoothing artifact): 158 of 2,122
            # intervals land within 0.1% of the max op_h (50,016h = 2,084 days continuous),
            # across all load classes and renewal indices -- see findings.md.
            ax.axvline(50.016, color=INK2, ls="--", lw=1)
            ax.text(49.6, ax.get_ylim()[1] * 0.55, "hard ceiling\n~50,016 op-h\n(2,084 days)",
                    ha="right", fontsize=8, color=INK2)

    axes[-1].axis("off")
    fig.suptitle("Failure rate vs. component age: rising = wear-out, flat = random, falling = infant mortality",
                 fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(OUT / "hazard_vs_age.png", dpi=180, bbox_inches="tight")
    print(f"Saved: {OUT / 'hazard_vs_age.png'}")

    pd.concat(rows_out, ignore_index=True).to_csv(OUT / "hazard_vs_age.csv", index=False)
    print(f"Saved: {OUT / 'hazard_vs_age.csv'}")


if __name__ == "__main__":
    main()
