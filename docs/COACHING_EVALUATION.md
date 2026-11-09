# Evaluating coaching cards with an experienced climber

No ratings exist yet. This protocol is ready for someone to carry out. Do not fill it with AI or invented judgments.

## Who and what

Ask at least one climber with coaching or substantial technique experience, ideally two who rate independently. Use development clips only. Do not use IMG_2532.MOV or IMG_2748.MOV until the rules are frozen.

## Blinded order

1. **Before seeing any card**, the rater watches the clip and writes down 3-5 moments they would coach, with a time and a suggestion. Use a plain file or the app's Reference labeling page for hand and foot movement episodes.
2. Create the blinded sheet with the app running. Replace the IDs and seed with your own:

   ```bash
   .venv/bin/python scripts/export_coaching_rating_sheet.py --attempts ATTEMPT_ID_1 ATTEMPT_ID_2 --seed 317 --output data/ratings/sheet.csv --key data/ratings/key.json
   ```

3. Give the rater `sheet.csv` and the video. Keep `key.json` from them. Cards are shuffled and have no rule names, measurements, or decisions.
4. For each row the rater scores:
   - `moment_is_real_0_2`: 0 did not happen, 1 partly, 2 clearly.
   - `suggestion_is_reasonable_0_2`: 0 unhelpful or wrong for this move, 1 could be, 2 sensible to try.
   - `would_coach_this_yes_no`.

## What to report

- By card kind, using the key: how many cards, and the share rated 2, 1, and 0 on each scale. Give counts, because the samples will be small.
- How many of the rater's own pre-written moments had a card within about 2 s. Moments without one are misses.
- If two raters took part, report their agreement before resolving any differences. Keep each rater's original file.
- Which card kinds never appeared. A kind with no real examples has no evaluation.

Thresholds can be tuned on these development clips, then frozen before any held-out clip is rated. Any claim about improvement needs matched attempts by the same climber with outcomes recorded, and even then one climber's change cannot be attributed to the app.
