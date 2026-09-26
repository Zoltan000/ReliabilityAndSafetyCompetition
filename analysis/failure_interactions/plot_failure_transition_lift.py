"""Does failure type i change the odds that the *next* failure is type j?

For every failure on a conveyor, find its immediate successor failure (LEAD by Date,
partitioned by Conveyor_ID). Group counts by (Load_Class, current_type, next_type).

Two confounds must be controlled, both handled by stratifying on Load_Class before
ratioing:
  1. Load_Class confound: Heavy conveyors have a different next-failure-type mix than
     Light ones regardless of what the current failure type is (see
     cross_conveyor_failure_correlation.py). Comparing P(next=j|i) to the fleet-wide
     marginal P(next=j) would pick this up as a false i->j effect.
  2. Generic restart-hazard confound: any failure is followed by 1 corrective day and a
     restart, and restart days carry elevated hazard for some components regardless of
     which component just failed (e.g. Contactor, see CLAUDE.md EDA notes). This shows
     up as a uniformly elevated column j across every row i, and cancels out in the
     ratio P(next=j|i) / P(next=j) as long as the baseline is computed the same way
     (both from "the type of the next failure after some failure").

Pooling across load classes uses an observed-vs-expected (standardized) ratio rather
than an average of per-class ratios, since it does not create ratio-of-ratios bias:
  pooled_lift[i,j] = sum_L(observed[i,j,L]) / sum_L(N[i,L] * P(j|L))
where N[i,L] is the number of type-i failures in load class L and P(j|L) is that load
class's own marginal next-failure-type distribution.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_failure_transition_lift.py
"""
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
COMPONENTS = ["Bearing", "Conveyor_Belt", "Motor_Reducer", "Speed_Sensor",
              "Controller_PC", "Control_Software", "Contactor"]


def main():
    con = duckdb.connect()
    print("Building failure-transition counts (LEAD by Conveyor_ID/Date)...")
    counts = con.sql(f"""
        WITH fails AS (
            SELECT Conveyor_ID, Date, Load_Class, Failure_Type AS current_type,
                   LEAD(Failure_Type) OVER (PARTITION BY Conveyor_ID ORDER BY Date) AS next_type
            FROM read_parquet('{FLEET}')
            WHERE Daily_State = 'FAILURE_DAY'
        )
        SELECT Load_Class, current_type, next_type, COUNT(*) AS n
        FROM fails
        WHERE next_type IS NOT NULL
        GROUP BY Load_Class, current_type, next_type
    """).df()
    print(f"  {counts.n.sum():,} failure transitions across {counts.Load_Class.nunique()} load classes")

    rows = []
    per_class = []
    for load, g in counts.groupby("Load_Class"):
        mat = g.pivot(index="current_type", columns="next_type", values="n") \
               .reindex(index=COMPONENTS, columns=COMPONENTS).fillna(0)
        total = mat.to_numpy().sum()
        marginal_j = mat.sum(axis=0) / total  # P(next=j | load), from the same event set
        n_i = mat.sum(axis=1)  # N[i, load]
        expected = np.outer(n_i.to_numpy(), marginal_j.to_numpy())
        lift = mat.to_numpy() / np.where(expected > 0, expected, np.nan)
        per_class.append(mat.assign(Load_Class=load).reset_index())
        rows.append({"load": load, "mat": mat.to_numpy(), "n_i": n_i.to_numpy(), "marginal_j": marginal_j.to_numpy()})

    # pooled observed/expected across load classes
    observed = sum(r["mat"] for r in rows)
    expected_pool = sum(np.outer(r["n_i"], r["marginal_j"]) for r in rows)
    pooled_lift = observed / np.where(expected_pool > 0, expected_pool, np.nan)
    pooled_lift_df = pd.DataFrame(pooled_lift, index=COMPONENTS, columns=COMPONENTS)
    n_i_total = pd.Series(sum(r["n_i"] for r in rows), index=COMPONENTS)

    per_class_df = pd.concat(per_class, ignore_index=True)
    per_class_df.to_csv(OUT / "failure_transition_counts_by_load_class.csv", index=False)
    pooled_lift_df.to_csv(OUT / "failure_transition_lift_pooled.csv")
    observed_df = pd.DataFrame(observed, index=COMPONENTS, columns=COMPONENTS)
    observed_df.to_csv(OUT / "failure_transition_counts_pooled.csv")

    print("\nPooled transition-count matrix (rows = current failure, cols = next failure):")
    print(observed_df.astype(int).to_string())
    print("\nRow totals (N of transitions starting from this type):")
    print(n_i_total.astype(int).to_string())
    print("\nPooled lift matrix (observed / load-class-expected; 1.0 = no effect beyond load+restart baseline):")
    print(pooled_lift_df.round(2).to_string())
    print("\nNote: Bearing is ~94% of all failure events (per-conveyor bearing population), so any modest")
    print("under/over-representation of Bearing-next mechanically inflates the lift on every other column")
    print("(compositional-data artifact). See the Bearing-excluded matrix below for the cleaner signal among")
    print("the 6 rarer components.")

    plot(pooled_lift_df, observed_df, n_i_total, OUT / "failure_transition_lift.png",
         "Failure-transition lift: P(next=j | current=i) / load-class-expected P(next=j)\n"
         "(load-class and generic restart-hazard effects cancel in this ratio; see script docstring)")

    # --- Bearing-excluded view: composition of the next failure among the 6 rarer types only,
    # removing the compositional-data artifact caused by Bearing's ~94% share of all events.
    sub_cols = [c for c in COMPONENTS if c != "Bearing"]
    rows_sub = []
    for r in rows:
        mat_sub = pd.DataFrame(r["mat"], index=COMPONENTS, columns=COMPONENTS)[sub_cols]
        n_i_sub = mat_sub.sum(axis=1).to_numpy()
        total_sub = mat_sub.to_numpy().sum()
        marginal_j_sub = mat_sub.sum(axis=0).to_numpy() / total_sub
        rows_sub.append({"mat": mat_sub.to_numpy(), "n_i": n_i_sub, "marginal_j": marginal_j_sub})
    observed_sub = sum(r["mat"] for r in rows_sub)
    expected_sub = sum(np.outer(r["n_i"], r["marginal_j"]) for r in rows_sub)
    lift_sub = observed_sub / np.where(expected_sub > 0, expected_sub, np.nan)
    lift_sub_df = pd.DataFrame(lift_sub, index=COMPONENTS, columns=sub_cols)
    observed_sub_df = pd.DataFrame(observed_sub, index=COMPONENTS, columns=sub_cols)
    n_i_sub_total = pd.Series(sum(r["n_i"] for r in rows_sub), index=COMPONENTS)
    lift_sub_df.to_csv(OUT / "failure_transition_lift_excl_bearing_next.csv")
    observed_sub_df.to_csv(OUT / "failure_transition_counts_excl_bearing_next.csv")

    print("\nBearing-excluded lift matrix (next failure restricted to the 6 rarer types; "
          "rows = all 7 current types, cols = 6 non-Bearing next types):")
    print(lift_sub_df.round(2).to_string())

    plot(lift_sub_df, observed_sub_df, n_i_sub_total, OUT / "failure_transition_lift_excl_bearing_next.png",
         "Failure-transition lift, next failure restricted to non-Bearing types\n"
         "(removes the compositional artifact from Bearing's ~94% share of all events)",
         cols=sub_cols)


def plot(lift_df, observed_df, n_i_total, path, title, cols=None):
    cols = cols or COMPONENTS
    n_rows, n_cols = len(COMPONENTS), len(cols)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_lift = np.log2(lift_df.to_numpy())
    finite = log_lift[np.isfinite(log_lift)]
    vmax = max(np.nanmax(np.abs(finite)), 0.5) if finite.size else 1

    fig, ax = plt.subplots(figsize=(1.1 * n_cols + 3, 1.0 * n_rows + 2))
    im = ax.imshow(log_lift, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(n_cols))
    ax.set_yticks(range(n_rows))
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels([f"{c} (n={int(n_i_total[c])})" for c in COMPONENTS], fontsize=9)
    ax.set_xlabel("Next failure type")
    ax.set_ylabel("Current failure type")
    for i in range(n_rows):
        for j in range(n_cols):
            v = lift_df.iat[i, j]
            cnt = int(observed_df.iat[i, j])
            txt = f"{v:.2f}x\n(n={cnt})" if np.isfinite(v) else "n/a"
            lv = log_lift[i, j]
            color = "white" if np.isfinite(lv) and abs(lv) > vmax * 0.55 else "#222222"
            ax.text(j, i, txt, ha="center", va="center", fontsize=7, color=color)
    ax.set_title(title, fontsize=10, fontweight="bold")
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("log2(lift)  [0 = no effect, red = elevated, blue = suppressed]")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
