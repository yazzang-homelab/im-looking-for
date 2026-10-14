# Rummage

**Describe it. Rummage finds it.** Search the files on your computer by what's *in* them — photos, PDFs, documents,
voice memos, podcasts and videos — on **Windows, macOS and Linux**. Everything runs on your machine; nothing is
uploaded.

```
$ rummage search "a dog running on the beach"
 1. 0.721  [image]  ~/Pictures/IMG_0412.jpg
 2. ...
$ rummage search "임대차 계약 해지 조건"
 1. 0.916  [pdf p.1]  ~/Documents/lease_2026.pdf
      주택 임대차 계약서 제1조 (목적) …
$ rummage search "where I talk about sleep problems"
 1. 0.742  [audio 0:00]  ~/Recordings/voice_memo_01.wav
```

Rummage is built on Google DeepMind's [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) (Apache 2.0,
740M parameters), which puts text, pictures, sound and video into one shared 768-dimensional space and understands
100+ languages, run by [llama.cpp](https://github.com/ggml-org/llama.cpp). It's a cross-platform take on
[DigUp](https://github.com/ARahim3/DigUp), the macOS app that first did this on the desktop.

## What it reads

| Files | How |
|---|---|
| Pictures: jpg, png, webp, gif, bmp, tiff | the picture itself (icons under 256 px are skipped) |
| PDF | each page's text; a page with almost no text (a scan, a slide) is read as a picture |
| Documents: txt, md, html, csv, srt, docx, pptx, xlsx, odt, hwpx, … | stretches of ~1,600 characters |
| Sound: mp3, wav, m4a, flac, ogg, opus, … | 30-second windows, every 25 seconds |
| Video: mp4, mov, mkv, webm, avi, … | a frame every 3 seconds (repeats dropped) and the soundtrack |
| Every file | its name and folders, for keyword search |

Searches mix meaning and exact words. Exact words use SQLite's trigram index, so they work in Korean, Japanese and
Chinese too — `고양이` finds `고양이가`, and two-letter words like `임차` still match.

It never reads hidden folders (`.ssh`, `.git`, …), dependency/build folders, app bundles, keys, certificates or files
named like secrets, and never follows links out of the folders you give it. It only reads files; it never changes,
moves or uploads them.

## Install

Python 3.10 or newer:

```sh
pipx install ./rummage          # from a clone; or: uv tool install ./rummage, pip install ./rummage
rummage setup          # once: llama.cpp (~12–35 MB) + the model (865 MB), pinned and checksum-verified
```

Or download a standalone build (no Python needed) from the Releases page and run `rummage setup` from it.

`setup` picks the llama.cpp build for your computer: **Metal** on Apple Silicon, **Vulkan** on Windows (any recent
NVIDIA/AMD/Intel GPU), the **CPU** on Linux and Intel Macs. On Linux with a GPU, `rummage setup --backend vulkan`
(needs the Vulkan loader, `libvulkan1`).

## Use

```sh
rummage add ~/Pictures ~/Documents     # folders to search
rummage index                          # read them; later runs only read what changed
rummage search "receipt from the hardware store"
rummage search "회의에서 예산 삭감 얘기" --kind doc --kind audio
rummage search "sunset over water" --open 1
rummage serve                          # the search page in your browser
rummage status
```

`rummage serve` opens a search page at `http://127.0.0.1:8765`: type, see thumbnails (video frames and PDF pages at
the matching moment or page), click to open, "Show in folder", and manage folders and indexing from the page. It is
only reachable from your own computer and checks a per-session token on every request.

Data lives in one folder (`RUMMAGE_HOME` overrides it): `%LOCALAPPDATA%\Rummage` on Windows,
`~/Library/Application Support/Rummage` on macOS, `~/.local/share/rummage` on Linux. It holds the model, llama.cpp,
`config.json` and `index.sqlite`. To remove Rummage, uninstall the package and delete that folder.

## How it works

```
folders ─► readers (Pillow, PDFium, ffmpeg) ─► segments: a picture, a page, a stretch of text, 30 s of sound, a frame
        ─► llama-server (llama.cpp) running EmbeddingGemma 2, a helper process on a random loopback port
        ─► index.sqlite: a 768-d vector per segment (float16) + a trigram keyword index
query   ─► the same model's text part ─► cosine similarity against every vector + exact-word boost ─► one result per file
```

Prompts follow the model card (`task: search result | query: …`, `title: … | text: …`). The index records which
model build and reading settings made its vectors and starts over when they change, so vectors never mix.

## Speed

Measured on a 6-core Intel i5-9500 (no AVX-512) with the CPU build, while the machine was busy with other work:
a picture takes ~7 s, a 1,300-character stretch of text ~2 s, a 30-second sound window ~1.3 s; a search takes
0.1–3 s. A GPU build (Metal, Vulkan) is much faster. The first pass over a big folder is slow; after that only new and
changed files are read.

## Quality

`scripts/make_testbed.py` builds a small mixed folder (Wikimedia Commons photos, a Korean lease as PDF, notes, a
thesis as .docx, spoken memos, a video), and `scripts/eval.py scripts/testbed_eval.json` scores 14 English and Korean
queries against it. Current result: **top-1 12/14, top-5 14/14, MRR 0.911**. The two misses: "red fruit" ranks the
testbed's own `SOURCES.txt` (which names `Red_Apple.jpg`) just above the apple photo, and a Korean memo synthesized
with espeak-ng isn't understood (robotic Korean speech; real recordings weren't tested yet).

This is a small testbed; per-modality score calibration (`MODALITY_OFFSET` in `search.py`) stays at zero until an
eval on real collections shows which shift helps.

## Develop

```sh
cd rummage
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                             # unit tests: no model needed
RUMMAGE_INTEGRATION=1 RUMMAGE_REAL_HOME=<data folder after setup> pytest tests/test_integration.py
```

CI runs the unit tests on Windows, macOS and Linux, and an integration job on each that downloads llama.cpp and the
model, indexes a picture and a Korean/English note, and checks the searches find them.

## Limits

- HEIC/HEIF photos aren't read yet (Pillow needs a plugin).
- Text inside photos and screenshots is only "seen" by the model's vision, not OCR'd, so exact-word search doesn't
  reach it.
- Code search (DigUp's `code:`) isn't implemented.
- Indexing runs when you ask (`rummage index` or the page's button); there's no background folder watcher yet.

## License

MIT. See `THIRD_PARTY_NOTICES.md` for llama.cpp (MIT), EmbeddingGemma 2 (Apache 2.0, Gemma Prohibited Use Policy) and
the Python dependencies.
