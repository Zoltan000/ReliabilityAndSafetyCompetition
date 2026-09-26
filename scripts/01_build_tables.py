"""Build cached training tables: as-of features at weekly origins + future labels (plan step 2).

Also runs the parity/leakage assertions:
- features at origin d from the full history == features from a file truncated at d;
- features of the example files at their last day == fleet features for P02CV27 at that date.

Run from the repo root: .venv/Scripts/python scripts/01_build_tables.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from conveyor.evaluate import sealed_conveyors  # noqa: E402
from conveyor.features import daily_features, features_asof  # noqa: E402
from conveyor.io import clean, iter_conveyors, load_conveyor, load_fleet, season_of  # noqa: E402
from conveyor.labels import labels_for  # noqa: E402

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
MIN_HISTORY = 200  # origin index 199 = 200 days of history
STEP = 7
CACHE = Path("outputs/cache")
ART = Path("artifacts")


def check_parity(full: pd.DataFrame, fleet_tmax, origins) -> float:
    """Max abs difference between fleet-computed and truncated-file features at the given origins."""
    daily = daily_features(full, fleet_tmax)
    worst = 0.0
    for o in origins:
        a = daily.iloc[o, 3:].to_numpy(dtype=float)
        b = features_asof(clean(full.iloc[: o + 1]), fleet_tmax).iloc[0, 3:].to_numpy(dtype=float)
        both_nan = np.isnan(a) & np.isnan(b)
        worst = max(worst, float(np.nanmax(np.where(both_nan, 0, np.abs(a - b)))))
    return worst


def main():
    t0 = time.time()
    CACHE.mkdir(parents=True, exist_ok=True)
    ART.mkdir(exist_ok=True)
    fleet = load_fleet(FLEET)
    # Climatology feeds the model (features.py), so it must not see the sealed conveyors: fit it on the
    # non-sealed conveyors only, even though the fleet-wide cache below still covers every conveyor.
    conv_plant = fleet.groupby("Conveyor_ID")["Plant_ID"].first()
    sealed = sealed_conveyors(conv_plant)
    clim_fleet = fleet[~fleet["Conveyor_ID"].isin(sealed)]
    seas = season_of(clim_fleet["Date"])
    fleet_tmax = [float(clim_fleet["Temperature_Max_C"][seas == s].mean()) for s in range(4)]
    (ART / "climatology.json").write_text(json.dumps({"fleet_tmax_by_season_DJF_MAM_JJA_SON": fleet_tmax}, indent=1))
    print(f"loaded {len(fleet):,} rows in {time.time()-t0:.0f}s ({len(sealed)} sealed conveyors excluded from "
          f"climatology); fleet Tmax by season {np.round(fleet_tmax, 2)}")

    feats, labs = [], []
    for cid, df in iter_conveyors(fleet):
        n = len(df)
        origins = np.arange(MIN_HISTORY - 1, n - 1, STEP)
        daily = daily_features(df, fleet_tmax)
        feats.append(daily.iloc[origins].reset_index(drop=True))
        labs.append(labels_for(df, origins))
        if cid == "P02CV27":
            p02 = df
    X = pd.concat(feats, ignore_index=True)
    Y = pd.concat(labs, ignore_index=True)
    assert (X["Conveyor_ID"].to_numpy() == Y["Conveyor_ID"].to_numpy()).all()
    assert (X["Date"].to_numpy() == Y["Date"].to_numpy()).all()
    X.to_parquet(CACHE / "features.parquet", index=False)
    Y.to_parquet(CACHE / "labels.parquet", index=False)
    print(f"features {X.shape}, labels {Y.shape}, built in {time.time()-t0:.0f}s")

    # Parity / leakage checks.
    worst = check_parity(p02, fleet_tmax, [199, 364, 1000, 2190, 7000])
    print(f"truncation parity (P02CV27, 5 origins): max abs diff = {worst:.3g}")
    daily = daily_features(p02, fleet_tmax).set_index("Date")
    for path in ["Example_P02CV27_1Year.parquet", "Example_P02CV27_6Years.parquet"]:
        ex = load_conveyor(path)
        a = features_asof(ex, fleet_tmax).iloc[0]
        b = daily.loc[a["Date"]]
        diff = np.nanmax(np.abs(a.iloc[3:].to_numpy(dtype=float) - b.iloc[2:].to_numpy(dtype=float)))
        print(f"example parity {path}: last day {a['Date'].date()}, rows {len(ex)}, max abs diff = {diff:.3g}")

    # Label sanity.
    print("censoring share: next failure", round(1 - Y["e1"].mean(), 4),
          "| 5th failure", round(1 - Y["e5"].mean(), 4),
          "| 3y window complete", round(Y["tot_fail"].notna().mean(), 3))
    print("comp of next failure (share):", Y.loc[Y.e1 == 1, "c1"].value_counts(normalize=True).round(4).to_dict())
    print("3y total downtime h (complete windows): mean", round(float(Y["tot_dt"].mean()), 1),
          "median", round(float(Y["tot_dt"].median()), 1))


if __name__ == "__main__":
    main()
