# ClimbReview status

Last updated 2026-11-25 after packaging ClimbReview as a Mac app. Start with `docs/WALL_GEOMETRY_REPORT.md`, `docs/AUTOMATION_REPORT.md`, `docs/ROUTE_TOOLS_REPORT.md` and `docs/PERFORMANCE_REPORT.md` for the latest work, `docs/FOOTWORK_REPORT.md` for foot tracking, and `docs/MORNING_REPORT.md` for the earlier overnight run.

## Bottom line

The local app, analysis pipeline, two detectors, review flow, exports, evaluation tooling, blind reference labeling, and manual reference-frame hold marking are implemented and tested. An experimental wrist-motion forecast and a camera-compensation study also exist, separately from the default analysis. **The provisional feasibility gate is not met** on the user's phone clips, because of camera motion on earlier handheld recordings and hidden wrists even on the new tripod clips. No independent human labels or user study exist, so **event accuracy is unknown**.

## Mac app (latest, 2026-11-25)

`bash desktop/build_macos.sh` builds `dist/ClimbReview.app` and a `.dmg` with PyInstaller 6.22.3 and pywebview 6.2.1 (`desktop/requirements-desktop.txt`). The app opens in its own window and starts the same API (in a thread) and the same single worker (the app run with `--worker`). Data goes to `~/Library/Application Support/ClimbReview` (D119). macOS only for now, by the user's choice. Built on macOS 15.7.4 (Apple Silicon); the newest minimum OS inside the bundle is 14.0.

**Code changes outside `desktop/`:** `settings.py` finds resources and the data folder in a packaged build; `video.tool_path` looks for the bundled FFmpeg first; the worker's single-instance lock also works on Windows (`msvcrt`), which removes the only POSIX-only import.

**Problems found while building, and fixed:**
- PyInstaller relinked FFmpeg against OpenCV's older bundled GLib, and FFmpeg failed to start (`_g_string_copy` not found). FFmpeg, FFprobe and their 75 libraries are now copied into the finished app untouched (`desktop/add_ffmpeg.py`), and the app is signed again ad hoc.
- MediaPipe imports matplotlib at load time; excluding matplotlib made every analysis fail at pose extraction. Caught by a real import, now covered by `--self-test`, which the build runs.
- Python's signal handlers do not run while the window's event loop runs, so a window process killed from outside could leave the worker behind. The worker now stops by itself when its parent disappears.

**Checks run on the built app** (scratch data folder, not the live data):
- `--self-test` passed: pose model with its checksum, MediaPipe, FFmpeg with libx264, FFprobe, frontend and window library.
- IMG_7859 (a development clip already used in earlier checks) was imported and analyzed in 30 s. All 15 events match the developer app's run on the same clip exactly (same config hash, same start and end of every event). JSON, CSV and HTML exports respond.
- In the window (computer-use, AI-assisted): the library, the review page, video playback with the pose overlay, and the More menu all work. An export opens the macOS Save dialog; the file was not saved, so the saved file's name and extension are not confirmed. Saved state survives a relaunch.
- Quit from the menu, and a forced kill, both leave no ClimbReview process running. A job cut off this way is marked interrupted on the next start.
- `pytest` 340 passed after the changes. Playwright was not re-run (the frontend did not change).

**Installing it (same day, after the user asked for an app instead of the browser):**
- `bash install.sh` now ends, on a Mac, by building the app and putting it in `/Applications` (or `~/Applications` when that is not writable), then opening it. If the build fails, the install still finishes and `bash start.command` (browser) works as before. `CLIMBREVIEW_NO_APP=1` skips the app.
- `scripts/make_release.sh` now also writes `dist/ClimbReview-<version>-macOS.dmg`: the app, an Applications shortcut to drag it onto, "Read me first.txt" (first-open steps) and "Licenses.txt" (FFmpeg is GPL; MediaPipe and OpenCV Apache 2.0). The zip now carries `desktop/` so `install.sh` can build the app from it.
- README and the tester guide now describe the app first and the browser as the fallback.
- `spctl` rejects the app (ad-hoc signature, not notarized), so a downloaded copy needs System Settings > Privacy & Security > Open Anyway once; on macOS 15 right-click > Open no longer bypasses this. A copy built on the same Mac by `install.sh` has no quarantine flag and opens directly.

**Not done:** no Developer ID signing or notarization (it costs money). No Intel or universal build, no Windows build, no app icon. Not tried on a second Mac, and the Open Anyway steps were not walked through on a quarantined copy.

## Second whole-app pass: details, search, scale check (2026-11-21)

A fresh upload was taken through import, setup, analysis and review on a separate scratch copy of the app (public clip, scratch data folder, nothing added to the live data). The live app's pages were opened again at desktop and phone widths.

**Added:**

- **Attempt details from the review.** A line under the title shows the problem, grade, outcome and climber, with "Edit details" opening a dialog for the name, problem, grade, outcome and climber. Outcome has one-tap choices (Finished, Fell, Not finished) plus free text, here and on the setup and Compare forms. Saving re-reads the review, so marking a climb Finished changes "You left the wall" to "You came down ..., after finishing" (D115). Problem is one name for the list and for Compare (D118).
- **Search on the attempts page** (shown with more than six attempts): matches name, problem, grade, outcome, climber and date.
- **Scale check** (D117): a scale line that makes the climber's torso implausible is flagged in the hold editor and the planner. It flags IMG_7547 (17 cm) and the 6 cm line on IMG_7768 (22 cm); the 15 cm line on IMG_7768 (57 cm) passes.
- **Portrait videos** get a narrower video column and a wider reading column.

**Checked and left as they were:** the setup, progress and empty-library screens, the opened opportunity card, and the hold editor with a hold selected. No console errors on any page.

**Noticed, not changed:** the live data has a second copy of IMG_7852, added on 2026-11-18 at 19:42 UTC, not by my scripts. It was left alone.

**Current verification:** `pytest` 340 passed. Playwright, 12 specs, passed; the smoke spec now also saves details from the dialog and checks them after a reload. Search was checked by hand on the live list, not by a spec.

## Whole-app pass: interface and accuracy (2026-11-18)

Every page was opened at desktop and phone widths, and the review cards of all 17 clips were read against the video. Judgments about what the videos show are mine from drawn skeletons and frames (AI-assisted), not human labels.

**Accuracy, checked and fixed:**

- IMG_7547 is recorded as Finished, but its review offered "You left the wall at 00:35.9 ... If this was a fall". The ending now follows the recorded outcome (D115): a finished climb says "You came down at 00:35.9, after finishing" and gets no card; "fall" gives "You fell at ...".
- A stop listed the movement that brought the climber into it as something done during it (IMG_7859, IMG_7547, IMG_7238, IMG_4301, IMG_7549). Only movements that start inside a stop, or mostly happen inside it, are counted now (D116).
- High-step cards on IMG_7865 (00:11.3) and IMG_7852 (00:05.3) were compared with frames and match the video: the hips stay beside the high foot until a late rock-over.
- The high step on IMG_7547 at 00:24.1 lands with the foot above the hips on a steep wall. The card's advice may not fit a hook or rock-over there; it was left unchanged because frames alone do not show which it was.

**Interface:**

- Attempts are shown as picture tiles; "Ready to review" is no longer printed on every attempt, only states that need action are.
- The Evidence tab shows each detected movement as one paragraph; the interpretation, chart and rating form open with "More, and rate this detection", or by themselves for the selected movement or one already rated. The page for IMG_7547 went from about 8,100 to 4,800 pixels tall.
- On a phone the review tabs wrap onto two rows instead of being cut off.
- Opportunity filters show only when there are both foot and hand cards, and never as a disabled "Hands 0".
- The route planner shows the marked route picture before you plan, not an empty box.
- Checked and left as they were: the video stays in view while the right column scrolls, and the page background covers long pages (it looked cut off only in full-page screenshots).

**Current verification:** `pytest` 339 passed. Playwright, 12 specs, passed.

## A new clip through the whole app (2026-11-16)

IMG_7859.MOV (35 s, 4K HLG, portrait) was downloaded from the shared Drive folder into `data/new_vids/new vids 1/` (ignored by git), imported, analyzed, reviewed, and given a hold map. It had not been used before and is now a development clip. Every judgment below comes from comparing the app's output with frames and drawn skeletons by eye (AI-assisted); no human labelled the clip.

**What the app got right:** the camera was reported still (it is); the climb was counted from 00:03.8, when the low foot leaves the floor; both stops match the video; the combined wall picture removed the climber cleanly; after the map-against-video check, every foot placement fell on the hold or volume the foot is on in the video, and both hands were matched to the finish at 00:33.5.

**Mistakes found and fixed:**

- A card said "Hips stayed left of your left foot after a high step" and advised standing up on that foot. The foot had been stepped sideways under an already straight leg, so there was nothing to stand up on. Such steps are now not flagged (D113). The same rule removed one card each on IMG_4301 and IMG_7238, both a trailing foot joining the other; high-step cards across the 17 clips went from 11 to 8.
- Tapping the cream finish hold (on a cream wall) or a volume with "Find holds by color" answered "Tap directly on a hold". The message now says a hold the same color as the wall cannot be found by color and should be added by hand.
- The planner found no sequence for this route. The climber crossed the volumes with one hand flat on the wall, which the planner cannot represent. The explanation now names this case.

**Not fixed:** the planner still cannot plan a slab section where a hand is on the bare wall, so this route has no planned sequence. Color search cannot find the finish hold or the volumes on this wall.

**A wrong fix that was removed:** I first read the tracker's crossed legs at 00:13.9 to 00:22.2 as a left/right mix-up and wrote a correction. Zoomed frames showed a real cross-step with the hips turned side-on, so the correction was deleted before any commit (D114). The two analysis runs it produced for this clip were deleted, after a backup to `data/app/backups/climbreview_before_run_cleanup_1116.sqlite`.

**Left in the live app:** the attempt "IMG_7859" with one analysis run and a hold map "Route 1" with six marks that I placed (start hand hold, start foothold, one hand hold, two volumes, finish). They are my marks, not a climber's.

**Current verification:** `pytest` 337 passed. Playwright, 12 specs, passed.

## Second round of the climber's review (2026-11-15)

The same climber sent 12 more points after using the new hold editor and planner. Decisions are D106 to D112 in `docs/DECISIONS.md`.

**Done**
- Color suggestions are more cautious (`color-suggest-v2`): tighter color limits, a separate limit on hue so orange does not spread into red, no regions that are streaky, run off the picture, or are far larger or smaller than the tapped hold, and nothing suggested inside another suggestion or an existing mark.
- "Find holds by color" is one click, not a mode. After the click the picture goes back to adding holds by hand, the pink outlines stay until accepted or discarded, and a second color adds to them.
- Marks are drawn largest first, so a small mark inside a large one can be clicked.
- Undo: Cmd+Z or Ctrl+Z and the Undo button take back adding (a whole "Add all" batch at once), deleting, moving, resizing, and role, use, pull, and kind changes, newest first.
- "New holds are for" is removed; who uses a hold is set on the hold. The route-name field moved under "Marking more than one route on this picture".
- The editor says that marking order does not matter.
- Start holds can be given to the left hand, right hand, both hands, left foot, or right foot. The mark shows it (for example "3 S LH").
- Volumes: a mark can be a Volume. The planner then tries three spots on its circle (top, left, right) for hands and feet.
- Planner (`candidate-beta-v3`): the hips can no longer sit on a foot (a hip stays at least 0.35 of a leg length from each foot it stands on); each move is charged for a strained position and for moving the body far in one move; a sequence ends with both hands on the finish; steps are tagged "strenuous position", "big body shift", and "on the volume".
- Dragging: the browser focus rectangle around a mark is gone, which is the likely source of the trail behind a dragged hold (see Limits). A moved or resized hold now stays where it was dropped instead of jumping back until the save returns.
- Two bugs found on the way: a resize straight after a move could save the hold's old position, because both saves were built from the same stale copy (saves are now sent one at a time, each built from the newest saved map); and on the planner page a slow earlier answer could replace a newer one (only the latest request's answer is shown).

**Not done, and why**
- Volumes are only partly answered. The three spots are a guess at where a volume is usable; its real surface and angle are unknown, and color matching still does not find volumes.

**Verification actually run**
- `.venv/bin/python -m pytest`: 336 passed (9 new: finish match, start limbs, leg-fold limit, strain ordering, volumes, step notes, close colors, nested suggestions, streaks and edge regions).
- `npx playwright test` in `frontend`: 12 passed, including one-click color search followed by a hand-added hold, batch undo, Ctrl+Z for add, delete, role, start limb, and volume, and the removed "New holds are for" field. The two editor tests were run two more times without a failure.
- Real route, IMG_7768 (17 holds, tracked body): before, most positions of the 20-move Balanced sequence had the pelvis on the feet. After, the Balanced sequence has 24 moves, stands with the legs extended, and ends on a match; 8 of its positions are still tagged strenuous and 4 moves are big body shifts. Compared by drawing both sequences over the wall picture; this was an AI-assisted look, not a climber's rating.
- Color suggestions on two real wall pictures (IMG_7768 orange, IMG_7238 blue), two taps each at all three settings: the large circles over the red panel, the floor, and the mat are gone and no suggestion is nested. They also find fewer real holds than before: about half of the marked holds at the Normal setting.
- The live database was backed up to `data/app/backups/climbreview_before_start_limb.sqlite` before the `start_limb` column was added. 16 attempts and 44 holds are unchanged.

**Limits**
- The drag trail was not reproduced here, so the fix is a likely cause removed, not a confirmed one. If it still shows, the browser and zoom level are needed.
- The effort score comes from the stick-figure sketch. It is not a measurement of force, and no climber has rated the new sequences.
- A seed hold in shadow or with a color close to a wall panel still pulls in a few patches of that panel.
- The saved maps on IMG_7768 and IMG_7547 carry 6 cm scale lines that make an entered climber far too large, so their measurement-based plans are not meaningful until the scale is reset.

## Changes after a climber's review (2026-11-15)

A more experienced climber tested the release and sent 22 points. Decisions are D96 to D105 in `docs/DECISIONS.md`.

**Done**
- Planner: no crossed feet, splits, giant moves, or hanging below the feet; profiles are Balanced, Fewer moves, and Low feet, small steps; alternative start footholds; hand matches named; a blocked search says where it stopped; optional pull direction per hold; top out as a finish.
- A wall-angle bug: plane coordinates could be rotated relative to the picture, which broke "below" and "left of" in every corrected plan. Fixed.
- Route sketch: a stick figure that can be stepped or played, hands blue and feet orange. The video skeleton uses the same colors with L and R tags.
- Hold editor: zoom to 600%, drag a hold to move it, drag its handle to resize, one-click role, use, and pull buttons with keys S, M, F, T, a scrub bar to choose the reference frame, "Fit to the hold's color", a prompt offering the highest hold as finish or top out, inches for the scale line, and marking tips (volumes, long holds, start holds reused later, unsure hand or foot).
- Planner page: height and wingspan in centimeters or feet and inches; distances in real units.
- Video: HLG phone clips are converted to a natural look for new imports.
- "Delete attempt" during an import or analysis now stops the job and deletes, instead of being greyed out.
- Seconds are written "52s".
- Installer: smaller package list for testers and a parallel downloader.

**Hold editor follow-up (2026-11-15):** the combined "climber removed" picture is no longer loaded and swapped in unasked. The editor opens on the chosen frame and offers "Load combined frames", says it can take up to a minute, lets marking continue meanwhile, and fades the picture in. A two-way switch returns to the frame. The choice is remembered per map in the browser. The 12 browser tests pass with this change.

**Not done, and why**
- Automatic recognition of start and finish holds: the app cannot read tape or tags, and an earlier rule based on tracked hands picked the wrong start on both routes tried. The finish is offered as the highest mark; the start stays a one-click choice.
- Holds that are not circles: marks stay circles. The planner measures from each circle's center, and the tips say to put one mark at each place you would grab.
- Telling a knee from a foot: the pose model reports ankles and knees as it sees them and the app cannot correct it. A knee on a hold is not recognized.

**Verification actually run**
- `.venv/bin/python -m pytest`: 327 passed.
- `npx playwright test` in `frontend`: 12 passed, including zoom, drag, resize, roles, top out, pull direction, the sketch controls, and unit switching on a drawn wall.
- Real routes: the marked IMG_7768 route (17 holds) went from one 14-move sequence with a 3.84 torso-length move to two sequences of 20 and 15 moves with a longest move of 2.42. IMG_7547 (10 holds) gives one 9-move sequence, longest move 2.02. `scripts/check_wall_geometry.py` results are in D104.
- Video look: one frame of IMG_7850 compared by measurement and by an AI-assisted look with macOS's rendering.
- Clean install from the release zip on this Mac (Apple Silicon, private micromamba): 21 seconds, of which 4 were Python packages. The package download cache was warm from a run minutes earlier, so a first install on another computer will take longer; that time was not measured.
- The live database was backed up to `data/app/backups/climbreview_before_feedback_changes.sqlite` before the `pull` column was added. 16 attempts and 41 holds are unchanged.

**Limits**
- Every new planner limit is a stated assumption. No climber has rated the new sequences, and the reviewer has not seen these changes.
- The auto-proposed 16-hold route on IMG_7238 in the browser test now returns no sequence; it includes holds from color matching that the climber never confirmed.
- Existing attempts keep the old, brighter video until imported again.
- The hold map on IMG_7768 carries a 6 cm scale line that makes an entered 170 cm climber about twice the size of the tracked one, so its measurement-based plan is not meaningful until the scale is reset.

## Installer and tester release (2026-11-14)

Added `install.sh`, `start.command`, `TESTER_README.md`, and `scripts/make_release.sh`.

- `scripts/make_release.sh tester-1` writes `dist/ClimbReview-tester-1.zip` (236 KB): the backend, built web pages, config, and the install and start scripts. It contains no course material, footage, database, tests, or notes; the script counts such files and reported 0.
- `bash install.sh` uses an existing conda or mamba, or asks before downloading micromamba into the folder. It creates `.venv` with Python 3.12 and FFmpeg, installs the locked packages, downloads the pose model and checks its SHA-256, and verifies that the packages and FFmpeg load. Everything stays inside the folder (about 1.1 GB installed). Running it again is safe.
- `bash start.command` starts the app and opens the browser, or just opens the browser if it is already running.

**Verified on this Mac (Apple Silicon) only:** unzipped the release into an empty folder with a space in its path, ran the installer with no conda on the PATH (the micromamba route), started it on port 8320, uploaded the public Khazanov sample through the API, and got a finished analysis with coaching and a climb story. Also checked a second install run, the already-running case, and the not-installed message. **Not tested:** Intel Mac, Linux, Windows/WSL, a Mac that has never had developer tools, and double-clicking `start.command` from Finder (macOS may block a downloaded script; the guide uses Terminal commands instead).

## Lavender theme (2026-11-14)

Visual pass only: a purple pastel palette, a sticky header with a logo mark and a "stays on this computer" badge, pill tabs, softer cards and shadows, stat tiles, a favicon, and dark backing behind the on-video labels. No behaviour, analysis, or API changed. The violet accent on white measures about 5.6:1 and muted text about 5.9:1. Playwright, 12 specs, passed; checked by screenshot at 1280 and 390 px with no horizontal scroll or console errors. Safari and a real phone were not checked.

## Self-review on eleven clips: what was wrong, and the high-step rework (2026-11-14)

I read every card the app produced for the eleven current clips and compared a sample with frames from the footage. This is an AI-assisted review, not a rating by a climber.

**What was going wrong**

1. **Hands are hidden about half the time, so the most specific cards almost never fire.** Wrists were tracked 7 to 64% of each clip. Frames show the low-confidence wrists really are behind the body or head when the climber is filmed from directly behind, so lowering the visibility threshold (0.6) would add guessed positions, not real ones. Over eleven clips the reach rules produced two cards. This is a filming-angle limit, not a bug.
2. **15 of 27 moment cards were "Large single foot move" with one generic suggestion** (find an intermediate foothold or smear). On IMG_7863 and IMG_7865 the footage shows something more specific: the foot steps onto a volume, the hips stay about one torso length beside it, and the climber cannot stand up (and comes off in 7863). The old text missed that.
3. **Pause cards repeated the stays** already reported at the attempt level.
4. **Stay and left-the-wall cards were vague** ("name what you were waiting for").
5. **Nothing on the video said where to look** beyond a dotted path.
6. IMG_7853 (low and steep, body near horizontal) still gets no cards: feet tracked 5 to 8%.

**What changed**

- **High steps are judged by the stand-up.** The card now measures how far sideways the hips are from the foot when it lands and how long they take to rise 0.5 torso lengths. Within 2 s is reported under "checked and not flagged" as a clean stand-up; 2.5 s or more, or leaving the wall first, is a card: "Hips stayed left of your right foot after a high step", with the suggestion to bring the hips over the foot before pushing. A high step followed by leaving the wall leads the list.
- **Stay cards list what moved and when**; **left-the-wall cards name the last limb that moved**.
- **Pause cards that mostly overlap a stay are dropped.**
- **On-video highlight:** opening a card draws its limbs heavier and fades the rest, and draws yellow marks for what was measured (where the foot landed, where the hips were, an arrow for the suggested shift, the area the hips stayed in, the drop), with a one-line caption.

**Results:** 11 high steps flagged across the clips, 5 reported as clean. IMG_7863 now shows "Hips stayed left of your right foot after a high step ... and then you left the wall" next to "You left the wall at 00:18.5 ... the last tracked movement before it was your right foot at 00:15.6".

**Still weak:** no hand-specific feedback from a rear camera; "left" and "right" are picture directions; the hip-over-foot rule cannot see distance from the wall; all thresholds are untuned and no climber has rated any card.

**Current verification:** `pytest` 317 passed. Playwright, 12 specs, passed, including highlight shapes and limb emphasis on real IMG_4301.

## Six new teammate clips, lift-off and sit-start detection (2026-11-13)

Six clips from the shared Drive folder were imported and analyzed: IMG_7850, 7852, 7853, 7855, 7863, 7865 (in `data/new_vids/`, ignored by git). They are development clips. Only the second zip part arrived, so 7 clips from "new vids 1" and IMG_7401, IMG_7732, IMG_7816 are still not on this computer.

What the new clips showed, and what changed:

- **Standing on the ground was counted as climbing.** IMG_7863 stands for about 8 s before pulling on, and that produced a "slow start" card and two foot cards about stepping on. Added lift-off detection: an ankle at the lowest foot level in the clip under a nearly straight leg, at the beginning of the clip. Climbing is now counted from 00:07.9 there. Cards before lift-off are dropped and counted.
- **Sitting down into a low start was read as leaving the wall** (IMG_7853, at 00:01.6). A fast descent in the first 20% of a clip with at least 10 s of tracked movement after it now moves the start instead.
- **A clip with nothing flagged had nothing to say.** IMG_7852 climbs for 17 s without a stop and now gets a "you kept moving" reference card.

Limits found: a straight leg on the lowest foothold looks the same as standing on the ground, so the text says "the ground or your first foothold"; on IMG_7549 this probably trims 5 s that were spent on the start footholds. IMG_7853 is a low, steep problem with the body near horizontal, and feet were tracked for only 5 to 8% of it, so it gets no moment cards. These judgments come from my reading of contact sheets (AI-assisted), not from human labels.

**Current verification:** `pytest` 314 passed (12 in `test_story.py`). Playwright, 12 specs, passed. `scripts/check_climb_story.py` prints all eleven clips.

## Climb story: on-wall time, stops, and how it ended (2026-11-13)

Added `backend/app/analysis/story.py` (`climb-story-v1`), read from the hip midpoint in the picture. It needs no reanalysis: it is computed from stored poses when a review opens.

- **On-wall detection:** a fast hip descent (at least 1.2 torso lengths within 1.5 s) ends the time on the wall. Suggestions and foot placements after it are dropped and counted. The video cannot tell a fall from a jump down, and the text says so.
- **Stops:** stretches of 3 s or more where the hips stay within 0.3 torso lengths, with neighbouring stops in the same area joined. Each lists the tracked hand and foot movements during it. Nothing is read across a tracking gap longer than 1 s.
- **Whole-attempt cards** lead the Opportunities list: the longest stay and its limb pattern, leaving the wall, small foot adjustments as a share of all foot movements, and a slow start. They use the same card layout, decisions, and timeline markers as moment cards. A whole-attempt stay replaces the older pause cards inside it.
- **Your climb panel:** time on the wall, moving, staying put, height gained, and a hip-height chart with stops shaded. Clicking it seeks.

**Results on the five tripod clips** (`scripts/check_climb_story.py`): hips tracked 96 to 100%. IMG_7549, recorded by the climber as a fall, is detected leaving the wall at 00:38.5; IMG_7547 at 00:35.9 after its finish. Stays of 7 to 12 s were found on every clip. I compared these with contact sheets of two clips by eye; that is an AI-assisted visual check, not a human label. No thresholds were tuned against labels, and no climber has rated the new cards.

**More Drive footage:** see the section above for what has arrived. To add the rest after downloading it into `data/new_vids/`:

```bash
.venv/bin/python scripts/import_folder.py data/new_vids
.venv/bin/python scripts/check_climb_story.py
```

**Current verification:** `pytest` 311 passed (9 new in `test_story.py`). Playwright, 12 specs, passed, including the profile numbers, drawn stops, and chart seeking on real IMG_4301.

## Review workspace redesign (2026-11-12)

The interface was reorganized around one question: where to look, what was measured, how sure, what to try. No detector, coaching rule, API, or stored data changed. See D81 to D84.

- **Home:** upload with limits beside the button, three filming tips, a "pick up where you left off" card, and an attempt list with thumbnails, status in plain words, and route, grade and outcome when recorded. The list follows running jobs.
- **Attempt header:** title, which analysis is shown, Mark route holds, and a More menu (plan, reanalyze, downloads, reference labeling, delete). A newest analysis that failed no longer hides an older finished one.
- **Review:** video and timeline on the left, tabs on the right: Opportunities, Next attempt, Route, Compare, Evidence. Coaching cards have markers on the timeline; card and marker are one selection. Cards read what happened, why it might matter, what to try, what to verify. Feet and Hands filters, previous and next, keys O, L, N, P.
- **Fixes found on the way:** a failed save used to replace the whole review with an error; scrubbing out of a loop snapped back; shortcuts did nothing while a checkbox had focus; notes typed before the saved ones loaded could be overwritten.
- **Hold editor:** save state, undo last added hold, mode hint, start and finish counts.

**Current verification:** `npm run build` clean. Playwright, 12 specs, passed, with new checks for card and marker sync, loop exit on scrub, filter fallback, the overlay key, and hold undo. Backend unchanged, so `pytest` was not rerun (303 passed at 8a43c99). Looked at 1280, 768 and 390 px on IMG_7238 and an older hands-only analysis: no horizontal scroll, no console errors; keyboard-only path from the list to playing a card's moment works. On a 390 px phone the first card starts about 1,050 px down, was about 3,850. Not checked: a screen reader, Safari, a real phone, and a landscape clip by eye.

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test
```

## Wall angle from the bolt grid (2026-11-12)

Added and tested: bolt-hole detection, a grid fit that recovers the wall plane, route distances and reach measured on that plane, the wall's angle relative to the camera, a grid overlay in the hold editor, and corrected distances shown on suggestion cards. Details and real results: `docs/WALL_GEOMETRY_REPORT.md`.

**Current verification:** `pytest` 303 passed. Playwright, 12 specs, passed, including the correction on real IMG_7238. Accuracy against measured walls is untested.

```bash
.venv/bin/python scripts/check_wall_geometry.py
```

## Automation and hold-aware feedback (2026-11-12)

Added and tested: automatic analysis after upload, two-click route setup with proposed finish and uses, role fill-in for hand-marked maps, a tracked-route panel, at-a-glance counts, a simple default view, and a planner scale fallback. Details and measured results: `docs/AUTOMATION_REPORT.md`.

**Current verification:** `pytest` 290 passed. Playwright, 12 specs, passed, including the default flow on real IMG_7238. Role proposals were compared with two hand-marked routes only. No experienced climber has rated any suggestion.

```bash
.venv/bin/python scripts/check_role_proposals.py
```

## Route tools (2026-11-11)

Added and tested: color-based hold suggestions confirmed by the user, photo import for marking and planning, a scale line on hold maps, and candidate sequences from entered height and wingspan on a new Plan a route page. Input limits are 5 minutes and 2.5 GB. Details: `docs/ROUTE_TOOLS_REPORT.md`.

The hold editor and planner also show a clear wall picture combined from the video with the tracked climber cut out.

**Current verification:** `pytest` 276 passed. Playwright, 11 specs, passed. Suggestions were compared with one hand-marked route as a development check; no real photo and no real planned route were tried. Suggestion accuracy and plan usefulness are unmeasured.

```bash
.venv/bin/python scripts/check_hold_suggestions.py --map bdafbf1504724a5884a5d377d74c3b53 --tolerance normal --output data/tripod_nov09/hold_suggestion_check_normal.json
```

## Performance phase

Added and tested: timestamped coaching hypotheses with counterexamples and unknowns, foot placement review confirmed only by the user, hold roles and uses, background-measured hold-map alignment, candidate 2D sequences on marked holds, explicit same-problem comparison, decision and trial recording, and coaching in JSON and HTML exports. Coaching is computed from stored analysis files, so 0.2.0 and later runs did not need reprocessing. Details: `docs/PERFORMANCE_REPORT.md`. Human evaluation plan: `docs/COACHING_EVALUATION.md`.

**Current verification:** `pytest` 257 passed. Playwright, 10 specs, passed, including the real IMG_4301 import-to-coaching flow. The live database was backed up to `data/app/backups/climbreview_before_performance_phase.sqlite` before its additive migration; the 11 hold marks and existing notes are unchanged. The clean-copy setup was not rerun for this phase. **Coaching has not been rated by any experienced climber, its accuracy is unmeasured, and no performance improvement is shown.** Four of seven card types did not occur on the two real clips.

Performance commands actually run:

```bash
.venv/bin/python scripts/demo_candidate_beta.py --attempt febff1724e424bcbbf052abe569c2c08 --output data/tripod_nov09/candidate_beta_demo_img7238.json
```

```bash
.venv/bin/python scripts/export_coaching_rating_sheet.py --attempts febff1724e424bcbbf052abe569c2c08 cc5dde8e42d1490c90685fa554432603 --seed 317 --output data/tripod_nov09/coaching_rating_sheet_blank.csv --key data/tripod_nov09/coaching_rating_key.json
```

## Footwork phase

Added and tested: background-only camera measurement, the official heavy pose model, separately gated left and right foot episodes, per-limb series, specific event explanations with limb context, an attempt-level digest, filters, foot overlay and path, speed and distance charts, foot exports, foot reference labels and evaluation, and old-run compatibility. Details and before/after numbers: `docs/FOOTWORK_REPORT.md`.

**Current verification:** `pytest` 218 passed after the independent review corrections. Playwright, 6 specs, passed on the final build, including real IMG_4301 import to review. The real v1 run of IMG_7238 opened in the live app with its results and exports, and reanalysis added a new run beside it. A clean copy of tracked files (no media) passed full setup with the heavy model, 216 tests, type-check, and app start; its packages match the project environment. Event accuracy remains unmeasured. Tripod coverage also does not meet the provisional low-movement target (19.4% and 15.6% against 70%).

**Independent final review, pipeline 0.2.1-footwork:** fixed chart connections across nulls, event-distance origins across tracking runs, whole-window quiet claims with missing boundary samples, and hidden loops after filtering. The final build passed type-check/production build, 218 backend tests, and 4 targeted Playwright checks (3 synthetic chart checks and the real-video footwork workflow). The earlier full 6-spec browser suite and clean-copy 216-test check are retained above as stage results, not rerun claims. Both tripod attempts have fresh 0.2.1 runs. Existing review/hold/annotation/reflection table fingerprints match the pre-review backup. See docs/FOOTWORK_REPORT.md.

Footwork commands actually run:

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/tripod_nov09/manifest.csv --output-root data/tripod_nov09/baseline_detectors_v1
```

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/tripod_nov09/manifest.csv --output-root data/tripod_nov09/footwork_v2 --overwrite
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test
```

## Implemented

- Probing, validation, canonical normalization, HLG tone mapping, repeated-frame detection.
- MediaPipe Tasks pose extraction with per-landmark validity, a whole-pose plausibility rule, and camera-motion exclusion.
- Detector-specific coverage, attempt scale, low-movement and per-wrist detectors (`detectors-v1`), deterministic feedback.
- FastAPI + SQLite + one dedicated worker: import, bounds, persisted jobs, cancel, retry, interruption handling, deletion.
- React/TypeScript/Vite UI: library, setup, progress, review with synchronized canvas overlay, timeline, tracking-gap explanations, separate judgments, tags, notes, reflection, summary, responsive layout.
- JSON, CSV, standalone HTML exports. Evaluation tool, annotation guide, manifest template.

Also added after the first report: import cancellation (`POST /api/attempts/{id}/cancel-import`, with a Cancel button during import) and a reproducible baseline comparison (`scripts/compare_baseline.py`).

Not implemented: attempt comparison, automatic hold detection or hold types, wrist-to-hold or foot-to-hold association, near-hold events, slip diagnosis, real-time coaching, accounts, hosting.

## Phase 2 additions (2026-11-09)

Added and tested: blind reference-annotation workflow, manual reference-frame hold editor, time-boxed camera-compensation study (development only, off by default), experimental wrist-motion forecast with grouped train/test evaluation, public clip collection, class demo script, next-steps list. Details: `docs/TRAINING_REPORT.md`, `docs/DEMO_SCRIPT.md`, `docs/NEXT_STEPS.md`.

Forecast result, held-out 5 groups: Ridge MAE 0.3228 L, persistence 0.3282 L, constant velocity 0.4747 L. The learned model is only marginally better than doing nothing, and it tied persistence on the user's clips.

**Historical Phase 2 verification:** `pytest` 172 passed. Playwright, 5 specs, passed: blind labeling, import Cancel, hold alignment on portrait and landscape, full review smoke with continuous playback (at most 49.7 ms from media time). Clean copy from `git archive`, zero media files: `scripts/setup_env.sh` exit 0, `pytest` 172 passed, type-check OK, API 200 and page served, `pip freeze` identical to the lock. The existing `data/app` database opened with all 5 attempts and the new annotation and hold endpoints.

## Environment and versions

Apple M4 Pro, arm64, macOS 15.7.4. Python 3.12.16 and FFmpeg 9.0.2 (conda-forge GPL build) in `./.venv`. MediaPipe 1.2.2, OpenCV 5.0.0, NumPy 2.5.4, FastAPI 0.162.2, Starlette 1.10.0, Uvicorn 0.54.0. Node 24.16.0, React 18.3.1, Vite 8.3.6, TypeScript ~5.9.3. Current pose model `pose_landmarker_heavy` float16, SHA-256 `64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b`, CPU delegate. Runs before the footwork phase and forecast-v1 used `pose_landmarker_full`, SHA-256 `4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`. Exact sets: `requirements.lock.txt`, `conda.lock.txt`, `frontend/package-lock.json`.

## Commands actually run

```bash
.venv/bin/python scripts/fetch_public_samples.py
```

```bash
.venv/bin/python scripts/prepare_phone_clips.py
```

```bash
.venv/bin/python scripts/run_feasibility.py --output-root data/feasibility --overwrite
```

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/public_samples/manifest.csv --output-root data/public_feasibility --provenance public_development_sample --overwrite
```

```bash
.venv/bin/python -m pytest
```

```bash
cd frontend && npm run build
```

```bash
.venv/bin/python scripts/load_manifest_into_app.py --url http://127.0.0.1:8318
```

```bash
.venv/bin/python scripts/compare_baseline.py
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright install chromium
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test --headed --repeat-each=2 --timeout=120000 --global-timeout=170000
```

## Baseline comparison (variants only, not accuracy)

Output: `data/baseline_comparison/baseline-comparison-v1.json`; each run also gets `events_baseline_raw.json`. Baseline means raw landmarks and no onset/offset hysteresis. Wrist event counts, final vs baseline:

| Clip | Left | Right |
| --- | --- | --- |
| phone01 | 3 vs 5 | 1 vs 1 |
| phone02 | 0 vs 0 | 6 vs 7 |
| phone03_a1 | 4 vs 4 | 3 vs 7 |
| phone04 | 2 vs 2 | 4 vs 8 |
| phone05 | 0 vs 0 | 2 vs 0 |
| public_khazanov_v3 | 1 vs 2 | 1 vs 1 |
| public_caulier | 0 vs 0 | 0 vs 0 |
| public_rockspot_v3 | 1 vs 1 | 7 vs 6 |

Low movement: 0 vs 0 where available; unavailable on public_caulier. The baseline usually splits movement into more episodes, but not always. Which variant is better cannot be known without human labels.

## Earlier verification (historical, before Phase 2)

These results are from the first follow-up round. The 118-test counts are historical; the current count is the 172 above. Later features are covered by the current verification.

| Check | Result |
| --- | --- |
| `pytest` (detectors, media, quality, overlay, API/worker, evaluation, baseline, real-model CLI) | 118 passed at that time, 1 deprecation warning from the test client |
| Frontend `tsc --noEmit` and production build | passed |
| Real browser run in the built-in pane: UI upload, real worker import and analysis, playback, canvas overlay, event selection, gap explanation, judgments, tags, autosaved note, reflection, reload persistence, three exports, loop, phone width, delete | passed on a public sample; details below |
| Same production path on five personal development clips | all completed |
| Playwright `frontend/tests/smoke.spec.ts`, bundled Chromium 158, headless | 1 passed (12.5 s) |
| Same spec, `--headed` (visible window, throwaway profile), `--repeat-each=2`, serial | 2 passed |
| Clean copy from `git archive` of commit 3016e45, zero media or model files, `./scripts/setup_env.sh` | exit 0, including `npm ci` and frontend build; `pip freeze` identical to the lock |
| In that clean copy: `pytest`, frontend type-check, `run_app.py` serving API and page | 118 passed at that time; type-check OK; API 200 and page served. Copy deleted afterward |
| `scripts/compare_baseline.py` on all 8 stored runs | all stored events reproduced exactly; results below |

Continuous playback (headed, 4 s of real playback, measured every display frame): 462 and 480 frames rendered, 40-41 distinct poses drawn, 40-41 distinct canvas images, video advanced 4.0 s, largest gap between drawn pose time and media time 49.6 ms (the drawing rule allows 60 ms). Headless runs gave 241 frames and at most 48.2 ms. Context loop wrapped back in every run. Frames captured during playback (`frontend/test-results/playing_strip.png`, public clip) show the skeleton following the climber.

Playwright diagnosis: the first run hung for 4 minutes in "setting up page". A bounded launch probe then started Chromium in 300 ms, and the spec passed on every serial run. **The original hang did not recur and its cause is unknown.** An intermediate `--repeat-each=3` run had 2 failures caused by the test design: copies ran in parallel and saw each other's same-titled clip. The config now forces one worker. Chromium logs `CVDisplayLinkCreateWithCGDisplay failed` warnings headless, without effect on the run.

Browser details: note persistence and escaping in the HTML report were confirmed on the final build; reflection and judgment persistence were confirmed by page reload on an earlier build; only the note-saving, loop, and cache code changed afterward. Loop wrap was seen at 12.8 s for an event ending at 11.7 s with 1 s of context. No horizontal overflow at 375 px. The manual pane session had a hidden pane; continuous playback was verified later by the headed Playwright run above.

Defects found and fixed during verification: stale cached `index.html` could leave a blank page after a rebuild; notes saved only on blur; context looping depended on animation frames.

The import Cancel button was not exercised in a browser in this earlier round. It has since passed in `frontend/tests/annotate.spec.ts`, and API tests cover stopping a running FFmpeg.

## Remaining work

All remaining items depend on people or new footage; the tooling for them exists. See `docs/NEXT_STEPS.md`.

1. Add the full rubric, submission instructions, deadlines, team size, and AI-use rules to `inputs/`.
2. Independent human annotation of hand and foot episodes on the tripod clips and any new footage, with a fixed split; then tune on dev data and freeze.
3. More tripod footage from other climbers, so a held-out group exists.
4. Run `scripts/evaluate.py` on both `events.json` and `events_baseline_raw.json` once labels exist.
5. Usability study with real beginners.

Held-out caveat: the forecast test groups have been evaluated once, so any new forecast method needs a fresh test set. IMG_2532.MOV and IMG_2748.MOV remain reserved: they were not viewed, analyzed, or used for training, tuning, or testing, and IMG_2532.MOV was only checksummed to confirm it is unchanged.

## Next exact action

Open http://127.0.0.1:8317, open IMG_7238, and choose **Mark route holds**. Mark start, finish, and hand or foot use to get candidate sequences. Then have an experienced climber follow `docs/COACHING_EVALUATION.md`.

```bash
.venv/bin/python scripts/run_app.py
```
