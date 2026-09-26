"""Bell curves (KDE of hours-until-failure) for the non-Bearing components, grouped two
ways per component: by Load_Class, and by first-life (renewal 0) vs. replacement
(renewal >= 1). Bearing is handled separately (plot_bearing_lifetime_vs_load_3d.py,
plot_light_bearing_selection_effect.py) since it needs per-position data; Contactor is
skipped here (only 12 fleet-wide failures -- too sparse for a density estimate).

Reuses outputs/req1/intervals_<component>.parquet (already computed by
scripts/02_reliability_analysis.py) -- no fleet-file re-query needed.

Usage (repo root):
  uv run --no-project --with matplotlib --with pandas --with numpy --with scipy --with pyarrow \
    python analysis/reliability_over_time/plot_other_component_bell_curves.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
import matplotlib.pyplot as plt

IN = Path("outputs/req1")
OUT = Path(__file__).parent
BLUE, ORANGE, AQUA, GREY, PURPLE = "#2a78d6", "#eb6834", "#1baf7a", "#8a8a86", "#7b5ea8"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
NAMES = {"Conveyor_Belt": "Belt", "Motor_Reducer": "Motor-reducer", "Speed_Sensor": "Speed sensor",
         "Controller_PC": "Controller PC", "Control_Software": "Control software"}
COMPONENTS = list(NAMES)
SPEED_SENSOR_CEILING = 50016
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def kde_curve(vals, x_hi):
    # Reflection boundary correction: a plain KDE is biased near a hard boundary at 0
    # (it smooths mass to negative values that then just vanishes, which for a
    # near-random/infant-mortality component -- highest true density AT zero -- fakes a
    # peak away from zero that isn't in the data; verified against the raw histogram for
    # Controller_PC before adding this). Mirroring the data across 0 and doubling the
    # resulting density on the positive side is the standard fix.
    xs = np.linspace(0, x_hi, 300)
    if len(vals) < 15:
        return xs, np.zeros_like(xs)
    reflected = np.concatenate([vals, -vals])
    return xs, 2 * gaussian_kde(reflected)(xs)


def main():
    for comp in COMPONENTS:
        iv = pd.read_parquet(IN / f"intervals_{comp}.parquet")
        ev = iv[iv.event == 1]
        x_hi = ev.op_h.quantile(0.98)

        fig, axes = plt.subplots(1, 2, figsize=(13, 5))

        ax = axes[0]
        for load in ["Light", "Medium", "Heavy"]:
            g = ev[ev.load == load]
            xs, ys = kde_curve(g.op_h.to_numpy(), x_hi)
            ax.plot(xs, ys, color=LOAD_COLOR[load], lw=2.2, label=f"{load} (n={len(g):,})")
        ax.set_title("By Load_Class", fontsize=11)
        ax.set_xlabel("Hours until failure")
        ax.set_ylabel("Density")
        ax.legend(fontsize=8.5, frameon=False)
        style(ax)

        ax = axes[1]
        first = ev[ev.renewal == 0]
        later = ev[ev.renewal >= 1]
        xs, ys = kde_curve(first.op_h.to_numpy(), x_hi)
        ax.plot(xs, ys, color=BLUE, lw=2.2, label=f"first life (n={len(first):,})")
        xs, ys = kde_curve(later.op_h.to_numpy(), x_hi)
        ax.plot(xs, ys, color=PURPLE, lw=2.2, label=f"replacement, any renewal ≥1 (n={len(later):,})")
        ax.set_title("By first life vs. replacement", fontsize=11)
        ax.set_xlabel("Hours until failure")
        ax.set_ylabel("Density")
        ax.legend(fontsize=8.5, frameon=False)
        style(ax)

        if comp == "Speed_Sensor":
            for ax in axes:
                if SPEED_SENSOR_CEILING <= x_hi:
                    ax.axvline(SPEED_SENSOR_CEILING, color=INK, ls="--", lw=1.2)
                    ax.text(SPEED_SENSOR_CEILING - x_hi * 0.02, ax.get_ylim()[1] * 0.9,
                            "hard ceiling\n~50,016 op-h", ha="right", fontsize=7.5, color=INK)

        fig.suptitle(f"{NAMES[comp]}: distribution of hours until failure  (n={len(ev):,} failures)",
                     fontsize=13, fontweight="bold", y=1.02)
        fig.tight_layout()
        fname = f"bell_curve_{comp.lower()}.png"
        fig.savefig(OUT / fname, dpi=170, bbox_inches="tight")
        print(f"Saved: {OUT / fname}")
        plt.close(fig)


if __name__ == "__main__":
    main()
