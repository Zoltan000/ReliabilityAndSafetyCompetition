"""Req. 1 reliability analysis on the fleet file. Prints compact tables; writes CSV/PNG to outputs/req1/.

A. Weibull (renewal intervals, right-censored) per component x exposure clock, load class as AFT covariate:
   common beta, eta per load class. The natural clock is the one where load explains least (ratio -> 1).
B. Renewal-number trend (imperfect repair): mean interval by renewal index (bearings per position, belts).
C. Season effect: failure rate per at-risk day by season (2006+, steady state), per component.
D. Daily-noise effect: failure rate vs same-day residual of temperature / humidity / voltage (within plant).
E. Condition-monitoring precursors: z-scored signals in the 30 days before each failure type vs baseline.

Run from the repo root: .venv/Scripts/python scripts/02_reliability_analysis.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import WeibullAFTFitter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conveyor.evaluate import sealed_conveyors  # noqa: E402
from conveyor.io import COMPONENTS, load_fleet, season_of  # noqa: E402

warnings.filterwarnings("ignore")
FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
OUT = Path("outputs/req1")
CLOCKS = {"days": "day_idx", "op_h": "Cumulative_Operating_Hours", "cycles": "Cumulative_Start_Stop_Cycles",
          "kg": "Cumulative_kg"}
pd.set_option("display.width", 220)


def intervals(f: pd.DataFrame, comp: str) -> pd.DataFrame:
    """Renewal intervals per unit (conveyor, or conveyor x bearing position) in every clock; last one censored."""
    ev = f[(f.Daily_State == "FAILURE_DAY") & (f.Failure_Type == comp)]
    unit = ["Conveyor_ID"] + (["Failed_Component_ID"] if comp == "Bearing" else [])
    end = f.groupby("Conveyor_ID").tail(1)
    load = f.groupby("Conveyor_ID")["Load_Class"].first()
    if comp == "Bearing":  # every position is a unit, even if it never failed
        units = f.groupby("Conveyor_ID")["Bearing_Count"].first()
        allu = pd.DataFrame([(c, f"BRG_{b:03d}") for c, n in units.items() for b in range(1, n + 1)], columns=unit)
    else:
        allu = pd.DataFrame({"Conveyor_ID": load.index})
    rows = []
    ev = ev.sort_values(unit + ["Date"])
    endv = end.set_index("Conveyor_ID")
    grp = {(k if isinstance(k, tuple) else (k,)): g for k, g in ev.groupby(unit)}
    for key in allu.itertuples(index=False):
        g = grp.get(tuple(key))
        cid = key[0]
        pts = {c: [0.0] for c in CLOCKS}
        if g is not None:
            for c, col in CLOCKS.items():
                pts[c] += list(g[col].to_numpy(dtype=float))
        for c, col in CLOCKS.items():
            pts[c].append(float(endv.loc[cid, col]))
        m = len(pts["days"]) - 1
        for r in range(m):
            rows.append({"cid": cid, "load": load[cid], "renewal": r, "event": int(r < m - 1),
                         **{c: pts[c][r + 1] - pts[c][r] for c in CLOCKS}})
    return pd.DataFrame(rows)


def weibull_by_clock(iv: pd.DataFrame) -> list[dict]:
    out = []
    d = pd.get_dummies(iv["load"])[[c for c in ["Medium", "Heavy"] if c in iv["load"].unique()]].astype(float)
    for c in CLOCKS:
        df = pd.concat([iv[[c, "event"]].rename(columns={c: "T"}), d], axis=1)
        df = df[df["T"] > 0]
        if df.event.sum() < 5 or df["T"].nunique() < 5:
            continue
        try:
            m = WeibullAFTFitter().fit(df, "T", "event")
        except Exception:
            continue
        beta = float(np.exp(m.params_.loc[("rho_", "Intercept")]))
        lam = m.params_.loc["lambda_"]
        eta_l = float(np.exp(lam["Intercept"]))
        row = {"clock": c, "n_ev": int(df.event.sum()), "beta": round(beta, 2), "eta_Light": round(eta_l, 1)}
        for lc in ["Medium", "Heavy"]:
            if lc in lam.index:
                row[f"eta_{lc}/Light"] = round(float(np.exp(lam[lc])), 3)
        ci = m.confidence_intervals_.loc[("rho_", "Intercept")]
        row["beta_95ci"] = f"{np.exp(ci.iloc[0]):.2f}-{np.exp(ci.iloc[1]):.2f}"
        out.append(row)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    f = load_fleet(FLEET)
    f["day_idx"] = f.groupby("Conveyor_ID").cumcount().astype(float)
    at_risk = f.Daily_State.isin(["RUNNING", "FAILURE_DAY"])
    fail = f.Daily_State == "FAILURE_DAY"

    print("## A. Weibull renewal fits: beta (common), eta for Light, eta ratio vs Light, per clock")
    allrows = []
    for comp in COMPONENTS:
        iv = intervals(f, comp)
        iv.to_parquet(OUT / f"intervals_{comp}.parquet", index=False)
        first = iv[iv.renewal == 0]
        later = iv[iv.renewal > 0]
        for label, sub in [("all", iv), ("first", first), ("renewed", later)]:
            if comp in ("Contactor",) and label != "all":
                continue
            for r in weibull_by_clock(sub):
                allrows.append({"component": comp, "intervals": label, **r})
    wt = pd.DataFrame(allrows)
    wt.to_csv(OUT / "weibull_by_clock.csv", index=False)
    print(wt[wt.intervals == "all"].drop(columns="intervals").to_string(index=False))
    print("\n(first life vs renewed, op_h clock)")
    print(wt[(wt.clock == "op_h") & (wt.intervals != "all")][["component", "intervals", "n_ev", "beta", "eta_Light"]].to_string(index=False))

    print("\n## A2. Bearing Weibull (op_h, all intervals), sealed conveyors excluded -> ML constants for features.py")
    print("(the fleet-wide table above is for Req. 1 reporting only; the model's own hard-coded BRG_BETA/BRG_ETA_OH")
    print(" must never see the sealed holdout, so they are fit separately here)")
    conv_plant = f.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    iv_brg_ml = pd.read_parquet(OUT / "intervals_Bearing.parquet")
    iv_brg_ml = iv_brg_ml[~iv_brg_ml.cid.isin(sealed)]
    ml_rows = [{"component": "Bearing", "intervals": "all_ex_sealed", **r}
               for r in weibull_by_clock(iv_brg_ml) if r["clock"] == "op_h"]
    ml = pd.DataFrame(ml_rows)
    ml.to_csv(OUT / "weibull_bearing_ml_constants.csv", index=False)
    print(f"({len(sealed)} sealed conveyors excluded)")
    print(ml.to_string(index=False))

    print("\n## B. Mean interval (op h) by renewal index (imperfect repair?)")
    for comp in ["Bearing", "Conveyor_Belt", "Motor_Reducer"]:
        iv = pd.read_parquet(OUT / f"intervals_{comp}.parquet")
        t = iv[iv.event == 1].groupby(["load", np.minimum(iv.renewal, 8)])["op_h"].mean().unstack().round(0)
        print(f"{comp}:\n{t.to_string()}")

    print("\n## C. Failure rate per 1000 at-risk days by season (2006+), ratio to component mean")
    s = f[at_risk & (f.Date >= "2006-01-01")].copy()
    s["season"] = np.array(["DJF", "MAM", "JJA", "SON"])[season_of(s.Date)]
    days = s.groupby(["Load_Class", "season"]).size()
    rows = []
    for comp in COMPONENTS[:-1]:
        cnt = s[s.Failure_Type == comp].groupby(["Load_Class", "season"]).size().reindex(days.index, fill_value=0)
        rate = cnt / days
        rel = (rate / rate.groupby(level=0).transform("mean")).unstack()[["DJF", "MAM", "JJA", "SON"]]
        rel["n"] = cnt.groupby(level=0).sum()
        rel.insert(0, "component", comp)
        rows.append(rel.reset_index())
    ct = pd.concat(rows).round(3)
    ct.to_csv(OUT / "season_effect.csv", index=False)
    print(ct.to_string(index=False))

    print("\n## D. Same-day weather/voltage noise: failure-rate ratio, top vs bottom quintile of residual (within plant x season)")
    s = f[at_risk].copy()
    s["season"] = season_of(s.Date)
    for col in ["Temperature_Max_C", "Humidity_pct", "Voltage_V"]:
        s["res"] = s[col] - s.groupby(["Plant_ID", "season"])[col].transform("mean")
        s["q"] = pd.qcut(s["res"], 5, labels=False)
        out = {}
        for comp in ["Bearing", "Conveyor_Belt", "Motor_Reducer", "Speed_Sensor", "Controller_PC", "Control_Software"]:
            r = (s.Failure_Type == comp).groupby(s.q).mean()
            out[comp] = round(float(r.iloc[-1] / r.iloc[0]), 3) if r.iloc[0] > 0 else np.nan
        print(f"{col:18s}", out)

    print("\n## E. CM precursors: mean within-conveyor z-score in days -30..-1 before failure (baseline -120..-61)")
    sig = {"vib": f.Structure_Vibration_RMS_mm_s,
           "cur_per_tp": f.Motor_Current_A / f.Throughput_kg_per_h,
           "vdrop_per_cur": f.Contact_Voltage_Drop_mV / f.Motor_Current_A,
           "mtemp_excess": f.Motor_Temperature_C - f.Temperature_Max_C,
           "closing_ms": f.Contactor_Closing_Time_ms}
    z = pd.DataFrame({k: (v - v.groupby(f.Conveyor_ID).transform("mean")) / v.groupby(f.Conveyor_ID).transform("std")
                      for k, v in sig.items()})
    z["cid"] = f.Conveyor_ID.to_numpy()
    idx = np.flatnonzero(fail.to_numpy())
    rows = []
    for comp in COMPONENTS:
        ids = idx[f.Failure_Type.to_numpy()[idx] == comp]
        ids = ids[f.day_idx.to_numpy()[ids] >= 120]
        if len(ids) > 3000:
            ids = np.random.default_rng(0).choice(ids, 3000, replace=False)
        pre = np.concatenate([ids - d for d in range(1, 31)])
        base = np.concatenate([ids - d for d in range(61, 121)])
        r = {"component": comp, "n": len(ids)}
        for k in sig:
            r[k] = round(float(np.nanmean(z[k].to_numpy()[pre]) - np.nanmean(z[k].to_numpy()[base])), 3)
        rows.append(r)
    cm = pd.DataFrame(rows)
    cm.to_csv(OUT / "cm_precursors.csv", index=False)
    print(cm.to_string(index=False))

    print("\n## F. Speed-sensor spike years: does time since last install/replacement explain them?")
    print("(all conveyors share EIS_Date 2005-01-01, so a fleet-wide age cohort shows up as a calendar-year spike)")
    SPIKE_YEARS = {2010, 2012, 2016, 2019, 2022}
    sr_date = f["Date"].where(f["Sensor_Replacement"].fillna(0).to_numpy() == 1)
    last_repl_before = sr_date.groupby(f["Conveyor_ID"]).transform(lambda s: s.ffill().shift(1))
    last_install = last_repl_before.fillna(pd.Series(pd.to_datetime(f["EIS_Date"]).to_numpy(), index=f.index))
    years_since = (f["Date"] - last_install).dt.days / 365.25
    ss_mask = (f.Daily_State == "FAILURE_DAY") & (f.Failure_Type == "Speed_Sensor")
    ss = pd.DataFrame({"Conveyor_ID": f.Conveyor_ID[ss_mask].to_numpy(),
                        "year": f.Date[ss_mask].dt.year.to_numpy(),
                        "years_since_last_install": years_since[ss_mask].to_numpy()})
    ss["is_spike_year"] = ss["year"].isin(SPIKE_YEARS)
    ss.to_csv(OUT / "speed_sensor_spikes.csv", index=False)
    print(ss.groupby("is_spike_year")["years_since_last_install"].agg(["count", "mean", "median", "std"]).round(2).to_string())
    hist = ss["years_since_last_install"].round().value_counts().sort_index()
    print("\nfailures by whole years since last install/replacement:")
    print(hist.to_string())

    print("\n## G. Bad-actor conveyors: does a conveyor's own excess failure rate persist across time?")
    print("(each conveyor's history split in half; relative-to-load-class-peers rate in half 1 vs half 2)")
    n_days = f.groupby("Conveyor_ID")["Conveyor_ID"].transform("size")
    half = np.where(f["day_idx"].to_numpy() < (n_days.to_numpy() // 2), 1, 2)
    g = pd.DataFrame({"cid": f.Conveyor_ID.to_numpy(), "load": f.Load_Class.to_numpy(), "half": half,
                       "at_risk": at_risk.to_numpy(), "fail": fail.to_numpy()})
    rate = g.groupby(["cid", "load", "half"], as_index=False).agg(at_risk_days=("at_risk", "sum"), fails=("fail", "sum"))
    rate["rate"] = rate["fails"] / rate["at_risk_days"].replace(0, np.nan)
    rate["rel_rate"] = rate["rate"] / rate.groupby(["load", "half"])["rate"].transform("mean")
    piv = rate.pivot(index=["cid", "load"], columns="half", values="rel_rate").reset_index()
    piv.columns = ["cid", "load", "rel_rate_h1", "rel_rate_h2"]
    piv.to_csv(OUT / "frailty_check.csv", index=False)
    corr_overall = piv[["rel_rate_h1", "rel_rate_h2"]].corr().iloc[0, 1]
    print(f"correlation of relative failure rate, first half vs second half of history: overall r={corr_overall:.3f}")
    print(piv.groupby("load").apply(lambda d: d["rel_rate_h1"].corr(d["rel_rate_h2"])).round(3).rename("r_by_load").to_string())


if __name__ == "__main__":
    main()
