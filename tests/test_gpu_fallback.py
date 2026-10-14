"""A GPU build that fails (a laptop without a working GPU driver) falls back to the processor, and swapping the
llama.cpp build never leaves a half-deleted one behind."""

from __future__ import annotations

import os
import zipfile
from typing import ClassVar

import numpy as np
import pytest

from im_looking_for import assets, paths
from im_looking_for import engine as engine_module
from im_looking_for.config import Config
from im_looking_for.embed import DIM, ServerEmbedder
from im_looking_for.engine import Engine
from im_looking_for.server import ServerUnavailable


class FakeServer:
    """Stands in for LlamaServer. ``broken`` decides how a GPU one fails: at "start", or "later" on the first input."""

    broken = "start"
    started: ClassVar[list[bool]] = []

    def __init__(self, media: bool = True, gpu: bool = True, **_):
        self.media, self.gpu, self.media_marker, self.alive = media, gpu, "<__media__>", False

    def start(self) -> None:
        if self.gpu and self.broken == "start":
            raise ServerUnavailable("llama-server exited with 3221225477")
        self.alive = True
        FakeServer.started.append(self.gpu)

    def running(self) -> bool:
        return self.alive

    def stop(self) -> None:
        self.alive = False

    def post(self, route: str, body: dict) -> dict:
        if self.gpu:
            raise ServerUnavailable("llama-server stopped")
        count = len(body["input"]) if isinstance(body["input"], list) else 1
        rows = np.random.default_rng(count).standard_normal((count, DIM))
        return {"data": [{"index": i, "embedding": row.tolist()} for i, row in enumerate(rows)]}


@pytest.fixture
def gpu_build(monkeypatch):
    monkeypatch.setattr(engine_module, "LlamaServer", FakeServer)
    monkeypatch.setattr(assets, "installed_backend", lambda: "vulkan")
    FakeServer.started = []
    paths.data_dir().mkdir(parents=True, exist_ok=True)


@pytest.mark.parametrize("broken", ["start", "later"])
def test_a_failing_gpu_falls_back_to_the_processor(gpu_build, tmp_path, broken):
    FakeServer.broken = broken
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "note.txt").write_text("a note about the quarterly budget meeting", encoding="utf-8")
    config = Config(folders=[str(folder)])
    with Engine(config=config) as engine:
        progress = engine.index()
        assert progress.done == 1 and progress.failed == 0
        assert engine.search("budget", limit=1)[0].path.endswith("note.txt")
        assert not engine.uses_gpu()
    assert FakeServer.started[-1] is False
    assert "llama-server" in Config.load().gpu_failed  # remembered: the next run starts on the processor
    FakeServer.started = []
    with Engine() as engine:
        engine.search("budget")
    assert FakeServer.started == [False]


def test_a_cpu_build_has_nothing_to_fall_back_to(monkeypatch):
    monkeypatch.setattr(engine_module, "LlamaServer", FakeServer)
    monkeypatch.setattr(assets, "installed_backend", lambda: "cpu")
    with Engine(config=Config()) as engine:
        assert not engine.uses_gpu()


def test_garbage_vectors_count_as_a_broken_server():
    class Zeros:
        def post(self, route, body):
            return {"data": [{"index": 0, "embedding": [0.0] * DIM}]}

    class NaNs:
        def post(self, route, body):
            return {"data": [{"index": 0, "embedding": [float("nan")] * DIM}]}

    for server in (Zeros(), NaNs()):
        with pytest.raises(ServerUnavailable):
            ServerEmbedder(server).texts(["hello"])


def _fake_download(content: str):
    def download(asset, destination, progress=None):
        with zipfile.ZipFile(destination, "w") as z:
            z.writestr(assets.server_executable_name(), content)
        return destination
    return download


def test_swapping_a_build_in_use_changes_nothing(monkeypatch):
    monkeypatch.setattr(assets, "host", lambda: ("windows", "x64"))
    monkeypatch.setattr(assets, "download", _fake_download("vulkan"))
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    assets.install_runtime("vulkan")
    root = paths.runtime_dir()
    before = sorted(p.name for p in root.iterdir())

    real_replace = os.replace

    def locked(src, dst):  # what Windows does while llama-server.exe has the DLLs open
        if os.fspath(src) == os.fspath(root):
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(assets.os, "replace", locked)
    monkeypatch.setattr(assets, "download", _fake_download("cpu"))
    with pytest.raises(RuntimeError, match="in use"):
        assets.install_runtime("cpu")
    assert sorted(p.name for p in root.iterdir()) == before
    assert assets.installed_backend() == "vulkan"

    monkeypatch.setattr(assets.os, "replace", real_replace)
    stopped = []
    assets.install_runtime("cpu", before_replace=lambda: stopped.append(True))
    assert stopped == [True]
    assert assets.installed_backend() == "cpu"
    assert (root / assets.server_executable_name()).read_text() == "cpu"
