"""Grouped folds, known-future helpers and conveyor-weighted metrics for Req. 2 and Req. 3."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from .features import PM_MONTH_DAYS
from .labels import BLOCK_EDGES, N_BLOCKS, N_NEXT

SEALED_FRACTION = 0.15
ALWAYS_SEALED = ["P02CV27"]  # example conveyor: keeps the example-file demo leak-free


def sealed_conveyors(conv_plant: pd.Series, seed: int = 0) -> list[str]:
    """~15% of conveyors per plant, fixed forever (touched once, at the very end)."""
    rng = np.random.default_rng(seed)
    out = []
    for _, ids in conv_plant.groupby(conv_plant).groups.items():
        forced = [i for i in ALWAYS_SEALED if i in ids]
        rest = sorted(set(ids) - set(forced))
        k = max(1, round(SEALED_FRACTION * len(ids))) - len(forced)
        out += forced + list(rng.choice(rest, size=max(k, 0), replace=False))
    return sorted(out)


def cv_folds(conv_plant: pd.Series, n_splits: int = 5, seed: int = 0) -> list[tuple[list[str], list[str]]]:
    """(train_ids, test_ids) per fold over non-sealed conveyors; test folds are whole conveyors, stratified by plant."""
    ids = conv_plant.index.to_numpy()
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    return [(list(ids[tr]), list(ids[te])) for tr, te in sgkf.split(ids, conv_plant.to_numpy(), groups=ids)]


def nominal_pm_blocks(origin_dates) -> np.ndarray:
    """Count of nominal PM dates (03-15, 07-15, 12-15) in each horizon block after each origin: (n, 36)."""
    d0 = pd.DatetimeIndex(origin_dates).to_numpy().astype("datetime64[D]")
    years = pd.DatetimeIndex(origin_dates).year.to_numpy()
    out = np.zeros((len(d0), N_BLOCKS), dtype=np.float32)
    for dy in range(0, 5):
        for m, d in PM_MONTH_DAYS:
            pm = (years + dy - 1970).astype("datetime64[Y]").astype("datetime64[M]") + (m - 1)
            off = (pm.astype("datetime64[D]") + (d - 1) - d0).astype(np.int64)
            blk = np.searchsorted(BLOCK_EDGES, off, side="left") - 1  # off in (edge[b], edge[b+1]]
            ok = (off >= 1) & (off <= BLOCK_EDGES[-1])
            np.add.at(out, (np.flatnonzero(ok), blk[ok]), 1)
    return out


def _conv_mean(values: np.ndarray, conv: np.ndarray, mask: np.ndarray) -> float:
    """Average per conveyor first, then across conveyors (so Heavy conveyors don't dominate)."""
    if mask.sum() == 0:
        return float("nan")
    s = pd.Series(values[mask]).groupby(conv[mask]).mean()
    return float(s.mean())


def score(pred: dict, Y: pd.DataFrame) -> dict:
    """pred keys: t1..t5 (days, point), c1..c5 (component code), fail_blocks (n,36), pm_blocks (n,36)."""
    conv = Y["Conveyor_ID"].to_numpy()
    res = {}
    for k in range(1, N_NEXT + 1):
        ev = Y[f"e{k}"].to_numpy() == 1
        true_t = Y[f"t{k}"].to_numpy()
        if f"t{k}" in pred:
            p = np.asarray(pred[f"t{k}"], dtype=float)
            res[f"t{k}_logerr"] = _conv_mean(np.abs(np.log1p(p) - np.log1p(true_t)), conv, ev)
            res[f"t{k}_mae"] = _conv_mean(np.abs(p - true_t), conv, ev)
        if f"c{k}" in pred:
            res[f"c{k}_acc"] = _conv_mean((np.asarray(pred[f"c{k}"]) == Y[f"c{k}"].to_numpy()).astype(float), conv, ev)
    if "fail_blocks" in pred:
        fb = np.asarray(pred["fail_blocks"], dtype=float)
        pmb = np.asarray(pred.get("pm_blocks", nominal_pm_blocks(Y["Date"])), dtype=float)
        dt_pred = 36.0 * fb + 24.0 * pmb
        true_dt = Y[[f"m{j}_dt" for j in range(1, N_BLOCKS + 1)]].to_numpy(dtype=float)
        true_f = Y[[f"m{j}_fail" for j in range(1, N_BLOCKS + 1)]].to_numpy(dtype=float)
        complete = ~np.isnan(true_dt).any(axis=1)
        tot_p, tot_t = dt_pred.sum(axis=1), true_dt.sum(axis=1)
        res["dt_tot_abs"] = _conv_mean(np.abs(tot_p - tot_t), conv, complete)
        res["dt_tot_pct"] = _conv_mean(np.abs(tot_p - tot_t) / np.maximum(tot_t, 1.0), conv, complete)
        res["dt_tot_bias"] = _conv_mean(tot_p - tot_t, conv, complete)
        sq = (dt_pred - true_dt) ** 2
        n_obs = (~np.isnan(sq)).sum(axis=1)
        rmse = np.sqrt(np.nansum(sq, axis=1) / np.maximum(n_obs, 1))
        res["dt_month_rmse"] = _conv_mean(rmse, conv, n_obs > 0)
        res["fail_tot_pct"] = _conv_mean(np.abs(fb.sum(1) - true_f.sum(1)) / np.maximum(true_f.sum(1), 1), conv, complete)
        if "tot_dt_lo" in pred:
            inside = (tot_t >= pred["tot_dt_lo"]) & (tot_t <= pred["tot_dt_hi"])
            res["dt_cover80"] = _conv_mean(inside.astype(float), conv, complete)
    return res


def score_by(pred: dict, Y: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    """Scores overall, by load class, and by origin age bucket."""
    rows = {"all": score(pred, Y)}
    groups = {
        "Light": X["load_class"].to_numpy() == 0, "Medium": X["load_class"].to_numpy() == 1,
        "Heavy": X["load_class"].to_numpy() == 2,
        "age<1y": X["age_days"].to_numpy() < 365, "age1-3y": (X["age_days"].to_numpy() >= 365) & (X["age_days"].to_numpy() < 1095),
        "age3y+": X["age_days"].to_numpy() >= 1095,
    }
    for g, m in groups.items():
        sub = {k: (v[m] if isinstance(v, np.ndarray) and len(v) == len(m) else v) for k, v in pred.items()}
        rows[g] = score(sub, Y.loc[m].reset_index(drop=True))
    return pd.DataFrame(rows).T
