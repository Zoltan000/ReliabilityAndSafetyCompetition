"""Best-effort: is a component's hazard elevated in the 90 days after another type fails?

For each component i, mark every conveyor-day as "post-i" if it falls in the 90 days
after that conveyor's most recent type-i failure (computed with a running MAX(Date)
window function per conveyor -- no row-exploding join needed). Then, for every
component j, compare the type-j failure rate per at-risk day inside the post-i window
vs. outside it (the same conveyor's own baseline), stratified by Load_Class and pooled
via the same observed/expected approach as plot_failure_transition_lift.py.

This is a stretch/time-boxed script per the plan: if a given cell has too few events to
say anything, it is left as a footnote in findings.md rather than a headline claim.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_failure_hazard_window.py
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
WINDOW_DAYS = 90


def main():
    con = duckdb.connect()
    last_cols = ",\n".join(
        f"MAX(CASE WHEN Failure_Type = '{c}' THEN Date END) "
        f"OVER (PARTITION BY Conveyor_ID ORDER BY Date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS last_{i}"
        for i, c in enumerate(COMPONENTS))
    print(f"Building per-day 'within {WINDOW_DAYS} days after a type-i failure' flags (single window pass)...")
    con.execute(f"""
        CREATE TEMP TABLE wl AS
        SELECT Conveyor_ID, Date, Load_Class, Daily_State, Failure_Type,
               CASE WHEN Daily_State IN ('RUNNING', 'FAILURE_DAY') THEN 1 ELSE 0 END AS at_risk,
               {last_cols}
        FROM read_parquet('{FLEET}')
    """)

    rows_per_class = {c: [] for c in COMPONENTS}
    n_i_post = {c: 0 for c in COMPONENTS}
    for i, comp_i in enumerate(COMPONENTS):
        post_expr = f"(last_{i} IS NOT NULL AND Date > last_{i} AND Date <= last_{i} + INTERVAL {WINDOW_DAYS} DAY)"
        denom = con.sql(f"""
            SELECT Load_Class, {post_expr} AS post, SUM(at_risk) AS at_risk_days
            FROM wl GROUP BY Load_Class, post
        """).df()
        fails = con.sql(f"""
            SELECT Load_Class, {post_expr} AS post, Failure_Type AS j_type, COUNT(*) AS n
            FROM wl WHERE Daily_State = 'FAILURE_DAY'
            GROUP BY Load_Class, post, Failure_Type
        """).df()
        rows_per_class[comp_i] = (denom, fails)
        print(f"  {comp_i}: done")

    # pooled observed/expected across load classes, per (i, j)
    observed = pd.DataFrame(0.0, index=COMPONENTS, columns=COMPONENTS)
    expected = pd.DataFrame(0.0, index=COMPONENTS, columns=COMPONENTS)
    post_at_risk_total = pd.Series(0, index=COMPONENTS, dtype=int)
    for comp_i, (denom, fails) in rows_per_class.items():
        for load, g in denom.groupby("Load_Class"):
            at_risk_post = g.loc[g.post, "at_risk_days"]
            at_risk_base = g.loc[~g.post, "at_risk_days"]
            if at_risk_post.empty or at_risk_base.empty:
                continue
            at_risk_post = float(at_risk_post.iloc[0])
            at_risk_base = float(at_risk_base.iloc[0])
            post_at_risk_total[comp_i] += at_risk_post
            fg = fails[fails.Load_Class == load]
            for comp_j in COMPONENTS:
                n_post = fg.loc[fg.post & (fg.j_type == comp_j), "n"].sum()
                n_base = fg.loc[(~fg.post) & (fg.j_type == comp_j), "n"].sum()
                base_rate = n_base / at_risk_base if at_risk_base > 0 else np.nan
                observed.loc[comp_i, comp_j] += n_post
                if np.isfinite(base_rate):
                    expected.loc[comp_i, comp_j] += at_risk_post * base_rate

    with np.errstate(divide="ignore", invalid="ignore"):
        lift = observed / expected.where(expected > 0)

    observed.to_csv(OUT / "failure_hazard_window_counts.csv")
    lift.to_csv(OUT / "failure_hazard_window_lift.csv")
    print(f"\nHazard-window lift ({WINDOW_DAYS}d post-i rate / same-conveyor baseline rate), "
          "observed/expected pooled across load classes:")
    print(lift.round(2).to_string())
    print("\nObserved post-window failure counts:")
    print(observed.astype(int).to_string())
    print("\nTotal post-i at-risk days (denominator scale, pooled):")
    print(post_at_risk_total.to_string())

    plot(lift, observed, post_at_risk_total, OUT / "failure_hazard_window.png")


def plot(lift_df, observed_df, post_at_risk_total, path):
    n = len(COMPONENTS)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_lift = np.log2(lift_df.to_numpy(dtype=float))
    finite = log_lift[np.isfinite(log_lift)]
    vmax = max(np.nanmax(np.abs(finite)), 0.5) if finite.size else 1

    fig, ax = plt.subplots(figsize=(9.5, 8))
    im = ax.imshow(log_lift, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(COMPONENTS, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels([f"{c} (at-risk-days={int(post_at_risk_total[c]):,})" for c in COMPONENTS], fontsize=8)
    ax.set_xlabel(f"Component j (failure rate measured)")
    ax.set_ylabel(f"Component i ({WINDOW_DAYS}-day window after its failure)")
    for i in range(n):
        for j in range(n):
            v = lift_df.iat[i, j]
            cnt = int(observed_df.iat[i, j])
            txt = f"{v:.2f}x\n(n={cnt})" if np.isfinite(v) else "n/a"
            lv = log_lift[i, j]
            color = "white" if np.isfinite(lv) and abs(lv) > vmax * 0.55 else "#222222"
            ax.text(j, i, txt, ha="center", va="center", fontsize=7, color=color)
    ax.set_title(f"{WINDOW_DAYS}-day post-failure hazard lift: rate(j) in window-after-i / same-conveyor "
                  f"baseline rate(j)\n(pooled across Load_Class via observed/expected; diagonal cross-checks "
                  f"the Weibull renewal fits)", fontsize=9.5, fontweight="bold")
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("log2(lift)  [0 = no effect, red = elevated, blue = suppressed]")
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
