# Hold suggestions and photo planning, November 11, 2026

**The app can now suggest hold outlines from a tapped color, import a photo of a climb, and plan candidate sequences from your height and wingspan. Suggestions and plans are unvalidated: they were checked against one hand-marked route and synthetic pictures only.**

## How to use it

1. Start the app and open http://127.0.0.1:8317.

   ```bash
   .venv/bin/python scripts/run_app.py
   ```

2. Open a climb, or choose a JPG or PNG photo of a wall on the first screen. A photo cannot be analyzed for movement.
3. Choose **Mark holds**, create a map, then **Suggest by color** and click directly on one hold of your route. Dashed pink outlines are suggestions only. Click one to add it, or **Add all**, then delete wrong ones and add missed ones by hand.
4. Set each hold's role (start, finish) and use (hands, feet).
5. Choose **Set scale**, click two points on the wall whose real distance you know, and enter it in centimeters.
6. Choose **Plan a route**, enter height and wingspan, and choose **Plan**.

## What each part does and cannot do

**Suggest by color.** It groups pixels whose color is close to the tapped point and outlines each group. It is not hold recognition. It cannot tell a hold from tape or a tag of the same color, cannot find volumes painted like the wall, and merges holds that touch. Tapping bare wall is refused. For a video, it first builds a wall picture from the median of up to 15 frames, used only when the background shows the camera stayed put, so a moving climber is mostly removed. Nothing is saved until you confirm it.

**Photo import.** A photo becomes a one-second still clip, so the same frame, hold, and planning tools apply. Its stored orientation is respected. HEIC photos are not supported; export them as JPG first.

**Planning from measurements.** Reach lengths come from average body proportions: torso 0.288 of height, hip to ankle 0.491 of height, and shoulder to mid-palm 0.339 of wingspan. The first two are the widely reproduced Drillis and Contini segment ratios as I recall them from Winter's biomechanics text; a search confirmed the source but not the exact figures. The arm figure is this project's own derivation from those ratios, rescaled to measured wingspan. Individual proportions differ, so treat the lengths as estimates within several centimeters. Height and wingspan stay in your browser and are not stored with the climb.

**Scale.** One marked line sets centimeters per pixel for the whole picture. Perspective is not corrected, so a photo taken from below makes upper reaches look shorter than they are, and the plan is optimistic near the top. The planner's other limits are unchanged: no hold quality, wall angle, balance, or dynamic moves, and no candidate is the best or easiest beta.

## Development check on one real route

`scripts/check_hold_suggestions.py` used each of your 11 hand-marked IMG_7238 holds once as the tapped seed, with the marks hidden. It is read-only and is not an accuracy study.

| Tapped seed | Marks found, of 11 | Suggestions matching no mark |
| --- | --- | --- |
| Hold 2 (normal) | 10 | 0 |
| Hold 11 (normal) | 10 | 2 |
| Hold 1 (normal / loose) | 6 / 10 | 0 / 0 |
| Holds 5, 8, 9, 10 (normal) | 9-10 | 17-21 |
| Holds 3, 4, 7 | refused | the mark's center was pale, chalked, or wall-colored |

- A saturated tap works well on this route. A pale or chalky tap either floods the result with extras or is refused.
- A mark counted as found if a suggestion's center lay within 1.5 radii, which is lenient. Two touching holds at the bottom came back as one large outline.
- Suggestions matching no mark are not necessarily wrong, since only your route was marked.
- The clean wall picture was built from 15 frames and left only a faint ghost of the climber (AI-assisted look at one image).

## Verification actually run

| Check | Result |
| --- | --- |
| Backend tests, including 13 new: same and other colors, existing marks, wall taps, specks, tolerance, clean wall with moving climber and moved camera, measurement math, scale and aspect ratio, short versus tall climber, photo import, unreadable photo, full API flow | 270 passed |
| Browser specs, including a new photo flow: upload, refused wall tap, suggestions, confirm one and all, manual hold, missing-scale message, two-click scale, plan, shorter climber gets no sequence, phone width | 11 passed |

The browser photo is a drawn synthetic wall. No real wall photo was imported, and no plan from measurements was tried on a real route, because your maps have no start, finish, or scale yet. Database backup before the change: `data/app/backups/climbreview_before_route_tools.sqlite`.

## Clear wall picture (added November 11)

The hold editor and planner now show one picture of the wall combined from across the video, instead of a single frame with the climber in it. It takes up to 25 moments from the analysis, cuts the tracked climber out of each using a box around the tracked joints, and keeps the median of the clear views for every pixel. A "Clear wall picture" checkbox switches back to the original frame.

- **Small camera shifts are corrected.** Each frame is lined up with the reference frame using background features before combining, and a frame that cannot be lined up reliably is left out. If fewer than 5 remain, the editor shows the single frame and says so. Large pans or a walking camera are not supported.
- **Works best with an analysis.** Without one, a plain median is used, which can leave a ghost where the climber stays for a long time.
- **Reports what it could not clear.** A pixel needs 3 clear views. Areas without them show the original frame, and their share is stated under the picture.
- **Limits.** A second person, a swinging rope, or chalk marks that change during the climb are not removed. The picture reflects typical lighting across the clip, not one instant.

On your two tripod clips, both pictures used 25 frames and every pixel was clear at least 3 times. In an AI-assisted look at the two results, the climber was fully removed on both, and the earlier untracked method had left a visible ghost on IMG_7238. Comparison image: `data/tripod_nov09/wall_pictures/compare.jpg`. Building takes about 5 seconds the first time and is then cached.

Verification after this addition: 274 backend tests and 11 browser specs passed, including the editor showing the combined picture for real IMG_4301.

On IMG_7768, whose map uses the very first frame, the camera shifted about 35 pixels afterward. 24 of 25 frames were shifted into line, the climber was removed, and holds she had covered became visible (AI-assisted look at one image: `data/tripod_nov09/wall_pictures/7768_compare.jpg`). About 2.9% of that picture, mainly an edge strip, shows the original frame. Final verification: 276 backend tests and 11 browser specs passed.

