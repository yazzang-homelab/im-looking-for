"""Runs the real llama-server and EmbeddingGemma 2 (after `ilf setup`). Opt in: ILF_INTEGRATION=1 and
ILF_REAL_HOME pointing at the data folder that has them."""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

pytestmark = pytest.mark.integration
REAL_HOME = os.environ.get("ILF_REAL_HOME")
if not (os.environ.get("ILF_INTEGRATION") == "1" and REAL_HOME):
    pytest.skip("set ILF_INTEGRATION=1 and ILF_REAL_HOME", allow_module_level=True)


@pytest.fixture
def real(monkeypatch, tmp_path):
    monkeypatch.setenv("ILF_MODEL_DIR", str(Path(REAL_HOME) / "models"))
    from im_looking_for import assets

    server = next((Path(REAL_HOME) / "llama.cpp").rglob(assets.server_executable_name()))
    monkeypatch.setenv("ILF_LLAMA_SERVER", str(server))


def test_text_and_picture_share_one_space(real, tmp_path):
    from im_looking_for.embed import ServerEmbedder, document_prompt, query_prompt
    from im_looking_for.server import LlamaServer

    picture = Image.new("RGB", (512, 512), "white")
    ImageDraw.Draw(picture).ellipse((96, 96, 416, 416), fill="red")
    path = tmp_path / "circle.png"
    picture.save(path)
    with LlamaServer(media=True) as server:
        embed = ServerEmbedder(server)
        q = embed.texts([query_prompt("a red circle"), query_prompt("tax invoice spreadsheet")])
        image = embed.media(path.read_bytes())
        docs = embed.texts([document_prompt("note", "The circle is filled with red paint.")])
    assert q.shape == (2, 768) and np.allclose(np.linalg.norm(q, axis=1), 1, atol=1e-3)
    assert q[0] @ image > q[1] @ image
    assert q[0] @ docs[0] > q[1] @ docs[0]
