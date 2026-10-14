"""Which files im-looking-for reads, and as what. Everything else is left alone.

It never reads hidden folders (``.ssh``, ``.git``, …), dependency and build folders, app bundles, keys, certificates,
password stores or files that look like secrets, and never follows a link out of the folders it was given.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
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


JUNCTION = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT


def _is_link(entry: os.DirEntry) -> bool:
    """Symlinks, and on Windows junctions too: every profile has ``Application Data`` and ``Local Settings``
    pointing back into it, so following them goes round forever. (OneDrive's cloud files are reparse points of
    another kind and are read.)"""
    if entry.is_symlink():
        return True
    return os.name == "nt" and getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0) == JUNCTION


def walk(roots: list[Path], excluded_folders: frozenset[str] = frozenset(),
         excluded_extensions: frozenset[str] = frozenset(), stop: threading.Event | None = None,
         on_folder: Callable[[str], None] | None = None) -> Iterator[tuple[Path, str, int, float]]:
    """Yields (path, kind, size, mtime) for every readable file under ``roots``, without following links or
    junctions. Sizes and times come from the directory listing itself, which on Windows saves a call per file.
    Ends early once ``stop`` is set; ``on_folder`` hears each folder as it's opened."""
    seen: set[Path] = set()
    for root in roots:
        root = Path(root).expanduser().resolve()
        if root in seen or not root.is_dir():
            continue
        seen.add(root)
        pending = [str(root)]
        while pending:
            if stop is not None and stop.is_set():
                return
            folder = pending.pop()
            if on_folder:
                on_folder(folder)
            try:
                with os.scandir(folder) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError:
                continue
            folders = []
            for entry in entries:
                try:
                    if _is_link(entry):
                        continue
                    if entry.is_dir():
                        if not skip_folder(entry.name, excluded_folders) and entry.path not in excluded_folders:
                            folders.append(entry.path)
                        continue
                    path = Path(entry.path)
                    kind = kind_of(path, excluded_extensions)
                    if kind:
                        info = entry.stat()
                        yield path, kind, info.st_size, info.st_mtime
                except OSError:
                    continue
            pending.extend(reversed(folders))  # depth first, in name order
