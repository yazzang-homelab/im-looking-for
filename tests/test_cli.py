import json

import pytest

from im_looking_for import assets, cli, engine


@pytest.fixture
def files(tmp_path, fake, monkeypatch, capsys):
    root = tmp_path / "files"
    root.mkdir()
    (root / "lake.txt").write_text("minutes of the lake offsite meeting", encoding="utf-8")
    (root / "tax.txt").write_text("tax return checklist for march", encoding="utf-8")
    (root / "setup.txt").write_text("how to setup the garden hose", encoding="utf-8")

    class FakeEngine(engine.Engine):
        def __init__(self, config=None, index_path=None, embedder=None):
            super().__init__(config, index_path, embedder or fake)

    monkeypatch.setattr(engine, "Engine", FakeEngine)
    monkeypatch.setattr(assets, "ready", lambda: True)
    assert cli.main(["add", str(root), "--json"]) == 0
    assert cli.main(["index", "--json"]) == 0
    capsys.readouterr()
    return root


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_bare_words_search(files, capsys):
    assert cli.main(["lake", "offsite", "--json"]) == 0
    data = out_json(capsys)
    assert data["query"] == "lake offsite"
    assert data["results"][0]["name"] == "lake.txt"
    assert set(data["results"][0]) >= {"path", "kind", "score", "where", "snippet", "loc"}


def test_options_before_words_and_kind_filter(files, capsys):
    assert cli.main(["-k", "doc", "-n", "1", "tax", "--json"]) == 0
    data = out_json(capsys)
    assert [r["name"] for r in data["results"]] == ["tax.txt"]
    assert cli.main(["-k", "image", "tax", "--json"]) == cli.NOT_FOUND
    assert out_json(capsys)["results"] == []


def test_command_words_need_search(files, capsys):
    assert cli.main(["search", "setup", "garden", "--json"]) == 0
    assert out_json(capsys)["results"][0]["name"] == "setup.txt"


def test_index_report_and_status(files, capsys):
    (files / "new.txt").write_text("a brand new note", encoding="utf-8")
    assert cli.main(["index", "--json"]) == 0
    report = out_json(capsys)
    assert report["read"] == 1 and report["unchanged"] == 3
    assert cli.main(["status", "--json"]) == 0
    status = out_json(capsys)
    assert status["folders"] == [str(files)]
    assert status["index"]["files"] == {"doc": 4}


def test_errors_are_json_with_exit_code(tmp_path, capsys):
    code = cli.main(["add", str(tmp_path / "nope"), "--json"])
    assert code == cli.FAILED
    assert "error" in out_json(capsys)


def test_not_set_up_is_exit_3(capsys, monkeypatch):
    monkeypatch.setattr(assets, "find_server", lambda: None)
    assert cli.main(["anything", "--json"]) == cli.NOT_READY
    assert "ilf setup" in out_json(capsys)["error"]


def test_no_arguments_opens_the_app(monkeypatch):
    from im_looking_for import web

    calls = []
    monkeypatch.setattr(web, "serve", lambda **kw: calls.append(kw) or 0)
    assert cli.main([]) == 0
    assert calls == [{"port": 8765, "open_browser": True, "app_window": True}]


@pytest.mark.parametrize("json_flag, tty, asked", [(False, True, True), (False, False, False), (True, True, False)])
def test_setup_asks_for_a_star_once_and_only_in_a_terminal(monkeypatch, capsys, json_flag, tty, asked):
    from im_looking_for import assets
    from im_looking_for.config import Config

    monkeypatch.setattr(assets, "install", lambda backend, progress=None: {"backend": backend, "runtime": None,
                                                                           "models": []})
    monkeypatch.setattr(assets, "ready", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: tty)
    args = ["setup", "--backend", "cpu"] + (["--json"] if json_flag else [])
    assert cli.main(args) == 0
    assert ("github.com/yazzang-homelab/im-looking-for" in capsys.readouterr().out) is asked
    assert Config.load().star_asked is asked
    if asked:
        assert cli.main(args) == 0
        assert "github.com" not in capsys.readouterr().out
