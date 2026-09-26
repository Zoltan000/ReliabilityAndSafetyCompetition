"""Final fit (plan step 6).

1. Calibration: empirical (conformal) quantiles of OOF residuals of the chosen model, per load class:
   log(true/pred) of days to the k-th failure, and true/pred of 3-year total downtime.
2. Sealed test (run once): train on all CV conveyors, score the sealed conveyors.
3. Refit on all 284 conveyors, bagged over seeds -> artifacts/ (text/JSON models + manifest with SHA-256).
The steps themselves live in conveyor.train (also run by the notebook's retrain mode).

Usage: .venv/Scripts/python scripts/05_fit_final.py [--spec direct] [--oof outputs/cache/oof_direct_gkf5s0.npz] [--seeds 5]
       --sealed-only: re-score the sealed test (e.g. after an expert-rule change) without touching artifacts/
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conveyor.evaluate import score_by, sealed_conveyors  # noqa: E402
from conveyor.forecast import apply_expert_rules, ensemble_predict  # noqa: E402
from conveyor.train import LOADS, calibration, fit_final, make, write_manifest  # noqa: E402

CACHE, ART = Path("outputs/cache"), Path("artifacts")
SHOW = ["t1_logerr", "t5_logerr", "t1_mae", "t5_mae", "c1_acc", "c5_acc",
        "dt_tot_abs", "dt_tot_pct", "dt_tot_bias", "dt_month_rmse", "fail_tot_pct", "dt_cover80"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="direct")
    ap.add_argument("--oof", default=None)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--skip-sealed", action="store_true")
    ap.add_argument("--sealed-only", action="store_true",
                    help="refit the sealed-test models and re-score them; don't touch artifacts/")
    a = ap.parse_args()
    X = pd.read_parquet(CACHE / "features.parquet")
    Y = pd.read_parquet(CACHE / "labels.parquet")
    conv_plant = X.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    is_sealed = X["Conveyor_ID"].isin(sealed).to_numpy()

    if a.sealed_only:  # re-score with the calibration the submitted tool actually uses
        cal = json.loads((ART / "manifest.json").read_text())["calibration"]
    else:
        oof_path = a.oof or CACHE / f"oof_{a.spec.replace(':', '_')}_gkf5s0.npz"
        oof = dict(np.load(oof_path))
        cal = calibration(oof, X[~is_sealed].reset_index(drop=True), Y[~is_sealed].reset_index(drop=True))
    print("calibration (q10/q90):", json.dumps(cal, indent=None)[:600])

    if not a.skip_sealed:
        Xtr, Ytr = X[~is_sealed].reset_index(drop=True), Y[~is_sealed].reset_index(drop=True)
        Xte, Yte = X[is_sealed].reset_index(drop=True), Y[is_sealed].reset_index(drop=True)
        models = [make(a.spec, s).fit(Xtr, Ytr) for s in range(a.seeds)]
        pred = ensemble_predict(models, Xte)
        load = Xte["load_class"].map(LOADS).to_numpy()
        tot = (36 * pred["fail_blocks"] + 24 * pred["pm_blocks"]).sum(axis=1)
        pred["tot_dt_lo"] = tot * np.array([cal["tot_ratio_q10_q90"][l][0] for l in load])
        pred["tot_dt_hi"] = tot * np.array([cal["tot_ratio_q10_q90"][l][1] for l in load])
        for name, p, out in [("ML only", pred, "sealed_test_ml_only.csv"),
                             ("ML + expert rules = submitted tool", apply_expert_rules(pred, Xte), "sealed_test.csv")]:
            table = score_by(p, Yte, Xte)
            table.to_csv(f"outputs/{out}")
            print(f"\nSEALED TEST, {name} ({len(sealed)} conveyors, scored once):")
            print(table[[c for c in SHOW if c in table.columns]].round(3).to_string())
    if a.sealed_only:
        return

    # Refit on all conveyors -> artifacts.
    ART.mkdir(exist_ok=True)
    dirs = fit_final(a.spec, X, Y, a.seeds, ART)
    files = write_manifest(ART, a.spec, dirs, cal, X)["sha256"]
    print(f"artifacts written: {len(files)} files")


if __name__ == "__main__":
    main()
