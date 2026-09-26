"""Load and validate one conveyor's (or the fleet's) daily history."""
from __future__ import annotations

import numpy as np
import pandas as pd

COMPONENTS = ["Bearing", "Conveyor_Belt", "Motor_Reducer", "Speed_Sensor",
              "Controller_PC", "Control_Software", "Contactor"]
STATES = ["RUNNING", "FAILURE_DAY", "CORRECTIVE_DOWNTIME", "PLANNED_MAINTENANCE"]
REQUIRED = ["Date", "Conveyor_ID", "Plant_ID", "Daily_State", "Failure_Type", "Failed_Component_ID",
            "Age_Calendar_Days", "Bearing_Count", "Cumulative_Operating_Hours", "Cumulative_kg",
            "Cumulative_Start_Stop_Cycles", "Downtime_Hours_Day"]
STATIC = ["Plant_ID", "Conveyor_ID", "EIS_Date", "Length_m", "Bearing_Count", "Load_Class",
          "Rated_Throughput_kg_h", "Belt_Speed_m_s", "Roller_Diameter_mm"]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Validate one conveyor's rows: parse dates, sort, dedupe, and fill missing calendar days.

    Uses every row supplied; the last observed day is simply the max Date.
    """
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Input is missing required columns: {missing}")
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    if df["Conveyor_ID"].nunique() != 1:
        raise ValueError("Input must contain exactly one conveyor")
    df = df.sort_values("Date").drop_duplicates("Date", keep="last").reset_index(drop=True)
    full = pd.date_range(df["Date"].iloc[0], df["Date"].iloc[-1], freq="D")
    if len(full) != len(df):  # calendar gaps: reindex, carry static/cumulative fields forward
        df = df.set_index("Date").reindex(full).rename_axis("Date").reset_index()
        ffill_cols = STATIC + ["Cumulative_Operating_Hours", "Cumulative_kg",
                               "Cumulative_Start_Stop_Cycles", "Cumulative_Failure_Count"]
        df[ffill_cols] = df[ffill_cols].ffill()
        df["Daily_State"] = df["Daily_State"].fillna("RUNNING")
        df["Age_Calendar_Days"] = (df["Date"] - pd.to_datetime(df["EIS_Date"])).dt.days
    return df


def load_conveyor(path: str) -> pd.DataFrame:
    return clean(pd.read_parquet(path))


def load_fleet(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    return df.sort_values(["Conveyor_ID", "Date"]).reset_index(drop=True)


def iter_conveyors(fleet: pd.DataFrame):
    """Yield (conveyor_id, cleaned frame) for each conveyor in a fleet frame."""
    for cid, g in fleet.groupby("Conveyor_ID", sort=True):
        yield cid, clean(g)


def season_of(dates) -> np.ndarray:
    """Meteorological season index: 0=DJF, 1=MAM, 2=JJA, 3=SON (steps fall on the 1st of Mar/Jun/Sep/Dec)."""
    m = pd.DatetimeIndex(dates).month.to_numpy()
    return ((m % 12) // 3).astype(np.int8)
