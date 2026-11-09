# What to do next

Your list, in order. Commands run from the project root.

## 1. Review the updated app

Open http://127.0.0.1:8317. IMG_4301 (teammate tripod) and IMG_7238 now have footwork analyses. Choose **Feet only**, select a timeline episode, inspect its ankle path and explanation, and use the chart or loop to rewatch it. Uncertain episodes are invitations to inspect the video, not proven errors. Earlier analyses and their notes remain selectable.

All currently available course guidance and permission for AI-assisted coding are recorded in `inputs/COURSE_UPDATE_2026-11-09.md`. The full rubric has not been released. Keep the project on option 3 (sports-behavior analytics), and add submission details when the course publishes them; their absence does not block the present work.

## 2. Improve recording conditions for future evaluation

Two supplied tripod clips have already been processed. Further footage should address the observed hidden hands and overlapping feet; simply using a tripod does not solve occlusion.

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
3. Do not label IMG_2532.MOV or IMG_2748.MOV yet; they stay reserved until methods are frozen. Label following `docs/ANNOTATION_GUIDE.md`. A second climber should label at least 20-30% of clips under a different alias without seeing your set.
4. Export each rater separately, or preserve **All real raters (CSV)** as the raw archive. Fill `evaluation/dataset_manifest.csv` from its template and fix the split by climber first. Score against one named rater or an explicitly adjudicated reference; several raters' raw events must never be pooled as duplicate ground truth. Keep original sets separate.
5. Tune thresholds on development clips only and freeze them. In these example commands replace `rater_1` with the actual reference alias; no human labels exist yet:

   ```bash
   .venv/bin/python scripts/evaluate.py --split test --reference-annotator rater_1 --output evaluation/results/test.json
   ```

   ```bash
   .venv/bin/python scripts/evaluate.py --split test --reference-annotator rater_1 --events-file events_baseline_raw.json --output evaluation/results/test_baseline.json
   ```

## 4. Run a small user study

Aim for 5-8 beginners, using the tasks in `docs/EVALUATION.md` section 6: find a moment, explain what was measured, judge correctness separately from usefulness, and save a reflection. Record what actually happens; do not claim learning gains.

## Keyboard shortcuts

- **Reference labeling:** `[` mark start, `]` mark end, `,` and `.` step 0.1 s (outside text fields). Use Tab to reach Edit and Delete.
- **Hold editor:** Tab to a hold, arrow keys move it, Delete removes it.
