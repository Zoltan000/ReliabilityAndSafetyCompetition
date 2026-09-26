"""Slide-ready versions of the 4 strongest findings from this session, picked for the
2 Req. 1 PowerPoint slides. Simplified/restyled from the full analysis-grade figures
(fewer panels, bigger fonts, punchier one-line titles meant to be read in 3 seconds
from the back of a room) -- the underlying evidence is unchanged, only the framing.

Reuses the exact palette from scripts/07_figures.py (the deck's existing figures) for
visual consistency, and reuses already-cached data throughout -- no fleet re-query:
  - outputs/req1/intervals_Speed_Sensor.parquet (ceiling scatter)
  - outputs/req1/intervals_Bearing.parquet (hazard vs age)
  - outputs/req1/frailty_check.csv (bad-actor persistence)
  - analysis/failure_interactions/motor_precursor_trajectory.csv (motor early warning)

Usage (repo root):
  uv run --no-project --with matplotlib --with pandas --with numpy --with lifelines --with pyarrow \
    python analysis/slide_candidates/build_slide_graphics.py
"""
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import NelsonAalenFitter
import matplotlib.pyplot as plt

REQ1 = Path("outputs/req1")
FI = Path("analysis/failure_interactions")
OUT = Path(__file__).parent
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
LOAD_COLOR = {"Light": AQUA, "Medium": GREY, "Heavy": ORANGE}
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0, labelsize=12)
    ax.grid(axis="y", color=GRID, lw=0.9)
    ax.set_axisbelow(True)


def ceiling_scatter():
    d = pd.read_parquet(REQ1 / "intervals_Speed_Sensor.parquet")
    rng = np.random.default_rng(0)
    jitter = rng.uniform(-0.35, 0.35, size=len(d))

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.axvspan(47, 50.016, color=ORANGE, alpha=0.12, zorder=0)
    censored = d[d.event == 0]
    failed = d[d.event == 1]
    ax.scatter(censored.op_h / 1000, jitter[censored.index], s=26, facecolor="none",
              edgecolor=INK2, linewidth=0.9, alpha=0.6, label="still working at end of history", zorder=2)
    ax.scatter(failed.op_h / 1000, jitter[failed.index], s=30, color=ORANGE, alpha=0.7,
              edgecolor=SURF, linewidth=0.3, label="failed", zorder=3)
    ax.axvline(50.016, color=INK, ls="--", lw=2, zorder=4)
    ax.set_yticks([])
    ax.set_xlabel("Operating hours since install / last replacement (thousands)", fontsize=13)
    ax.set_title("Speed sensors fail randomly — until they hit a hard 50,000-hour ceiling",
                 fontsize=16, fontweight="bold", pad=14)
    leg = ax.legend(fontsize=12, frameon=True, loc="lower center", bbox_to_anchor=(0.5, -0.32),
                    ncol=2, columnspacing=1.5)
    leg.get_frame().set_facecolor(SURF)
    leg.get_frame().set_edgecolor(GRID)
    ax.text(50.4, 0.44, "every sensor dies\nby ~50,000 hours", fontsize=13, color=INK,
            fontweight="bold", va="top", transform=ax.get_xaxis_transform())
    style(ax)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(OUT / "slide_speed_sensor_ceiling.png", dpi=200, bbox_inches="tight")
    print(f"Saved: {OUT / 'slide_speed_sensor_ceiling.png'}")


def cap_for(d, min_risk=30):
    vals = np.sort(d["op_h"].to_numpy())
    return float(vals[-min(min_risk, len(vals))])


def smoothed_curve(df, cap):
    naf = NelsonAalenFitter()
    naf.fit(df["op_h"].clip(lower=0.01), event_observed=df["event"])
    bw = max(cap * 0.1, 200.0)
    extended = np.linspace(0, cap * 1.25, 250)
    haz = naf.smoothed_hazard_(bandwidth=bw)
    y_ext = np.interp(extended, haz.index.to_numpy(), haz.iloc[:, 0].to_numpy())
    timeline = np.linspace(0, cap, 200)
    return np.interp(timeline, extended, y_ext), timeline


def bearing_hazard_by_load():
    iv = pd.read_parquet(REQ1 / "intervals_Bearing.parquet")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for load in ["Light", "Medium", "Heavy"]:
        d = iv[iv.load == load]
        cap = cap_for(d)
        y, x = smoothed_curve(d, cap)
        ax.plot(x / 1000, y * 1000, color=LOAD_COLOR[load], lw=3.5, label=load)
    ax.set_xlabel("Operating hours since last replacement (thousands)", fontsize=13)
    ax.set_ylabel("Failure rate\n(per 1,000 operating hours)", fontsize=13)
    ax.set_title("Bearing failure risk climbs with age — much faster under heavy load",
                 fontsize=16, fontweight="bold", pad=14)
    ax.legend(fontsize=13, frameon=False, title="Load", title_fontsize=12)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "slide_bearing_hazard_by_load.png", dpi=200, bbox_inches="tight")
    print(f"Saved: {OUT / 'slide_bearing_hazard_by_load.png'}")


def bad_actor_persistence():
    d = pd.read_csv(REQ1 / "frailty_check.csv")
    r = d["rel_rate_h1"].corr(d["rel_rate_h2"])
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for load in ["Light", "Medium", "Heavy"]:
        g = d[d.load == load]
        ax.scatter(g.rel_rate_h1, g.rel_rate_h2, s=42, color=LOAD_COLOR[load], alpha=0.75,
                  edgecolor=SURF, linewidth=0.5, label=load)
    lo, hi = 0, max(d.rel_rate_h1.max(), d.rel_rate_h2.max()) * 1.05
    ax.plot([lo, hi], [lo, hi], "--", color=INK2, lw=1.3, zorder=0)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("Relative failure rate — first half of its life", fontsize=13)
    ax.set_ylabel("Relative failure rate — second half", fontsize=13)
    ax.set_title(f"A conveyor that runs hot early keeps running hot for its whole life  (r={r:.2f})",
                 fontsize=15.5, fontweight="bold", pad=14)
    ax.legend(fontsize=13, frameon=False, loc="upper left", title="Load", title_fontsize=12)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "slide_bad_actor_persistence.png", dpi=200, bbox_inches="tight")
    print(f"Saved: {OUT / 'slide_bad_actor_persistence.png'}")


def motor_early_warning():
    traj = pd.read_csv(FI / "motor_precursor_trajectory.csv")
    keep = {"Motor_Temperature_C": ("Motor temperature", ORANGE),
            "Motor_Current_A": ("Motor current", BLUE),
            "Structure_Vibration_RMS_mm_s": ("Vibration", AQUA)}
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for field, (label, color) in keep.items():
        d = traj[traj.field == field]
        ax.plot(d.day_offset, d.mean_z, lw=3.5, color=color, label=label)
    ax.axvline(0, color=INK, ls="--", lw=1.8)
    ax.text(1, ax.get_ylim()[1] * 0.85 if ax.get_ylim()[1] > 0 else 0.1, "failure", fontsize=12, color=INK)
    ax.set_xlim(-60, 10)
    ax.set_xlabel("Days before / after the failure", fontsize=13)
    ax.set_ylabel("Signal level\n(relative to that conveyor's normal)", fontsize=13)
    ax.set_title("The motor gives about 2 months' warning before it fails",
                 fontsize=16, fontweight="bold", pad=14)
    ax.legend(fontsize=13, frameon=False, loc="upper left")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "slide_motor_early_warning.png", dpi=200, bbox_inches="tight")
    print(f"Saved: {OUT / 'slide_motor_early_warning.png'}")


if __name__ == "__main__":
    ceiling_scatter()
    bearing_hazard_by_load()
    bad_actor_persistence()
    motor_early_warning()
