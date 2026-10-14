"""Sound and video through ffmpeg: the one on PATH, else the build that ships with ``imageio-ffmpeg``."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from PIL import Image

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@lru_cache(maxsize=1)
def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg  # bundled binaries for Windows, macOS and Linux

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, creationflags=_NO_WINDOW)


def probe(path: Path) -> tuple[float, bool, bool]:
    """(duration in seconds, has video, has audio). Cover art in a music file doesn't count as video."""
    result = _run(["-i", str(path)], timeout=60)
    text = result.stderr.decode("utf-8", "replace")
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]) if match else 0.0
    video = any("attached pic" not in line for line in re.findall(r"Stream #.*Video:.*", text))
    audio = "Audio:" in text
    return duration, video, audio


def audio_window(path: Path, start: float, length: float) -> bytes:
    """``length`` seconds from ``start`` as 16 kHz mono 16-bit WAV, what the model's audio encoder takes."""
    result = _run(["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-vn", "-ac", "1",
                   "-ar", "16000", "-sample_fmt", "s16", "-f", "wav", "pipe:1"], timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-300:])
    return result.stdout


def audio_windows(path: Path, duration: float, window: float, hop: float,
                  limit: int) -> Iterator[tuple[float, float, bytes]]:
    """(start, end, wav) for overlapping windows; a last window shorter than 2 s is dropped."""
    start = 0.0
    count = 0
    while start < max(duration, 0.1) and count < limit:
        end = min(start + window, duration) if duration else start + window
        if count and end - start < 2.0:
            break
        data = audio_window(path, start, end - start)
        if len(data) > 44 + 16000:  # more than half a second of sound after the header
            yield start, end, data
        start += hop
        count += 1


def frames(path: Path, interval: float, max_side: int, limit: int) -> Iterator[tuple[float, Image.Image]]:
    """One frame every ``interval`` seconds (at most ``limit``), as (time, picture)."""
    scale = f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'"
    result = _run(["-i", str(path), "-an", "-vf", f"fps=1/{interval},{scale}", "-frames:v", str(limit),
                   "-c:v", "mjpeg", "-q:v", "4", "-f", "image2pipe", "pipe:1"], timeout=3600)
    data = result.stdout
    index = 0
    position = 0
    while True:
        start = data.find(b"\xff\xd8", position)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            break
        position = end + 2
        try:
            picture = Image.open(io.BytesIO(data[start:position]))
            picture.load()
        except OSError:
            continue
        yield index * interval, picture
        index += 1
