"""The two things Rummage downloads on first use, pinned and checksummed:

* llama.cpp's prebuilt ``llama-server`` for this computer (MIT), at the first build that runs EmbeddingGemma 2's
  text, vision and audio parts.
* ggml-org's Q8_0 GGUF conversion of google/embeddinggemma-2 (Apache 2.0): the text model and the image/audio
  encoders. Never the F16 files: the model's activations overflow float16.

Nothing is fetched unless asked (``rummage setup``), and a file only gets its final name once its SHA-256 matches.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import paths

LLAMA_TAG = "b11461"
USER_AGENT = "Rummage/0.1 (on-device file search; python-urllib)"

Progress = Callable[[str, int, int], None]


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str


MODEL_REPO = "ggml-org/embeddinggemma-2-GGUF"
MODEL_REVISION = "bfcd298762cc34d0357ece5ebdd31791a3a374d8"


def _model(name: str, size: int, sha256: str) -> Asset:
    return Asset(name, f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}", size, sha256)


TEXT_MODEL = _model("embeddinggemma-2-Q8_0.gguf", 309_855_456,
                    "2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135")
MEDIA_MODEL = _model("mmproj-embeddinggemma-2-Q8_0.gguf", 554_821_024,
                     "c4a8a52691ecef40618438928bdf9e68379b854e24166f292592353db0aab64f")
MODELS = (TEXT_MODEL, MEDIA_MODEL)

# (os, arch, backend) -> (release file, size, sha256). Sizes and digests are GitHub's, for tag LLAMA_TAG.
_RUNTIMES: dict[tuple[str, str, str], tuple[str, int, str]] = {
    ("darwin", "arm64", "metal"): ("macos-arm64.tar.gz", 12_007_683,
                                   "6cbf2bcbfe616e9e14f1e326fe34d15fbe127846ad4275f076b36694101ff2c1"),
    ("darwin", "x64", "cpu"): ("macos-x64.tar.gz", 11_525_318,
                               "a7a535031f6d54418ff8f34f29cdc53d5aa3bce3a5225ed19088b136a74ee1d5"),
    ("linux", "x64", "cpu"): ("ubuntu-x64.tar.gz", 17_732_768,
                              "9462d9b8243df6de8b6bf1baded7008a97e57d9f88611705a535b64d0682d87a"),
    ("linux", "x64", "vulkan"): ("ubuntu-vulkan-x64.tar.gz", 31_678_968,
                                 "6e1e169c5b045cf2ce83bb017448f11929ef40a02e028b5e7bdda9835fdc80fe"),
    ("linux", "arm64", "cpu"): ("ubuntu-arm64.tar.gz", 13_724_350,
                                "93f9d5043b6cef6044c2afd583ba74a09c43bddabf90403b584371e3a95764aa"),
    ("linux", "arm64", "vulkan"): ("ubuntu-vulkan-arm64.tar.gz", 24_887_582,
                                   "2ae500f379e0e379dd71e8641899d2251e2c9948410379d30b609fa1ee57eb85"),
    ("windows", "x64", "cpu"): ("win-cpu-x64.zip", 19_437_105,
                                "e283199134e74405a3684cfaa3911708ca7d051a8c2a8dcb10b3dfa1678913c3"),
    ("windows", "x64", "vulkan"): ("win-vulkan-x64.zip", 33_377_638,
                                   "6b9ca8ad3e43ac3e166d1997875709e4547214bb5bf1c2ebfdd17a2350a8380c"),
    ("windows", "arm64", "cpu"): ("win-cpu-arm64.zip", 12_264_397,
                                  "451257223ca76804a0cd1b3196cd08491b3c20e992a78e4243b8446a5eb2e382"),
}

# What a backend-less `setup` picks: the GPU where one is always there (Metal), Vulkan on Windows (drivers ship it),
# the CPU on Linux (Vulkan needs libvulkan, which a minimal install lacks; `--backend vulkan` asks for it).
_DEFAULT_BACKEND = {("darwin", "arm64"): "metal", ("darwin", "x64"): "cpu", ("linux", "x64"): "cpu",
                    ("linux", "arm64"): "cpu", ("windows", "x64"): "vulkan", ("windows", "arm64"): "cpu"}


def host() -> tuple[str, str]:
    """This computer as (os, arch) in the runtime table's words."""
    system = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if system is None or arch is None:
        raise RuntimeError(f"no llama.cpp build for {platform.system()} {platform.machine()}")
    return system, arch


def backends() -> list[str]:
    system, arch = host()
    return [b for (s, a, b) in _RUNTIMES if (s, a) == (system, arch)]


def default_backend() -> str:
    return _DEFAULT_BACKEND[host()]


def runtime_asset(backend: str | None = None) -> Asset:
    system, arch = host()
    backend = backend or default_backend()
    try:
        suffix, size, sha = _RUNTIMES[(system, arch, backend)]
    except KeyError:
        raise RuntimeError(f"no '{backend}' build of llama.cpp for {system} {arch}; "
                           f"choose one of: {', '.join(backends())}") from None
    name = f"llama-{LLAMA_TAG}-bin-{suffix}"
    return Asset(name, f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{name}", size, sha)


def server_executable_name() -> str:
    return "llama-server.exe" if sys.platform == "win32" else "llama-server"


def find_server() -> Path | None:
    """``RUMMAGE_LLAMA_SERVER`` if set, else the runtime ``setup`` installed. ``None`` when there is neither."""
    explicit = os.environ.get("RUMMAGE_LLAMA_SERVER")
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    root = paths.runtime_dir()
    if not root.is_dir():
        return None
    for found in sorted(root.rglob(server_executable_name())):
        if found.is_file():
            return found
    return None


def model_path(asset: Asset) -> Path:
    override = os.environ.get("RUMMAGE_MODEL_DIR")
    folder = Path(override) if override else paths.models_dir()
    return folder / asset.name


def missing_models() -> list[Asset]:
    return [m for m in MODELS if not model_path(m).is_file()]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for piece in iter(lambda: handle.read(8 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def download(asset: Asset, destination: Path, progress: Progress | None = None) -> Path:
    """Fetches ``asset`` to ``destination`` (resuming a partial ``.part``) and checks its size and SHA-256 before
    giving it its final name. A mismatch deletes the partial file and raises."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    have = partial.stat().st_size if partial.exists() else 0
    if have > asset.size:
        partial.unlink()
        have = 0
    if have < asset.size:
        request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
        if have:
            request.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(request, timeout=60) as response:
            if have and response.status != 206:  # the server ignored the range: start over
                have = 0
            with open(partial, "ab" if have else "wb") as out:
                while True:
                    piece = response.read(1 << 20)
                    if not piece:
                        break
                    out.write(piece)
                    have += len(piece)
                    if progress:
                        progress(asset.name, have, asset.size)
    if partial.stat().st_size != asset.size or sha256_of(partial) != asset.sha256:
        partial.unlink()
        raise RuntimeError(f"{asset.name}: the download doesn't match its pinned checksum; try again")
    os.replace(partial, destination)
    return destination


def install_models(progress: Progress | None = None) -> None:
    for asset in missing_models():
        download(asset, model_path(asset), progress)


def install_runtime(backend: str | None = None, progress: Progress | None = None) -> Path:
    """Downloads and unpacks llama.cpp into the runtime folder (replacing any other build there)."""
    asset = runtime_asset(backend)
    root = paths.runtime_dir()
    with tempfile.TemporaryDirectory(dir=paths.data_dir()) as scratch:
        archive = download(asset, Path(scratch) / asset.name, progress)
        unpacked = Path(scratch) / "unpacked"
        if asset.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                _check_members(z.namelist())
                z.extractall(unpacked)
        else:
            with tarfile.open(archive) as t:
                _check_members(t.getnames())
                if hasattr(tarfile, "data_filter"):
                    t.extractall(unpacked, filter="data")
                else:
                    t.extractall(unpacked)
        if root.exists():
            shutil.rmtree(root)
        shutil.move(str(unpacked), root)
    (root / "BUILD").write_text(f"{asset.name}\n", encoding="utf-8")
    server = find_server()
    if server is None:
        raise RuntimeError(f"{asset.name} has no {server_executable_name()}")
    if sys.platform != "win32":
        server.chmod(server.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return server


def _check_members(names: list[str]) -> None:
    for name in names:
        if name.startswith(("/", "\\")) or ".." in Path(name).parts:
            raise RuntimeError(f"refusing an archive entry outside its folder: {name}")


def installed_runtime() -> str | None:
    build = paths.runtime_dir() / "BUILD"
    return build.read_text(encoding="utf-8").strip() if build.is_file() else None
