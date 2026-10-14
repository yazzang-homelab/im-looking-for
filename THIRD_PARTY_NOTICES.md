# Third-party notices

Rummage itself is MIT-licensed (see `LICENSE`). It uses, or downloads at `rummage setup`, the following.

## Downloaded on first use (not shipped with Rummage)

| Component | License | Notes |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) prebuilt `llama-server`, tag `b11461` | MIT | Runs the model. Pinned by SHA-256 in `src/rummage/assets.py`. |
| [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2) by Google DeepMind, as [ggml-org/embeddinggemma-2-GGUF](https://huggingface.co/ggml-org/embeddinggemma-2-GGUF) Q8_0 at revision `bfcd298` | Apache 2.0 | Use is subject to the [Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy). |

## Python dependencies

| Package | License |
|---|---|
| numpy | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| pypdfium2 (with PDFium) | Apache-2.0 or BSD-3-Clause; PDFium: BSD-3-Clause / Apache-2.0 |
| platformdirs | MIT |
| imageio-ffmpeg | BSD-2-Clause; the FFmpeg binary it carries is licensed under the GPL/LGPL — see [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) |

When an `ffmpeg` is on `PATH`, Rummage uses that one instead.

## Prior art

Rummage is an independent, cross-platform take on [DigUp](https://github.com/ARahim3/DigUp) (MIT, macOS), which
showed EmbeddingGemma 2 file search on the desktop. No DigUp code is included; Rummage follows several of its measured
choices: the model card's task prompts, 30-second audio windows with a 25-second hop (the model ignores sound past
30 s of one input), a frame every 3 seconds with near-duplicates dropped, rendering a PDF page as a picture when it has
almost no text, and a boost for exact words on top of vector search.
