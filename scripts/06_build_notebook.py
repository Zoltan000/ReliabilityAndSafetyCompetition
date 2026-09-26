"""Generate the submission Colab notebook from src/ (single source of truth).

Each module is written by a %%writefile cell, so the notebook (and its printed PDF) contains the complete
code, and imports work exactly as in the tested package. Fitted artifacts are fetched from a pinned commit.

Usage: .venv/Scripts/python scripts/06_build_notebook.py --raw-base https://raw.githubusercontent.com/<owner>/<repo>/<sha>
"""
import argparse
from pathlib import Path

import nbformat as nbf

MODULES = ["__init__.py", "io.py", "features.py", "labels.py", "evaluate.py", "models.py", "forecast.py"]
SRC = Path("src/conveyor")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-base", default="https://raw.githubusercontent.com/OWNER/REPO/COMMIT_SHA")
    ap.add_argument("--team", default="TEAM MEMBER NAMES")
    ap.add_argument("--out", default="notebooks/Conveyor_Forecast.ipynb")
    a = ap.parse_args()

    md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
    cells = [
        md(f"# Industrial Conveyor Reliability: forecasting tool (Req. 2 + Req. 3)\n\n**Team:** {a.team}\n\n"
           "Point `INPUT_PATH` at a Parquet file with one conveyor's daily history (same columns as the fleet file) and "
           "run all cells. The tool uses every row, sorts by `Date`, detects the last observed day itself, and forecasts:\n"
           "- **Req. 2:** the next five failures (component and expected date / days from the last observed day);\n"
           "- **Req. 3:** expected downtime per month for the 3 years after the last observed day, cumulative curve and total.\n\n"
           "**Method (fitted offline on the full fleet, 284 conveyors × 20 years):** supervised models on features computed "
           "*as of* the last observed day. Labels were the known future of each training origin: days to each of the next 5 failures "
           "(XGBoost AFT, censoring-aware), the component of each (LightGBM multiclass), and failures per future month "
           "(LightGBM Poisson), hyperparameters tuned with Optuna on grouped cross-validation, 5 seeds bagged. "
           "Validation is grouped cross-validation where every test fold is a set of whole conveyors. "
           "**Expert rule on top of the ML (fleet observation):** speed sensors have a hard design-life ceiling of "
           "≈50,000 operating hours (fleet maximum 50,016 h), so when the input conveyor's sensor will reach it before the "
           "5th predicted failure, a Speed_Sensor failure is inserted at that date (marked `Source = Rule` in the table). "
           "Weather enters only through its known seasonal expectation. Downtime = 36 h per failure (12 h failure day + one "
           "24 h corrective day, constant in the data) + 24 h per planned-maintenance day (3 per year, 15 Mar / 15 Jul / 15 Dec)."),
        md("## 1. Input"),
        code('INPUT_PATH = "Example_P02CV27_6Years.parquet"  #@param {type:"string"}\n'
             '# A local path, a mounted Drive path (/content/drive/...), or an http(s) URL.\n'
             f'ARTIFACTS_BASE = "{a.raw_base}"  # pinned commit: artifacts cannot change after submission'),
        md("## 2. Environment"),
        code("!pip -q install lightgbm==4.7.0 xgboost==3.2.0 pyarrow\n"
             "import sys, os, json, hashlib, urllib.request\n"
             "os.makedirs('conveyor', exist_ok=True)"),
        md("## 3. Tool source code\nIdentical to the tested package `src/conveyor/` in the submission repository."),
    ]
    for mod in MODULES:
        cells.append(code(f"%%writefile conveyor/{mod}\n" + (SRC / mod).read_text()))
    cells += [
        md("## 4. Fetch fitted models (pinned commit, SHA-256 verified)"),
        code("def fetch(rel):\n"
             "    dst = os.path.join('artifacts', rel)\n"
             "    os.makedirs(os.path.dirname(dst), exist_ok=True)\n"
             "    urllib.request.urlretrieve(f'{ARTIFACTS_BASE}/artifacts/{rel}', dst)\n"
             "    return dst\n\n"
             "manifest = json.load(open(fetch('manifest.json')))\n"
             "for rel, sha in manifest['sha256'].items():\n"
             "    got = hashlib.sha256(open(fetch(rel), 'rb').read()).hexdigest()\n"
             "    assert got == sha, f'checksum mismatch: {rel}'\n"
             "print(f\"{len(manifest['sha256'])} artifact files verified; models: {manifest['model_dirs']}\")"),
        md("## 5. Run the forecast"),
        code("import pandas as pd\n"
             "from conveyor.forecast import forecast, plot_downtime\n"
             "pd.set_option('display.width', 200)\n"
             "if INPUT_PATH.startswith('http'):\n"
             "    INPUT_PATH = urllib.request.urlretrieve(INPUT_PATH, 'input.parquet')[0]\n"
             "result = forecast(INPUT_PATH, 'artifacts')\n"
             "for k, v in result['summary'].items():\n"
             "    print(f'{k:32s} {v}')"),
        md("### Req. 2: next five failures"),
        code("result['next5']"),
        md("### Req. 3: downtime over the next three years"),
        code("s = result['summary']\n"
             "print(f\"Expected total downtime (3 years): {s['expected_total_downtime_h']:.0f} h \"\n"
             "      f\"= corrective {s['expected_corrective_downtime_h']:.0f} h + planned {s['expected_planned_downtime_h']:.0f} h; \"\n"
             "      f\"80% interval {s['total_downtime_P10_P90_h']}\")\n"
             "fig = plot_downtime(result['monthly'], f\"{s['conveyor']}: expected downtime after {s['last_observed_day']}\")"),
        code("result['monthly']"),
    ]
    nb = nbf.v4.new_notebook(cells=cells, metadata={"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"}})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb, a.out)
    print(f"wrote {a.out} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
