import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from rummage import web
from rummage.config import Config
from rummage.engine import Engine


@pytest.fixture
def site(tmp_path, fake, monkeypatch):
    root = tmp_path / "files"
    root.mkdir()
    (root / "note.txt").write_text("meeting about the lake offsite", encoding="utf-8")
    engine = Engine(Config(folders=[str(root)]), tmp_path / "index.sqlite", embedder=fake)
    engine.index()
    opened = []
    monkeypatch.setattr("rummage.opener.open_file", opened.append)
    app = web.App(engine, 0)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web._handler(app))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app, root, opened
    httpd.shutdown()
    engine.close()


def call(url, token=None, body=None, host=None):
    headers = {}
    if token:
        headers["X-Rummage-Token"] = token
    if host:
        headers["Host"] = host
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as r:
        return r.status, r.read()


def test_page_carries_token_and_api_requires_it(site):
    base, app, _, _ = site
    status, page = call(base + "/")
    assert status == 200 and app.token.encode() in page
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + "/api/status")
    assert e.value.code == 403
    status, body = call(base + "/api/search?q=lake", token=app.token)
    assert json.loads(body)[0]["name"] == "note.txt"


def test_foreign_host_is_refused(site):
    base = site[0]
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + "/", host="evil.example:80")
    assert e.value.code == 403


def test_open_only_indexed_files(site, tmp_path):
    base, app, root, opened = site
    call(base + "/api/open", token=app.token, body={"path": str(root / "note.txt")})
    assert opened == [str(root / "note.txt")]
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + "/api/open", token=app.token, body={"path": "/etc/passwd"})
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base + f"/thumb?path=/etc/passwd&token={app.token}")
    assert e.value.code == 404
