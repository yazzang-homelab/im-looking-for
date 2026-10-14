"""im-looking-for as an MCP server (``ilf mcp``), so an AI agent can find files on this computer by description.

Tools: ``search``, ``read_passages``, ``status``, ``add_folder``, ``remove_folder``, ``index``, ``stop_indexing``.
Indexing a folder can take minutes to hours on a CPU, so ``index`` starts it in the background and returns; the agent
polls ``status`` (its ``indexing`` field) while searches keep working on what's already read.

Nothing here leaves the computer: the model runs in a local llama.cpp process and the index is a local SQLite file.
"""

from __future__ import annotations

import threading
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, assets, status
from .engine import Engine
from .indexer import Progress

Kind = Literal["image", "pdf", "doc", "audio", "video"]

INSTRUCTIONS = """\
Searches the files on this computer by what is in them: photos, scanned and text PDFs, documents (txt/md/docx/pptx/
xlsx/odt/rtf/html), voice memos and other audio, and video. Describe what the file shows or says in any language
("receipt from the dentist", "슬라이드에 매출 그래프", "a cat on a red sofa") rather than guessing file names.
Search always returns the nearest files, even when nothing truly matches: a score (cosine similarity, roughly
0.5-0.95) is only meaningful relative to the other results. Trust a result that clearly leads the rest or whose snippet
says what was asked; treat a flat list of similar scores as "probably not here". Call read_passages to see more of a
match before relying on it. Only folders the user added are searched; if status shows none, or ready=false, tell the user to run `ilf setup` / `ilf add <folder>` (or use
add_folder + index if they asked you to). Never claim a file doesn't exist just because search found nothing."""


class Agent:
    """The engine plus a background indexing job, shared by every tool call."""

    def __init__(self, engine: Engine | None = None):
        self._engine = engine
        self._lock = threading.Lock()
        self.progress: Progress | None = None
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.error: str | None = None

    @property
    def engine(self) -> Engine:
        with self._lock:
            if self._engine is None:
                self._engine = Engine()
            return self._engine

    def indexing(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start_index(self, folders: list[str] | None) -> bool:
        if self.indexing():
            return False
        self.stop.clear()
        self.error = None
        self.progress = None

        def run() -> None:
            try:
                self.engine.index(folders, on_progress=lambda p: setattr(self, "progress", p), stop=self.stop)
            except Exception as e:  # reported by status()
                self.error = f"{type(e).__name__}: {e}"

        self.thread = threading.Thread(target=run, name="ilf-index", daemon=True)
        self.thread.start()
        return True

    def status(self) -> dict:
        report = status.describe(self.engine.config, self.engine.store)
        p = self.progress
        report["indexing"] = self.indexing()
        report["progress"] = None if p is None else {
            "total": p.total, "read": p.done, "unchanged": p.skipped, "unreadable": p.failed, "current": p.current}
        report["index_error"] = self.error
        return report

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
        if self._engine is not None:
            self._engine.close()


def build(agent: Agent) -> MCPServer:
    mcp = MCPServer("im-looking-for", instructions=INSTRUCTIONS, version=__version__)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @mcp.tool(annotations=read_only)
    def search(query: str, limit: int = 10, kinds: list[Kind] | None = None) -> dict:
        """Find files on this computer by describing their content, in any language.

        query: what the file shows, says or is about ("whiteboard photo with a timeline", "invoice from March").
        limit: how many results (1-50). kinds: only these kinds of file, e.g. ["image"] or ["pdf", "doc"].
        Returns results best first, each with path, kind, score, the matching page/second (where) and a snippet.
        """
        if not assets.ready():
            return {"error": "not set up: the user needs to run `ilf setup`", "results": []}
        results = agent.engine.search(query, limit=max(1, min(limit, 50)), kinds=set(kinds) if kinds else None)
        return {"query": query, "results": [r.to_dict() for r in results]}

    @mcp.tool(annotations=read_only)
    def read_passages(path: str, loc: float | None = None, limit: int = 10) -> dict:
        """The indexed text of a file found by search: the passage at loc (the page, chunk or second a result gave),
        or the first passages of the file. Images have no text; audio and video give their time ranges only."""
        if agent.engine.store.file(path) is None:
            return {"error": "not in the index; use a path returned by search", "passages": []}
        return {"path": path, "passages": agent.engine.store.passages(path, loc, max(1, min(limit, 50)))}

    @mcp.tool(name="status", annotations=read_only)
    def get_status() -> dict:
        """Whether the model is installed (ready), which folders are searched, what the index holds, and whether
        indexing is running (indexing, progress)."""
        return agent.status()

    @mcp.tool(annotations=ToolAnnotations(idempotent_hint=True, destructive_hint=False, open_world_hint=False))
    def add_folder(folder: str) -> dict:
        """Add a folder (and everything under it) to what gets searched. Run index afterwards to read it."""
        config = agent.engine.config
        added = config.add_folder(folder)
        config.save()
        return {"added": added, "folders": config.folders}

    @mcp.tool(annotations=ToolAnnotations(idempotent_hint=True, destructive_hint=True, open_world_hint=False))
    def remove_folder(folder: str) -> dict:
        """Stop searching a folder. Its files leave the index on the next full index run; nothing on disk is
        touched."""
        config = agent.engine.config
        removed = config.remove_folder(folder)
        config.save()
        return {"removed": removed, "folders": config.folders}

    @mcp.tool(annotations=ToolAnnotations(idempotent_hint=True, destructive_hint=False, open_world_hint=False))
    def index(folders: list[str] | None = None) -> dict:
        """Start reading new and changed files, in the background: all added folders, or just the ones given.
        Returns at once; poll status until indexing is false. Unchanged files are skipped, so it's cheap to rerun."""
        if not assets.ready():
            return {"error": "not set up: the user needs to run `ilf setup`", "started": False}
        if not (folders or agent.engine.config.folders):
            return {"error": "no folders added yet; use add_folder first", "started": False}
        started = agent.start_index(folders)
        return {"started": started, "already_running": not started}

    @mcp.tool(annotations=ToolAnnotations(idempotent_hint=True, destructive_hint=False, open_world_hint=False))
    def stop_indexing() -> dict:
        """Stop a running index job after the current file; the next index run continues from there."""
        agent.stop.set()
        return {"stopping": agent.indexing()}

    return mcp


def run() -> None:
    agent = Agent()
    try:
        build(agent).run("stdio")
    finally:
        agent.close()
