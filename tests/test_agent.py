import json
import time

import anyio
import pytest
from mcp import Client

from im_looking_for import agent, assets
from im_looking_for.config import Config
from im_looking_for.engine import Engine


@pytest.fixture
def server(tmp_path, fake, monkeypatch):
    root = tmp_path / "files"
    root.mkdir()
    (root / "receipt.txt").write_text("dentist receipt paid in cash\n\nsecond paragraph about teeth",
                                      encoding="utf-8")
    (root / "trip.md").write_text("# Trip\nplanning the mountain hike", encoding="utf-8")
    monkeypatch.setattr(assets, "ready", lambda: True)
    eng = Engine(Config(folders=[]), tmp_path / "index.sqlite", embedder=fake)
    a = agent.Agent(eng)
    yield agent.build(a), a, root
    a.close()


def call(mcp, name, args=None):
    async def go():
        async with Client(mcp) as client:
            result = await client.call_tool(name, args or {})
            assert not result.is_error, result
            return json.loads(result.content[0].text)

    return anyio.run(go)


def test_tools_are_listed_with_hints(server):
    mcp, _, _ = server

    async def go():
        async with Client(mcp) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in anyio.run(go)}
    assert set(tools) == {"search", "read_passages", "status", "add_folder", "remove_folder", "index",
                          "stop_indexing"}
    assert tools["search"].annotations.read_only_hint
    assert "query" in tools["search"].input_schema["properties"]


def test_add_index_search_read(server):
    mcp, _, root = server
    assert call(mcp, "add_folder", {"folder": str(root)})["folders"] == [str(root)]
    assert call(mcp, "index")["started"]
    deadline = time.time() + 20
    while call(mcp, "status")["indexing"] and time.time() < deadline:
        time.sleep(0.05)
    status = call(mcp, "status")
    assert status["index"]["files"] == {"doc": 2} and status["index_error"] is None
    found = call(mcp, "search", {"query": "dentist receipt", "limit": 3})["results"]
    assert found[0]["name"] == "receipt.txt"
    passages = call(mcp, "read_passages", {"path": found[0]["path"]})["passages"]
    assert any("dentist" in p["text"] for p in passages)
    assert call(mcp, "search", {"query": "dentist", "kinds": ["image"]})["results"] == []


def test_refuses_unknown_paths_and_empty_setup(server, tmp_path):
    mcp, _, _ = server
    assert "error" in call(mcp, "read_passages", {"path": str(tmp_path / "secret.txt")})
    assert call(mcp, "index")["started"] is False
