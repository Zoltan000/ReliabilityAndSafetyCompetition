"""Forecasting models. Each has fit(X, Y) and predict(X) -> pred dict (see evaluate.score).

- Baselines: OwnRate (conveyor's own failure rate) and EmpiricalBayes (shrunk to the load-class prior).
- DirectML: XGBoost AFT for days to the k-th next failure (censoring-aware), LightGBM multiclass for
  the k-th failure's component, and a stacked LightGBM Poisson model for failures per horizon block.
"""
from __future__ import annotations

import os

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import nbinom

from .evaluate import nominal_pm_blocks
from .features import season_day_counts
from .labels import BLOCK_EDGES, N_BLOCKS, N_NEXT

ID_COLS = ["Conveyor_ID", "Date", "Plant_ID"]
BLOCK_LEN = np.diff(BLOCK_EDGES).astype(np.float32)
CAL_START = pd.Timestamp("2000-01-01")
CAL = season_day_counts(CAL_START, 365 * 60)  # cumulative season-day counts, 2000..2060


def feature_cols(X: pd.DataFrame, drop: tuple[str, ...] = ()) -> list[str]:
    return [c for c in X.columns if c not in ID_COLS and not any(c.startswith(p) for p in drop)]


def block_features(X: pd.DataFrame) -> dict[str, np.ndarray]:
    """Known-future features per horizon block: (n, 36) arrays."""
    base = (pd.DatetimeIndex(X["Date"]) - CAL_START).days.to_numpy()
    levels = X[[f"temp_level_s{s}" for s in range(4)]].to_numpy(dtype=float)
    temp = np.empty((len(X), N_BLOCKS), dtype=np.float32)
    for j in range(N_BLOCKS):
        counts = CAL[base + BLOCK_EDGES[j + 1] + 1] - CAL[base + BLOCK_EDGES[j] + 1]
        temp[:, j] = (counts * levels).sum(axis=1) / BLOCK_LEN[j]
    mid = pd.DatetimeIndex(X["Date"]).to_numpy()[:, None] + ((BLOCK_EDGES[:-1] + BLOCK_EDGES[1:]) // 2).astype("timedelta64[D]")
    month = pd.DatetimeIndex(mid.ravel()).month.to_numpy().reshape(len(X), N_BLOCKS).astype(np.float32)
    return {"blk_temp": temp, "blk_month": month, "blk_pm": nominal_pm_blocks(X["Date"])}


def rate_to_pred(p: np.ndarray, X: pd.DataFrame) -> dict:
    """Turn a per-at-risk-day failure probability into Req. 2/3 predictions (geometric process)."""
    p = np.clip(p, 1e-5, 0.95)
    pm = nominal_pm_blocks(X["Date"])
    fail_blocks = (BLOCK_LEN[None, :] - pm) * (p / (1 + p))[:, None]
    extra = (X["state_code"].to_numpy() == 1).astype(float)  # origin is a failure day -> next day corrective
    pred = {"fail_blocks": fail_blocks, "pm_blocks": pm}
    for k in range(1, N_NEXT + 1):
        at_risk_days = nbinom.median(k, p) + k
        pred[f"t{k}"] = at_risk_days + (k - 1) + extra
        pred[f"c{k}"] = np.zeros(len(X), dtype=int)  # Bearing
    return pred


class OwnRate:
    name = "own_rate"

    def fit(self, X, Y):
        return self

    def predict(self, X):
        return rate_to_pred(X["rate_all"].to_numpy(dtype=float), X)


class EmpiricalBayes:
    """Recent own rate shrunk toward the load-class prior (prior from mature training conveyors)."""

    def __init__(self, a: float = 200.0):
        self.a, self.name = a, f"emp_bayes_a{int(a)}"

    def fit(self, X, Y):
        mature = X["age_days"] >= 730
        self.prior = X[mature].groupby("load_class")["rate_365"].mean().to_dict()
        return self

    def predict(self, X):
        prior = X["load_class"].map(self.prior).to_numpy(dtype=float)
        h = np.minimum(X["age_days"].to_numpy() + 1, 365) * X["availability_all"].to_numpy()
        p = (X["rate_365"].to_numpy() * h + self.a * prior) / (h + self.a)
        return rate_to_pred(p, X)


LGB_COUNT = dict(objective="poisson", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
                 feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1)
LGB_COMP = dict(objective="multiclass", num_class=7, learning_rate=0.05, num_leaves=31, min_data_in_leaf=200,
                feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1)
XGB_AFT = dict(objective="survival:aft", eval_metric="aft-nloglik", aft_loss_distribution="normal",
               aft_loss_distribution_scale=1.0, tree_method="hist", learning_rate=0.05, max_depth=6,
               min_child_weight=20, subsample=0.8, colsample_bytree=0.8, nthread=-1,
               device=os.environ.get("CONVEYOR_XGB_DEVICE", "cpu"))  # set to "cuda" on a GPU machine


class DirectML:
    name = "direct_ml"

    def __init__(self, drop: tuple[str, ...] = (), count_stride: int = 4, rounds_count: int = 600,
                 rounds_aft: int = 400, rounds_comp: int = 300, aft_dist: str = "normal", seed: int = 0,
                 lgb_count: dict | None = None, xgb_aft: dict | None = None, lgb_comp: dict | None = None):
        self.drop, self.count_stride, self.seed = drop, count_stride, seed
        self.rounds = dict(count=rounds_count, aft=rounds_aft, comp=rounds_comp)
        self.p_count = {**LGB_COUNT, **(lgb_count or {}), "seed": seed}
        self.p_aft = {**XGB_AFT, **(xgb_aft or {}), "aft_loss_distribution": aft_dist, "seed": seed}
        self.p_comp = {**LGB_COMP, **(lgb_comp or {}), "seed": seed}
        self.name = "direct_ml" + ("_drop-" + "-".join(drop) if drop else "")

    # --- stacked count model -------------------------------------------------------------
    def _long(self, X: pd.DataFrame, Xf: np.ndarray):
        bf = block_features(X)
        n = len(X)
        rep = np.repeat(np.arange(n), N_BLOCKS)
        j = np.tile(np.arange(N_BLOCKS), n)
        extra = np.column_stack([j + 1, BLOCK_LEN[j], bf["blk_temp"].ravel(), bf["blk_month"].ravel(), bf["blk_pm"].ravel()])
        return np.hstack([Xf[rep], extra.astype(np.float32)])

    def fit(self, X: pd.DataFrame, Y: pd.DataFrame):
        self.cols = feature_cols(X, self.drop)
        Xf = X[self.cols].to_numpy(dtype=np.float32)
        w = 1.0 / X.groupby("Conveyor_ID")["Conveyor_ID"].transform("size").to_numpy()  # equal weight per conveyor
        w = w / w.mean()

        # Req. 3: failures per block (stacked over blocks), subsampled origins.
        sub = np.arange(0, len(X), self.count_stride)
        L = self._long(X.iloc[sub], Xf[sub])
        yb = Y.iloc[sub][[f"m{j}_fail" for j in range(1, N_BLOCKS + 1)]].to_numpy(dtype=np.float32).ravel()
        wb = np.repeat(w[sub], N_BLOCKS)
        ok = ~np.isnan(yb)
        self.count_model = lgb.train(self.p_count, lgb.Dataset(L[ok], yb[ok], weight=wb[ok]), self.rounds["count"])

        # Req. 2: days to k-th failure (AFT, censoring-aware) and its component (multiclass).
        self.aft, self.comp = [], []
        for k in range(1, N_NEXT + 1):
            t = Y[f"t{k}"].to_numpy(dtype=float)
            ev = Y[f"e{k}"].to_numpy() == 1
            lo = np.maximum(t, 0.5)
            hi = np.where(ev, lo, np.inf)
            d = xgb.DMatrix(Xf, weight=w)
            d.set_float_info("label_lower_bound", lo)
            d.set_float_info("label_upper_bound", hi)
            self.aft.append(xgb.train(self.p_aft, d, self.rounds["aft"]))
            c = Y[f"c{k}"].to_numpy()
            self.comp.append(lgb.train(self.p_comp, lgb.Dataset(Xf[ev], c[ev], weight=w[ev]), self.rounds["comp"]))
        return self

    # --- persistence: text/JSON only, so artifacts don't depend on pickle or library versions ---
    def save(self, d):
        import json
        from pathlib import Path
        d = Path(d)
        d.mkdir(parents=True, exist_ok=True)
        self.count_model.save_model(str(d / "count.txt"))
        for k in range(N_NEXT):
            self.aft[k].save_model(str(d / f"aft_{k+1}.json"))
            self.comp[k].save_model(str(d / f"comp_{k+1}.txt"))
        (d / "meta.json").write_text(json.dumps({"cols": self.cols, "name": self.name}, indent=1))

    @classmethod
    def load(cls, d):
        import json
        from pathlib import Path
        d = Path(d)
        m = cls.__new__(cls)
        meta = json.loads((d / "meta.json").read_text())
        m.cols, m.name = meta["cols"], meta["name"]
        m.count_model = lgb.Booster(model_file=str(d / "count.txt"))
        m.aft, m.comp = [], []
        for k in range(N_NEXT):
            b = xgb.Booster()
            b.load_model(str(d / f"aft_{k+1}.json"))
            m.aft.append(b)
            m.comp.append(lgb.Booster(model_file=str(d / f"comp_{k+1}.txt")))
        return m

    def predict(self, X: pd.DataFrame) -> dict:
        Xf = X[self.cols].to_numpy(dtype=np.float32)
        fb = self.count_model.predict(self._long(X, Xf)).reshape(len(X), N_BLOCKS)
        pred = {"fail_blocks": fb, "pm_blocks": nominal_pm_blocks(X["Date"])}
        d = xgb.DMatrix(Xf)
        prev = np.zeros(len(X))
        for k in range(N_NEXT):
            t = self.aft[k].predict(d)
            t = np.maximum(t, np.where(prev > 0, prev + 2, 1))  # ordered; a failure day is followed by a corrective day
            pred[f"t{k+1}"], prev = t, t
            proba = self.comp[k].predict(Xf)
            pred[f"c{k+1}"], pred[f"p{k+1}"] = proba.argmax(axis=1), proba
        return pred
