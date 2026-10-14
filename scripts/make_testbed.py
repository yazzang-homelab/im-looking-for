"""Builds a folder of test files for trying im-looking-for and for `scripts/eval.py`.

Needs ffmpeg; LibreOffice (``soffice``) for the .docx/.pdf, espeak-ng for spoken audio, and network access for the
Wikimedia Commons photos (their authors and licenses are on each file's page, listed in ``SOURCES.txt``).
Whatever a missing tool would make is skipped and reported.

    python scripts/make_testbed.py ./testbed
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UA = "im-looking-for-testbed/0.1 (test data builder; python-urllib)"

PHOTOS = {  # Wikimedia Commons file name -> local name
    "Dog_on_beach.jpg": "IMG_0412.jpg",
    "Cat_November_2010-1a.jpg": "IMG_0977.jpg",
    "Matterhorn_from_Domhütte_-_2.jpg": "DSC_2201.jpg",
    "Red_Apple.jpg": "photo_3.jpg",
    "Bicycle_in_Amsterdam.jpg": "P1010034.jpg",
}

DOCS = {
    "lease_2026.txt": (
        "주택 임대차 계약서\n\n제1조 (목적) 임대인과 임차인은 아래 표시 주택에 관하여 다음과 같이 임대차 계약을 체결한다.\n\n"
        "제5조 (계약의 해지) 임차인이 2기의 차임액에 달하도록 연체하는 경우 임대인은 계약을 해지할 수 있다. "
        "임차인은 계약 만료 1개월 전까지 갱신 거절의 통지를 하여야 한다.\n\n"
        "제7조 (반려동물) 임차인은 임대인의 서면 동의 없이 반려동물을 사육할 수 없다.\n"),
    "meeting_notes.txt": (
        "Q3 planning meeting\n\nAttendees: Mina, Joon, Sarah.\n\nBudget: marketing spend is cut by 15 percent for the "
        "fourth quarter. Hiring freeze until January. Sarah will draft the new travel policy.\n\n"
        "Action items: Joon books the offsite venue near the lake; Mina sends the revised forecast by Friday.\n"),
    "kimchi.txt": (
        "김치찌개 끓이는 법\n\n잘 익은 김치 두 컵과 돼지고기 앞다리살 200그램을 준비한다. 냄비에 기름을 두르고 고기를 볶다가 "
        "김치를 넣고 함께 볶는다. 물을 붓고 고춧가루와 다진 마늘을 넣어 20분간 끓인 뒤 두부와 대파를 넣는다.\n"),
    "thesis_intro.txt": (
        "Chapter 1. Introduction\n\nCoral reefs cover less than one percent of the ocean floor but support about a "
        "quarter of all marine species. Rising sea temperatures cause coral bleaching, in which corals expel the algae "
        "living in their tissues. This thesis measures bleaching recovery rates on three reefs between 2019 and 2025.\n"),
}

SPEECH = {
    "voice_memo_01.wav": ("en", "Remind me to talk to the doctor about sleep. I have been waking up at four in the "
                                "morning every night this week and I cannot fall asleep again."),
    "voice_memo_02.wav": ("ko", "내일 오전 열 시에 치과 예약이 있습니다. 가는 길에 세탁소에 들러서 정장을 찾아 오세요."),
}


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    notes = []
    (out / "photos").mkdir(exist_ok=True)
    for remote, local in PHOTOS.items():
        target = out / "photos" / local
        if target.exists():
            continue
        url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(remote)}?width=1024"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            target.write_bytes(urllib.request.urlopen(request, timeout=60).read())
            notes.append(f"photos/{local}: https://commons.wikimedia.org/wiki/File:{remote}")
        except OSError as e:
            print(f"skipped {remote}: {e}")
    (out / "docs").mkdir(exist_ok=True)
    for name, text in DOCS.items():
        (out / "docs" / name).write_text(text, encoding="utf-8")
    soffice = shutil.which("soffice")
    if soffice:
        lease = out / "docs" / "lease_2026.txt"
        thesis = out / "docs" / "thesis_intro.txt"
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out / "docs"), str(lease)],
                       check=True, capture_output=True)
        subprocess.run([soffice, "--headless", "--convert-to", "docx", "--outdir", str(out / "docs"), str(thesis)],
                       check=True, capture_output=True)
        lease.unlink()
        thesis.unlink()
    else:
        print("skipped .pdf/.docx: no soffice")
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    (out / "recordings").mkdir(exist_ok=True)
    if espeak:
        for name, (voice, text) in SPEECH.items():
            subprocess.run([espeak, "-v", voice, "-s", "150", "-w", str(out / "recordings" / name), text], check=True)
    else:
        print("skipped speech: no espeak-ng")
    if notes:
        (out / "SOURCES.txt").write_text("\n".join(notes) + "\n", encoding="utf-8")
    print(f"Test files are in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "testbed")))
