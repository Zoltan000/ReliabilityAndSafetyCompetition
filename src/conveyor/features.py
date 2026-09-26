"""As-of-origin features, identical for training (every origin day) and inference (last observed day).

Every feature on day i uses only rows 0..i of the conveyor's own history, plus the fixed
fleet climatology profile (4 seasonal temperature levels). Future weather is replaced by its
known expectation: the conveyor's own per-season temperature levels applied to the future calendar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .io import COMPONENTS, STATES, season_of

PM_MONTH_DAYS = [(3, 15), (7, 15), (12, 15)]
# Weibull fit of bearing-position renewal intervals on the operating-hour clock, EXCLUDING the sealed
# holdout conveyors (scripts/02_reliability_analysis.py §A2 -> outputs/req1/weibull_bearing_ml_constants.csv):
# common beta, eta by load class. Must stay fit on non-sealed conveyors only; see evaluate.sealed_conveyors.
BRG_BETA = 2.97
BRG_ETA_OH = {0: 45885.6, 1: 45885.6 * 0.162, 2: 45885.6 * 0.079}  # Light, Medium, Heavy
HORIZON_DAYS = 1096  # 3 years
CM_SIGNALS = ["vib", "cur_per_tp", "vdrop_per_cur", "mtemp_excess"]


def _last_idx(mask: np.ndarray) -> np.ndarray:
    """Index of the most recent True at or before each position, or -1."""
    return np.maximum.accumulate(np.where(mask, np.arange(len(mask)), -1))


def _roll_sum(x: np.ndarray, w: int) -> np.ndarray:
    cs = np.concatenate([[0.0], np.cumsum(x, dtype=np.float64)])
    i = np.arange(1, len(x) + 1)
    return cs[i] - cs[np.maximum(i - w, 0)]


def _roll_mean_nan(x: np.ndarray, w: int) -> np.ndarray:
    ok = ~np.isnan(x)
    s, c = _roll_sum(np.where(ok, x, 0.0), w), _roll_sum(ok.astype(float), w)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(c > 0, s / c, np.nan)


def _since(ref: np.ndarray, last: np.ndarray, never_value: np.ndarray) -> np.ndarray:
    return np.where(last >= 0, ref - ref[np.maximum(last, 0)], never_value)


def days_to_next_pm(dates: pd.DatetimeIndex) -> np.ndarray:
    years = dates.year.to_numpy()
    day0 = dates.to_numpy().astype("datetime64[D]")
    best = np.full(len(dates), 10_000, dtype=np.int64)
    for dy in (0, 1):
        for m, d in PM_MONTH_DAYS:
            cand = (years + dy - 1970).astype("datetime64[Y]").astype("datetime64[M]") + (m - 1)
            diff = (cand.astype("datetime64[D]") + (d - 1) - day0).astype(np.int64)
            best = np.where((diff >= 1) & (diff < best), diff, best)
    return best


def season_day_counts(start: pd.Timestamp, n_days: int) -> np.ndarray:
    """Cumulative count of days per season from `start`: shape (n_days + 1, 4)."""
    seas = season_of(pd.date_range(start, periods=n_days, freq="D"))
    onehot = np.zeros((n_days, 4))
    onehot[np.arange(n_days), seas] = 1
    return np.vstack([np.zeros(4), np.cumsum(onehot, axis=0)])


def daily_features(df: pd.DataFrame, fleet_tmax: list[float]) -> pd.DataFrame:
    """Features for every day of one cleaned conveyor frame (row i = state at end of day i)."""
    n = len(df)
    i = np.arange(n)
    dates = pd.DatetimeIndex(df["Date"])
    st = df["Daily_State"].to_numpy()
    ft = df["Failure_Type"].fillna("").to_numpy()
    fail = st == "FAILURE_DAY"
    at_risk = (st == "RUNNING") | fail
    age = df["Age_Calendar_Days"].to_numpy(dtype=float)
    cum_oh = df["Cumulative_Operating_Hours"].to_numpy(dtype=float)
    cum_cyc = df["Cumulative_Start_Stop_Cycles"].to_numpy(dtype=float)
    cum_kg = df["Cumulative_kg"].to_numpy(dtype=float)
    f: dict[str, np.ndarray] = {}

    # Static attributes (Plant_ID deliberately excluded: the model must generalise to unseen plants).
    f["load_class"] = df["Load_Class"].map({"Light": 0, "Medium": 1, "Heavy": 2}).to_numpy(dtype=float)
    for c in ["Length_m", "Bearing_Count", "Rated_Throughput_kg_h", "Belt_Speed_m_s", "Roller_Diameter_mm"]:
        f[c] = df[c].to_numpy(dtype=float)

    # Age and exposure.
    f["age_days"], f["cum_oh"], f["cum_cycles"], f["cum_kg"] = age, cum_oh, cum_cyc, cum_kg
    f["availability_all"] = np.cumsum(at_risk) / (i + 1)

    # Overall failure history and recent rates per at-risk day.
    risk_cs = np.cumsum(at_risk)
    f["n_fail_all"] = np.cumsum(fail).astype(float)
    f["rate_all"] = f["n_fail_all"] / np.maximum(risk_cs, 1)
    for w in (30, 90, 365):
        f[f"rate_{w}"] = _roll_sum(fail, w) / np.maximum(_roll_sum(at_risk, w), 1)
    last_fail = _last_idx(fail)
    f["days_since_fail"] = np.where(last_fail >= 0, i - last_fail, age)

    # Per-component clocks since last failure (never failed -> clock since EIS, flagged).
    for comp in COMPONENTS:
        m = fail & (ft == comp)
        last = _last_idx(m)
        k = comp.lower()
        f[f"{k}_n"] = np.cumsum(m).astype(float)
        f[f"{k}_never"] = (last < 0).astype(float)
        f[f"{k}_since_days"] = np.where(last >= 0, i - last, age)
        f[f"{k}_since_oh"] = _since(cum_oh, last, cum_oh)
        f[f"{k}_since_cyc"] = _since(cum_cyc, last, cum_cyc)
        f[f"{k}_since_kg"] = _since(cum_kg, last, cum_kg)
        f[f"{k}_rate_365"] = _roll_sum(m, 365) / np.maximum(_roll_sum(at_risk, 365), 1)
        f[f"{k}_rate_all"] = f[f"{k}_n"] / np.maximum(risk_cs, 1)

    # Bearing population: per-position age in operating hours since its last renewal.
    B = int(df["Bearing_Count"].iloc[0])
    last_b = np.full((n, B), -1, dtype=np.int64)
    ids = df["Failed_Component_ID"].fillna("").to_numpy()
    bmask = fail & (ft == "Bearing") & (pd.Series(ids).str.startswith("BRG_").to_numpy())
    rows = np.flatnonzero(bmask)
    pos = np.array([int(s[4:]) - 1 for s in ids[rows]], dtype=np.int64)
    keep = (pos >= 0) & (pos < B)
    last_b[rows[keep], pos[keep]] = rows[keep]
    last_b = np.maximum.accumulate(last_b, axis=0)
    age_oh = np.where(last_b >= 0, cum_oh[:, None] - cum_oh[np.maximum(last_b, 0)], cum_oh[:, None])
    f["brg_never"] = (last_b < 0).sum(axis=1).astype(float)
    f["brg_age_mean"] = age_oh.mean(axis=1)
    for q in (0, 25, 50, 75, 90, 100):
        f[f"brg_age_p{q}"] = np.percentile(age_oh, q, axis=1)
    f["brg_age_std"] = age_oh.std(axis=1)
    # Expected bearing failures over the next d days: sum over positions of the Weibull cumulative-hazard
    # increment (first failure per position), at the conveyor's recent operating hours per day.
    eta = BRG_ETA_OH.get(int(np.nan_to_num(f["load_class"][0], nan=1)), BRG_ETA_OH[1])
    oh_per_day = np.maximum(_roll_sum(np.diff(cum_oh, prepend=cum_oh[0]), 90) / np.minimum(i + 1, 90), 1.0)
    h_now = (age_oh / eta) ** BRG_BETA
    for d in (7, 30, 90, 365):
        dh = (oh_per_day * d)[:, None]
        f[f"brg_whaz_next{d}"] = (((age_oh + dh) / eta) ** BRG_BETA - h_now).sum(axis=1)

    # Restart / state at origin / planned maintenance / calendar.
    down = ~at_risk
    f["days_since_restart"] = np.where(_last_idx(down) >= 0, i - _last_idx(down), age)
    f["state_code"] = pd.Series(st).map({s: k for k, s in enumerate(STATES)}).to_numpy(dtype=float)
    pm = st == "PLANNED_MAINTENANCE"
    f["days_since_pm"] = np.where(_last_idx(pm) >= 0, i - _last_idx(pm), age)
    f["days_to_next_pm"] = days_to_next_pm(dates).astype(float)
    f["doy"] = dates.dayofyear.to_numpy(dtype=float)
    f["season"] = season_of(dates).astype(float)

    # Climatology: own per-season temperature levels (expanding mean), humidity and voltage levels.
    seas = season_of(dates)
    tmax = df["Temperature_Max_C"].to_numpy(dtype=float)
    ok = ~np.isnan(tmax)
    levels = np.empty((n, 4))
    for s in range(4):
        m = ok & (seas == s)
        num, den = np.cumsum(np.where(m, tmax, 0.0)), np.cumsum(m)
        with np.errstate(invalid="ignore", divide="ignore"):
            levels[:, s] = np.where(den > 0, num / den, np.nan)
    resid = np.where(ok, tmax - np.asarray(fleet_tmax)[seas], 0.0)
    offset = np.cumsum(resid) / np.maximum(np.cumsum(ok), 1)
    for s in range(4):  # unseen season so far: fleet level + this conveyor's mean offset
        levels[:, s] = np.where(np.isnan(levels[:, s]), fleet_tmax[s] + offset, levels[:, s])
        f[f"temp_level_s{s}"] = levels[:, s]
    f["temp_offset"] = offset
    cal = season_day_counts(dates[0], n + HORIZON_DAYS + 2)
    for w in (30, 90, 365):
        counts = cal[i + w + 1] - cal[i + 1]
        f[f"temp_exp_next{w}"] = (counts * levels).sum(axis=1) / w
    for col, name in [("Humidity_pct", "humidity_level"), ("Voltage_V", "voltage_level")]:
        x = df[col].to_numpy(dtype=float)
        okx = ~np.isnan(x)
        f[name] = np.cumsum(np.where(okx, x, 0.0)) / np.maximum(np.cumsum(okx), 1)

    # Condition monitoring at origin: 7/30-day means over operating days, and 30-day change.
    tp = df["Throughput_kg_per_h"].to_numpy(dtype=float)
    cur = df["Motor_Current_A"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        cm = {
            "vib": df["Structure_Vibration_RMS_mm_s"].to_numpy(dtype=float),
            "cur_per_tp": cur / tp * 1000.0,
            "vdrop_per_cur": df["Contact_Voltage_Drop_mV"].to_numpy(dtype=float) / cur,
            "mtemp_excess": df["Motor_Temperature_C"].to_numpy(dtype=float) - tmax,
        }
    for k, x in cm.items():
        m7, m30 = _roll_mean_nan(x, 7), _roll_mean_nan(x, 30)
        f[f"cm_{k}_7"], f[f"cm_{k}_30"] = m7, m30
        f[f"cm_{k}_d30"] = m30 - np.concatenate([np.full(30, np.nan), m30[:-30]])
    close = df["Contactor_Closing_Time_ms"].to_numpy(dtype=float)
    cs = pd.Series(close).dropna().rolling(5, min_periods=1).mean()
    f["cm_closing_last5"] = pd.Series(np.nan, index=range(n)).fillna(cs).ffill().to_numpy()
    f["tp_90"] = _roll_mean_nan(tp, 90)

    out = pd.DataFrame(f).astype(np.float32)
    out.insert(0, "Date", dates)
    out.insert(0, "Conveyor_ID", df["Conveyor_ID"].iloc[0])
    out.insert(2, "Plant_ID", df["Plant_ID"].iloc[0])
    return out


def features_asof(df: pd.DataFrame, fleet_tmax: list[float]) -> pd.DataFrame:
    """Features at the last observed day (the forecast origin)."""
    return daily_features(df, fleet_tmax).iloc[[-1]].reset_index(drop=True)
