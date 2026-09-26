"""Does repair actually reset the clock? Visual for an already-made claim.

Slide 1's second bullet already says "every component renews perfectly: first-life and
replacement lives are identical" (scripts/02_reliability_analysis.py SS B), but that
bullet has no figure. Plot mean renewal-interval length (operating hours to failure,
event==1 only) by renewal index (0 = first life, 1 = after first repair, ...), per
Load_Class, for the 3 load-driven wear-out components. A flat line across renewal index
= perfect renewal (repair resets the component to as-good-as-new); a declining line
would mean imperfect repair / wear accumulating across renewals.

Usage (repo root):
  uv run --no-project --with matplotlib --with pandas --with numpy --with pyarrow \
    python analysis/reliability_over_time/plot_renewal_check.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

IN = Path("outputs/req1")
OUT = Path(__file__).parent
ORANGE, AQUA, GREY = "#eb6834", "#1baf7a", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
NAMES = {"Bearing": "Bearings", "Conveyor_Belt": "Belt", "Motor_Reducer": "Motor-reducer"}
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
RENEWAL_CAP = 8
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def main():
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
    rows_out = []

    for ax, comp in zip(axes, NAMES):
        iv = pd.read_parquet(IN / f"intervals_{comp}.parquet")
        iv = iv[iv.event == 1].copy()
        iv["renewal_capped"] = np.minimum(iv.renewal, RENEWAL_CAP)
        g = iv.groupby(["load", "renewal_capped"])["op_h"].agg(["mean", "count"]).reset_index()
        rows_out.append(g.assign(component=comp))
        for load in ["Light", "Medium", "Heavy"]:
            d = g[(g.load == load) & (g["count"] >= 10)].sort_values("renewal_capped")
            if d.empty:
                continue
            ax.plot(d.renewal_capped, d["mean"], "o-", color=LOAD_COLOR[load], lw=2, ms=5, label=load)
        ax.set_title(NAMES[comp], fontsize=12, fontweight="bold")
        xt = list(range(RENEWAL_CAP + 1))
        ax.set_xticks(xt, [str(v) for v in xt[:-1]] + [f"{RENEWAL_CAP}+"])
        ax.set_xlabel("Renewal index (0 = first life)")
        ax.set_ylabel("Mean life to failure (op-h)")
        ax.legend(fontsize=8, frameon=False)
        style(ax)
        if comp == "Bearing":
            # Verified survivorship bias, not imperfect repair -- see
            # plot_light_bearing_selection_effect.py: only ~1.4% of Light-class bearing
            # *positions* ever accumulate 6 renewals in 20 years, so "index 5" here is,
            # by construction, a population of chronically short-lived positions. Tracking
            # the SAME 76 physical positions through their own renewal 0 vs. renewal 5
            # shows +11% (not a decline), p=0.18 -- no real effect. Medium/Heavy show no
            # such selection pressure within 20 years and stay genuinely flat.
            ax.text(0.98, 0.92, "Light decline = survivorship bias, verified\n(light_bearing_selection_effect.png), not imperfect repair",
                    transform=ax.transAxes, ha="right", va="top", fontsize=7.5, color=INK2, style="italic")

    fig.suptitle("Mean life is flat across renewal index: repair resets each component to as-good-as-new",
                 fontsize=13, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(OUT / "renewal_check.png", dpi=180, bbox_inches="tight")
    print(f"Saved: {OUT / 'renewal_check.png'}")

    pd.concat(rows_out, ignore_index=True).to_csv(OUT / "renewal_check.csv", index=False)
    print(f"Saved: {OUT / 'renewal_check.csv'}")


if __name__ == "__main__":
    main()
