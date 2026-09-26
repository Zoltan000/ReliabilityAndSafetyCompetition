"""Slide figures for Req. 1 from outputs/req1/*.csv -> outputs/figures/*.png.

Palette: validated default categorical slots (dataviz skill), direct labels on every mark.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

IN, OUT = Path("outputs/req1"), Path("outputs/figures")
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
NAMES = {"Bearing": "Bearings", "Conveyor_Belt": "Belt", "Motor_Reducer": "Motor-reducer",
         "Speed_Sensor": "Speed sensor", "Controller_PC": "Controller PC",
         "Control_Software": "Control software", "Contactor": "Contactor"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def beta_plot(w):
    d = w[(w.intervals == "all") & (w.clock == "op_h")].copy()
    d["lo"] = d.beta_95ci.str.split("-").str[0].astype(float)
    d["hi"] = d.beta_95ci.str.split("-").str[1].astype(float)
    d = d.sort_values("beta")
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.axvspan(0.3, 0.95, color="#f0efec", zorder=0)
    ax.axvspan(1.35, 7, color="#f0efec", zorder=0)
    for x, t in [(0.62, "infant\nmortality"), (1.15, "random"), (4.8, "wear-out")]:
        ax.text(x, len(d) - 0.35, t, ha="center", va="bottom", color=INK2, fontsize=9)
    y = np.arange(len(d))
    ax.hlines(y, d.lo, d.hi, color=BLUE, lw=2)
    ax.plot(d.beta, y, "o", color=BLUE, ms=8, mec=SURF, mew=2)
    for yi, (b, n) in enumerate(zip(d.beta, d.n_ev)):
        ax.text(b, yi + 0.28, f"β={b:.2f}", ha="center", fontsize=9, color=INK)
    ax.set_yticks(y, [f"{NAMES[c]}  (n={n:,})" for c, n in zip(d.component, d.n_ev)])
    ax.set_xscale("log")
    ax.set_xticks([0.5, 1, 2, 3, 5], ["0.5", "1", "2", "3", "5"])
    ax.xaxis.set_minor_formatter(plt.NullFormatter())
    ax.set_xlim(0.45, 7)
    ax.set_ylim(-0.6, len(d) + 0.2)
    ax.set_xlabel("Weibull shape β with 95% CI (renewal intervals)")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "beta.png", dpi=220)


def load_plot(w):
    d = w[(w.intervals == "all") & (w.clock == "op_h") & (w.component != "Contactor")].copy()
    d["factor"] = 1 / d["eta_Heavy/Light"]
    d = d.sort_values("factor")
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    y = np.arange(len(d))
    ax.barh(y, np.log10(d.factor), color=[ORANGE if f > 1.5 else (AQUA if f < 0.67 else "#b5b3ad") for f in d.factor],
            height=0.6)
    ax.axvline(0, color=INK2, lw=1)
    for yi, f in enumerate(d.factor):
        lab = f"{f:.1f}× shorter" if f > 1.5 else (f"{1/f:.0f}× longer" if f < 0.67 else "no effect")
        inside = f < 0.67
        x = np.log10(f) + 0.06 if inside else max(np.log10(f), 0) + 0.04
        ax.text(x, yi, lab, va="center", ha="left", fontsize=9, color="white" if inside else INK)
    ax.set_yticks(y, [NAMES[c] for c in d.component])
    ax.set_xticks(np.log10([1 / 30, 0.1, 1, 10, 30]), ["1/30", "1/10", "1", "10", "30"])
    ax.set_xlim(np.log10(1 / 60), np.log10(60))
    ax.set_xlabel("Life on Heavy vs Light conveyors (same operating hours)")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "load.png", dpi=220)


def cm_plot(cm):
    d = cm[cm.component != "Contactor"].set_index("component")
    cols = {"vib": "Vibration", "cur_per_tp": "Current /\nthroughput", "mtemp_excess": "Motor temp\nexcess",
            "vdrop_per_cur": "Contact\nV-drop", "closing_ms": "Closing\ntime"}
    m = d[list(cols)].to_numpy()
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    im = ax.imshow(np.clip(m, 0, 0.4), cmap=plt.matplotlib.colors.LinearSegmentedColormap.from_list(
        "b", ["#f4f8fe", "#86b6ef", "#1c5cab"]), vmin=0, vmax=0.4, aspect="auto")
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            ax.text(j, i, f"{m[i, j]:+.2f}", ha="center", va="center", fontsize=9,
                    color="white" if m[i, j] > 0.25 else INK)
    ax.set_xticks(range(len(cols)), list(cols.values()), fontsize=9)
    ax.set_yticks(range(len(d)), [NAMES[c] for c in d.index])
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("Signal shift in the 30 days before failure (σ, within conveyor)", fontsize=10, color=INK2)
    fig.tight_layout()
    fig.savefig(OUT / "cm.png", dpi=220)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    w = pd.read_csv(IN / "weibull_by_clock.csv")
    beta_plot(w)
    load_plot(w)
    cm_plot(pd.read_csv(IN / "cm_precursors.csv"))
    print("figures:", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
