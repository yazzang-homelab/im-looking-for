"""What's installed, which folders are searched and what the index holds, as one JSON-ready dict.

The CLI (``ilf status --json``), the GUI and the MCP server all report this same shape; it never starts the model.
"""

from __future__ import annotations

from . import __version__, assets, paths
from .config import Config
from .store import Store


def describe(config: Config | None = None, store: Store | None = None) -> dict:
    config = config or Config.load()
    missing = assets.missing_models()
    report = {
        "version": __version__,
        "ready": assets.ready(),
        "data_dir": str(paths.data_dir()),
        "runtime": assets.installed_runtime(),
        "backend": assets.installed_backend() or config.backend,
        "gpu_failed": config.gpu_failed,  # why the GPU build runs on the processor; None when it doesn't
        "backends": assets.backends(),
        "missing_models": [m.name for m in missing],
        "download_bytes": sum(m.size for m in missing),
        "folders": config.folders,
        "excluded_folders": config.excluded_folders,
        "excluded_extensions": config.excluded_extensions,
        "index": {"files": {}, "errors": 0, "vectors": 0, "bytes": 0},
    }
    if store is not None:
        report["index"] = store.stats()
    elif paths.index_file().exists():
        own = Store(paths.index_file())
        try:
            report["index"] = own.stats()
        finally:
            own.close()
    return report
