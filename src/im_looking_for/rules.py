"""Which files im-looking-for reads, and as what. Everything else is left alone.

It never reads hidden folders (``.ssh``, ``.git``, …), dependency and build folders, app bundles, keys, certificates,
password stores or files that look like secrets, and never follows a link out of the folders it was given.
"""

from __future__ import annotations

import os
from pathlib import Path

IMAGE = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff"}
PDF = {"pdf"}
TEXT = {"txt", "md", "markdown", "rst", "org", "csv", "tsv", "log", "html", "htm", "xml", "srt", "vtt", "tex"}
OFFICE = {"docx", "pptx", "xlsx", "odt", "odp", "ods", "hwpx"}
AUDIO = {"mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "wma"}
VIDEO = {"mp4", "mov", "m4v", "mkv", "webm", "avi", "wmv", "mpg", "mpeg"}

KINDS = {**{e: "image" for e in IMAGE}, **{e: "pdf" for e in PDF}, **{e: "doc" for e in TEXT | OFFICE},
         **{e: "audio" for e in AUDIO}, **{e: "video" for e in VIDEO}}

SKIPPED_FOLDERS = {
    "node_modules", "__pycache__", "venv", ".venv", "site-packages", "dist", "build", "target", "vendor",
    "Library", "AppData", "Program Files", "Program Files (x86)", "Windows", "$RECYCLE.BIN",
    "System Volume Information", "Caches", "cache", ".cache", "Trash", ".Trash",
}
SKIPPED_SUFFIXES = (".app", ".framework", ".bundle", ".photoslibrary", ".lrlibrary", ".xcassets", ".pkg")
SECRET_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "credentials", "known_hosts", ".netrc", ".pgpass",
                "secrets.txt", "passwords.txt"}
SECRET_EXTENSIONS = {"pem", "key", "p12", "pfx", "crt", "cer", "der", "keychain", "kdbx", "gpg", "asc", "ovpn"}


def extension(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def kind_of(path: Path, excluded_extensions: frozenset[str] = frozenset()) -> str | None:
    """What a file is read as, or None when it isn't read at all."""
    name = path.name
    lowered = name.lower()
    ext = extension(path)
    if name.startswith(".") or lowered in SECRET_NAMES or ext in SECRET_EXTENSIONS or ext in excluded_extensions:
        return None
    if lowered.startswith(".env") or "secret" in lowered or "password" in lowered:
        return None
    return KINDS.get(ext)


def skip_folder(name: str, excluded: frozenset[str] = frozenset()) -> bool:
    return (name.startswith(".") or name in SKIPPED_FOLDERS or name.endswith(SKIPPED_SUFFIXES)
            or name in excluded)


def walk(roots: list[Path], excluded_folders: frozenset[str] = frozenset(),
         excluded_extensions: frozenset[str] = frozenset()):
    """Yields (path, kind) for every readable file under ``roots``, without following links."""
    seen: set[Path] = set()
    for root in roots:
        root = Path(root).expanduser().resolve()
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        for folder, folders, files in os.walk(root, followlinks=False, onerror=lambda error: None):
            folders[:] = sorted(f for f in folders if not skip_folder(f, excluded_folders)
                                and str(Path(folder, f)) not in excluded_folders)
            for name in sorted(files):
                path = Path(folder, name)
                if path.is_symlink():
                    continue
                kind = kind_of(path, excluded_extensions)
                if kind:
                    yield path, kind
