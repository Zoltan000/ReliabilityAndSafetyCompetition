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

# Expert rule (fleet observation): speed sensors have a hard design-life ceiling on the operating-hours clock.
# Fleet max life is 50,016 op-h and 158 of 1,838 lives end in 49,980-50,016 (50,000 +/- one half-day).
# Grouped-CV check on held-out conveyors: when the ceiling is < 30 days away, a speed-sensor failure follows
# with probability 0.93 and the date error is within +/-2 days (P10/P90); 30-90 days away: 0.65; further: 0.44.
SS_CEILING_OH = 50_000.0
SS_RULE_CONFIDENCE = [(30, 0.93), (90, 0.65), (np.inf, 0.44)]  # (days-to-ceiling upper bound, P(failure there))


def speed_sensor_ceiling_days(X: pd.DataFrame) -> np.ndarray:
    """Days from the origin until the speed sensor reaches SS_CEILING_OH, at the conveyor's average op-h per day."""
    oh_per_day = X["cum_oh"].to_numpy(dtype=float) / (X["age_days"].to_numpy(dtype=float) + 1)
    return np.ceil((SS_CEILING_OH - X["speed_sensor_since_oh"].to_numpy(dtype=float)) / np.maximum(oh_per_day, 1.0))


def apply_expert_rules(pred: dict, X: pd.DataFrame) -> dict:
    """Insert a rule-based Speed_Sensor failure into the next-5 sequence when its ceiling date comes first.

    Later ML failures shift back one slot (and 2 days: the failure day + corrective day). Adds `rule{k}` flags.
    """
    ss = COMPONENTS.index("Speed_Sensor")
    out = {k: np.array(v, copy=True) for k, v in pred.items()}
    T = np.column_stack([out[f"t{k}"] for k in range(1, N_NEXT + 1)]).astype(float)
    P = np.stack([out[f"p{k}"] for k in range(1, N_NEXT + 1)], axis=1)
    R = np.zeros(T.shape, dtype=bool)
    dc = speed_sensor_ceiling_days(X)
    for i in np.flatnonzero((dc >= 1) & (dc < T[:, -1])):
        j = int(np.searchsorted(T[i], dc[i]))
        P[i, :, ss] = 0.0  # the rule now owns the sensor failure; a renewed sensor won't fail again this soon
        P[i] /= P[i].sum(axis=1, keepdims=True)
        conf = next(c for ub, c in SS_RULE_CONFIDENCE if dc[i] < ub)
        p_rule = np.full(P.shape[2], (1 - conf) / (P.shape[2] - 1))
        p_rule[ss] = conf
        T[i] = np.concatenate([T[i, :j], [dc[i]], T[i, j:-1] + 2])
        P[i] = np.concatenate([P[i, :j], p_rule[None], P[i, j:-1]])
        R[i] = np.concatenate([R[i, :j], [True], R[i, j:-1]])
    for k in range(N_NEXT):
        out[f"t{k+1}"], out[f"p{k+1}"], out[f"rule{k+1}"] = T[:, k], P[:, k], R[:, k]
        out[f"c{k+1}"] = P[:, k].argmax(axis=1)
    return out


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
    pred = apply_expert_rules(ensemble_predict(models, X), X)
    last_day = pd.Timestamp(df["Date"].iloc[-1])
    load = str(df["Load_Class"].iloc[0])

    # Req. 2: next five failures.
    rows = []
    n_ml = 0
    for k in range(1, N_NEXT + 1):
        t = float(pred[f"t{k}"][0])
        proba = pred[f"p{k}"][0]
        order = np.argsort(proba)[::-1]
        if pred[f"rule{k}"][0]:
            source = "Rule: speed-sensor 50,000 op-h design-life ceiling"
            lo_d, hi_d = max(1, round(t - max(2.0, 0.3 * t))), round(t + 3)
        else:
            n_ml += 1  # ML slot n_ml keeps the calibration of the model that predicted it
            source = "ML model"
            lo_q, hi_q = cal.get("t_logratio_q10_q90", {}).get(load, {}).get(str(n_ml), [np.nan, np.nan])
            lo_d = max(1, round(t * np.exp(lo_q))) if np.isfinite(lo_q) else None
            hi_d = round(t * np.exp(hi_q)) if np.isfinite(hi_q) else None
        rows.append({
            "Failure #": k,
            "Expected component": COMPONENTS[order[0]],
            "P(component)": round(float(proba[order[0]]), 3),
            "Runner-up": f"{COMPONENTS[order[1]]} ({proba[order[1]]:.2f})",
            "Expected date": (last_day + pd.Timedelta(days=round(t))).date(),
            "Days from last observed day": round(t),
            "P10 date": (last_day + pd.Timedelta(days=lo_d)).date() if lo_d is not None else None,
            "P90 date": (last_day + pd.Timedelta(days=hi_d)).date() if hi_d is not None else None,
            "Source": source,
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
        "speed_sensor_days_to_50k_oh_ceiling": int(speed_sensor_ceiling_days(X)[0]),
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
