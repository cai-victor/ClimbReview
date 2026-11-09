# Performance review report, November 9, 2026

**ClimbReview now opens on specific, timestamped things to try, backed by the tracked movement. These are unvalidated coaching hypotheses: no experienced climber has rated them, no accuracy has been measured, and no improvement in climbing has been shown.** The frame checks below are AI-assisted development spot checks, not human ground truth.

## Start it

```bash
.venv/bin/python scripts/run_app.py
```

Open http://127.0.0.1:8317 on this computer and choose an attempt. IMG_7238 and IMG_4301 (teammate tripod) already have foot analysis, so they show coaching at once. Older phone clips show a Reanalyze action instead.

## What a card contains

Every card answers five questions: what moment, what was measured, why it could matter, a concrete thing to try, and when to keep your own way. Below those, it shows measurements with their rule values and what makes the conclusion uncertain. You can mark each one "I'll try this", "Was intentional", "Doesn't apply", or "Can't tell", and record whether trying it helped. Opening a card jumps to the moment, draws the tracked paths, and can loop it.

| Card | Fires when | Not flagged when |
| --- | --- | --- |
| Try the step before the reach | A hand rises at least 0.5 L, no foot stepped in the 1.5 s before, and a foot then rises at least 0.4 L | A foot moved first, or at the same time |
| Reach ended with the arm near full length | Same reach, no following step, projected arm straightness at least 0.97 and at least 0.88 of that arm's own tracked length | The arm still had room. A straight arm alone never fires it |
| Hand and foot moved up together | Both rose and overlapped at least 40% of the shorter movement, with the foot not more than 0.3 s ahead | The foot clearly led |
| Repeated foot adjustment near a reach | Two or more moves of one foot within 2 s, net travel at most 0.6 of summed travel, with a reach nearby | The moves went steadily one way, which looks like progress |
| Foot shifted while the hand moved | Ankle moved at least 0.25 L and the toe at least 0.2 L during a reach | The toe stayed put, which fits a heel change on a planted foot |
| Large single foot move | One step rises at least 1.0 L | It was the very start, likely leaving the ground |
| Long stop before the next move | At least 3.5 s with no movement episode and both feet tracked | Either foot was not tracked continuously |

L is the attempt's torso length in the picture. All values are unvalidated development hypotheses in `backend/app/analysis/coaching.py`, and they are returned with every result. Reaches that could not be assessed are listed under "Could not be judged", and ones that looked fine under "Checked and not flagged". An empty card list is a valid result.

## Foot placement and smearing

The app lists moments where a foot appeared to settle after moving. With a verified hold map, it reports only geometric proximity. If no marked hold is close, it says this could be a smear, an unmarked hold, or a foot off the wall. **It never converts proximity into contact and never calls a smear bad.** Only you can confirm "On a marked hold", "On an unmarked hold", "Intentional smear", "Not placed", or "Can't tell". Sole angle, friction, and pressure are not measurable here.

## Alternative beta

- **Route setup:** the hold editor now numbers holds and lets you mark start or finish and hand or foot use. Your 11 existing marks are unchanged, with these fields empty.
- **Verified mapping:** before marks are compared with movement, the app measures the background of 12 frames against the reference frame. This does not trust a tripod label. Your IMG_7238 map verified, with at most 1.2 px of movement, so it now appears on the video. A moved or unmeasurable camera disables comparison and says so.
- **Foot setup on a card:** with a verified map, a reach card can name a marked foothold that gives at least 0.15 L more 2D reach margin than your observed feet, within a step of 1.5 L. A large-step card can name a marked foothold between the two heights.
- **Candidate sequences:** a shortest-path search over marked holds gives up to three different options (fewer moves, shorter moves, more reach margin), each with move count, limb travel, and tightest margin. It uses your own tracked arm and leg lengths and never proposes a foot above both hands.
- **Stated limits:** it does not know wall angle, hold quality, pull direction, balance, rotation, or dynamic moves. A candidate is something to try, never the best or easiest beta. Holds with no use marked are treated as possible for both, and the panel says so.

Until you mark start and finish, the panel shows that setup action and proposes nothing. As a development demonstration only, with assumed roles and an in-memory copy of your IMG_7238 marks (nothing saved), the planner found 6-move and 8-move sequences. Both keep one foot off the marked holds, so that route likely needs more footholds marked. Output: `data/tripod_nov09/candidate_beta_demo_img7238.json`.

## Comparing attempts

Attempts are compared only when you give them the same problem name and climber name, so the two teammate routes are never compared. The table shows your outcome text, time, foot coverage, foot moves per analyzable minute, and reaches with a foot step first. Tracking-based rows read "not comparable" if either foot was analyzable for under 60% of an attempt. These are proxies and do not show that one attempt was better. No success predictor was trained, since there are no outcome labels to learn from.

## What the real clips produced

| Latest analysis | Cards | Kinds | Placements to check | Checked, not flagged | Could not be judged |
| --- | --- | --- | --- | --- | --- |
| IMG_7238 | 5 | 2 large step, 1 hand and foot together, 2 long stop | 6 | 2 | 5 |
| IMG_4301 | 7 | 3 large step, 1 hand and foot together, 3 long stop | 9 | 3 | 5 |

Four card types did not fire on these two clips: step before reach, arm near full length, repeated adjustment, and foot shift. They are exercised only by synthetic tests, so their real-world behavior is unseen. Few reaches qualified: 1 and 2 reaches met the rules for evaluation.

**AI-assisted spot check of 10 of the 12 cards against frames:**
- Four large-step cards matched real large steps.
- The IMG_4301 hand-and-foot card at 22.1 s matched: both limbs visibly moved together.
- The IMG_7238 hand-and-foot card at 19.9 s is doubtful. The hand appears placed early in that episode, so the two may not have been moving together for as long as measured.
- All four sampled long-stop cards matched a mostly still climber. In one (IMG_7238, 16.1 s), a hand visibly moved near the end while untracked, which the card's warning about hand tracking covers.

Foot placement review was exercised but not assessed for contact, because video cannot establish it.

## Sources

Rationale comes from these. Thresholds are this project's own heuristics and do not come from them.

- Seifert, Boulanger, Orth, Davids (2015), [Environmental design shapes perceptual-motor exploration, learning, and transfer in climbing](https://www.frontiersin.org/articles/10.3389/fpsyg.2015.01819/full): exploratory movements decline with practice and fluency is measured from hip trajectory. Why repeated adjustment is not assumed to be an error.
- Philadelphia Rock Gyms, [straight-arming](https://philarockgym.com/?p=25593): straight arms save energy, and some moves need bent arms. Why a straight arm alone is not flagged.
- Philadelphia Rock Gyms, [smearing](https://philarockgym.com/?p=26439): smearing is a deliberate technique that relies on pressing into the wall. Why an absent foothold is not an error.
- Sportrock, [basics of footwork](https://www.sportrock.com/post/basics-of-footwork): precise, quiet placement.
- Bouldering Boss, [10 bouldering habits to avoid](https://boulderingboss.com/new-at-bouldering-10-habits-to-avoid/): placing feet before hands.
- [MediaPipe Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker): landmark coordinates, and z is relative to the hips, so it is not used as wall distance.

Two PubMed Central articles from the search required a browser verification check, so they were not read or cited.

## Verification actually run

| Check | Result |
| --- | --- |
| Backend tests, including 39 new coaching tests: straight and bent arms, foot setup before, tracking breaks with valid endpoints, unstable anchors, planted toe, progress versus adjustment, ground starts, foot above hands, camera moved versus fixed, migration | 257 passed |
| Browser specs on real IMG_4301, including cards, seek, loop enable, decisions, reload persistence, placement confirmation, setup action, fixture route, candidate display, alignment, matching and non-matching comparison, phone width | 10 passed |
| Live app with your data | Your map verified and appears on the video; 11 marks unchanged; old v1 run reports that it needs reanalysis |
| Clean-copy setup | Not rerun for this phase. Dependencies and setup did not change; the last clean-copy pass was 0.2.0 |

Software tests do not establish that any suggestion is correct or useful.

## Limits and next human validation

- Both clips are from one teammate group and are development data. Nothing here is independent evaluation.
- Thresholds were chosen from coaching rationale and two clips, and are not tuned against any reference.
- IMG_2532, IMG_2748 and locked forecast test groups were not used. The forecast was not retrained.
- Next: an experienced climber rates the blinded sheet (`docs/COACHING_EVALUATION.md`), and you mark start, finish, and hand or foot use to get real candidate sequences. Then try one suggestion and record the result, on matched attempts.
