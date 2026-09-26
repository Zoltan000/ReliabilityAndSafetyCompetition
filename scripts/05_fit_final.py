"""Final fit (plan step 6).

1. Calibration: empirical (conformal) quantiles of OOF residuals of the chosen model, per load class:
   log(true/pred) of days to the k-th failure, and true/pred of 3-year total downtime.
2. Sealed test (run once): train on all CV conveyors, score the sealed conveyors.
3. Refit on all 284 conveyors, bagged over seeds -> artifacts/ (text/JSON models + manifest with SHA-256).

Usage: .venv/Scripts/python scripts/05_fit_final.py [--spec direct] [--oof outputs/cache/oof_direct_gkf5s0.npz] [--seeds 5]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conveyor.evaluate import score_by, sealed_conveyors  # noqa: E402
from conveyor.forecast import apply_expert_rules, ensemble_predict  # noqa: E402
from conveyor.labels import N_BLOCKS, N_NEXT  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module  # noqa: E402

cv = import_module("03_cv")
CACHE, ART = Path("outputs/cache"), Path("artifacts")
LOADS = {0: "Light", 1: "Medium", 2: "Heavy"}


def calibration(oof: dict, X: pd.DataFrame, Y: pd.DataFrame) -> dict:
    load = X["load_class"].map(LOADS).to_numpy()
    cal = {"t_logratio_q10_q90": {}, "tot_ratio_q10_q90": {}}
    true_dt = Y[[f"m{j}_dt" for j in range(1, N_BLOCKS + 1)]].to_numpy(dtype=float)
    complete = ~np.isnan(true_dt).any(axis=1)
    pred_tot = (36 * oof["fail_blocks"] + 24 * oof["pm_blocks"]).sum(axis=1)
    for lc in LOADS.values():
        m = load == lc
        cal["t_logratio_q10_q90"][lc] = {}
        for k in range(1, N_NEXT + 1):
            ev = m & (Y[f"e{k}"].to_numpy() == 1)
            r = np.log(np.maximum(Y[f"t{k}"].to_numpy()[ev], 1) / oof[f"t{k}"][ev])
            cal["t_logratio_q10_q90"][lc][str(k)] = [float(np.quantile(r, 0.1)), float(np.quantile(r, 0.9))]
        mc = m & complete
        ratio = true_dt.sum(axis=1)[mc] / pred_tot[mc]
        cal["tot_ratio_q10_q90"][lc] = [float(np.quantile(ratio, 0.1)), float(np.quantile(ratio, 0.9))]
    return cal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="direct")
    ap.add_argument("--oof", default=None)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--skip-sealed", action="store_true")
    a = ap.parse_args()
    X = pd.read_parquet(CACHE / "features.parquet")
    Y = pd.read_parquet(CACHE / "labels.parquet")
    conv_plant = X.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    is_sealed = X["Conveyor_ID"].isin(sealed).to_numpy()

    oof_path = a.oof or CACHE / f"oof_{a.spec.replace(':', '_')}_gkf5s0.npz"
    oof = dict(np.load(oof_path))
    cal = calibration(oof, X[~is_sealed].reset_index(drop=True), Y[~is_sealed].reset_index(drop=True))
    print("calibration (q10/q90):", json.dumps(cal, indent=None)[:600])

    if not a.skip_sealed:
        Xtr, Ytr = X[~is_sealed].reset_index(drop=True), Y[~is_sealed].reset_index(drop=True)
        Xte, Yte = X[is_sealed].reset_index(drop=True), Y[is_sealed].reset_index(drop=True)
        models = [cv.make(a.spec, s).fit(Xtr, Ytr) for s in range(a.seeds)]
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
            print(table[[c for c in cv.SHOW + ["dt_cover80"] if c in table.columns]].round(3).to_string())

    # Refit on all conveyors -> artifacts.
    ART.mkdir(exist_ok=True)
    dirs = []
    for s in range(a.seeds):
        m = cv.make(a.spec, s).fit(X, Y)
        d = f"model_seed{s}"
        m.save(ART / d)
        dirs.append(d)
        print(f"saved {d}", flush=True)
    files = sorted(p for p in ART.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {"spec": a.spec, "model_dirs": dirs, "calibration": cal, "n_conveyors": int(X.Conveyor_ID.nunique()),
                "n_origins": len(X), "created": pd.Timestamp.now().isoformat(timespec="seconds"),
                "sha256": {str(p.relative_to(ART)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (ART / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"artifacts written: {len(files)} files")


if __name__ == "__main__":
    main()
