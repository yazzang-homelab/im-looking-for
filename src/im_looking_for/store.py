"""The index: one SQLite file with a row per file, a row per segment (with its vector), and a keyword index.

Vectors are stored as float16 (1.5 KB each); the keyword index uses SQLite's trigram tokenizer, so it finds words in
Korean, Japanese and Chinese too, where words aren't separated by spaces or carry particles ("고양이가").
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embed import DIM

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    status TEXT NOT NULL,          -- ok | empty | error
    error TEXT,
    indexed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,            -- name | image | page | page_image | chunk | audio | frame
    modality TEXT NOT NULL,        -- none | text | image | audio
    loc REAL NOT NULL DEFAULT 0,
    loc_end REAL,
    text TEXT NOT NULL DEFAULT '',
    vector BLOB
);
CREATE INDEX IF NOT EXISTS segments_file ON segments(file_id);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""


@dataclass
class FileRow:
    id: int
    path: str
    kind: str
    size: int
    mtime: float
    status: str


@dataclass
class Vectors:
    """Every vector in the index, in one matrix, with the segment ids and modalities of its rows."""
    ids: np.ndarray        # int64
    file_ids: np.ndarray   # int64
    modalities: np.ndarray  # str
    matrix: np.ndarray     # float32 (n, DIM)


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5("
                            "text, content='segments', content_rowid='id', tokenize='trigram')")
            self.trigram = True
        except sqlite3.OperationalError:  # SQLite before 3.34
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5("
                            "text, content='segments', content_rowid='id')")
            self.trigram = False
        self._cache: Vectors | None = None
        self._cache_generation = -1

    def close(self) -> None:
        self.db.close()

    def _rows(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, params).fetchall()

    def _row(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # meta

    def get_meta(self, key: str) -> str | None:
        row = self._row("SELECT value FROM meta WHERE key = ?", (key,))
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO meta(key, value) VALUES (?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def generation(self) -> int:
        return int(self.get_meta("generation") or 0)

    def _bump(self) -> None:
        self.db.execute("INSERT INTO meta(key, value) VALUES ('generation', '1') "
                        "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1")

    # files

    def file(self, path: str) -> FileRow | None:
        row = self._row("SELECT id, path, kind, size, mtime, status FROM files WHERE path = ?", (path,))
        return FileRow(**dict(row)) if row else None

    def file_by_id(self, file_id: int) -> FileRow | None:
        row = self._row("SELECT id, path, kind, size, mtime, status FROM files WHERE id = ?", (file_id,))
        return FileRow(**dict(row)) if row else None

    def paths(self) -> list[str]:
        return [r[0] for r in self._rows("SELECT path FROM files")]

    def replace_file(self, path: str, kind: str, size: int, mtime: float, status: str, error: str | None,
                     segments: list[tuple[str, str, float, float | None, str, np.ndarray | None]]) -> None:
        """Writes a file and its segments (kind, modality, loc, loc_end, text, vector) in one transaction,
        replacing whatever the index had for that path."""
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute("DELETE FROM files WHERE path = ?", (path,))
                file_id = self.db.execute(
                    "INSERT INTO files(path, kind, size, mtime, status, error, indexed_at) VALUES (?,?,?,?,?,?,?)",
                    (path, kind, size, mtime, status, error, time.time())).lastrowid
                self.db.executemany(
                    "INSERT INTO segments(file_id, kind, modality, loc, loc_end, text, vector) VALUES (?,?,?,?,?,?,?)",
                    [(file_id, k, m, loc, end, text,
                      None if v is None else np.asarray(v, np.float16).tobytes())
                     for k, m, loc, end, text, v in segments])
                self._bump()
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def remove_files(self, paths: list[str]) -> None:
        if not paths:
            return
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in paths])
            self._bump()
            self.db.execute("COMMIT")

    def clear(self) -> None:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("DELETE FROM files")
            self.db.execute("INSERT INTO segments_fts(segments_fts) VALUES ('rebuild')")
            self._bump()
            self.db.execute("COMMIT")

    # reading

    def vectors(self) -> Vectors:
        generation = self.generation()
        if self._cache is not None and generation == self._cache_generation:
            return self._cache
        rows = self._rows("SELECT id, file_id, modality, vector FROM segments WHERE vector IS NOT NULL")
        if rows:
            matrix = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float16).reshape(len(rows), DIM)
            cache = Vectors(np.array([r[0] for r in rows], np.int64), np.array([r[1] for r in rows], np.int64),
                            np.array([r[2] for r in rows]), matrix.astype(np.float32))
        else:
            cache = Vectors(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, str),
                            np.zeros((0, DIM), np.float32))
        self._cache, self._cache_generation = cache, generation
        return cache

    def passages(self, path: str, loc: float | None = None, limit: int = 20) -> list[dict]:
        """The text the index holds for a file: the segments at ``loc`` (a page, chunk or second), else the first
        ``limit`` segments in reading order. Pictures and sound have no text; they come back with an empty one."""
        sql = ("SELECT s.kind, s.modality, s.loc, s.loc_end, s.text FROM segments s JOIN files f ON f.id = s.file_id "
               "WHERE f.path = ? AND s.kind != 'name'")
        params: list = [path]
        if loc is not None:
            sql += " AND s.loc <= ? AND COALESCE(s.loc_end, s.loc) >= ?"
            params += [loc, loc]
        sql += " ORDER BY s.loc, s.id LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._rows(sql, params)]

    def segment(self, segment_id: int) -> sqlite3.Row:
        return self._row("SELECT * FROM segments WHERE id = ?", (segment_id,))

    def keyword_hits(self, terms: list[str], limit: int = 500) -> dict[int, float]:
        """Segment id → share of ``terms`` (0–1] found in it. Terms of 3+ characters use the keyword index;
        shorter ones (common in Korean: "책", "회의") are matched only within the segments the long ones found,
        or by a capped scan when there are no long ones."""
        terms = [t for t in dict.fromkeys(t.strip().lower() for t in terms) if t]
        if not terms:
            return {}
        long_terms = [t for t in terms if len(t) >= 3] if self.trigram else terms
        found: dict[int, set[str]] = {}
        for term in long_terms:
            quoted = '"' + term.replace('"', '""') + '"'
            for (rowid,) in self._rows("SELECT rowid FROM segments_fts WHERE segments_fts MATCH ? LIMIT ?",
                                       (quoted, limit)):
                found.setdefault(rowid, set()).add(term)
        short_terms = [t for t in terms if t not in long_terms]
        if short_terms:
            if found:
                ids = list(found)
                placeholders = ",".join("?" * len(ids))
                rows = self._rows(f"SELECT id, lower(text) FROM segments WHERE id IN ({placeholders})", ids)
            else:
                like = " OR ".join("instr(lower(text), ?) > 0" for _ in short_terms)
                rows = self._rows(f"SELECT id, lower(text) FROM segments WHERE {like} LIMIT ?",
                                  (*short_terms, limit))
            for segment_id, text in rows:
                for term in short_terms:
                    if term in text:
                        found.setdefault(segment_id, set()).add(term)
        return {segment_id: len(hit) / len(terms) for segment_id, hit in found.items()}

    def stats(self) -> dict:
        files = {r[0]: r[1] for r in self._rows("SELECT kind, COUNT(*) FROM files WHERE status = 'ok' GROUP BY kind")}
        errors = self._row("SELECT COUNT(*) FROM files WHERE status = 'error'")[0]
        segments = self._row("SELECT COUNT(*) FROM segments WHERE vector IS NOT NULL")[0]
        return {"files": files, "errors": errors, "vectors": segments,
                "bytes": self.path.stat().st_size if self.path.exists() else 0}
