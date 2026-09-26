"""Does a conveyor prone to one failure mode also get others?

Per conveyor, compute each component's failure rate (failures / at-risk days) over its
whole 20-year history, then correlate those 7 rate columns across the 284 conveyors.

Two versions:
  - raw: dominated by the Load_Class confound (Heavy conveyors fail more at everything,
    so every component pair looks positively correlated even with no real relationship).
  - adjusted: each conveyor's rate is divided by its Load_Class peer mean first (same
    normalization as outputs/req1/frailty_check.csv SS G), which removes the load
    confound and isolates whether failure-proneness is a shared whole-asset trait
    vs. component-specific.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib --with pandas --with numpy \
    python analysis/failure_interactions/plot_cross_conveyor_failure_correlation.py
"""
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path(__file__).parent
COMPONENTS = ["Bearing", "Conveyor_Belt", "Motor_Reducer", "Speed_Sensor",
              "Controller_PC", "Control_Software", "Contactor"]


def plot_pair(raw_corr, adj_corr, path):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"wspace": 0.45})
    for k, (ax, corr, title) in enumerate([(axes[0], raw_corr, "Raw failure rate\n(Load_Class confound present)"),
                                            (axes[1], adj_corr, "Load-adjusted relative rate\n(peer-normalized)")]):
        n = len(COMPONENTS)
        im = ax.imshow(corr.to_numpy(), cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(COMPONENTS, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(COMPONENTS if k == 0 else [], fontsize=8)
        for i in range(n):
            for j in range(n):
                v = corr.iat[i, j]
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                        color="white" if abs(v) > 0.6 else "#222222")
        ax.set_title(title, fontsize=11, fontweight="bold")
    cb = fig.colorbar(im, ax=axes, shrink=0.8, location="right", pad=0.03)
    cb.set_label("Pearson r (across 284 conveyors)")
    fig.suptitle("Cross-conveyor failure-count correlation between component types", fontsize=13, fontweight="bold")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved: {path}")


def main():
    con = duckdb.connect()
    case_sums = ",\n".join(
        f"SUM(CASE WHEN Daily_State = 'FAILURE_DAY' AND Failure_Type = '{c}' THEN 1 ELSE 0 END) AS {c}"
        for c in COMPONENTS)
    print("Aggregating per-conveyor failure counts and at-risk days...")
    df = con.sql(f"""
        SELECT Conveyor_ID,
               any_value(Load_Class) AS Load_Class,
               SUM(CASE WHEN Daily_State IN ('RUNNING', 'FAILURE_DAY') THEN 1 ELSE 0 END) AS at_risk_days,
               {case_sums}
        FROM read_parquet('{FLEET}')
        GROUP BY Conveyor_ID
    """).df()
    print(f"  {len(df)} conveyors, load classes: {df.Load_Class.value_counts().to_dict()}")

    rate = df[COMPONENTS].div(df["at_risk_days"], axis=0)
    rate.columns = COMPONENTS
    rate["Load_Class"] = df["Load_Class"].to_numpy()

    raw_corr = rate[COMPONENTS].corr()

    rel = rate[COMPONENTS].div(rate.groupby(rate["Load_Class"])[COMPONENTS].transform("mean"))
    adj_corr = rel.corr()

    raw_corr.to_csv(OUT / "cross_conveyor_failure_correlation_raw.csv")
    adj_corr.to_csv(OUT / "cross_conveyor_failure_correlation_adjusted.csv")
    print("\nRaw failure-rate correlation (load confound present):")
    print(raw_corr.round(3).to_string())
    print("\nLoad-adjusted relative-rate correlation:")
    print(adj_corr.round(3).to_string())

    plot_pair(raw_corr, adj_corr, OUT / "cross_conveyor_failure_correlation.png")


if __name__ == "__main__":
    main()
