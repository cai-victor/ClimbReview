# Training report: experimental wrist-motion forecast

Status: **experimental**. Standalone report with charts: [training_report_forecast-v1.html](training_report_forecast-v1.html).

**Finding:** the learned Ridge model was only slightly better than a do-nothing baseline on held-out public clips, and it tied that baseline on your own steady-camera clips. It almost always predicted very little motion. A simple baseline remains a reasonable choice.

## What this is, and what it is not

| Term | Meaning here |
| --- | --- |
| Pose inference | MediaPipe's pretrained model. Its weights are frozen and were not trained here. |
| Trained motion forecast | A Ridge model predicting where a tracked wrist moves relative to the hips over the next 0.5 s. |
| Unvalidated coaching interpretation | Fixed wording on event cards. The forecast does not feed it. |

Targets are later pose estimates, which are themselves noisy, so these errors are not human-verified. Nothing here measures technique, event correctness, injury risk, or climbing improvement.

## Data

| Item | Value |
| --- | --- |
| New public clips | 22, downloaded 249.8 MB (cap 500 MB) |
| Licenses | CC0, CC BY 1.0, CC BY 3.0, CC BY-SA 3.0, CC BY-SA 4.0, verified per file against the Wikimedia Commons API |
| Groups | 18 from the new clips (test 5, train 13). Grouped by climber when known, otherwise by recording |
| Extra train-only clips | 3 earlier public development clips |
| Separate stress set | Your 5 development clips, never trained on |
| Reserved clips | IMG_2532 and IMG_2748 were not used |

Sources and split: `config/public_training_sources.json`, `config/public_training_split.json`. Test groups: anna_stoehr, mina_markovic, sergei_luzhetskii, unknown_chiba_2025, unknown_finale_m_6666.

**Main limitation:** public climbing video almost always has a moving camera. Only 187 steady-camera training windows and 48 held-out steady windows (one clip) exist. The model therefore trained on all reliable windows, with results reported by camera condition. Body-relative targets cancel camera translation but not zoom or rotation.

Venues and events partly overlap between splits, so unseen-gym generalization was not tested. Unknown climbers are separate groups, so one person could appear in more than one group.

## Method

- **Input:** 1.0 s of history (11 samples at 10 Hz), all required landmarks valid and contiguous. No smoothing and no future values.
- **Features (48):** wrist, elbow, and shoulder positions relative to the hip midpoint, wrist velocities over 100-1000 ms, visibility summaries, torso-length stability. Scale is the median torso length in the history only.
- **Target:** change in wrist-minus-hip-midpoint from t to t+0.5 s, in history torso lengths.
- **Model:** separate left and right scikit-learn Ridge pipelines, with scaling fitted on training data. Alpha was chosen by grouped 4-fold cross-validation inside training groups. The first grid's best value was at its edge, so it was extended, using training data only; alpha 100,000 was selected for both sides.
- **Baselines:** persistence (no body-relative motion) and constant velocity (500 ms window, chosen on training groups).

## Results

Error is the Euclidean distance between predicted and observed displacement, in torso lengths (L), not centimeters. Every method uses identical examples. Windows overlap and are correlated, so example counts are not independent observations. Group counts are the meaningful sample size.

| Set | Examples | Clips | Groups | Ridge MAE | Persistence MAE | Constant velocity MAE |
| --- | --- | --- | --- | --- | --- | --- |
| Held-out, all reliable windows | 1,332 | 6 | 5 | 0.3228 | 0.3282 | 0.4747 |
| Held-out, steady camera | 48 | 1 | 1 | 0.2818 | 0.2911 | 0.3599 |
| Held-out, camera moving | 1,284 | 6 | 5 | 0.3243 | 0.3296 | 0.4790 |
| Your clips, steady camera | 681 | 5 | 5 | 0.1257 | 0.1234 | 0.1743 |
| Your clips, camera moving | 1,522 | 5 | 5 | 0.1763 | 0.1756 | 0.2573 |

| Held-out, all windows | Ridge | Persistence | Constant velocity |
| --- | --- | --- | --- |
| Pooled RMSE (L) | 0.5008 | 0.5075 | 0.7386 |
| Macro-group MAE (L) | 0.3072 | 0.3129 | 0.4431 |
| Macro-clip MAE (L) | 0.3162 | 0.3215 | 0.4555 |

Group-level held-out MAE (L):

| Group | Examples | Ridge | Persistence | Constant velocity |
| --- | --- | --- | --- | --- |
| anna_stoehr | 377 | 0.366 | 0.370 | 0.525 |
| mina_markovic | 278 | 0.361 | 0.364 | 0.583 |
| sergei_luzhetskii | 133 | 0.202 | 0.210 | 0.206 |
| unknown_chiba_2025 | 266 | 0.323 | 0.330 | 0.468 |
| unknown_finale_m_6666 | 278 | 0.284 | 0.290 | 0.433 |

**Reading these results:** Ridge was lower than persistence in all 5 held-out groups, but only by about 1-2%, and with 5 groups I make no significance claim. The chosen regularization is very strong, and the example plots show predictions close to zero, so the model mostly learned to predict little motion. Constant velocity was clearly worse: over 0.5 s, recent wrist speed did not extend into future motion. On your clips Ridge and persistence were essentially tied, and persistence was slightly better pooled on steady-camera windows.

## Reproduce

```bash
.venv/bin/python scripts/collect_public_training.py
```

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/public_training/manifest.csv --output-root data/public_training/runs --provenance public_development_sample --overwrite
```

```bash
.venv/bin/python scripts/build_forecast_dataset.py
```

```bash
.venv/bin/python scripts/train_forecast.py
```

```bash
.venv/bin/python scripts/evaluate_forecast.py
```

```bash
.venv/bin/python scripts/report_forecast.py
```

`freeze_public_split.py` refuses to overwrite the frozen split. `evaluate_forecast.py` keeps a ledger and refuses a changed model on the test split without an explicit flag. The evaluation ran once (`data/public_training/results/test_access_log.jsonl`).

Artifacts: model `data/public_training/models/forecast-v1.json` (SHA-256 `15c928634390620b622a77aa7c76d392d346854f1a34830c2ca47f853ad3e5d9`), dataset `data/public_training/dataset/`, results `evaluation/forecast/results_forecast-v1.json`. Dependencies: scikit-learn 1.9.1, NumPy 2.5.4, Python 3.12.16, seed 317.

Tests in `backend/tests/test_forecast.py` cover no future leakage, group separation, missing targets and gaps, units and time, baselines, deterministic refits, and model save and load.

## Next steps that would help

Tripod footage from several climbers would give steady-camera windows, and a longer horizon or a nonlinear model could then be tried. Any new method needs a fresh test set, because these held-out groups have now been used once.
