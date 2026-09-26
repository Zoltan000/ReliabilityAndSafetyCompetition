"""Training workflow: fleet Parquet -> training tables -> calibration -> final bagged models -> artifacts/.

This is the code that produced the submitted artifacts. scripts/01, 03 and 05 call it offline, and the
notebook can run it end to end (`train_all`). Hyperparameters come from the Optuna study (scripts/04_tune.py),
stored in artifacts/tuned/*.json.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import cv_folds, sealed_conveyors
from .features import daily_features
from .io import iter_conveyors, load_fleet, season_of
from .labels import N_BLOCKS, N_NEXT, labels_for
from .models import DirectML, EmpiricalBayes, OwnRate

MIN_HISTORY = 200  # first training origin at index 199 = 200 days of history (the spec's minimum input)
STEP = 7  # weekly training origins
LOADS = {0: "Light", 1: "Medium", 2: "Heavy"}


def _log(msg: str) -> None:
    print(msg, flush=True)


DROPS = {"direct": (), "direct-nocm": ("cm_",), "direct-noclim": ("temp_", "humidity", "voltage"),
         "direct-nobrg": ("brg_",)}


def fit_climatology(fleet: pd.DataFrame) -> list[float]:
    """Fleet mean Tmax per season (DJF, MAM, JJA, SON), fit on non-sealed conveyors only (it feeds the model)."""
    conv_plant = fleet.groupby("Conveyor_ID")["Plant_ID"].first()
    clim_fleet = fleet[~fleet["Conveyor_ID"].isin(sealed_conveyors(conv_plant))]
    seas = season_of(clim_fleet["Date"])
    return [float(clim_fleet["Temperature_Max_C"][seas == s].mean()) for s in range(4)]


def build_tables(fleet: pd.DataFrame, fleet_tmax, log=_log) -> tuple[pd.DataFrame, pd.DataFrame]:
    """As-of features (X) and future labels (Y) at weekly origins from day 200, for every conveyor."""
    t0 = time.time()
    feats, labs = [], []
    for cid, df in iter_conveyors(fleet):
        origins = np.arange(MIN_HISTORY - 1, len(df) - 1, STEP)
        feats.append(daily_features(df, fleet_tmax).iloc[origins].reset_index(drop=True))
        labs.append(labels_for(df, origins))
    X = pd.concat(feats, ignore_index=True)
    Y = pd.concat(labs, ignore_index=True)
    assert (X["Conveyor_ID"].to_numpy() == Y["Conveyor_ID"].to_numpy()).all()
    assert (X["Date"].to_numpy() == Y["Date"].to_numpy()).all()
    log(f"features {X.shape}, labels {Y.shape}, built in {time.time()-t0:.0f}s")
    return X, Y


def tuned_kwargs(tuned_dir: str | Path = "artifacts/tuned") -> dict:
    """DirectML keyword arguments from the Optuna best params (defaults where a study is missing)."""
    kw = {}
    for sub, (pkey, rkey) in {"count": ("lgb_count", "rounds_count"), "aft": ("xgb_aft", "rounds_aft"),
                              "comp": ("lgb_comp", "rounds_comp")}.items():
        f = Path(tuned_dir) / f"{sub}.json"
        if f.exists():
            t = json.loads(f.read_text())
            kw[pkey], kw[rkey] = dict(t["params"]), int(t["rounds"])
    if "xgb_aft" in kw:
        kw["aft_dist"] = kw["xgb_aft"].pop("aft_loss_distribution", "normal")
    return kw


def make(spec: str, seed: int, tuned_dir: str | Path = "artifacts/tuned"):
    """Model factory for a spec name (the submitted tool uses `direct-tuned`)."""
    if spec == "own_rate":
        return OwnRate()
    if spec.startswith("eb:"):
        return EmpiricalBayes(float(spec.split(":")[1]))
    if spec in DROPS:
        m = DirectML(drop=DROPS[spec], seed=seed)
    elif spec == "direct-tuned":
        m = DirectML(seed=seed, **tuned_kwargs(tuned_dir))
    elif spec.startswith("direct-aft:"):
        m = DirectML(aft_dist=spec.split(":")[1], seed=seed)
    else:
        raise ValueError(spec)
    m.name = spec
    return m


def oof_predict(spec: str, X: pd.DataFrame, Y: pd.DataFrame, folds, seed: int = 0,
                tuned_dir: str | Path = "artifacts/tuned", log=_log) -> dict:
    """Out-of-fold predictions: each fold's test conveyors are predicted by a model that never saw them."""
    t0 = time.time()
    oof = None
    for k, (tr, te) in enumerate(folds):
        itr, ite = X["Conveyor_ID"].isin(tr).to_numpy(), X["Conveyor_ID"].isin(te).to_numpy()
        model = make(spec, seed, tuned_dir).fit(X[itr].reset_index(drop=True), Y[itr].reset_index(drop=True))
        pred = model.predict(X[ite].reset_index(drop=True))
        if oof is None:
            oof = {key: np.zeros((len(X),) + np.shape(v)[1:], dtype=np.asarray(v).dtype) for key, v in pred.items()}
        for key, v in pred.items():
            oof[key][ite] = v
        log(f"  fold {k+1}/{len(folds)} done ({time.time()-t0:.0f}s)")
    return oof


def calibration(oof: dict, X: pd.DataFrame, Y: pd.DataFrame) -> dict:
    """Empirical (conformal) q10/q90 of OOF residuals per load class: log(true/pred) of days to the k-th
    failure, and true/pred of the 3-year total downtime. These become the tool's P10/P90 bands."""
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


def fit_final(spec: str, X: pd.DataFrame, Y: pd.DataFrame, seeds: int, art: str | Path,
              tuned_dir: str | Path = "artifacts/tuned", log=_log) -> list[str]:
    """Fit one model per seed on all rows supplied and save each to art/model_seed<s>/ (text/JSON only)."""
    t0 = time.time()
    dirs = []
    for s in range(seeds):
        make(spec, s, tuned_dir).fit(X, Y).save(Path(art) / f"model_seed{s}")
        dirs.append(f"model_seed{s}")
        log(f"  saved model_seed{s} ({time.time()-t0:.0f}s)")
    return dirs


def write_manifest(art: str | Path, spec: str, dirs: list[str], cal: dict, X: pd.DataFrame) -> dict:
    """manifest.json: model list, calibration, and SHA-256 of every artifact file."""
    art = Path(art)
    files = sorted(p for p in art.rglob("*") if p.is_file() and p.name != "manifest.json")
    manifest = {"spec": spec, "model_dirs": dirs, "calibration": cal, "n_conveyors": int(X.Conveyor_ID.nunique()),
                "n_origins": len(X), "created": pd.Timestamp.now().isoformat(timespec="seconds"),
                "sha256": {str(p.relative_to(art)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in files}}
    (art / "manifest.json").write_text(json.dumps(manifest, indent=1), newline="\n")
    return manifest


def train_all(fleet_path: str, art: str | Path = "artifacts", spec: str = "direct-tuned", seeds: int = 5,
              folds: int = 5, tuned_dir: str | Path | None = None, log=_log) -> dict:
    """The full training workflow, from the fleet file to the artifacts the forecast tool loads.

    1. Climatology (non-sealed conveyors) and training tables (weekly origins from day 200, all conveyors).
    2. Calibration: grouped K-fold CV over the non-sealed conveyors -> OOF residual quantiles per load class.
    3. Final models: one per seed on all conveyors -> art/model_seed*/, plus manifest.json.
    """
    art = Path(art)
    tuned_dir = Path(tuned_dir) if tuned_dir is not None else art / "tuned"
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    fleet = load_fleet(fleet_path)
    fleet_tmax = fit_climatology(fleet)
    (art / "climatology.json").write_text(json.dumps({"fleet_tmax_by_season_DJF_MAM_JJA_SON": fleet_tmax}, indent=1),
                                        newline="\n")  # LF on every OS: the manifest hashes these bytes
    log(f"[1/3] loaded {len(fleet):,} rows ({fleet.Conveyor_ID.nunique()} conveyors) in {time.time()-t0:.0f}s; "
        f"fleet Tmax by season {np.round(fleet_tmax, 2)}")
    X, Y = build_tables(fleet, fleet_tmax, log)
    del fleet

    conv_plant = X.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    keep = ~X["Conveyor_ID"].isin(sealed).to_numpy()
    log(f"[2/3] calibration: {folds}-fold grouped CV over {len(conv_plant) - len(sealed)} conveyors")
    Xc, Yc = X[keep].reset_index(drop=True), Y[keep].reset_index(drop=True)
    oof = oof_predict(spec, Xc, Yc, cv_folds(conv_plant.drop(sealed), folds, 0), 0, tuned_dir, log)
    cal = calibration(oof, Xc, Yc)
    del oof, Xc, Yc

    log(f"[3/3] final fit: {seeds} seeds on all {len(conv_plant)} conveyors")
    dirs = fit_final(spec, X, Y, seeds, art, tuned_dir, log)
    manifest = write_manifest(art, spec, dirs, cal, X)
    log(f"done in {(time.time()-t0)/60:.1f} min; {len(manifest['sha256'])} artifact files")
    return manifest
