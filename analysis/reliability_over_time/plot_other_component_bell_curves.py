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


MIN_N_FOR_KDE = 15


def kde_curve(vals, x_hi):
    # Reflection boundary correction: a plain KDE is biased near a hard boundary at 0
    # (it smooths mass to negative values that then just vanishes, which for a
    # near-random/infant-mortality component -- highest true density AT zero -- fakes a
    # peak away from zero that isn't in the data; verified against the raw histogram for
    # Controller_PC before adding this). Mirroring the data across 0 and doubling the
    # resulting density on the positive side is the standard fix.
    xs = np.linspace(0, x_hi, 300)
    reflected = np.concatenate([vals, -vals])
    return xs, 2 * gaussian_kde(reflected)(xs)


def draw_group(ax, vals, x_hi, color, label):
    """KDE curve if there's enough data to trust one; otherwise honest rug ticks --
    never a fake flat/zero line, which would misread as "this never happens"."""
    n = len(vals)
    if n >= MIN_N_FOR_KDE:
        xs, ys = kde_curve(vals, x_hi)
        ax.plot(xs, ys, color=color, lw=2.2, label=f"{label} (n={n:,})")
    else:
        ax.plot(vals, np.zeros(n), "|", color=color, ms=18, mew=2.5,
                 label=f"{label} (n={n} — too few for a curve, actual failure times shown)")


def make_by_load_and_renewal(comp, ev):
    """3 panels, one per Load_Class, each with first-life vs. replacement overlaid --
    the full cross of both groupings instead of two separate marginal views. Each
    panel gets its own x-axis scale (load classes can differ by an order of magnitude
    in lifetime), unlike the pooled-scale panels in the main by-load/by-renewal figure."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for ax, load in zip(axes, ["Light", "Medium", "Heavy"]):
        g = ev[ev.load == load]
        x_hi = g.op_h.quantile(0.98) if len(g) else 1.0
        first = g[g.renewal == 0]
        later = g[g.renewal >= 1]
        draw_group(ax, first.op_h.to_numpy(), x_hi, BLUE, "first life")
        draw_group(ax, later.op_h.to_numpy(), x_hi, PURPLE, "replacement, any renewal ≥1")
        ax.set_title(f"{load}  (n={len(g):,})", fontsize=11, fontweight="bold")
        ax.set_xlabel("Hours until failure")
        ax.set_ylabel("Density")
        ax.legend(fontsize=8, frameon=False)
        style(ax)
        if comp == "Speed_Sensor" and SPEED_SENSOR_CEILING <= x_hi:
            ax.axvline(SPEED_SENSOR_CEILING, color=INK, ls="--", lw=1.2)
            ax.text(SPEED_SENSOR_CEILING - x_hi * 0.02, ax.get_ylim()[1] * 0.9,
                    "ceiling\n~50,016", ha="right", fontsize=7, color=INK)
    fig.suptitle(f"{NAMES[comp]}: hours until failure, by load class and first-life vs. replacement",
                 fontsize=13, fontweight="bold", y=1.03)
    fig.tight_layout()
    fname = f"bell_curve_{comp.lower()}_by_load_and_renewal.png"
    fig.savefig(OUT / fname, dpi=170, bbox_inches="tight")
    print(f"Saved: {OUT / fname}")
    plt.close(fig)


RENEWAL_LINE_CAP = 6  # groups 0..RENEWAL_LINE_CAP-1 each get their own line; the rest pool into "cap+"


def make_by_load_each_renewal(comp, ev):
    """Same 3-panel-by-Load_Class layout, but every renewal index gets its own line
    (light->dark = renewal 0->cap+) instead of collapsing to first-life vs. any-
    replacement -- "each line represents a replacement," per request. Falls back to
    rug ticks (via draw_group) for any renewal index too thin on data within a load
    class, most relevant for components that rarely get replaced many times."""
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.5))
    cmap = plt.get_cmap("Blues")
    for ax, load in zip(axes, ["Light", "Medium", "Heavy"]):
        g = ev[ev.load == load].copy()
        if g.empty:
            ax.set_title(f"{load}  (n=0)", fontsize=11, fontweight="bold")
            style(ax)
            continue
        g["ridx"] = np.minimum(g.renewal, RENEWAL_LINE_CAP)
        x_hi = g.op_h.quantile(0.98)
        present = sorted(g.ridx.unique())
        shades = cmap(np.linspace(0.35, 0.95, len(present)))
        for shade, ridx in zip(shades, present):
            vals = g.loc[g.ridx == ridx, "op_h"].to_numpy()
            label = f"renewal {ridx}" if ridx < RENEWAL_LINE_CAP else f"renewal {RENEWAL_LINE_CAP}+"
            draw_group(ax, vals, x_hi, shade, label)
        ax.set_title(f"{load}  (n={len(g):,})", fontsize=11, fontweight="bold")
        ax.set_xlabel("Hours until failure")
        ax.set_ylabel("Density")
        ax.legend(fontsize=7, frameon=False, ncol=2 if len(present) > 5 else 1)
        style(ax)
        if comp == "Speed_Sensor" and SPEED_SENSOR_CEILING <= x_hi:
            ax.axvline(SPEED_SENSOR_CEILING, color=INK, ls="--", lw=1.2)
            ax.text(SPEED_SENSOR_CEILING - x_hi * 0.02, ax.get_ylim()[1] * 0.9,
                    "ceiling\n~50,016", ha="right", fontsize=7, color=INK)
    fig.suptitle(f"{NAMES[comp]}: hours until failure, by load class -- every renewal index its own line\n"
                 "(light = original/early replacement, dark = many replacements in)",
                 fontsize=12.5, fontweight="bold", y=1.05)
    fig.tight_layout()
    fname = f"bell_curve_{comp.lower()}_by_load_each_renewal.png"
    fig.savefig(OUT / fname, dpi=170, bbox_inches="tight")
    print(f"Saved: {OUT / fname}")
    plt.close(fig)


def main():
    for comp in COMPONENTS:
        iv = pd.read_parquet(IN / f"intervals_{comp}.parquet")
        ev = iv[iv.event == 1]
        x_hi = ev.op_h.quantile(0.98)

        fig, axes = plt.subplots(1, 2, figsize=(13, 5))

        ax = axes[0]
        for load in ["Light", "Medium", "Heavy"]:
            g = ev[ev.load == load]
            draw_group(ax, g.op_h.to_numpy(), x_hi, LOAD_COLOR[load], load)
        ax.set_title("By Load_Class", fontsize=11)
        ax.set_xlabel("Hours until failure")
        ax.set_ylabel("Density")
        ax.legend(fontsize=8.5, frameon=False)
        style(ax)

        ax = axes[1]
        first = ev[ev.renewal == 0]
        later = ev[ev.renewal >= 1]
        draw_group(ax, first.op_h.to_numpy(), x_hi, BLUE, "first life")
        draw_group(ax, later.op_h.to_numpy(), x_hi, PURPLE, "replacement, any renewal ≥1")
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

        make_by_load_and_renewal(comp, ev)
        make_by_load_each_renewal(comp, ev)


if __name__ == "__main__":
    main()
