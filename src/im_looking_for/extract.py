"""Reads a file into searchable segments: a picture, a PDF page, a stretch of text, 30 s of sound, a video frame.

A segment carries what gets embedded (a text prompt or media bytes) and the words keyword search sees.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from . import media
from .embed import document_prompt


@dataclass
class Options:
    min_image_side: int = 256        # smaller pictures are icons and UI bits
    max_image_side: int = 1024
    chunk_chars: int = 1600
    chunk_overlap: int = 200
    min_page_text: int = 200         # fewer characters on a PDF page: embed the rendered page instead
    max_pages: int = 2000
    max_chunks: int = 4000
    frame_interval: float = 3.0      # seconds between sampled video frames (near-duplicates are dropped)
    max_frames: int = 1200
    audio_window: float = 30.0       # the model ignores sound past 30 s of one input
    audio_hop: float = 25.0
    max_audio_windows: int = 480     # 3 h 20 min
    max_text_bytes: int = 32 << 20

    def fingerprint(self) -> str:
        return (f"img{self.max_image_side} chunk{self.chunk_chars}/{self.chunk_overlap} page{self.min_page_text} "
                f"frame{self.frame_interval} audio{self.audio_window}/{self.audio_hop}")


@dataclass
class Segment:
    kind: str                  # image | page | page_image | chunk | audio | frame
    modality: str              # text | image | audio
    loc: float = 0.0           # page (from 1), chunk (from 0) or seconds
    loc_end: float | None = None
    text: str = ""             # what keyword search sees and the result shows
    prompt: str | None = None  # text to embed
    data: bytes | None = field(default=None, repr=False)  # picture or sound to embed


def _jpeg(picture: Image.Image, max_side: int) -> bytes:
    picture = ImageOps.exif_transpose(picture)
    if picture.mode not in ("RGB", "L"):
        background = Image.new("RGB", picture.size, "white")
        rgba = picture.convert("RGBA")
        background.paste(rgba, mask=rgba.getchannel("A"))
        picture = background
    picture = picture.convert("RGB")
    picture.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=88)
    return out.getvalue()


def decode_text(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    for encoding in ("utf-8", "cp949", "shift_jis"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


_SENTENCE_END = re.compile(r"(?<=[.!?。！？다요죠음함])\s+")


def chunks(text: str, size: int, overlap: int) -> list[str]:
    """Pieces of about ``size`` characters, cut at a paragraph, else a sentence, else a space, overlapping a little."""
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if not text:
        return []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            floor = size // 2
            cut = window.rfind("\n\n", floor)
            if cut < 0:
                matches = [m.start() for m in _SENTENCE_END.finditer(window, floor)]
                cut = matches[-1] if matches else window.rfind(" ", floor)
            if cut > 0:
                end = start + cut
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        # begin the overlap at a word
        space = text.find(" ", start, end)
        if 0 <= space < end:
            start = space + 1
    return pieces


_TAG = re.compile(r"<[^>]+>")


def _xml_text(xml: str) -> str:
    xml = re.sub(r"</(w:p|a:p|text:p|text:h|hp:p|row)>", "\n", xml)
    xml = re.sub(r"<(w:tab|text:tab)/>", " ", xml)
    return html.unescape(_TAG.sub("", xml))


def office_text(path: Path) -> str:
    """The words in a .docx/.pptx/.xlsx/.odt/.odp/.ods/.hwpx (they are zip files of XML)."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        ext = path.suffix.lower()
        if ext == ".docx":
            parts = [n for n in names if re.fullmatch(r"word/(document|footnotes|endnotes)\.xml", n)]
        elif ext == ".pptx":
            parts = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                           key=lambda n: int(re.findall(r"\d+", n)[-1]))
        elif ext == ".xlsx":
            parts = [n for n in names if n == "xl/sharedStrings.xml"]
        elif ext == ".hwpx":
            parts = sorted(n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n))
        else:
            parts = [n for n in names if n == "content.xml"]
        return "\n\n".join(_xml_text(z.read(n).decode("utf-8", "replace")) for n in parts)


def _text_segments(text: str, title: str, options: Options) -> Iterator[Segment]:
    for i, piece in enumerate(chunks(text, options.chunk_chars, options.chunk_overlap)[:options.max_chunks]):
        yield Segment("chunk", "text", loc=i, text=piece, prompt=document_prompt(title, piece))


def read_doc(path: Path, options: Options) -> Iterator[Segment]:
    if path.stat().st_size > options.max_text_bytes:
        return
    ext = path.suffix.lower()
    if ext in (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods", ".hwpx"):
        text = office_text(path)
    else:
        text = decode_text(path.read_bytes())
        if ext in (".html", ".htm", ".xml"):
            text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
            text = html.unescape(_TAG.sub(" ", text))
        elif ext in (".srt", ".vtt"):
            text = re.sub(r"(?m)^\d+\s*$|^[\d:.,]+ --> [\d:.,]+.*$|^WEBVTT.*$", "", text)
    yield from _text_segments(text, path.stem, options)


def read_pdf(path: Path, options: Options) -> Iterator[Segment]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        for number in range(min(len(document), options.max_pages)):
            page = document[number]
            try:
                textpage = page.get_textpage()
                text = textpage.get_text_range().strip()
                textpage.close()
                if len(text) >= options.min_page_text:
                    # a dense page is read in pieces: one vector for 6,000 characters blurs them together
                    for piece in chunks(text, options.chunk_chars * 2, options.chunk_overlap):
                        yield Segment("page", "text", loc=number + 1, text=piece,
                                      prompt=document_prompt(path.stem, piece))
                else:
                    width, height = page.get_size()
                    scale = options.max_image_side / max(width, height, 1)
                    bitmap = page.render(scale=scale)
                    picture = bitmap.to_pil()
                    yield Segment("page_image", "image", loc=number + 1, text=text,
                                  data=_jpeg(picture, options.max_image_side))
            finally:
                page.close()
    finally:
        document.close()


def read_image(path: Path, options: Options) -> Iterator[Segment]:
    with Image.open(path) as picture:
        if min(picture.size) < options.min_image_side:
            return
        picture.seek(0)
        yield Segment("image", "image", data=_jpeg(picture, options.max_image_side))


def read_audio(path: Path, options: Options, duration: float | None = None) -> Iterator[Segment]:
    if duration is None:
        duration, _, has_audio = media.probe(path)
        if not has_audio:
            return
    for start, end, wav in media.audio_windows(path, duration, options.audio_window, options.audio_hop,
                                               options.max_audio_windows):
        yield Segment("audio", "audio", loc=start, loc_end=end, data=wav)


def _signature(picture: Image.Image) -> np.ndarray:
    return np.asarray(picture.convert("L").resize((16, 16)), dtype=np.float32)


def read_video(path: Path, options: Options) -> Iterator[Segment]:
    duration, has_video, has_audio = media.probe(path)
    if has_video:
        previous = None
        for time, picture in media.frames(path, options.frame_interval, options.max_image_side,
                                          options.max_frames):
            signature = _signature(picture)
            if previous is not None and float(np.abs(signature - previous).mean()) < 6.0:
                continue  # the same shot as the frame kept before it
            previous = signature
            yield Segment("frame", "image", loc=time, data=_jpeg(picture, options.max_image_side))
    if has_audio:
        yield from read_audio(path, options, duration)


READERS = {"doc": read_doc, "pdf": read_pdf, "image": read_image, "audio": read_audio, "video": read_video}


def read(path: Path, kind: str, options: Options) -> Iterator[Segment]:
    return READERS[kind](path, options)
