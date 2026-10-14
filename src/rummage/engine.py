"""The index and the model server together, as the CLI and the web UI use them.

The helper process starts on first use and keeps running while the engine lives. A search alone loads only the text
model; indexing restarts it with the image and audio encoders when they're needed.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import extract, indexer, paths
from .config import Config
from .embed import Embedder, ServerEmbedder
from .search import Result, search
from .server import LlamaServer
from .store import Store


class Engine:
    def __init__(self, config: Config | None = None, index_path: Path | None = None,
                 embedder: Embedder | None = None):
        self.config = config or Config.load()
        self.store = Store(index_path or paths.index_file())
        self._fixed_embedder = embedder  # tests: no helper process
        self._server: LlamaServer | None = None
        self._server_lock = threading.Lock()

    def embedder(self, media: bool) -> Embedder:
        if self._fixed_embedder is not None:
            return self._fixed_embedder
        with self._server_lock:
            if self._server is not None and media and not self._server.media:
                self._server.stop()
                self._server = None
            if self._server is None:
                self._server = LlamaServer(media=media)
                self._server.start()
            return ServerEmbedder(self._server)

    def search(self, query: str, limit: int = 30, kinds: set[str] | None = None) -> list[Result]:
        return search(self.store, self.embedder(media=False), query, limit=limit, kinds=kinds)

    def index(self, folders: list[str] | None = None, on_progress=None,
              stop: threading.Event | None = None) -> indexer.Progress:
        everything = not folders
        roots = [Path(f) for f in (folders or self.config.folders)]
        if not roots:
            raise ValueError("no folders to index; add one with `rummage add <folder>`")
        excluded_folders, excluded_extensions = self.config.exclusions()
        return indexer.index(self.store, self.embedder(media=True), roots, extract.Options(),
                             excluded_folders, excluded_extensions, on_progress, stop,
                             prune_outside=everything)

    def close(self) -> None:
        with self._server_lock:
            if self._server is not None:
                self._server.stop()
                self._server = None
        self.store.close()

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
