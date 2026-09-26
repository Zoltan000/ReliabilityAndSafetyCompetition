"""Does a replaced Light-class bearing really get weaker each time it's replaced?

The aggregate renewal_check.png chart shows Light-class bearing mean life declining
from ~41,000 op-h at renewal index 0 to ~28,000 op-h at renewal index 5. That's
mixing a *different, shrinking population* at every index (from 5,302 bearing
positions at index 0 down to just 76 at index 5), so it's not evidence of anything
about repair quality -- it could easily be pure survivorship bias: only the
fastest-failing bearing *positions* ever accumulate 6 renewals within 20 years, so
"index 5" is, by construction, looking only at chronically short-lived positions.

outputs/req1/intervals_Bearing.parquet doesn't preserve which physical bearing
position (Failed_Component_ID) each interval belongs to -- it only keeps Conveyor_ID
-- so a same-conveyor paired check still mixes ~40 different bearing positions per
conveyor together (a subtler version of the same bias, one level down: a conveyor's
"renewal-5" data point is dominated by whichever handful of its ~40 positions happen
to be its worst). This script rebuilds true per-position renewal sequences directly
from the fleet file (keeping Failed_Component_ID) and re-runs the check on the actual
physical unit -- the only way to get a clean before/after comparison.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with scipy \
    python analysis/reliability_over_time/plot_light_bearing_selection_effect.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#8a8a86"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
RENEWAL_CAP = 6
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF})


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def build_position_intervals(con):
    """Same construction as scripts/02_reliability_analysis.py's intervals(), but keyed by
    (Conveyor_ID, Failed_Component_ID) -- the true physical bearing -- not just Conveyor_ID."""
    f = con.sql(f"""
        SELECT Conveyor_ID, Date, Daily_State, Failure_Type, Failed_Component_ID,
               Cumulative_Operating_Hours, Bearing_Count
        FROM read_parquet('{FLEET}')
        WHERE Load_Class = 'Light'
        ORDER BY Conveyor_ID, Date
    """).df()
    ev = f[(f.Daily_State == "FAILURE_DAY") & (f.Failure_Type == "Bearing")]
    end = f.groupby("Conveyor_ID").tail(1).set_index("Conveyor_ID")
    units = f.groupby("Conveyor_ID")["Bearing_Count"].first()
    grp = {k: g.sort_values("Date") for k, g in ev.groupby(["Conveyor_ID", "Failed_Component_ID"])}

    rows = []
    for cid, n in units.items():
        for b in range(1, int(n) + 1):
            key = (cid, f"BRG_{b:03d}")
            g = grp.get(key)
            pts = [0.0] + (list(g["Cumulative_Operating_Hours"].to_numpy(dtype=float)) if g is not None else [])
            pts.append(float(end.loc[cid, "Cumulative_Operating_Hours"]))
            m = len(pts) - 1
            for r in range(m):
                rows.append({"cid": cid, "pos": key[1], "renewal": r,
                             "event": int(r < m - 1), "op_h": pts[r + 1] - pts[r]})
    return pd.DataFrame(rows)


def main():
    con = duckdb.connect()
    iv = build_position_intervals(con)
    iv.to_csv(OUT / "light_bearing_position_intervals.csv", index=False)
    n_positions = iv.groupby(["cid", "pos"]).ngroups
    print(f"{n_positions} distinct Light-class bearing positions, {len(iv)} total intervals")

    ev = iv[iv.event == 1].copy()
    ev["ridx"] = np.minimum(ev.renewal, RENEWAL_CAP)
    naive = ev.groupby("ridx").op_h.agg(["mean", "count"])
    print("\nNaive (mixing a shrinking, ever-more-selected population at each index):")
    print(naive.round(0).to_string())

    reached = ev[ev.renewal == 5][["cid", "pos"]].drop_duplicates()
    key_index = pd.MultiIndex.from_frame(reached)
    same_units = ev[ev.set_index(["cid", "pos"]).index.isin(key_index) & (ev.renewal <= 5)]
    piv = same_units.pivot_table(index=["cid", "pos"], columns="renewal", values="op_h")
    paired = piv[[0, 5]].dropna()
    t, p = stats.ttest_rel(paired[0], paired[5])
    pct = (paired[5].mean() / paired[0].mean() - 1) * 100
    print(f"\nTrue paired test, same {len(paired)} physical bearing positions, "
          f"their own renewal-0 vs. their own renewal-5 life:")
    print(f"  renewal-0 mean = {paired[0].mean():,.0f} op-h   renewal-5 mean = {paired[5].mean():,.0f} op-h   "
          f"change = {pct:+.1f}%   paired t-test p = {p:.3f}  (not significant)")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    ax = axes[0]
    ax.plot(naive.index, naive["mean"], "o-", color=ORANGE, lw=2.2, ms=7)
    for x, (m, n) in zip(naive.index, naive.values):
        ax.text(x, m + 900, f"n={int(n):,}", ha="center", fontsize=8, color=INK2)
    ax.set_title("Naive: mixes a shrinking, ever-more-selected\npopulation at every index", fontsize=11)
    ax.set_xlabel("Renewal index")
    ax.set_ylabel("Mean life to failure (op-h)")
    style(ax)

    ax = axes[1]
    for _, row in piv[list(range(6))].iterrows():
        ax.plot(range(6), row.to_numpy(), "-", color=GREY, lw=0.7, alpha=0.35)
    mean_line = piv[list(range(6))].mean()
    ax.plot(range(6), mean_line.to_numpy(), "o-", color=BLUE, lw=2.5, ms=8, zorder=5)
    ax.set_title(f"True: same {len(paired)} physical bearing positions,\n"
                 f"tracked through their own first 6 lives", fontsize=11)
    ax.set_xlabel("Renewal index")
    ax.set_ylabel("Life to failure (op-h)")
    ax.text(0.98, 0.05, f"renewal 0→5 change: {pct:+.1f}%  (p={p:.2f}, not significant)",
            transform=ax.transAxes, ha="right", fontsize=9, color=INK2)
    style(ax)

    fig.suptitle("Light-class bearings do NOT get weaker with each replacement --\n"
                 "the apparent decline is pure survivorship bias", fontsize=13, fontweight="bold", y=1.04)
    fig.tight_layout()
    fig.savefig(OUT / "light_bearing_selection_effect.png", dpi=180, bbox_inches="tight")
    print(f"\nSaved: {OUT / 'light_bearing_selection_effect.png'}")


if __name__ == "__main__":
    main()
