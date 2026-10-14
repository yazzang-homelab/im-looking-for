"""A search: the query's vector against every vector in the index, plus a boost for exact words, one result per file.

Scores of different modalities sit on slightly different scales (DigUp measured text 0.75–0.86 against picture and
sound 0.67–0.78 for the same topic). ``MODALITY_OFFSET`` shifts a modality before everything is ranked together; it
is zero until an eval on real collections shows which shift helps (``scripts/eval.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .embed import Embedder, query_prompt
from .store import Store

MODALITY_OFFSET = {"text": 0.0, "image": 0.0, "audio": 0.0}
KEYWORD_WEIGHT = 0.12   # a segment holding every query word gains this much
NAME_WEIGHT = 0.08      # a file whose name or folders hold every query word gains this much


@dataclass
class Result:
    path: str
    kind: str          # the file's kind
    score: float
    segment: str       # which part matched: image | page | page_image | chunk | audio | frame | name
    loc: float
    loc_end: float | None
    snippet: str

    def to_dict(self) -> dict:
        """The documented JSON shape of a result (CLI ``--json``, the GUI's API and the MCP ``search`` tool)."""
        return {"path": self.path, "name": Path(self.path).name, "kind": self.kind, "score": self.score,
                "match": self.segment, "loc": self.loc, "loc_end": self.loc_end, "where": self.where(),
                "snippet": self.snippet}

    def where(self) -> str:
        if self.segment in ("page", "page_image"):
            return f"p.{int(self.loc)}"
        if self.segment in ("audio", "frame"):
            return _clock(self.loc)
        return ""


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def terms(query: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", query.strip().strip('"').lower()) if t]


def snippet(text: str, words: list[str], width: int = 220) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    lowered = text.lower()
    positions = [lowered.find(w) for w in words if w in lowered]
    center = min(positions) if positions else 0
    start = max(0, center - width // 3)
    piece = text[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")


def search(store: Store, embedder: Embedder, query: str, limit: int = 30, kinds: set[str] | None = None,
           min_score: float = 0.0) -> list[Result]:
    query = query.strip()
    if not query:
        return []
    words = terms(query)
    vectors = store.vectors()
    keyword = store.keyword_hits(words)

    best: dict[int, tuple[float, int]] = {}  # file id → (score, segment id)
    if len(vectors.ids):
        q = embedder.texts([query_prompt(query)])[0]
        scores = vectors.matrix @ q
        for modality, offset in MODALITY_OFFSET.items():
            if offset:
                scores[vectors.modalities == modality] += offset
        if keyword:
            boost = np.array([keyword.get(int(i), 0.0) for i in vectors.ids], np.float32)
            scores = scores + KEYWORD_WEIGHT * boost
        # the best segment of each file
        order = np.argsort(-scores)
        for row in order[: max(limit * 40, 2000)]:
            file_id = int(vectors.file_ids[row])
            if file_id not in best:
                best[file_id] = (float(scores[row]), int(vectors.ids[row]))

    # names and folders: a file-level boost, and files found only by name still show up
    name_hits = {}
    for segment_id, share in keyword.items():
        row = store.segment(segment_id)
        if row is not None and row["kind"] == "name":
            name_hits[row["file_id"]] = (share, segment_id)
    for file_id, (share, segment_id) in name_hits.items():
        score, best_segment = best.get(file_id, (0.0, segment_id))
        best[file_id] = (score + NAME_WEIGHT * share, best_segment)

    results: list[Result] = []
    for file_id, (score, segment_id) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        if score < min_score:
            break
        file = store.file_by_id(file_id)
        if file is None:
            continue
        if kinds and file.kind not in kinds:
            continue
        segment = store.segment(segment_id)
        results.append(Result(file.path, file.kind, round(score, 4), segment["kind"], segment["loc"],
                              segment["loc_end"], snippet(segment["text"], words) if segment["kind"] != "name" else ""))
        if len(results) >= limit:
            break
    return results
