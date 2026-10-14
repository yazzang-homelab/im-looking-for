"""Opens a result with the app the system uses for it, or shows it in the file manager."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def open_file(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _chromium() -> str | None:
    """A Chromium-family browser, which can show a page as its own window (``--app``)."""
    names = ["msedge", "chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave",
             "brave-browser"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        roots = [os.environ.get(v, "") for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        tails = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
        candidates = [os.path.join(r, t) for r in roots if r for t in tails]
    elif sys.platform == "darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                      "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        candidates = []
    return next((c for c in candidates if os.path.isfile(c)), None)


def open_app(url: str, window: bool = True) -> None:
    """Show the app: a window of its own if a Chromium browser is installed, else a tab in the default browser."""
    browser = _chromium() if window else None
    if browser:
        try:
            subprocess.Popen([browser, f"--app={url}", "--window-size=1200,820"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)
