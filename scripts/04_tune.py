"""Optuna tuning of the DirectML sub-models on grouped CV (3 folds over non-sealed conveyors, seed 0).

One study per sub-model, meant to run as parallel processes (count/comp on CPU, aft on GPU):
- count: LightGBM Poisson on stacked horizon blocks; objective all:dt_tot_pct (3-year total downtime error).
- aft:   XGBoost survival:aft for k=1 and k=5; objective t1_logerr + t5_logerr.
- comp:  LightGBM multiclass for the next failure's component; objective multi_logloss (c1_acc logged).
The number of boosting rounds is picked from the fold-averaged learning curve (a CV choice, not per-fold
early stopping). Trial 0 is the current default, so the best is never worse than it on this harness.
Best params -> artifacts/tuned/<sub>.json, read by the `direct-tuned` spec in 03_cv.py.

Usage: .venv/Scripts/python scripts/04_tune.py {count,aft,comp} [--timeout 2400] [--threads 8] [--folds 3]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conveyor.evaluate import cv_folds, nominal_pm_blocks, sealed_conveyors  # noqa: E402
from conveyor.labels import N_BLOCKS  # noqa: E402
from conveyor.models import LGB_COMP, LGB_COUNT, XGB_AFT, DirectML, feature_cols  # noqa: E402

CACHE, OUT = Path("outputs/cache"), Path("artifacts/tuned")
TEST_STRIDE = 2  # count study: every 2nd complete test origin (memory); metrics are per-conveyor means anyway


def load(n_folds):
    X = pd.read_parquet(CACHE / "features.parquet")
    Y = pd.read_parquet(CACHE / "labels.parquet")
    conv_plant = X.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    keep = ~X["Conveyor_ID"].isin(sealed).to_numpy()
    X, Y = X[keep].reset_index(drop=True), Y[keep].reset_index(drop=True)
    folds = cv_folds(conv_plant.drop(sealed), n_folds, 0)
    w = 1.0 / X.groupby("Conveyor_ID")["Conveyor_ID"].transform("size").to_numpy()
    return X, Y, folds, w / w.mean()


def conv_mean(err, conv_codes, n_conv):
    s = np.bincount(conv_codes, weights=err, minlength=n_conv)
    c = np.bincount(conv_codes, minlength=n_conv)
    return float((s[c > 0] / c[c > 0]).mean())


# --- count ------------------------------------------------------------------------------------
def prep_count(X, Y, folds, w, stride=4):
    cols = feature_cols(X)
    Xf = X[cols].to_numpy(dtype=np.float32)
    helper = DirectML()
    yb_all = Y[[f"m{j}_fail" for j in range(1, N_BLOCKS + 1)]].to_numpy(dtype=np.float32)
    true_tot = Y[[f"m{j}_dt" for j in range(1, N_BLOCKS + 1)]].to_numpy(dtype=float)
    complete = ~np.isnan(true_tot).any(axis=1)
    conv_codes = pd.factorize(X["Conveyor_ID"])[0]
    data = []
    for tr, te in folds:
        itr = np.flatnonzero(X["Conveyor_ID"].isin(tr).to_numpy())[::stride]
        L = helper._long(X.iloc[itr], Xf[itr])
        yb, wb = yb_all[itr].ravel(), np.repeat(w[itr], N_BLOCKS)
        ok = ~np.isnan(yb)
        dtr = lgb.Dataset(L[ok], yb[ok], weight=wb[ok], params={"feature_pre_filter": False, "verbose": -1}).construct()
        del L
        ite = np.flatnonzero(X["Conveyor_ID"].isin(te).to_numpy() & complete)[::TEST_STRIDE]
        Lte = helper._long(X.iloc[ite], Xf[ite])
        pm_tot = 24.0 * nominal_pm_blocks(X["Date"].iloc[ite]).sum(axis=1)
        dte = lgb.Dataset(Lte, np.nan_to_num(yb_all[ite].ravel()), reference=dtr).construct()
        del Lte
        codes, uniq = pd.factorize(conv_codes[ite])
        data.append(dict(dtr=dtr, dte=dte, n=len(ite), pm_tot=pm_tot, true=true_tot[ite].sum(axis=1),
                         codes=codes, n_conv=len(uniq)))
        print(f"  prepared fold: train {int(ok.sum()):,} block rows, test {len(ite):,} origins", flush=True)
    return data


def count_objective(data, threads):
    def objective(trial):
        lr = trial.suggest_float("learning_rate", 0.015, 0.15, log=True)
        p = {**LGB_COUNT, "learning_rate": lr, "metric": "None", "num_threads": threads, "seed": 0,
             "num_leaves": trial.suggest_int("num_leaves", 15, 255, log=True),
             "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 50, 3000, log=True),
             "feature_fraction": trial.suggest_float("feature_fraction", 0.4, 1.0),
             "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
             "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 30, log=True)}
        max_rounds = int(min(2500, 36 / lr))
        curves = []
        for f in data:
            def feval(preds, _ds, f=f):
                tot = 36.0 * preds.reshape(f["n"], N_BLOCKS).sum(axis=1) + f["pm_tot"]
                err = np.abs(tot - f["true"]) / np.maximum(f["true"], 1.0)
                return "dt_tot_pct", conv_mean(err, f["codes"], f["n_conv"]), False
            rec = {}
            lgb.train(p, f["dtr"], max_rounds, valid_sets=[f["dte"]], valid_names=["te"], feval=feval,
                      callbacks=[lgb.record_evaluation(rec)])
            curves.append(rec["te"]["dt_tot_pct"])
        curve = np.mean(curves, axis=0)
        best = int(np.argmin(curve))
        trial.set_user_attr("rounds", best + 1)
        return float(curve[best])
    return objective


def count_default():
    return {k: LGB_COUNT[k] for k in ("learning_rate", "num_leaves", "min_data_in_leaf", "feature_fraction",
                                      "bagging_fraction", "lambda_l2")}


# --- aft --------------------------------------------------------------------------------------
def prep_aft(X, Y, folds, w, ks=(1, 5)):
    Xf = X[feature_cols(X)].to_numpy(dtype=np.float32)
    conv_codes = pd.factorize(X["Conveyor_ID"])[0]
    data = []
    for tr, te in folds:
        itr = X["Conveyor_ID"].isin(tr).to_numpy()
        ite = X["Conveyor_ID"].isin(te).to_numpy()
        per_k = []
        for k in ks:
            t = Y[f"t{k}"].to_numpy(dtype=float)
            ev = Y[f"e{k}"].to_numpy() == 1
            lo = np.maximum(t, 0.5)
            hi = np.where(ev, lo, np.inf)
            dtr = xgb.QuantileDMatrix(Xf[itr], weight=w[itr], label_lower_bound=lo[itr], label_upper_bound=hi[itr])
            sel = ite & ev
            codes, uniq = pd.factorize(conv_codes[sel])
            per_k.append(dict(dtr=dtr, dte=xgb.DMatrix(Xf[sel]), true=t[sel], codes=codes, n_conv=len(uniq)))
        data.append(per_k)
        print("  prepared fold", flush=True)
    return data


def aft_objective(data, threads):
    def objective(trial):
        lr = trial.suggest_float("learning_rate", 0.01, 0.2, log=True)
        p = {**XGB_AFT, "learning_rate": lr, "nthread": threads, "seed": 0,
             "device": os.environ.get("CONVEYOR_XGB_DEVICE", "cpu"),
             "max_depth": trial.suggest_int("max_depth", 3, 10),
             "min_child_weight": trial.suggest_float("min_child_weight", 1, 300, log=True),
             "subsample": trial.suggest_float("subsample", 0.5, 1.0),
             "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 1.0),
             "lambda": trial.suggest_float("lambda", 1e-3, 30, log=True),
             "aft_loss_distribution": trial.suggest_categorical("aft_loss_distribution", ["normal", "logistic", "extreme"]),
             "aft_loss_distribution_scale": trial.suggest_float("aft_loss_distribution_scale", 0.3, 2.0, log=True)}
        max_rounds = int(min(2000, 25 / lr))
        grid = np.unique(np.linspace(max_rounds / 20, max_rounds, 20).astype(int))
        curves = []
        for per_k in data:
            fold_curve = np.zeros(len(grid))
            for d in per_k:
                bst = xgb.train(p, d["dtr"], max_rounds)
                for i, r in enumerate(grid):
                    pred = bst.predict(d["dte"], iteration_range=(0, int(r)))
                    err = np.abs(np.log1p(pred) - np.log1p(d["true"]))
                    fold_curve[i] += conv_mean(err, d["codes"], d["n_conv"])
            curves.append(fold_curve)
        curve = np.mean(curves, axis=0)
        best = int(np.argmin(curve))
        trial.set_user_attr("rounds", int(grid[best]))
        return float(curve[best])
    return objective


def aft_default():
    return {"learning_rate": 0.05, "max_depth": 6, "min_child_weight": 20, "subsample": 0.8, "colsample_bytree": 0.8,
            "lambda": 1.0, "aft_loss_distribution": "normal", "aft_loss_distribution_scale": 1.0}


# --- comp -------------------------------------------------------------------------------------
def prep_comp(X, Y, folds, w, k=1):
    Xf = X[feature_cols(X)].to_numpy(dtype=np.float32)
    conv_codes = pd.factorize(X["Conveyor_ID"])[0]
    ev = Y[f"e{k}"].to_numpy() == 1
    c = Y[f"c{k}"].to_numpy()
    data = []
    for tr, te in folds:
        itr = X["Conveyor_ID"].isin(tr).to_numpy() & ev
        ite = X["Conveyor_ID"].isin(te).to_numpy() & ev
        dtr = lgb.Dataset(Xf[itr], c[itr], weight=w[itr], params={"feature_pre_filter": False, "verbose": -1}).construct()
        dte = lgb.Dataset(Xf[ite], c[ite], weight=w[ite], reference=dtr).construct()
        codes, uniq = pd.factorize(conv_codes[ite])
        data.append(dict(dtr=dtr, dte=dte, Xte=Xf[ite], true=c[ite], codes=codes, n_conv=len(uniq)))
    print("  prepared folds", flush=True)
    return data


def comp_objective(data, threads):
    def objective(trial):
        lr = trial.suggest_float("learning_rate", 0.01, 0.15, log=True)
        p = {**LGB_COMP, "learning_rate": lr, "metric": "multi_logloss", "num_threads": threads, "seed": 0,
             "num_leaves": trial.suggest_int("num_leaves", 7, 127, log=True),
             "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 50, 5000, log=True),
             "feature_fraction": trial.suggest_float("feature_fraction", 0.3, 1.0),
             "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
             "lambda_l2": trial.suggest_float("lambda_l2", 1e-3, 100, log=True)}
        max_rounds = int(min(2000, 20 / lr))
        curves, boosters = [], []
        for f in data:
            rec = {}
            boosters.append(lgb.train(p, f["dtr"], max_rounds, valid_sets=[f["dte"]], valid_names=["te"],
                                      callbacks=[lgb.record_evaluation(rec)]))
            curves.append(rec["te"]["multi_logloss"])
        curve = np.mean(curves, axis=0)
        best = int(np.argmin(curve))
        acc = np.mean([conv_mean((b.predict(f["Xte"], num_iteration=best + 1).argmax(1) == f["true"]).astype(float),
                                 f["codes"], f["n_conv"]) for b, f in zip(boosters, data)])
        base = np.mean([conv_mean((f["true"] == 0).astype(float), f["codes"], f["n_conv"]) for f in data])
        trial.set_user_attr("rounds", best + 1)
        trial.set_user_attr("c1_acc", float(acc))
        trial.set_user_attr("c1_acc_always_bearing", float(base))
        return float(curve[best])
    return objective


def comp_default():
    return {k: LGB_COMP[k] for k in ("learning_rate", "num_leaves", "min_data_in_leaf", "feature_fraction",
                                     "bagging_fraction", "lambda_l2")}


STUDIES = {"count": (prep_count, count_objective, count_default, 600),
           "aft": (prep_aft, aft_objective, aft_default, 400),
           "comp": (prep_comp, comp_objective, comp_default, 300)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sub", choices=list(STUDIES))
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--sampler-seed", type=int, default=0, help="use a different seed for each extra parallel worker")
    a = ap.parse_args()
    prep, make_obj, default, default_rounds = STUDIES[a.sub]
    t0 = time.time()
    X, Y, folds, w = load(a.folds)
    data = prep(X, Y, folds, w)
    del X, Y
    print(f"[{a.sub}] data ready in {time.time()-t0:.0f}s", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{(CACHE / 'optuna.db').as_posix()}"
    study = optuna.create_study(study_name=f"{a.sub}_f{a.folds}", storage=storage, direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=a.sampler_seed, n_startup_trials=8), load_if_exists=True)
    if len(study.trials) == 0:
        study.enqueue_trial(default())

    def save(study, trial):
        if trial.state != optuna.trial.TrialState.COMPLETE:
            return
        print(f"[{a.sub}] trial {trial.number}: {trial.value:.5f} rounds={trial.user_attrs.get('rounds')} "
              f"{({k: v for k, v in trial.user_attrs.items() if k != 'rounds'})} ({time.time()-t0:.0f}s)", flush=True)
        b = study.best_trial
        (OUT / f"{a.sub}.json").write_text(json.dumps(
            {"params": b.params, "rounds": b.user_attrs["rounds"], "cv_value": b.value, "trial": b.number,
             "default_value": study.trials[0].value, "n_trials": len(study.trials), "user_attrs": b.user_attrs,
             "harness": f"grouped CV, {a.folds} folds, seed 0, non-sealed conveyors"}, indent=1))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study.optimize(make_obj(data, a.threads), timeout=a.timeout, callbacks=[save], gc_after_trial=True)
    b = study.best_trial
    print(f"[{a.sub}] BEST {b.value:.5f} (default {study.trials[0].value:.5f}) rounds={b.user_attrs['rounds']} {b.params}")


if __name__ == "__main__":
    main()
