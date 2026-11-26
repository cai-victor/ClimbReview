"""Copy the project environment's FFmpeg and FFprobe, with their own libraries, into a built ClimbReview.app.

They keep conda's bin/ + lib/ layout so their @loader_path/../lib search path works unchanged, separate from the
libraries PyInstaller collected for OpenCV and MediaPipe.   Usage: python desktop/add_ffmpeg.py dist/ClimbReview.app
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def dependencies(binaries: list[Path], lib: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    todo = list(binaries)
    while todo:
        listing = subprocess.run(["otool", "-L", str(todo.pop())], capture_output=True, text=True, check=True).stdout
        for line in listing.splitlines()[1:]:
            name = line.strip().split(" (")[0]
            if name.startswith("@rpath/") and name[7:] not in found and (lib / name[7:]).exists():
                found[name[7:]] = lib / name[7:]
                todo.append(lib / name[7:])
    return found


def main(app: Path) -> int:
    prefix = Path(sys.prefix)
    tools = [prefix / "bin" / "ffmpeg", prefix / "bin" / "ffprobe"]
    target = app / "Contents" / "Frameworks" / "ffmpeg"
    shutil.rmtree(target, ignore_errors=True)
    (target / "bin").mkdir(parents=True)
    (target / "lib").mkdir()
    for tool in tools:
        shutil.copy2(tool, target / "bin" / tool.name)
    libraries = dependencies(tools, prefix / "lib")
    for name, path in libraries.items():
        shutil.copy2(path.resolve(), target / "lib" / name)   # a real file under the name the binaries ask for
    for tool in tools:
        subprocess.run([str(target / "bin" / tool.name), "-hide_banner", "-version"], check=True, capture_output=True)
    print(f"Added FFmpeg and FFprobe with {len(libraries)} libraries to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
