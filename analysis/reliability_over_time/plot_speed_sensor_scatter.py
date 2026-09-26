"""Raw scatter of every Speed_Sensor renewal interval: operating hours vs. renewal index.

The smoothed hazard curve in hazard_vs_age.png flagged a spike right around 50,016
operating hours. This plots the underlying raw events (no smoothing) to show that
pileup directly: each dot is one interval from outputs/req1/intervals_Speed_Sensor.parquet
(cid, load, renewal, event, op_h -- already computed, no recomputation here).

Usage (repo root):
  uv run --no-project --with matplotlib --with pandas --with numpy --with pyarrow \
    python analysis/reliability_over_time/plot_speed_sensor_scatter.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

IN = Path("outputs/req1")
OUT = Path(__file__).parent
ORANGE, AQUA, GREY = "#eb6834", "#1baf7a", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
CEILING = 50016
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
    d = pd.read_parquet(IN / "intervals_Speed_Sensor.parquet")
    rng = np.random.default_rng(0)
    jitter = rng.uniform(-0.32, 0.32, size=len(d))

    fig, ax = plt.subplots(figsize=(11, 6.5))
    failed = d[d.event == 1]
    censored = d[d.event == 0]

    ax.scatter(censored.op_h / 1000, censored.renewal + jitter[censored.index], s=26,
               facecolor="none", edgecolor=INK2, linewidth=0.8, alpha=0.55,
               label=f"still alive at end of history (n={len(censored)})", zorder=2)
    for load in ["Light", "Medium", "Heavy"]:
        g = failed[failed.load == load]
        ax.scatter(g.op_h / 1000, g.renewal + jitter[g.index], s=30, color=LOAD_COLOR[load],
                   alpha=0.75, edgecolor=SURF, linewidth=0.4, label=f"failed -- {load} (n={len(g)})", zorder=3)

    ax.axvline(CEILING / 1000, color=INK, ls="--", lw=1.2, zorder=1)
    ax.text(CEILING / 1000 - 0.5, ax.get_ylim()[1] if ax.get_ylim()[1] else 10,
            f"hard ceiling\n~{CEILING:,} op-h", ha="right", va="top", fontsize=9, color=INK)

    ax.set_xlabel("Operating hours since restart/replacement (thousands)")
    ax.set_ylabel("Renewal index (0 = original sensor; jittered for visibility)")
    ax.set_title("Every Speed_Sensor renewal interval: failures pile up at the same operating-hours ceiling,\n"
                  "at every renewal index and every load class", fontsize=12, fontweight="bold")
    ax.legend(fontsize=8.5, frameon=False, loc="upper left")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "speed_sensor_scatter.png", dpi=180, bbox_inches="tight")
    print(f"Saved: {OUT / 'speed_sensor_scatter.png'}")
    print(f"Total intervals: {len(d)}  (failed={len(failed)}, censored={len(censored)})")
    print(f"Failures within 500 op-h of the {CEILING} ceiling: {(failed.op_h >= CEILING - 500).sum()}")


if __name__ == "__main__":
    main()
