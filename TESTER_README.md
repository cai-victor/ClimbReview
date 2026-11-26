# ClimbReview: try it on your own computer

ClimbReview reviews a video of one bouldering attempt. It runs entirely on your computer: your videos are never uploaded.

If you were sent a disk image (`ClimbReview-...-macOS.dmg`) instead of this folder, use that: open it, drag ClimbReview to Applications, and follow "Read me first" inside it.

## What you need

- A Mac (tested on Apple Silicon). Intel Macs and Linux should work but have not been tested. On Windows, use WSL.
- About 2.5 GB of free disk space and an internet connection for the install.

## Install (once, a few minutes on a fast connection)

1. Unzip the folder somewhere you can find it, for example your Desktop.
2. Open the Terminal app, type `cd ` (with a space), drag the unzipped folder onto the Terminal window, and press Return.
3. Run:

   ```bash
   bash install.sh
   ```

   If you have no conda, it asks before downloading a small tool called micromamba into the same folder. On a Mac it ends by putting **ClimbReview** in your Applications folder and opening it.

## Start it

Open **ClimbReview** from Applications or Launchpad. It opens in its own window; quit it like any app.

Without the app (on Linux, or if the app could not be built), run `bash start.command` in the folder. Your browser opens http://127.0.0.1:8317. Leave the Terminal window open while you use it, and press Ctrl+C in it to stop.

## Filming tips

- Prop the phone up so the camera does not move.
- Keep hands and feet in the frame for the whole climb, one climber at a time.
- MP4 or MOV, up to 5 minutes and 2.5 GB.

## What to expect

- Analysis takes roughly as long as the clip, sometimes a little longer.
- Suggestions are things to test on the wall, not verdicts. The thresholds behind them have not been validated, and no climbing coach has rated them.
- A camera directly behind the climber hides the hands about half the time, so most feedback is about hips and feet.

## Remove it

Drag ClimbReview from Applications to the Trash and delete this folder. Your videos and notes from the app are in `~/Library/Application Support/ClimbReview`; delete that folder too if you do not want to keep them. The browser version keeps its own in this folder's `data` folder.

## If something goes wrong

Send the files in `~/Library/Application Support/ClimbReview/logs`, or the last 20 lines from the Terminal window, to whoever gave you the app.
