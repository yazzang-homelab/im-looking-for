import os
import subprocess
import threading
from pathlib import Path

import pytest

from im_looking_for import rules


def touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_kinds_and_secrets():
    assert rules.kind_of(Path("a/IMG_1.JPG")) == "image"
    assert rules.kind_of(Path("report.pdf")) == "pdf"
    assert rules.kind_of(Path("notes.hwpx")) == "doc"
    assert rules.kind_of(Path("talk.m4a")) == "audio"
    assert rules.kind_of(Path("clip.mkv")) == "video"
    assert rules.kind_of(Path("program.exe")) is None
    for secret in ["id_rsa", "server.pem", "my.key", ".env", ".env.local", "passwords.txt", "aws_secret.txt",
                   ".hidden.txt", "vault.kdbx"]:
        assert rules.kind_of(Path(secret)) is None, secret
    assert rules.kind_of(Path("notes.txt"), frozenset({"txt"})) is None


def test_walk_skips_hidden_dependency_and_excluded_folders(tmp_path):
    keep = touch(tmp_path / "docs" / "a.txt")
    touch(tmp_path / ".ssh" / "config.txt")
    touch(tmp_path / ".git" / "notes.md")
    touch(tmp_path / "node_modules" / "pkg" / "README.md")
    touch(tmp_path / "Photos.photoslibrary" / "x.jpg")
    touch(tmp_path / "private" / "b.txt")
    found = [w[0] for w in rules.walk([tmp_path], excluded_folders=frozenset({"private"}))]
    assert found == [keep]


def test_walk_does_not_follow_links(tmp_path):
    outside = touch(tmp_path / "outside" / "secret.txt")
    root = tmp_path / "root"
    touch(root / "a.txt")
    try:
        (root / "link.txt").symlink_to(outside)
        (root / "linkdir").symlink_to(outside.parent, target_is_directory=True)
    except OSError:  # Windows without the symlink privilege
        return
    assert [w[0].name for w in rules.walk([root])] == ["a.txt"]


def test_walk_stops_when_asked_and_reports_folders(tmp_path):
    for i in range(3):
        touch(tmp_path / f"d{i}" / "a.txt")
    stop, opened = threading.Event(), []

    def on_folder(folder):
        opened.append(folder)
        if len(opened) == 2:
            stop.set()

    found = list(rules.walk([tmp_path], stop=stop, on_folder=on_folder))
    assert len(opened) == 2 and len(found) <= 1
    path, kind, size, mtime = next(rules.walk([tmp_path]))
    assert kind == "doc" and size == path.stat().st_size and mtime == path.stat().st_mtime


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows thing")
def test_walk_does_not_follow_junctions(tmp_path):
    root = tmp_path / "root"
    touch(root / "a.txt")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "Application Data"), str(root)], check=True,
                   capture_output=True)
    assert [w[0].name for w in rules.walk([root])] == ["a.txt"]
