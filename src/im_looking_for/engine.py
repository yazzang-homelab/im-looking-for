"""The index and the model server together, as the CLI and the web UI use them.

The helper process starts on first use and keeps running while the engine lives. A search alone loads only the text
model; indexing restarts it with the image and audio encoders when they're needed.

A GPU build that can't start, dies, or returns garbage (a laptop's missing or broken GPU driver) isn't fatal: the same
build runs on the processor instead, and the config remembers why so later runs don't try the GPU again.
"""

from __future__ import annotations

import threading
from pathlib import Path

from . import assets, extract, indexer, paths
from .config import Config
from .embed import Embedder, ServerEmbedder
from .search import Result, search
from .server import LlamaServer, ServerUnavailable
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
            if self._server is not None and (media and not self._server.media or not self._server.running()):
                self._server.stop()
                self._server = None
            if self._server is None:
                self._server = self._start(media)
            return ServerEmbedder(self._server)

    def uses_gpu(self) -> bool:
        return self.config.gpu_failed is None and assets.installed_backend() not in (None, "cpu")

    def _start(self, media: bool) -> LlamaServer:
        server = LlamaServer(media=media, gpu=self.uses_gpu())
        try:
            server.start()
        except ServerUnavailable as e:
            if not server.gpu:
                raise
            self._give_up_gpu(e)
            server = LlamaServer(media=media, gpu=False)
            server.start()
        return server

    def _give_up_gpu(self, error: Exception) -> None:
        self.config.gpu_failed = str(error)[:300]
        self.config.save()

    def _retry_on_cpu(self, error: ServerUnavailable) -> bool:
        """After the server failed mid-way: whether it ran on the GPU, in which case the next one won't."""
        with self._server_lock:
            if self._fixed_embedder is not None or self._server is None or not self._server.gpu:
                return False
            self._server.stop()
            self._server = None
            self._give_up_gpu(error)
            return True

    def search(self, query: str, limit: int = 30, kinds: set[str] | None = None) -> list[Result]:
        try:
            return search(self.store, self.embedder(media=False), query, limit=limit, kinds=kinds)
        except ServerUnavailable as e:
            if not self._retry_on_cpu(e):
                raise
            return search(self.store, self.embedder(media=False), query, limit=limit, kinds=kinds)

    def index(self, folders: list[str] | None = None, on_progress=None,
              stop: threading.Event | None = None) -> indexer.Progress:
        everything = not folders
        roots = [Path(f) for f in (folders or self.config.folders)]
        if not roots:
            raise ValueError("no folders to index; add one with `ilf add <folder>`")
        excluded_folders, excluded_extensions = self.config.exclusions()

        def run() -> indexer.Progress:
            return indexer.index(self.store, lambda: self.embedder(media=True), roots, extract.Options(),
                                 excluded_folders, excluded_extensions, on_progress, stop,
                                 prune_outside=everything)

        try:
            return run()
        except ServerUnavailable as e:
            if not self._retry_on_cpu(e):
                raise
            return run()  # what the GPU already read is kept and counted as unchanged

    def stop_server(self) -> None:
        """Stops the helper process (it starts again on next use): on Windows it locks the build ``setup`` replaces."""
        with self._server_lock:
            if self._server is not None:
                self._server.stop()
                self._server = None

    def close(self) -> None:
        self.stop_server()
        self.store.close()

    def __enter__(self) -> Engine:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
