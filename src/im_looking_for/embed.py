"""Turns text, pictures and sound into EmbeddingGemma 2 vectors through ``llama-server``'s ``/embeddings``.

Every vector is 768 floats, L2-normalized, in one space shared by all four kinds of input.
Prompts follow the model card: queries are ``task: search result | query: …``, documents
``title: … | text: …``, and media inputs carry no prompt besides the server's media marker (random per run,
read from ``/props``).
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Protocol

import numpy as np

DIM = 768
# What made the vectors. An index records it and is rebuilt when it changes.
VECTOR_VERSION = "embeddinggemma-2-Q8_0@bfcd298/llama.cpp-b11461/mean"


def query_prompt(text: str) -> str:
    return f"task: search result | query: {text}"


def document_prompt(title: str | None, text: str) -> str:
    return f"title: {title or 'none'} | text: {text}"


class Embedder(Protocol):
    def texts(self, prompts: Sequence[str]) -> np.ndarray: ...

    def media(self, data: bytes) -> np.ndarray: ...


def normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return (matrix / np.maximum(norms, 1e-12)).astype(np.float32)


class ServerEmbedder:
    """An ``Embedder`` backed by a running ``LlamaServer``."""

    def __init__(self, server, batch: int = 8):
        self.server = server
        self.batch = batch

    def _vectors(self, content) -> np.ndarray:
        reply = self.server.post("/v1/embeddings", {"input": content, "encoding_format": "float"})
        rows = [item["embedding"] for item in sorted(reply["data"], key=lambda item: item["index"])]
        matrix = np.asarray(rows, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != DIM:
            raise RuntimeError(f"expected {DIM}-dimensional vectors, got shape {matrix.shape}")
        return normalize(matrix)

    def texts(self, prompts: Sequence[str]) -> np.ndarray:
        if not prompts:
            return np.zeros((0, DIM), np.float32)
        parts = [self._vectors(list(prompts[i:i + self.batch])) for i in range(0, len(prompts), self.batch)]
        return np.concatenate(parts)

    def media(self, data: bytes) -> np.ndarray:
        """One picture (PNG/JPEG/…) or one sound (WAV/MP3/FLAC): llama.cpp tells them apart by their bytes."""
        if not self.server.media_marker:
            raise RuntimeError("this llama-server runs without the image/audio encoders")
        prompt = {"prompt_string": self.server.media_marker,
                  "multimodal_data": [base64.b64encode(data).decode("ascii")]}
        return self._vectors(prompt)[0]
