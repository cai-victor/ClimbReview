# ClimbReview: try it on your own computer

ClimbReview reviews a video of one bouldering attempt. It runs entirely on your computer: your videos are never uploaded.

## What you need

- A Mac (tested on Apple Silicon). Intel Macs and Linux should work but have not been tested. On Windows, use WSL.
- About 2 GB of free disk space and an internet connection for the install.

## Install (once, about 5 to 10 minutes)

1. Unzip the folder somewhere you can find it, for example your Desktop.
2. Open the Terminal app, type `cd ` (with a space), drag the unzipped folder onto the Terminal window, and press Return.
3. Run:

   ```bash
   bash install.sh
   ```

   If you have no conda, it asks before downloading a small tool called micromamba into the same folder. Everything stays inside this folder.

## Start it

```bash
bash start.command
```

Your browser opens http://127.0.0.1:8317. Leave the Terminal window open while you use the app, and press Ctrl+C in it to stop.

## Filming tips

- Prop the phone up so the camera does not move.
- Keep hands and feet in the frame for the whole climb, one climber at a time.
- MP4 or MOV, up to 5 minutes and 2.5 GB.

## What to expect

- Analysis takes roughly as long as the clip, sometimes a little longer.
- Suggestions are things to test on the wall, not verdicts. The thresholds behind them have not been validated, and no climbing coach has rated them.
- A camera directly behind the climber hides the hands about half the time, so most feedback is about hips and feet.

## Remove it

Delete the folder. Nothing was installed anywhere else. Your videos and notes are in its `data` folder, so copy that out first if you want to keep them.

## If something goes wrong

Copy the last 20 lines from the Terminal window and send them to whoever gave you the app.
