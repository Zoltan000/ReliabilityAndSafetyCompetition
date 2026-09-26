"""The reusable forecasting tool: Parquet path of one conveyor -> next 5 failures + 3-year downtime.

Uses every row supplied, sorts by Date, and forecasts from the last observed day. Nothing about
history length is assumed (minimum 200 days per the spec; shorter input still runs, with a warning).
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import nominal_pm_blocks
from .features import features_asof
from .io import COMPONENTS, load_conveyor
from .labels import BLOCK_EDGES, N_BLOCKS, N_NEXT
from .models import DirectML

H_PER_FAILURE = 36.0  # 12 h on the failure day + one 24 h corrective day (constant in the fleet data)
H_PER_PM = 24.0


def load_models(art: Path) -> tuple[list[DirectML], dict]:
    art = Path(art)
    meta = json.loads((art / "manifest.json").read_text())
    models = [DirectML.load(art / d) for d in meta["model_dirs"]]
    return models, meta


def ensemble_predict(models: list[DirectML], X: pd.DataFrame) -> dict:
    preds = [m.predict(X) for m in models]
    out = {"fail_blocks": np.mean([p["fail_blocks"] for p in preds], axis=0),
           "pm_blocks": preds[0]["pm_blocks"]}
    prev = np.zeros(len(X))
    for k in range(1, N_NEXT + 1):
        t = np.exp(np.mean([np.log(p[f"t{k}"]) for p in preds], axis=0))  # geometric mean of medians
        out[f"t{k}"] = prev = np.maximum(t, np.where(prev > 0, prev + 2, 1))
        out[f"p{k}"] = np.mean([p[f"p{k}"] for p in preds], axis=0)
        out[f"c{k}"] = out[f"p{k}"].argmax(axis=1)
    return out


def forecast(path: str, artifacts: str | Path = "artifacts") -> dict:
    """Run the full tool on one conveyor file. Returns dict of DataFrames and a summary."""
    df = load_conveyor(path)
    if len(df) < 200:
        warnings.warn(f"Only {len(df)} days of history (spec guarantees >= 200); forecasting anyway.")
    art = Path(artifacts)
    fleet_tmax = json.loads((art / "climatology.json").read_text())["fleet_tmax_by_season_DJF_MAM_JJA_SON"]
    models, meta = load_models(art)
    cal = meta.get("calibration", {})
    X = features_asof(df, fleet_tmax)
    pred = ensemble_predict(models, X)
    last_day = pd.Timestamp(df["Date"].iloc[-1])
    load = str(df["Load_Class"].iloc[0])

    # Req. 2: next five failures.
    rows = []
    for k in range(1, N_NEXT + 1):
        t = float(pred[f"t{k}"][0])
        proba = pred[f"p{k}"][0]
        order = np.argsort(proba)[::-1]
        lo_q, hi_q = cal.get("t_logratio_q10_q90", {}).get(load, {}).get(str(k), [np.nan, np.nan])
        rows.append({
            "Failure #": k,
            "Expected component": COMPONENTS[order[0]],
            "P(component)": round(float(proba[order[0]]), 3),
            "Runner-up": f"{COMPONENTS[order[1]]} ({proba[order[1]]:.2f})",
            "Expected date": (last_day + pd.Timedelta(days=round(t))).date(),
            "Days from last observed day": round(t),
            "P10 date": (last_day + pd.Timedelta(days=max(1, round(t * np.exp(lo_q))))).date() if np.isfinite(lo_q) else None,
            "P90 date": (last_day + pd.Timedelta(days=round(t * np.exp(hi_q)))).date() if np.isfinite(hi_q) else None,
        })
    next5 = pd.DataFrame(rows)

    # Req. 3: 36 horizon blocks (~1 month each) over the 3 years after the last observed day.
    fb = pred["fail_blocks"][0]
    pm = nominal_pm_blocks([last_day])[0]
    start = [last_day + pd.Timedelta(days=int(BLOCK_EDGES[j]) + 1) for j in range(N_BLOCKS)]
    end = [last_day + pd.Timedelta(days=int(BLOCK_EDGES[j + 1])) for j in range(N_BLOCKS)]
    monthly = pd.DataFrame({
        "Month": np.arange(1, N_BLOCKS + 1), "From": [d.date() for d in start], "To": [d.date() for d in end],
        "Expected failures": fb.round(2),
        "Corrective downtime h": (H_PER_FAILURE * fb).round(1),
        "Planned downtime h": (H_PER_PM * pm).round(1),
    })
    monthly["Total downtime h"] = monthly["Corrective downtime h"] + monthly["Planned downtime h"]
    monthly["Cumulative downtime h"] = monthly["Total downtime h"].cumsum().round(1)
    total = float(monthly["Total downtime h"].sum())
    lo_r, hi_r = cal.get("tot_ratio_q10_q90", {}).get(load, [np.nan, np.nan])
    summary = {
        "conveyor": str(df["Conveyor_ID"].iloc[0]), "load_class": load,
        "history_days": len(df), "first_day": df["Date"].iloc[0].date(), "last_observed_day": last_day.date(),
        "forecast_to": end[-1].date(),
        "expected_failures_3y": round(float(fb.sum()), 1),
        "expected_corrective_downtime_h": round(float(monthly["Corrective downtime h"].sum()), 1),
        "expected_planned_downtime_h": round(float(monthly["Planned downtime h"].sum()), 1),
        "expected_total_downtime_h": round(total, 1),
        "total_downtime_P10_P90_h": (round(total * lo_r, 0), round(total * hi_r, 0)) if np.isfinite(lo_r) else None,
    }
    return {"next5": next5, "monthly": monthly, "summary": summary}


def plot_downtime(monthly: pd.DataFrame, title: str = ""):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 4))
    x = monthly["Month"]
    ax.bar(x, monthly["Corrective downtime h"], label="Corrective (expected)", color="#4C72B0")
    ax.bar(x, monthly["Planned downtime h"], bottom=monthly["Corrective downtime h"], label="Planned", color="#DD8452")
    ax.set_xlabel("Month after last observed day")
    ax.set_ylabel("Downtime h / month")
    ax2 = ax.twinx()
    ax2.plot(x, monthly["Cumulative downtime h"], color="black", lw=2, label="Cumulative")
    ax2.set_ylabel("Cumulative downtime h")
    ax.legend(loc="upper left")
    ax.set_title(title or "Expected downtime over the next 3 years")
    fig.tight_layout()
    return fig
