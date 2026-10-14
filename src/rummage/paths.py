"""Where Rummage keeps its files: one data folder per user (``RUMMAGE_HOME`` overrides it).

* Windows: ``%LOCALAPPDATA%\\Rummage``
* macOS: ``~/Library/Application Support/Rummage``
* Linux: ``$XDG_DATA_HOME/rummage`` (``~/.local/share/rummage``)
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs


def data_dir() -> Path:
    override = os.environ.get("RUMMAGE_HOME")
    folder = Path(override) if override else Path(platformdirs.user_data_dir("Rummage", appauthor=False))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def models_dir() -> Path:
    return data_dir() / "models"


def runtime_dir() -> Path:
    return data_dir() / "llama.cpp"


def index_file() -> Path:
    return data_dir() / "index.sqlite"


def config_file() -> Path:
    return data_dir() / "config.json"


def log_file() -> Path:
    return data_dir() / "llama-server.log"
