from pathlib import Path

from rummage import rules


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
    found = [p for p, _ in rules.walk([tmp_path], excluded_folders=frozenset({"private"}))]
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
    assert [p.name for p, _ in rules.walk([root])] == ["a.txt"]
