"""Grouped CV harness: test folds are whole conveyors (stratified by plant); sealed set excluded.

Usage: .venv/Scripts/python scripts/03_cv.py MODEL [MODEL ...] [--seed S] [--folds K] [--lopo]
MODEL: own_rate | eb:<a> | direct | direct-tuned | direct-nocm | direct-noclim | direct-nobrg | direct-aft:<dist>
--lopo: leave-one-plant-out instead of grouped K-fold.
Appends one row per run to outputs/experiments.csv and prints a compact summary.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conveyor.evaluate import cv_folds, score_by, sealed_conveyors  # noqa: E402
from conveyor.train import oof_predict  # noqa: E402

CACHE = Path("outputs/cache")
SHOW = ["t1_logerr", "t5_logerr", "t1_mae", "t5_mae", "c1_acc", "c5_acc",
        "dt_tot_abs", "dt_tot_pct", "dt_tot_bias", "dt_month_rmse", "fail_tot_pct"]


def run(spec, X, Y, folds, seed, tag):
    t0 = time.time()
    oof = oof_predict(spec, X, Y, folds, seed)
    table = score_by(oof, Y, X)
    np.savez_compressed(CACHE / f"oof_{spec.replace(':', '_')}_{tag}.npz", **oof)
    row = {"model": spec, "cv": tag, "seed": seed, "time": pd.Timestamp.now().isoformat(timespec="seconds"),
           "secs": round(time.time() - t0)}
    for g in table.index:
        for m in SHOW:
            if m in table.columns:
                row[f"{g}:{m}"] = round(float(table.loc[g, m]), 4)
    log = Path("outputs/experiments.csv")
    pd.DataFrame([row]).to_csv(log, mode="a", header=not log.exists(), index=False)
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--lopo", action="store_true")
    a = ap.parse_args()

    X = pd.read_parquet(CACHE / "features.parquet")
    Y = pd.read_parquet(CACHE / "labels.parquet")
    conv_plant = X.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    keep = ~X["Conveyor_ID"].isin(sealed).to_numpy()
    X, Y = X[keep].reset_index(drop=True), Y[keep].reset_index(drop=True)
    conv_plant = conv_plant.drop(sealed)
    if a.lopo:
        folds = [(list(conv_plant.index[conv_plant != p]), list(conv_plant.index[conv_plant == p]))
                 for p in sorted(conv_plant.unique())]
        tag = "lopo"
    else:
        folds = cv_folds(conv_plant, a.folds, a.seed)
        tag = f"gkf{a.folds}s{a.seed}"
    print(f"{len(conv_plant)} CV conveyors ({len(sealed)} sealed), {len(X):,} origins, {len(folds)} folds [{tag}]")

    pd.set_option("display.width", 200)
    for spec in a.models:
        print(f"\n### {spec}")
        table = run(spec, X, Y, folds, a.seed, tag)
        print(table[[c for c in SHOW if c in table.columns]].round(3).to_string())


if __name__ == "__main__":
    main()
