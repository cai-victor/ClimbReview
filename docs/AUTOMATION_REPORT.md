# Review, automation, and hold-aware feedback, November 12, 2026

**A new clip now needs three inputs before you see route advice: choose the file, click one hold of your route, and click your start hold. The review opens on a short view. Everything proposed is still unvalidated and needs your confirmation.**

## What the review found

| Gap | What it cost | What changed |
| --- | --- | --- |
| Analysis had to be started by hand after setting bounds | Two screens and a wait before any result | Analysis of the whole clip starts by itself after upload |
| Route setup took about one action per hold | You set role and use on 15 of 17 holds by hand on one route | Two clicks propose holds, finish, and uses; you confirm once |
| Existing hand-marked maps had no roles | No candidate sequences | One button proposes the finish and uses, filling only empty fields |
| The review page showed about a dozen panels at once | Hard to know where to look | A simple view is the default; Detailed shows the rest |
| Suggestions were listed by time | Generic cards came first | Three cards are shown first, one per kind, most specific kind first |
| Feedback ignored the marked holds | No link between movement and the route | A tracked-route panel lists which holds each limb rested near and which none approached |
| The planner needed a marked scale line | An extra step for videos | Without a line, scale comes from the climber's tracked torso |

## How to use it

```bash
.venv/bin/python scripts/run_app.py
```

1. Open http://127.0.0.1:8317 and choose a video. Analysis starts by itself. Untick the box on that screen to set the start and end first.
2. On the review, choose **Set up my route**. Click one hold of your route, then click your start hold, then **Use this route**.
3. Read the suggestions, the candidate sequences, and **Your route as tracked**. Open the **Evidence** tab (this replaced the Detailed switch on 2026-11-12) for the limb tracks, charts, every event, foot placements, comparison, and exports.

## What is proposed, and how well it did

`scripts/check_role_proposals.py` compared proposals with the roles and uses you marked yourself on two routes. It is read-only, the routes are development data, and four maps are far too few to call this accuracy.

| | IMG_7768 (17 holds) | IMG_7547 (10 holds) |
| --- | --- | --- |
| Finish: proposed as the highest hold | matched your mark | matched your mark |
| Uses where you had set one: compatible / conflicting / left unset | 12 / 0 / 3 | 3 / 0 / 4 |
| Holds a tracked limb rested near | 12 of 17 | 3 of 10 |

- **The finish rule was chosen after looking at these same two routes**, so its two matches are not an independent test.
- **A start hold is never proposed.** Two rules based on tracked hands each picked a neighboring hold on both routes, so you click it instead.
- **"Compatible" is lenient**: a proposal of hands-and-feet counts as agreeing with a mark of hands only.
- **Choosing the route color with no click was tried and removed.** Against your four marked routes it matched 5 of 11, 3 of 3, 7 of 17 with the wrong color, and 0 of 10 holds.
- On IMG_7547 a limb rested near only 3 of 10 holds, so little could be proposed there. Hidden hands are the main cause.

Proposals use rest points: stretches of at least half a second where a tracked limb stayed under 0.2 torso lengths per second. Feet use the toe when tracked, hands a point just past the wrist. When the camera drifted, each rest is moved into the wall picture using the nearest lined-up frame, and dropped if none is within 3 seconds.

## Limits

- Resting near a mark does not show the hold was touched. "Not approached" can mean a hidden limb used it.
- Automatic analysis uses the whole clip. Time on the ground before or after the climb can add long-stop suggestions, so narrow the bounds if that happens.
- The tracked-route panel appears only when the marks line up with the video (still camera).
- Ranking the first three suggestions is a fixed order by kind. It is not a measure of importance.

## Verification actually run

| Check | Result |
| --- | --- |
| Backend tests, including 14 new: rest timing, gaps and tracking breaks, toe and palm points, camera registration, role proposals, use limits, tracked route, ranking, glance counts, automatic analysis on success, failure, photo, and flag off | 290 passed |
| Browser specs, including a new default-flow run on real IMG_7238: upload, automatic analysis, simple view, refused wall click, 11 holds proposed, finish proposed and no start guessed, nothing saved before confirming, save, marks verified against the video, detailed view, phone width | 12 passed |

In that browser run the planner found no sequence, because the test clicks the lowest outline as the start, which is not the real start hold. A rest-detection bug was found by the new tests and fixed before any result above was recorded.
