from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest

from rummage.embed import DIM, normalize


def _bucket(word: str) -> int:
    return int.from_bytes(hashlib.sha256(word.encode("utf-8")).digest()[:4], "little") % DIM


class FakeEmbedder:
    """Bag-of-words vectors: texts sharing words point the same way. Media get a vector from their bytes."""

    def __init__(self):
        self.text_calls = 0
        self.media_calls = 0

    def texts(self, prompts):
        self.text_calls += len(prompts)
        rows = np.zeros((len(prompts), DIM), np.float32)
        for i, prompt in enumerate(prompts):
            body = prompt.split("text: ", 1)[-1].split("query: ", 1)[-1]
            for word in re.findall(r"\w+", body.lower()):
                rows[i, _bucket(word)] += 1
            rows[i, 0] += 0.01
        return normalize(rows)

    def media(self, data):
        self.media_calls += 1
        rng = np.random.default_rng(int.from_bytes(hashlib.sha256(data).digest()[:8], "little"))
        return normalize(rng.standard_normal((1, DIM)).astype(np.float32))[0]


@pytest.fixture
def fake():
    return FakeEmbedder()


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RUMMAGE_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
