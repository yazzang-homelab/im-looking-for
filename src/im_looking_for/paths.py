"""Where im-looking-for keeps its files: one data folder per user (``ILF_HOME`` overrides it).

* Windows: ``%LOCALAPPDATA%\\im-looking-for``
* macOS: ``~/Library/Application Support/im-looking-for``
* Linux: ``$XDG_DATA_HOME/im-looking-for`` (``~/.local/share/im-looking-for``)
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs


def data_dir() -> Path:
    override = os.environ.get("ILF_HOME")
    folder = Path(override) if override else Path(platformdirs.user_data_dir("im-looking-for", appauthor=False))
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
