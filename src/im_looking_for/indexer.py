"""Keeps the index in step with the folders: reads new and changed files, forgets deleted ones.

A file is read again only when its size or modification time changed. Each file's segments are written in one
transaction, so a stopped run leaves a consistent index and the next run carries on where it stopped.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import extract, rules
from .embed import VECTOR_VERSION, Embedder
from .server import ServerUnavailable
from .store import Store

# What people look for most gets searchable first.
ORDER = {"image": 0, "pdf": 1, "doc": 2, "audio": 3, "video": 4}


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0
    current: str = ""
    started: float = field(default_factory=time.time)
    errors: list[tuple[str, str]] = field(default_factory=list)


def name_text(path: Path, roots: list[Path]) -> str:
    """The file name and the folders between it and its root: what keyword search matches a name against."""
    for root in roots:
        try:
            relative = path.relative_to(root)
            return " ".join([root.name, *relative.parts])
        except ValueError:
            continue
    return path.name


def _under(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def ensure_version(store: Store, options: extract.Options) -> None:
    """An index made by another model build or other reading settings is emptied, so vectors never mix."""
    version = f"{VECTOR_VERSION} {options.fingerprint()}"
    if store.get_meta("vector_version") not in (None, version):
        store.clear()
    store.set_meta("vector_version", version)


def index(store: Store, embedder: Embedder, roots: list[Path], options: extract.Options | None = None,
          excluded_folders: frozenset[str] = frozenset(), excluded_extensions: frozenset[str] = frozenset(),
          on_progress: Callable[[Progress], None] | None = None,
          stop: threading.Event | None = None, prune_outside: bool = False) -> Progress:
    options = options or extract.Options()
    roots = [Path(r).expanduser().resolve() for r in roots]
    ensure_version(store, options)
    progress = Progress()

    found = list(rules.walk(roots, excluded_folders, excluded_extensions))
    present = {str(p) for p, _ in found}
    # forget files that were deleted, or are now left out; with `prune_outside`, also files outside every root
    # (a folder taken off the list). Without it, other folders' files are left alone.
    # A root that isn't there right now (an unplugged drive) keeps its files.
    offline = [r for r in roots if not r.is_dir()]
    gone = [p for p in store.paths() if p not in present and not _under(Path(p), offline)
            and (prune_outside or _under(Path(p), roots))]
    store.remove_files(gone)
    progress.removed = len(gone)

    todo = []
    for path, kind in found:
        try:
            info = path.stat()
        except OSError:
            continue
        row = store.file(str(path))
        # unreadable files are tried again each run: the cause may have been fixed since
        if (row and row.status != "error" and row.size == info.st_size and row.mtime == info.st_mtime
                and row.kind == kind):
            progress.skipped += 1
            continue
        todo.append((ORDER[kind], path, kind, info.st_size, info.st_mtime))
    todo.sort(key=lambda t: t[0])
    progress.total = len(todo)
    if on_progress:
        on_progress(progress)

    for _, path, kind, size, mtime in todo:
        if stop is not None and stop.is_set():
            break
        progress.current = str(path)
        if on_progress:
            on_progress(progress)
        name = ("name", "none", 0.0, None, name_text(path, roots), None)
        try:
            segments = _embed_file(path, kind, options, embedder, stop)
        except ServerUnavailable:
            raise  # every file would fail the same way: stop and say why
        except Exception as e:  # one bad file never stops the rest
            error = f"{type(e).__name__}: {e}"[:500]
            progress.failed += 1
            progress.errors.append((str(path), error))
            store.replace_file(str(path), kind, size, mtime, "error", error, [name])
            continue
        if segments is None:
            break  # stopped in the middle of a file: it isn't written, the next run reads it whole
        store.replace_file(str(path), kind, size, mtime, "ok" if segments else "empty", None, [name, *segments])
        progress.done += 1
    progress.current = ""
    if on_progress:
        on_progress(progress)
    return progress


def _embed_file(path: Path, kind: str, options: extract.Options, embedder: Embedder,
                stop: threading.Event | None, batch: int = 8) -> list[tuple] | None:
    """The file's segments with their vectors, in reading order; None when ``stop`` was set on the way."""
    done: list[tuple] = []
    pending: list[extract.Segment] = []

    def flush() -> None:
        if pending:
            vectors = embedder.texts([s.prompt for s in pending])
            done.extend((s.kind, s.modality, s.loc, s.loc_end, s.text, np.asarray(v, np.float32))
                        for s, v in zip(pending, vectors))
            pending.clear()

    for segment in extract.read(path, kind, options):
        if stop is not None and stop.is_set():
            return None
        if segment.data is not None:
            flush()
            vector = embedder.media(segment.data)
            done.append((segment.kind, segment.modality, segment.loc, segment.loc_end, segment.text,
                         np.asarray(vector, np.float32)))
        else:
            pending.append(segment)
            if len(pending) >= batch:
                flush()
    flush()
    return done
