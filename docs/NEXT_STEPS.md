# What to do next

Your list, in order. Commands run from the project root.

## 1. Add the course documents

Put the full rubric, submission instructions, due dates, team size, and AI-use rules in `inputs/`.

## 2. Film at the gym

- Use a tripod or fixed mount. This matters most.
- Keep the whole body, hands, and feet in frame through the top of the problem.
- Have the climber fill about a third or more of the frame height.
- Film at a slight angle so both arms are visible more often.
- Turn HDR video off. Do not use slow motion or zoom.
- Keep bystanders out of frame if you can.
- Record 3-5 attempts of 30-90 seconds, on two or more routes, ideally with a second climber.

Add the clips to `data/raw/`, add rows to `data/raw/manifest.csv`, then run:

```bash
.venv/bin/python scripts/run_feasibility.py --output-root data/feasibility_tripod
```

Watch each `overlay.mp4` and complete the checklist in its `report.md`.

## 3. Collect independent labels

1. Start the app and import a clip. Do not open its analysis first.

   ```bash
   .venv/bin/python scripts/run_app.py
   ```

2. Open the attempt, choose **Reference labeling**, and enter a non-identifying alias.
3. Label following `docs/ANNOTATION_GUIDE.md`. A second climber should label at least 20-30% of clips under a different alias without seeing your set.
4. Export **All real raters (CSV)**, combine into `evaluation/annotations.csv`, and fill `evaluation/dataset_manifest.csv` from its template. Fix the split by climber first.
5. Tune thresholds on development clips only, freeze them, then run:

   ```bash
   .venv/bin/python scripts/evaluate.py --split test --output evaluation/results/test.json
   ```

   ```bash
   .venv/bin/python scripts/evaluate.py --split test --events-file events_baseline_raw.json --output evaluation/results/test_baseline.json
   ```

## 4. Run a small user study

Aim for 5-8 beginners, using the tasks in `docs/EVALUATION.md` section 6: find a moment, explain what was measured, judge correctness separately from usefulness, and save a reflection. Record what actually happens; do not claim learning gains.

## Keyboard shortcuts

- **Reference labeling:** `[` mark start, `]` mark end, `,` and `.` step 0.1 s (outside text fields). Use Tab to reach Edit and Delete.
- **Hold editor:** Tab to a hold, arrow keys move it, Delete removes it.
