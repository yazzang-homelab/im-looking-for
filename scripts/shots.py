"""Screenshots of the app's main states, for docs and review: python scripts/shots.py OUT_DIR [--lang ko|en].

Starts ``ilf serve`` twice: against an empty data folder (the first-run wizard) and against ILF_HOME (an installed,
indexed one), then drives the page with Playwright. Needs ``pip install playwright`` and a Chromium
(CHROMIUM=/path or ``playwright install chromium``).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def start(home: str) -> tuple[subprocess.Popen, str]:
    env = {**os.environ, "ILF_HOME": home, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "im_looking_for", "serve", "--no-browser", "--port", "0"],
                            env=env, stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline()
    url = re.search(r"http://\S+/", line).group(0)
    return proc, url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--query", default=None)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    query = args.query or ("탁자 위의 빨간 과일" if args.lang == "ko" else "a red fruit on a table")
    real_home = os.environ["ILF_HOME"]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None, args=["--no-sandbox"])

        def page_for(url):
            page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2,
                                    locale="ko-KR" if args.lang == "ko" else "en-US")
            page.add_init_script(f"localStorage.setItem('ilf.lang', '{args.lang}')")
            page.goto(url)
            page.wait_for_timeout(600)
            return page

        with tempfile.TemporaryDirectory() as empty:
            proc, url = start(empty)
            try:
                page = page_for(url)
                page.screenshot(path=out / f"wizard-{args.lang}.png")
            finally:
                proc.terminate()

        proc, url = start(real_home)
        try:
            page = page_for(url)
            page.screenshot(path=out / f"home-{args.lang}.png")
            page.fill("#q", query)
            page.press("#q", "Enter")
            page.wait_for_selector(".card", timeout=120_000)
            page.wait_for_timeout(2500)
            page.screenshot(path=out / f"results-{args.lang}.png")
            page.click(".chip[data-kind=doc]")
            page.wait_for_timeout(2500)
            page.click(".chip[data-kind=all]")
            page.wait_for_timeout(2500)
            page.click("#pill")
            page.wait_for_timeout(800)
            page.screenshot(path=out / f"library-{args.lang}.png")
            page.click("#addfolder")
            page.wait_for_timeout(1200)
            page.screenshot(path=out / f"folders-{args.lang}.png")
        finally:
            proc.terminate()
        browser.close()
    print("\n".join(sorted(str(f) for f in out.glob(f"*-{args.lang}.png"))))
    time.sleep(0.2)


if __name__ == "__main__":
    main()
