"""Future labels for training origins (training only: these look past the origin by design).

For origin row i (end of day i), with T = last observed row index:
- t{k}, e{k}: days from origin to the k-th next failure (k=1..5), event flag (0 = right-censored at T-i).
- c{k}: component code of the k-th next failure (-1 if censored).
- nx_{comp}, ex_{comp}: days to the next failure of each component, event flag.
- m{j}_fail, m{j}_dt, m{j}_pm: failures, downtime hours, PM days in horizon block j=1..36
  (block j covers days (edge[j-1], edge[j]] after the origin); NaN when the block passes T.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import HORIZON_DAYS
from .io import COMPONENTS

N_NEXT = 5
N_BLOCKS = 36
BLOCK_EDGES = np.round(np.arange(N_BLOCKS + 1) * HORIZON_DAYS / N_BLOCKS).astype(int)  # 0..1096


def _next_after(event_idx: np.ndarray, origins: np.ndarray, k: int, T: int):
    """Days to the k-th event strictly after each origin, and event flags (censored at T)."""
    j = np.searchsorted(event_idx, origins, side="right") + (k - 1)
    has = j < len(event_idx)
    padded = np.append(event_idx, T)  # censored rows index the sentinel T
    t = np.where(has, padded[np.minimum(j, len(event_idx))], T) - origins
    return t.astype(np.float32), has.astype(np.int8), np.where(has, j, -1)


def labels_for(df: pd.DataFrame, origins: np.ndarray) -> pd.DataFrame:
    T = len(df) - 1
    st = df["Daily_State"].to_numpy()
    ft = df["Failure_Type"].fillna("").to_numpy()
    fail_idx = np.flatnonzero(st == "FAILURE_DAY")
    comp_code = pd.Series(ft[fail_idx]).map({c: k for k, c in enumerate(COMPONENTS)}).fillna(-1).to_numpy()
    out = {"Conveyor_ID": df["Conveyor_ID"].iloc[0], "Date": df["Date"].to_numpy()[origins]}

    for k in range(1, N_NEXT + 1):
        t, e, j = _next_after(fail_idx, origins, k, T)
        out[f"t{k}"], out[f"e{k}"] = t, e
        out[f"c{k}"] = np.append(comp_code, -1)[np.where(j >= 0, j, len(comp_code))].astype(np.int8)
    for comp in COMPONENTS:
        idx = fail_idx[ft[fail_idx] == comp]
        t, e, _ = _next_after(idx, origins, 1, T)
        out[f"nx_{comp.lower()}"], out[f"ex_{comp.lower()}"] = t, e

    cs_fail = np.concatenate([[0], np.cumsum(st == "FAILURE_DAY")])
    cs_dt = np.concatenate([[0.0], np.cumsum(df["Downtime_Hours_Day"].fillna(0).to_numpy(dtype=float))])
    cs_pm = np.concatenate([[0], np.cumsum(st == "PLANNED_MAINTENANCE")])

    def block(cs, a, b):  # sum over days (origin+a, origin+b]; NaN if past the last row
        hi = origins + b
        ok = hi <= T
        v = cs[np.minimum(hi, T) + 1] - cs[np.minimum(origins + a, T) + 1]
        return np.where(ok, v, np.nan).astype(np.float32)

    for jb in range(1, N_BLOCKS + 1):
        a, b = BLOCK_EDGES[jb - 1], BLOCK_EDGES[jb]
        out[f"m{jb}_fail"] = block(cs_fail, a, b)
        out[f"m{jb}_dt"] = block(cs_dt, a, b)
        out[f"m{jb}_pm"] = block(cs_pm, a, b)
    out["tot_fail"] = block(cs_fail, 0, HORIZON_DAYS)
    out["tot_dt"] = block(cs_dt, 0, HORIZON_DAYS)
    out["days_observed_after"] = (T - origins).astype(np.int32)
    return pd.DataFrame(out)
