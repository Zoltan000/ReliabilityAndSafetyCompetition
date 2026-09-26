"""Failure rate vs. component age (operating hours since restart) -- the concrete,
visual counterpart to outputs/figures/beta.png's abstract Weibull shape (beta) plot.

Reuses outputs/req1/intervals_<component>.parquet (one row per renewal interval:
cid, load, renewal, event, days, op_h, cycles, kg -- see scripts/02_reliability_analysis.py
`intervals()`). Fits a Nelson-Aalen smoothed hazard on op_h. Every component gets all
4 series -- All loads, Light, Medium, Heavy -- not just the 3 components where load is
known to matter; this makes "does load matter here" a direct visual read (overlapping
lines) rather than an assumption baked into which panels get split. Groups with too
few events for a reliable curve (event count < MIN_EVENTS) render as rug ticks at
their actual failure times instead of a fabricated smooth line -- most relevant for
Contactor (12 fleet-wide failures) and Control_Software/Heavy (6).

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with lifelines --with pyarrow \
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
         "Control_Software": "Control software", "Contactor": "Contactor"}
GROUP_COLOR = {"All": BLUE, "Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
GROUPS = ["All", "Light", "Medium", "Heavy"]
MIN_EVENTS = 20
NO_WEIBULL_OVERLAY = {"Contactor"}  # n=12 fleet-wide -> the fit is degenerate (eta_Light ~65M op-h), not usable
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def cap_for(d, min_risk=30):
    """The largest op_h with at least min_risk intervals still at/beyond it -- i.e. how
    far the curve can honestly extend before too few real units remain to support the
    estimate. A fixed percentile (e.g. 97th) is the wrong rule here: for a group this
    large (n in the hundreds of thousands for Bearing) it cuts the curve off well
    before the data runs out, hiding real shape near the tail; for a small group it
    could do the opposite. A minimum-risk-count rule adapts to each group's actual size."""
    vals = np.sort(d["op_h"].to_numpy())
    k = min(min_risk, len(vals))
    return float(vals[-k])


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


def weibull_params(comp):
    """beta and eta per load class from outputs/req1/weibull_by_clock.csv (op_h clock,
    all intervals) -- an MLE fit, completely independent of the Nelson-Aalen smoothing
    used elsewhere in this script. Used as a cross-check: a Weibull hazard with
    beta > 1 is mathematically strictly increasing (h(t) = (beta/eta)*(t/eta)^(beta-1),
    and beta-1 > 0), so it CANNOT produce a peak-then-decline. If it tracks the
    empirical curve, that's strong evidence the empirical curve's shape is real."""
    w = pd.read_csv(IN / "weibull_by_clock.csv")
    row = w[(w.component == comp) & (w.intervals == "all") & (w.clock == "op_h")].iloc[0]
    beta = row["beta"]
    eta = {"Light": row["eta_Light"], "Medium": row["eta_Light"] * row["eta_Medium/Light"],
           "Heavy": row["eta_Light"] * row["eta_Heavy/Light"]}
    return beta, eta


def weibull_hazard(t, beta, eta):
    return (beta / eta) * (np.maximum(t, 1e-6) / eta) ** (beta - 1)


def draw_group(ax, d, group, color, comp):
    """Smoothed hazard curve if there's enough data to trust one; otherwise honest rug
    ticks at the actual failure times -- never a fabricated curve from too few events."""
    n = int(d.event.sum())
    if n >= MIN_EVENTS:
        cap = cap_for(d)
        y, x = smoothed_curve(d, cap)
        ax.plot(x / 1000, y * 1000, color=color, lw=2.2, label=f"{group} (n={n:,})")
        if group == "Heavy" and comp not in NO_WEIBULL_OVERLAY:
            beta, eta = weibull_params(comp)
            ax.plot(x / 1000, weibull_hazard(x, beta, eta["Heavy"]) * 1000, color=color,
                    lw=1.3, ls="--", alpha=0.8, label=f"Heavy (Weibull fit, β={beta:.2f})")
        return pd.DataFrame({"component": comp, "load": group, "op_h": x, "hazard_per_op_h": y})
    else:
        vals = d.loc[d.event == 1, "op_h"].to_numpy()
        ax.plot(vals / 1000, np.zeros(len(vals)), "|", color=color, ms=16, mew=2.2,
                label=f"{group} (n={n} — too few for a curve)")
        return pd.DataFrame({"component": comp, "load": group, "op_h": vals, "hazard_per_op_h": np.nan})


def main():
    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    axes = axes.flatten()
    rows_out = []

    for ax, comp in zip(axes, NAMES):
        iv = pd.read_parquet(IN / f"intervals_{comp}.parquet")
        for group in GROUPS:
            d = iv if group == "All" else iv[iv.load == group]
            if d.empty:
                continue
            rows_out.append(draw_group(ax, d, group, GROUP_COLOR[group], comp))
        ax.set_title(f"{NAMES[comp]}  (n={int(iv.event.sum()):,} failures)", fontsize=11, fontweight="bold")
        ax.set_xlabel("Operating hours since restart (thousands)")
        ax.set_ylabel("Hazard / 1,000 op-h")
        ax.legend(fontsize=6.8, frameon=False, ncol=1)
        style(ax)

        if comp == "Speed_Sensor":
            # Real, data-backed hard ceiling (not a smoothing artifact): 158 of 2,122
            # intervals land within 0.1% of the max op_h (50,016h = 2,084 days continuous),
            # across all load classes and renewal indices -- see findings.md.
            ax.axvline(50.016, color=INK2, ls="--", lw=1)
            ax.text(49.6, ax.get_ylim()[1] * 0.55, "hard ceiling\n~50,016 op-h\n(2,084 days)",
                    ha="right", fontsize=7.5, color=INK2)

    axes[-1].axis("off")
    fig.suptitle("Failure rate vs. component age, every load class + pooled, every component\n"
                 "rising = wear-out, flat = random, falling = infant mortality",
                 fontsize=13, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(OUT / "hazard_vs_age.png", dpi=180, bbox_inches="tight")
    print(f"Saved: {OUT / 'hazard_vs_age.png'}")

    pd.concat(rows_out, ignore_index=True).to_csv(OUT / "hazard_vs_age.csv", index=False)
    print(f"Saved: {OUT / 'hazard_vs_age.csv'}")


if __name__ == "__main__":
    main()
