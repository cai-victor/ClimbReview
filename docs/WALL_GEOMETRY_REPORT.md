# Wall angle from the bolt grid, November 12, 2026

**The app now reads the wall's angle from its grid of bolt holes and measures route distances on the wall plane instead of in the picture. On IMG_7238 this changes distances by about -15% at the bottom of the route and +20% at the top. It is checked against known synthetic cameras, not against tape-measured walls, so real-world accuracy is unmeasured.**

## How it works

1. **Find dots.** Small dark round spots are picked out of the clear wall picture. Many are not bolt holes.
2. **Fit a grid.** Starting near your holds, the fit finds the two shortest repeating steps between neighboring dots, then walks outward giving each dot a grid position while letting the step size drift with perspective. A plane-to-picture mapping is fitted to those positions, keeping only dots that agree within 3 pixels.
3. **Measure on the plane.** Hold positions are mapped onto the wall plane, where equal grid steps are equal distances. The climber's torso, arm, and leg lengths are measured on the same plane, so reach is compared like with like.
4. **Report the angle.** The same mapping gives the angle between the wall and the camera's view.

The fit needs at least 30 agreeing dots with a median error of 2 pixels or less. Otherwise it reports that it could not correct, and distances stay as they appear.

## What uses it

- **Candidate sequences** in the review and on the Plan a route page. A checkbox on that page turns the correction off.
- **Suggestion cards** gain a row with the movement measured on the wall plane next to the picture value. The rules that decide which cards appear still use picture values, so existing cards did not change.
- **The hold editor** has "Show the fitted bolt grid", which draws the dots the fit used so you can see whether they sit on real holes.

## Assumptions and limits

- **Square grid.** The bolt holes are assumed to form a square grid, straight or diagonal. A rectangular or triangular pattern would be stretched wrongly. On four of your walls the lens focal length implied by this assumption was 750 to 1150 pixels, which is believable for a phone, and that supports it there without proving it.
- **One flat face.** The correction applies to the face where the grid was fitted. Holds on volumes, or on another face, are off that plane.
- **Applied only with evidence.** At least 80% of the holds must lie inside the fitted area, within 3 grid steps of it, or among holes that follow the same grid. Otherwise nothing is corrected and the app says why.
- **Angle is relative to the camera, not gravity.** It equals the wall's overhang only if the phone was level and upright. No overhang in degrees is claimed.
- **Relative, not absolute.** The grid's real spacing is unknown, so size still comes from the tracked climber or a marked scale line.
- **The body is assumed close to the wall.** Joints are mapped as if they lay on the wall plane.
- **Not used for detecting events.** Movement episodes and their thresholds still use picture distances with one scale per attempt.

## Results on your marked routes

`scripts/check_wall_geometry.py`, read-only. Angles are relative to the camera.

| Route | Bolt holes used | Holds on the fitted face | Corrected | Wall turned from the camera | Wall distance over picture distance, bottom third / top third |
| --- | --- | --- | --- | --- | --- |
| IMG_7238 | 509 | 11 of 11 | yes | 23° (top leans 16° away) | 0.85 / 1.20 |
| IMG_7549 | 514 | 3 of 3 | yes | 25° (mostly sideways) | 0.94 / 0.95 |
| IMG_7768 | 220 | 11 of 17 | no | 17° | not applied |
| IMG_7547 | none agreed near the holds | | no | | not applied |

- **IMG_7238:** the picture shrinks the top of the route by about 36% compared with the bottom. The largest gap between neighboring holds changes little (2.00 to 2.07 torso lengths), because it lies mid-route.
- **IMG_7768:** the six lowest holds sit below the fitted area, where large holds hide the bolt holes. They are probably on the same face, but the app could not show that, so it left the route uncorrected.
- **IMG_7547:** the route crosses two faces, so no single plane applies.

In an AI-assisted look at one overlay image, the fitted dots sat on real bolt holes on all five walls checked.

## Verification actually run

| Check | Result |
| --- | --- |
| Backend tests, including 13 new ones drawn from known cameras: equal wall distances recovered from a 25° tilt within 3%, angle within 3° for four camera poses, a square-on wall, diagonal grids with 25% of holes missing and 150 stray dots, random dots and blank walls refused, two-face walls, correction withheld across faces, planner distances, and a speed guard | 303 passed |
| Browser specs, including the real IMG_7238 flow: correction applied from 509 bolt holes, the note shown with its assumption, the uncorrected option, and the fitted grid drawn in the editor | 12 passed |

A defect was found and fixed during this work: on a speckled floor, estimating the grid step took 155 seconds and made the review page hang. It now takes under 0.1 seconds, and a test guards it.
