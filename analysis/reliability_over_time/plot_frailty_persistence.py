"""Individual-conveyor uncertainty: is a conveyor's own excess failure rate persistent?

Direct visual for the spec's explicit Req. 1 "uncertainty" ask. Reuses
outputs/req1/frailty_check.csv (scripts/02_reliability_analysis.py SS G, already
computed -- no recomputation here): each conveyor's history is split in half, and its
failure rate relative to its own Load_Class peers is compared, first half vs. second
half. A conveyor that runs hot relative to peers early keeps running hot late -- this
is a real, persistent per-conveyor trait, not noise, and is exactly the kind of
"uncertainty is structured, not random" finding the spec asks for.

Usage (repo root):
  uv run --no-project --with matplotlib --with pandas --with numpy \
    python analysis/reliability_over_time/plot_frailty_persistence.py
"""
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

IN = Path("outputs/req1")
OUT = Path(__file__).parent
ORANGE, AQUA, GREY = "#eb6834", "#1baf7a", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def main():
    d = pd.read_csv(IN / "frailty_check.csv")
    r_overall = d["rel_rate_h1"].corr(d["rel_rate_h2"])
    r_by_load = d.groupby("load").apply(lambda g: g["rel_rate_h1"].corr(g["rel_rate_h2"]), include_groups=False)

    fig, ax = plt.subplots(figsize=(7, 6.5))
    for load in ["Light", "Medium", "Heavy"]:
        g = d[d.load == load]
        ax.scatter(g.rel_rate_h1, g.rel_rate_h2, s=32, color=LOAD_COLOR[load], alpha=0.75,
                   edgecolor=SURF, linewidth=0.5, label=f"{load}  (r={r_by_load[load]:.2f})")

    lo, hi = 0, max(d.rel_rate_h1.max(), d.rel_rate_h2.max()) * 1.05
    ax.plot([lo, hi], [lo, hi], "--", color=INK2, lw=1, zorder=0)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("Relative failure rate vs. own load-class peers -- first half of history")
    ax.set_ylabel("Relative failure rate vs. own load-class peers -- second half of history")
    ax.set_title(f"A conveyor that runs hot early keeps running hot late  (fleet-wide r={r_overall:.2f})",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=9, frameon=False, loc="upper left")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "frailty_persistence.png", dpi=180, bbox_inches="tight")
    print(f"Saved: {OUT / 'frailty_persistence.png'}")
    print(f"Fleet-wide r={r_overall:.3f}")
    print(r_by_load.round(3).to_string())


if __name__ == "__main__":
    main()
