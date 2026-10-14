"""The user's choices: which folders to search and what to leave out. A JSON file in the data folder."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths


@dataclass
class Config:
    folders: list[str] = field(default_factory=list)
    excluded_folders: list[str] = field(default_factory=list)      # folder names or full paths
    excluded_extensions: list[str] = field(default_factory=list)   # "heic", "txt", …
    backend: str | None = None                                     # llama.cpp build: cpu | vulkan | metal
    # Why the GPU was given up on (it failed to start or died) and the processor is used instead; None = use the GPU.
    # Choosing a backend again (`ilf setup`, Settings) clears it, so the GPU gets another try.
    gpu_failed: str | None = None

    @classmethod
    def load(cls) -> Config:
        path = paths.config_file()
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = paths.config_file()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def add_folder(self, folder: str) -> str:
        resolved = str(Path(folder).expanduser().resolve())
        if not Path(resolved).is_dir():
            raise ValueError(f"not a folder: {folder}")
        if resolved not in self.folders:
            self.folders.append(resolved)
        return resolved

    def remove_folder(self, folder: str) -> bool:
        resolved = str(Path(folder).expanduser().resolve())
        if resolved in self.folders:
            self.folders.remove(resolved)
            return True
        return False

    def exclusions(self) -> tuple[frozenset[str], frozenset[str]]:
        return (frozenset(self.excluded_folders),
                frozenset(e.lower().lstrip("*.") for e in self.excluded_extensions))
