# Morning report (checkpoint, updated during the run)

Run in progress. Status: analytics, API, worker, and exports are built and tested; the frontend is being built next.

## Personal-footage findings so far (phone01-05)

No reserved clip (IMG_2532, IMG_2748) has been opened or used. Artifacts: `data/feasibility/<clip_id>/contact_sheet.jpg`, `overlay.mp4`, `report.md`, and `data/feasibility/summary.csv`.

- Upright orientation is correct on all five; four are portrait (`rotation=-90`), IMG_1314 is landscape.
- All are HLG HDR. They are now converted with a project LUT (tested against known signal values), not relabeled.
- IMG_1314 excerpt: `data/raw/derived/phone03_a1.mov`, original time = canonical time + 57,940 ms.
- A pose is returned on 94-100% of samples. Sampled overlays were visually well aligned on the four portrait clips.
- Coverage for low movement is 3-30%, well below the provisional 70% target. **The feasibility gate is not met.**
- Main cause: handheld camera drift, excluded because image-space stillness cannot be trusted while the camera moves. Second cause: wrists often low-visibility in back views.
- A tripod is the highest-value change for the next gym session.
