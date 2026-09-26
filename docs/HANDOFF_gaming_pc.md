# Handoff: continue the pipeline on the gaming PC (agent A)

You are picking up the forecasting work on the team's gaming PC (Ryzen 9 9900X, RTX 5090). The earlier
sessions ran on a laptop that was too slow for the heavy steps. Read `CLAUDE.md` first: it holds the spec
summary, the confirmed data facts, the Req. 1 findings and the pipeline run order. `docs/PLAN.md` is the
plan of record. `docs/SESSION_2026-09-26_leak_fix_and_gap_analysis.md` covers the latest teammate session.

**Your job: run, verify and finish the pipeline** (plan steps 4, 6 and 7). A second agent (B) works in
parallel from `docs/IMPROVEMENTS.md` on the branch `improvements`. Stay on `main`, and don't edit
`src/conveyor/features.py` or `src/conveyor/models.py` yourself. Model or feature changes go through
agent B's branch, which is merged only when grouped CV shows a gain. If you find a bug in those files,
fix it minimally on `main` and note it in the commit message so B can rebase.

## Where things stand (2026-09-26)

| Plan step | Status |
|---|---|
| 1. Environment + EDA checks | Done. Facts in `CLAUDE.md` |
| 2. Feature/label tables | Done. Parity asserts pass (max abs diff 0). The cache is **not** in git: rebuild it |
| 3. Baselines in grouped CV | Done. `eb:1000`: 3-year downtime error 9.1% |
| 4. Direct ML + tuning + robustness | **In progress.** One `direct` run: 3-year downtime error 4.5% (conveyors < 1 year old: 5.9%). Not yet re-verified after the teammate's constant fix |
| 5. Req. 1 analysis + figures | Mostly done. Slide 2's accuracy chart is missing |
| 6. Final fit → sealed test → artifacts → notebook | Scripts written; nothing run yet. The sealed test is **unspent** |
| 7. Slides + submission | Builder written; needs team names and the accuracy chart |

Known weakness: the component classifier (`c1_acc` 0.859) is slightly worse than always predicting
"Bearing" (0.864). Agent B owns that fix.

## 0. Setup (Windows, PowerShell, repo root)

```powershell
git pull
# Copy 2026-09_compet_Student_Historical_Data_V03.parquet into the repo root (gitignored, ~144 MB).
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
$env:CONVEYOR_XGB_DEVICE = "cuda"      # XGBoost AFT trains on the GPU; LightGBM uses the CPU
$env:PYTHONIOENCODING = "utf-8"        # DuckDB table printing on Windows
```

- Check that XGBoost sees the GPU: `.\.venv\Scripts\python -c "import xgboost as xgb, numpy as np; xgb.train({'device':'cuda'}, xgb.DMatrix(np.random.rand(100,3), label=np.random.rand(100)), 2); print('cuda ok')"`.
  If it fails, drop the env var; everything runs on the CPU.
- **Log redirection:** `*>` in PowerShell writes UTF-16 logs that grep can't read. Run long jobs in the
  background, piping through `Out-File -Encoding utf8`, or use the Bash tool with `> file 2>&1`.

## 1. Rebuild tables and re-verify the headline CV numbers

```powershell
.\.venv\Scripts\python scripts\01_build_tables.py
.\.venv\Scripts\python scripts\03_cv.py eb:1000 direct --seed 0 --folds 5
```

- `01` must print `max abs diff = 0` three times (truncation parity plus both example files). If not, stop and fix it.
- Compare the new `direct` row in `outputs/experiments.csv` against the one timestamped `2026-09-26T12:16:32`.
  Expect ≈4.5% `all:dt_tot_pct`. This rebuild also adds the `brg_whaz_*` bearing-age features, which the
  old row didn't have, so a small improvement is plausible. Update the numbers quoted in `CLAUDE.md`.

## 2. Robustness and ablation runs (each appends a row to `outputs/experiments.csv`)

```powershell
.\.venv\Scripts\python scripts\03_cv.py direct-nocm direct-nobrg direct-noclim direct-aft:logistic direct-aft:extreme --seed 0
.\.venv\Scripts\python scripts\03_cv.py eb:1000 direct --lopo                 # leave-one-plant-out (12 folds)
.\.venv\Scripts\python scripts\03_cv.py direct --seed 1; .\.venv\Scripts\python scripts\03_cv.py direct --seed 2
```

- Pick the spec with the lowest `all:dt_tot_pct`, with `all:t5_logerr` and `age<1y:*` as tie-breakers.
  Keep an ingredient only if removing it hurts. Record the decision and the numbers in `CLAUDE.md`.
- **Leave-one-plant-out** tells us whether the model generalizes to an unseen plant. `Bearing_Count`
  uniquely identifies each plant, so the model may be memorizing plants. If LOPO is much worse than
  grouped CV, report that to the user. Agent B's backlog has the fix.
- Optuna tuning is agent B's item (`scripts/04_tune.py`, not yet written). If B has merged it by then,
  run it here: it's the main reason to use this PC.

## 3. Final fit and the one-time sealed test (only after the user agrees the model is final)

`05_fit_final.py` spends the sealed test. It must run **once**, on the final spec, so ask the user before running it.

```powershell
.\.venv\Scripts\python scripts\05_fit_final.py --spec <winner> --seeds 5
```

- It prints the sealed-test table (saved to `outputs/sealed_test.csv`), writes `artifacts/model_seed*/`
  plus `artifacts/manifest.json` (with SHA-256 hashes), and uses the OOF file
  `outputs/cache/oof_<spec>_gkf5s0.npz` for the P10/P90 calibration.
  Pass `--oof` if the winner came from another seed.
- Smoke-test the tool on both example files:
  `.\.venv\Scripts\python -c "import sys; sys.path.insert(0,'src'); from conveyor.forecast import forecast; r=forecast('Example_P02CV27_6Years.parquet'); print(r['summary']); print(r['next5'])"`.
  P02CV27 is in the sealed set, so this demo doesn't leak.
- Commit `artifacts/` (it's small: text/JSON models).

## 4. Notebook, figures, slides

- **Public submission repo:** ask the user to create it, or to approve creating it (e.g. with `gh repo create`). It should hold only
  `artifacts/` and `notebooks/`, and must be public for Colab. Don't make the team repo public. Push, note the commit SHA, then:
  `.\.venv\Scripts\python scripts\06_build_notebook.py --raw-base https://raw.githubusercontent.com/<owner>/<repo>/<sha> --team "<names>"`.
  Commit the generated notebook to the submission repo as well.
- **Slide 2 accuracy chart:** add an `accuracy_plot()` to `scripts/07_figures.py` that reads `outputs/experiments.csv`.
  - Show 3-year downtime % error for own-rate vs. `eb:1000` vs. the final model, overall and for conveyors < 1 year old.
  - Use one chart, a single axis, direct labels, the palette already defined in the file, and the file name `outputs/figures/accuracy.png`.
  - Consider adding the frailty finding (r = 0.93 between the first and second half of each conveyor's life) to a slide.
- Then run `07_figures.py` and `08_make_slides.py --names "<all team names>"`. Check: exactly 2 slides, names on both, no title slide.
- **Colab acceptance test:** run the generated notebook top to bottom in a fresh Colab runtime on both example files. The
  outputs must match the local `forecast()`. Then the user prints it to PDF, and the 7-day freeze starts.

## Rules that matter

- Features must stay causal. `01_build_tables.py` asserts it, so never skip or weaken those asserts.
- The sealed conveyors are scored exactly once (step 3).
- Commit `outputs/experiments.csv` after each batch of runs. End commit messages with the attribution line in the
  harness reminder. Pushing to `main` is the team's normal workflow.
- Open questions for the organizers (the user relays them): the scoring metric for Req. 2 and 3; the email address and deadline;
  whether the hidden conveyor comes from a fleet plant and falls within 2005–2024.
