"""3D "ridgeline" plots: distribution of bearing lifetimes, sliced by daily throughput.

X = hours until failure (one physical bearing position's lifetime, event==1 only)
Y = density (the bell-curve height -- a Gaussian KDE of X within that throughput slice)
Z = daily throughput, binned into 6 quantile slices -- two competing definitions,
    produced as two separate figures per the discussion:
      (a) raw Total_kg_Day -- the whole conveyor's daily throughput
      (b) Total_kg_Day / Bearing_Count -- an estimated load share per bearing, since a
          conveyor with more bearings spreads the same total load across more support
          points
Each figure has one 3D subplot per Load_Class (Heavy/Medium/Light).

Uses true per-bearing-position renewal intervals (same construction as
plot_light_bearing_selection_effect.py, generalized to the whole fleet) so that a
conveyor with 50 bearings contributes 50 lifetimes, not 1 -- Bearing_Count is handled
by construction, independent of which Z-axis definition is chosen.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy --with scipy \
    python analysis/reliability_over_time/plot_bearing_lifetime_vs_load_3d.py
"""
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers the '3d' projection)

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
LOADS = ["Heavy", "Medium", "Light"]
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
N_BINS = 6
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "figure.facecolor": SURF,
                     "axes.facecolor": SURF})


def build_all_positions(con):
    f = con.sql(f"""
        SELECT Conveyor_ID, Date, Daily_State, Failure_Type, Failed_Component_ID,
               Cumulative_Operating_Hours, Bearing_Count, Load_Class
        FROM read_parquet('{FLEET}')
        ORDER BY Conveyor_ID, Date
    """).df()
    ev = f[(f.Daily_State == "FAILURE_DAY") & (f.Failure_Type == "Bearing")]
    end = f.groupby("Conveyor_ID").tail(1).set_index("Conveyor_ID")
    units = f.groupby("Conveyor_ID")["Bearing_Count"].first()
    loads = f.groupby("Conveyor_ID")["Load_Class"].first()
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
                rows.append({"cid": cid, "pos": key[1], "load": loads[cid], "renewal": r,
                             "event": int(r < m - 1), "op_h": pts[r + 1] - pts[r]})
    return pd.DataFrame(rows), units


def ridge_subplot(ax, d, z_col, z_label, color):
    d = d.copy()
    d["zbin"] = pd.qcut(d[z_col], N_BINS, labels=False, duplicates="drop")
    bin_centers = d.groupby("zbin")[z_col].mean().sort_index()
    cmap = plt.get_cmap("Blues")
    shades = cmap(np.linspace(0.35, 0.95, len(bin_centers)))

    x_hi = d.op_h.quantile(0.98)
    xs = np.linspace(0, x_hi, 200)
    for shade, (zbin, zval) in zip(shades, bin_centers.items()):
        vals = d.loc[d.zbin == zbin, "op_h"].to_numpy()
        if len(vals) < 30:
            continue
        # Reflection boundary correction (see plot_other_component_bell_curves.py): makes
        # no visible difference for Bearing since it's strongly wear-out (true density is
        # genuinely ~0 near hours=0), but applied for consistency/correctness.
        densities = 2 * gaussian_kde(np.concatenate([vals, -vals]))(xs)
        # ax.plot(X, Y, Z) maps positionally to data-space axes regardless of view angle:
        # X = hours until failure, Y = density (the bell curve), Z = throughput slice.
        ax.plot(xs, densities, np.full_like(xs, zval), color=shade, lw=1.6)

    ax.set_xlabel("Hours until failure", labelpad=8, fontsize=8.5)
    ax.set_ylabel("Density", labelpad=8, fontsize=8.5)
    ax.set_zlabel(z_label, labelpad=2, fontsize=8.5)
    ax.set_xlim(0, x_hi)
    ax.view_init(elev=22, azim=-60)
    ax.tick_params(labelsize=7)


def make_figure(df, z_col, z_label, title, fname):
    fig = plt.figure(figsize=(16, 5.5))
    for i, load in enumerate(LOADS):
        ax = fig.add_subplot(1, 3, i + 1, projection="3d")
        d = df[(df.load == load) & (df.event == 1)]
        ridge_subplot(ax, d, z_col, z_label, load)
        ax.set_title(f"{load}  (n={len(d):,} bearing failures)", fontsize=11, fontweight="bold", y=1.0)
    fig.suptitle(title, fontsize=13, fontweight="bold", y=1.03)
    fig.tight_layout()
    fig.savefig(OUT / fname, dpi=170, bbox_inches="tight")
    print(f"Saved: {OUT / fname}")


def main():
    con = duckdb.connect()
    print("Building per-bearing-position renewal intervals for the whole fleet...")
    iv, bearing_count = build_all_positions(con)
    print(f"{iv.groupby(['cid', 'pos']).ngroups:,} distinct bearing positions, {len(iv):,} intervals")

    kg = con.sql(f"""
        SELECT Conveyor_ID, AVG(Total_kg_Day) AS mean_kg_day
        FROM read_parquet('{FLEET}')
        WHERE Total_kg_Day IS NOT NULL
        GROUP BY Conveyor_ID
    """).df().set_index("Conveyor_ID")["mean_kg_day"]

    iv["kg_day"] = iv["cid"].map(kg)
    iv["bearing_count"] = iv["cid"].map(bearing_count)
    iv["kg_day_per_bearing"] = iv["kg_day"] / iv["bearing_count"]
    iv.to_csv(OUT / "bearing_position_intervals_all_loads.csv", index=False)

    make_figure(iv, "kg_day", "Total kg / day (whole conveyor)",
                "Bearing lifetime distribution vs. whole-conveyor daily throughput",
                "bearing_lifetime_vs_kgday_raw_3d.png")
    make_figure(iv, "kg_day_per_bearing", "Total kg / day ÷ Bearing_Count",
                "Bearing lifetime distribution vs. estimated load share per bearing",
                "bearing_lifetime_vs_kgday_per_bearing_3d.png")


if __name__ == "__main__":
    main()
