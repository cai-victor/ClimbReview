# Primary documentation checked

Checked November 9, 2026. These references support the tool capabilities in the plan; all product scope, thresholds, study sizes, and evaluation targets are proposed design choices.

- [MediaPipe Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker): pretrained body-landmark task and available output types. It does not establish accuracy for climbing footage.
- [PoseLandmarker Python API](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker): VIDEO mode and monotonic timestamp requirements.
- [MediaPipe Python setup](https://developers.google.com/edge/mediapipe/solutions/setup_python): supported environments; verify compatibility on the actual development computer.
- [FFprobe reference](https://www.ffmpeg.org/ffprobe.html): inspect media stream/container metadata in machine-readable form.
- [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/): distinction between ordinary background work and heavier computation. The proposed single local worker is our project-specific architecture choice.
- [Pose Landmarker Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python): VIDEO-mode usage implemented in `backend/app/analysis/pose.py` (checked November 9, 2026).
- [MediaPipe on PyPI](https://pypi.org/project/mediapipe/1.2.2/): wheel availability for macOS arm64.
- [conda-forge](https://conda-forge.org/): source of the project-local Python and FFmpeg builds.

Recheck official API examples and mutually compatible dependency versions when coding. Do not copy legacy pose APIs merely because an older tutorial uses them.
