# PyInstaller recipe for the macOS app. Build with:  bash desktop/build_macos.sh
# Bundles: the API and worker code, the built frontend, the detector config and the pose model.
# Never bundles data/, footage, tests, docs or the forecast experiment.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
VENV_BIN = Path(sys.prefix) / "bin"

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "config" / "detectors.yaml"), "config"),
    (str(ROOT / "config" / "model_manifest.json"), "config"),
    (str(ROOT / "models" / "pose_landmarker_heavy.task"), "models"),
]

# FFmpeg/FFprobe are copied in afterwards by desktop/add_ffmpeg.py, untouched: PyInstaller would relink them
# against OpenCV's older copies of the same libraries, and then FFmpeg fails to start.
binaries = []
hiddenimports = [name for name in collect_submodules("app") if not name.startswith("app.forecast")]
hiddenimports += collect_submodules("uvicorn")

for package in ("mediapipe", "webview"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["app.forecast", "sklearn", "scipy", "pytest", "tkinter", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClimbReview",
    console=False,
    argv_emulation=False,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ClimbReview")
app = BUNDLE(
    coll,
    name="ClimbReview.app",
    icon=str(ROOT / "desktop" / "ClimbReview.icns") if (ROOT / "desktop" / "ClimbReview.icns").exists() else None,
    bundle_identifier="local.climbreview.app",
    version="1.0.0",
    info_plist={
        "CFBundleDisplayName": "ClimbReview",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "NSHumanReadableCopyright": "Runs on this Mac only; videos never leave it.",
    },
)
