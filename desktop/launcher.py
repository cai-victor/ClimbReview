"""ClimbReview as a desktop app: one window, the same local API and worker, nothing installed system-wide.

The packaged executable runs in two roles:
  ClimbReview            the window, plus the API server on 127.0.0.1 in a background thread
  ClimbReview --worker   the one dedicated worker process for imports and analyses (started by the first role)
  ClimbReview --self-test  checks that the pose model, MediaPipe and FFmpeg load from inside the bundle

Attempts and the database live in the user's app-data folder (see app.settings.user_data_dir), not in the bundle.
Run it from source with:  .venv/bin/python desktop/launcher.py
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
if not FROZEN:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

PREFERRED_PORT = 8327   # not the developer app's 8317, so both can run at once
TITLE = "ClimbReview"


def _quiet_child_consoles() -> None:
    """A windowed Windows app would flash a console window for every FFmpeg call; start children without one."""
    if os.name != "nt":
        return
    original = subprocess.Popen

    class QuietPopen(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = QuietPopen  # type: ignore[misc]


def _log_to_file(data_dir: Path, name: str) -> None:
    """A windowed app has no console. Keep its messages in a log file the user can send when something fails."""
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stream = open(logs / f"{name}.log", "a", buffering=1, encoding="utf-8")
    stream.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    sys.stdout = sys.stderr = stream


def _try_lock(path: Path):
    handle = path.open("a+")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _free_port() -> int:
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("no free local port")


def _answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/attempts", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def _open_window(url: str) -> None:
    try:
        import webview
    except ImportError:   # running from source without pywebview: use the browser instead
        import webbrowser
        webbrowser.open(url)
        print(f"ClimbReview is running at {url}  (Ctrl+C to stop)", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(TITLE, url, width=1360, height=900, min_size=(900, 640))
    webview.start(private_mode=False)


def _stop_with_parent() -> None:
    """If the window process dies without closing (force quit, crash), stop the worker instead of orphaning it.
    SIGTERM lets the worker finish its current step and leave the job for the interrupted-job recovery."""
    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def run_worker() -> int:
    from app.settings import load_settings
    if FROZEN:
        _log_to_file(load_settings().data_dir, "worker")
    _stop_with_parent()
    from app.worker import main
    return main()


def self_test() -> int:
    """Run by the build: everything an analysis needs must load from inside the bundle."""
    from app.analysis.pose import MediaPipePoseDetector, load_verified_model_manifest
    from app.analysis.video import tool_path, tool_version
    from app.settings import PROJECT_ROOT, load_pipeline_config
    pose = load_pipeline_config().pose_model
    model = PROJECT_ROOT / pose.model_path
    load_verified_model_manifest(model, PROJECT_ROOT / pose.manifest_path)
    with MediaPipePoseDetector(model, pose):
        pass
    for tool in ("ffmpeg", "ffprobe"):
        print(tool_path(tool), "|", tool_version(tool))
    assert (PROJECT_ROOT / "frontend" / "dist" / "index.html").exists(), "the frontend is missing"
    import webview  # noqa: F401  (the window library must load too)
    print("self-test passed: pose model, MediaPipe, FFmpeg, FFprobe, frontend and window library all load")
    return 0


def run_app() -> int:
    from app.settings import load_settings
    settings = load_settings()
    settings.prepare()
    if FROZEN:
        _log_to_file(settings.data_dir, "app")
    os.environ["CLIMBREVIEW_DATA_DIR"] = str(settings.data_dir)   # the API and the worker must share one folder

    port_file = settings.data_dir / "desktop.port"
    instance = _try_lock(settings.data_dir / "desktop.lock")
    if instance is None:   # already open: show the running copy instead of starting a second worker
        url = f"http://127.0.0.1:{port_file.read_text().strip()}" if port_file.exists() else ""
        if url and _answers(url):
            _open_window(url)
            return 0
        print("Another ClimbReview is starting or stuck. Close it and try again.", flush=True)
        return 1

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    port_file.write_text(str(port))
    worker_command = [sys.executable, "--worker"] if FROZEN else [sys.executable, str(Path(__file__).resolve()), "--worker"]
    worker = subprocess.Popen(worker_command, env=os.environ.copy())

    import uvicorn
    from app.main import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, name="api", daemon=True)
    thread.start()
    try:
        for _ in range(240):
            if _answers(url):
                break
            if not thread.is_alive() or worker.poll() is not None:
                raise RuntimeError("the local server or worker stopped while starting; see the logs folder")
            time.sleep(0.25)
        else:
            raise RuntimeError("the local server did not start within a minute")
        print(f"ClimbReview data: {settings.data_dir}", flush=True)
        _open_window(url)
    finally:
        server.should_exit = True
        if worker.poll() is None:
            worker.terminate()   # the worker marks unfinished jobs as interrupted on its next start
            try:
                worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.kill()
        thread.join(timeout=10)
        port_file.unlink(missing_ok=True)
    return 0


def main() -> int:
    _quiet_child_consoles()
    if "--worker" in sys.argv[1:]:
        return run_worker()
    if "--self-test" in sys.argv[1:]:
        return self_test()
    return run_app()


if __name__ == "__main__":
    if FROZEN:
        import multiprocessing
        multiprocessing.freeze_support()
    raise SystemExit(main())
