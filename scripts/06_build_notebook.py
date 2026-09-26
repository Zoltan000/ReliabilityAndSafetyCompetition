"""Generate the submission Colab notebook from src/ (single source of truth).

Each module is written by a %%writefile cell, so the notebook (and its printed PDF) contains the complete
workflow for Req. 2 + 3: data loading, features, labels, training, calibration, the forecast tool, and (appendix)
the hyperparameter search. By default the notebook loads the fitted models from a pinned commit (SHA-256
verified); with RETRAIN_FROM_FLEET = True it rebuilds them from the fleet file with the same code.

Usage: .venv/Scripts/python scripts/06_build_notebook.py --raw-base https://raw.githubusercontent.com/<owner>/<repo>/<sha> --team "..."
"""
import argparse
from pathlib import Path

import nbformat as nbf

MODULES = ["__init__.py", "io.py", "features.py", "labels.py", "evaluate.py", "models.py", "train.py", "forecast.py"]
SRC = Path("src/conveyor")
TUNE_SCRIPT = Path("scripts/04_tune.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-base", default="https://raw.githubusercontent.com/OWNER/REPO/COMMIT_SHA")
    ap.add_argument("--team", default="TEAM MEMBER NAMES")
    ap.add_argument("--fleet-path", default="", help="default FLEET_PATH (Drive path or URL of the fleet Parquet)")
    ap.add_argument("--out", default="notebooks/Conveyor_Forecast.ipynb")
    ap.add_argument("--input", default=None,
                    help="default INPUT_PATH shown in the notebook (default: the 6-year example at --raw-base)")
    a = ap.parse_args()
    input_path = a.input or f"{a.raw_base}/Example_P02CV27_6Years.parquet"

    md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
    cells = [
        md(f"# Industrial Conveyor Reliability: forecasting tool (Req. 2 + Req. 3)\n\n**Team:** {a.team}\n\n"
           "**How to run:** set `INPUT_PATH` to a Parquet file with one conveyor's daily history (same columns as the fleet "
           "file), or leave it empty to upload one, then *Runtime → Run all*. The tool uses every row, sorts by `Date`, "
           "detects the last observed day itself, and forecasts:\n"
           "- **Req. 2:** the next five failures: component, expected date, days from the last observed day, P10–P90 dates;\n"
           "- **Req. 3:** expected downtime per month for the 3 years after the last observed day, the cumulative curve, "
           "and the expected total with an 80% interval.\n\n"
           "**Method.** Supervised models on features computed *as of* the last observed day (component ages on their "
           "own clocks, per-bearing-position ages, own failure rates, condition-monitoring trends, load class, seasonal "
           "climate). Training origins are every week of every fleet conveyor from day 200 on, labelled with what "
           "actually happened next: days to each of the next 5 failures (XGBoost AFT, censoring-aware), the component "
           "of each (LightGBM multiclass), and failures per future month (LightGBM Poisson). Hyperparameters were tuned "
           "with Optuna on grouped cross-validation (appendix); 5 seeds are bagged. The P10/P90 bands are empirical "
           "quantiles of out-of-fold errors per load class.\n\n"
           "**Expert rule on top of the ML (fleet observation):** speed sensors have a hard design-life ceiling of "
           "≈50,000 operating hours (lives end at 49,980–50,016 h), so when the input conveyor's sensor will reach it "
           "before the 5th predicted failure, a Speed_Sensor failure is inserted at that date (`Source = Rule`).\n\n"
           "**Downtime** = 36 h per failure (12 h failure day + one 24 h corrective day, constant in the data) + 24 h "
           "per planned-maintenance day (3 per year: 15 Mar, 15 Jul, 15 Dec). Corrective and planned are reported "
           "separately and as a total.\n\n"
           "**Models.** By default the notebook loads the models fitted by `train_all` (section 3) from a pinned "
           "commit and checks every file's SHA-256, so the result cannot change after submission. Set "
           "`RETRAIN_FROM_FLEET = True` to rebuild them here from the fleet file with the same code instead."),
        md("## 1. Input"),
        code(f'INPUT_PATH = "{input_path}"  #@param {{type:"string"}}\n'
             "# A local path, a mounted Drive path (/content/drive/...), or an http(s) URL. Leave empty to upload a file.\n\n"
             "RETRAIN_FROM_FLEET = False  #@param {type:\"boolean\"}\n"
             f'FLEET_PATH = "{a.fleet_path}"  #@param {{type:"string"}}\n'
             "# Only used when RETRAIN_FROM_FLEET is True: path or URL (Google Drive links work) of\n"
             "# 2026-09_compet_Student_Historical_Data_V03.parquet. Retraining fits 10 models (5 CV folds for the\n"
             "# calibration + 5 final seeds): ~35 min on a 22-core PC, several hours on a free 2-core Colab runtime.\n\n"
             f'ARTIFACTS_BASE = "{a.raw_base}"  # pinned commit: fitted models cannot change after submission'),
        md("## 2. Environment"),
        code("!pip -q install lightgbm==4.7.0 xgboost==3.2.0 pyarrow\n"
             "import os, sys, json, hashlib, urllib.request\n"
             "os.makedirs('conveyor', exist_ok=True)"),
        md("## 3. Workflow source code\n"
           "Identical to the tested package `src/conveyor/` in the submission repository:\n"
           "`io` (load + validate one conveyor), `features` (as-of features, causal), `labels` (future targets, "
           "training only), `evaluate` (sealed split, grouped CV, metrics), `models` (baselines + the direct ML model), "
           "`train` (fleet file → tables → calibration → final models), `forecast` (the tool)."),
    ]
    for mod in MODULES:
        cells.append(code(f"%%writefile conveyor/{mod}\n" + (SRC / mod).read_text()))
    cells += [
        md("## 4. Models: load the pinned fitted models, or retrain from the fleet file"),
        code("def fetch(rel):\n"
             "    dst = os.path.join('artifacts', rel)\n"
             "    os.makedirs(os.path.dirname(dst), exist_ok=True)\n"
             "    urllib.request.urlretrieve(f'{ARTIFACTS_BASE}/artifacts/{rel}', dst)\n"
             "    return dst\n\n"
             "def fetch_verified(rel, sha):\n"
             "    got = hashlib.sha256(open(fetch(rel), 'rb').read()).hexdigest()\n"
             "    assert got == sha, f'checksum mismatch: {rel}'\n\n"
             "pinned = json.load(open(fetch('manifest.json')))\n"
             "if not RETRAIN_FROM_FLEET:\n"
             "    for rel, sha in pinned['sha256'].items():\n"
             "        fetch_verified(rel, sha)\n"
             "    print(f\"{len(pinned['sha256'])} artifact files verified; models: {pinned['model_dirs']}\")\n"
             "else:\n"
             "    # Hyperparameters are the Optuna result (appendix); everything else is refit here.\n"
             "    for rel, sha in pinned['sha256'].items():\n"
             "        if rel.startswith('tuned/'):\n"
             "            fetch_verified(rel, sha)\n"
             "    fleet_path = FLEET_PATH\n"
             "    if 'drive.google.com' in fleet_path:\n"
             "        import gdown\n"
             "        fleet_path = gdown.download(fleet_path, 'fleet.parquet', fuzzy=True, quiet=True)\n"
             "    elif fleet_path.startswith('http'):\n"
             "        fleet_path = urllib.request.urlretrieve(fleet_path, 'fleet.parquet')[0]\n"
             "    from conveyor.train import train_all\n"
             "    train_all(fleet_path, 'artifacts')"),
        md("## 5. Run the forecast"),
        code("import pandas as pd\n"
             "from conveyor.forecast import forecast, plot_downtime\n"
             "pd.set_option('display.width', 200)\n"
             "if not INPUT_PATH:\n"
             "    from google.colab import files\n"
             "    INPUT_PATH = next(iter(files.upload()))\n"
             "elif INPUT_PATH.startswith('http'):\n"
             "    INPUT_PATH = urllib.request.urlretrieve(INPUT_PATH, 'input.parquet')[0]\n"
             "result = forecast(INPUT_PATH, 'artifacts')\n"
             "for k, v in result['summary'].items():\n"
             "    print(f'{k:36s} {v}')"),
        md("### Req. 2: next five failures"),
        code("result['next5']"),
        md("### Req. 3: downtime over the next three years"),
        code("s = result['summary']\n"
             "print(f\"Expected total downtime (3 years): {s['expected_total_downtime_h']:.0f} h \"\n"
             "      f\"= corrective {s['expected_corrective_downtime_h']:.0f} h + planned {s['expected_planned_downtime_h']:.0f} h; \"\n"
             "      f\"80% interval {s['total_downtime_P10_P90_h']}\")\n"
             "fig = plot_downtime(result['monthly'], f\"{s['conveyor']}: expected downtime after {s['last_observed_day']}\")"),
        code("result['monthly']"),
        md("## Appendix: hyperparameter search (run offline, not executed here)\n"
           "Optuna studies on 3-fold grouped CV over the non-sealed conveyors; the best parameters are the "
           "`artifacts/tuned/*.json` files used by `train.make('direct-tuned')`. It takes hours, so it is written out "
           "for the record only (it expects the training tables cached by the offline pipeline)."),
        code("%%writefile tune_offline.py\n" + TUNE_SCRIPT.read_text()),
    ]
    nb = nbf.v4.new_notebook(cells=cells, metadata={"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, a.out)
    print(f"wrote {a.out} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
