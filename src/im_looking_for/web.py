"""The app: a small HTTP server on 127.0.0.1 and one HTML page, opened as its own window when a Chromium browser is
around (``--app`` mode), else as a browser tab.

Only this computer can reach it. Every API call and preview carries a token the page got when it loaded, the Host
header must be the loopback address (no DNS rebinding), and previews, passages and "open" only work for files in the
index, so another web page can't use it to read or launch anything. The folder browser lists folder names only.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from . import __version__, assets, media, opener
from .agent import Agent
from .engine import Engine


def mcp_command() -> list[str]:
    """How an agent should launch this install's MCP server."""
    for name in ("ilf", "im-looking-for"):
        found = shutil.which(name)
        if found:
            return [found, "mcp"]
    if getattr(sys, "frozen", False):  # the PyInstaller bundle
        return [sys.executable, "mcp"]
    return [sys.executable, "-m", "im_looking_for", "mcp"]


class App(Agent):
    """The engine, the background index job (shared with the MCP server's logic) and the setup download."""

    def __init__(self, engine: Engine, port: int = 0):
        super().__init__(engine)
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.setup_thread: threading.Thread | None = None
        self.setup_progress: dict = {}
        self.setup_error: str | None = None

    def start_setup(self, backend: str | None) -> bool:
        if self.setup_thread and self.setup_thread.is_alive() or self.indexing():
            return False
        self.setup_error = None
        self.setup_progress = {}

        def progress(name: str, have: int, total: int) -> None:
            self.setup_progress = {"file": name, "have": have, "total": total}

        def run() -> None:
            try:
                config = self.engine.config
                chosen = backend or config.backend or assets.default_backend()
                assets.install(chosen, progress, before_replace=self.engine.stop_server)
                config.backend = chosen
                config.gpu_failed = None
                config.save()
                self.warm()
            except Exception as e:  # shown on the page
                self.setup_error = f"{type(e).__name__}: {e}"

        self.setup_thread = threading.Thread(target=run, name="ilf-setup", daemon=True)
        self.setup_thread.start()
        return True

    def status(self) -> dict:
        report = super().status()
        report["setup"] = {"running": bool(self.setup_thread and self.setup_thread.is_alive()),
                           "progress": self.setup_progress, "error": self.setup_error,
                           "default_backend": assets.default_backend()}
        report["mcp_command"] = mcp_command()
        report["star_asked"] = self.engine.config.star_asked
        return report

    def warm(self) -> None:
        try:
            self.engine.embedder(media=False)
        except Exception:  # the first search reports it
            pass

    def thumbnail(self, path: str, loc: float, size: int = 360) -> bytes:
        kind = self.engine.store.file(path).kind
        if kind == "pdf":
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(path)
            try:
                page = document[max(int(loc) - 1, 0)]
                width, height = page.get_size()
                picture = page.render(scale=size * 1.5 / max(width, height)).to_pil()
            finally:
                document.close()
        elif kind == "video":
            result = media._run(["-ss", f"{loc:.2f}", "-i", path, "-frames:v", "1", "-f", "image2pipe",
                                 "-c:v", "mjpeg", "pipe:1"], timeout=60)
            picture = Image.open(io.BytesIO(result.stdout))
        elif kind == "image":
            picture = Image.open(path)
        else:
            raise FileNotFoundError(path)
        picture = picture.convert("RGB")
        picture.thumbnail((size, size))
        out = io.BytesIO()
        picture.save(out, "JPEG", quality=82)
        return out.getvalue()


def places() -> list[dict]:
    """Starting points for the folder picker: home, the usual user folders that exist, and drives or volumes."""
    home = Path.home()
    found = [{"name": "~", "path": str(home)}]
    for name in ("Desktop", "Documents", "Pictures", "Downloads", "Music", "Videos", "Movies"):
        if (home / name).is_dir():
            found.append({"name": name, "path": str(home / name)})
    if sys.platform == "win32":
        from string import ascii_uppercase

        found += [{"name": f"{d}:", "path": f"{d}:\\"} for d in ascii_uppercase if os.path.isdir(f"{d}:\\")]
    else:  # external drives: macOS mounts them in /Volumes, Linux desktops in /media/<user>
        found.append({"name": "/", "path": "/"})
        for mounts in ("/Volumes", f"/media/{home.name}", f"/run/media/{home.name}"):
            try:
                found += [{"name": e.name, "path": e.path} for e in os.scandir(mounts) if e.is_dir()][:12]
            except OSError:
                pass
    return found


def browse(path: str) -> dict:
    """The sub-folders of ``path`` (names only, hidden ones left out)."""
    folder = Path(path or Path.home()).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    entries = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_dir() and not e.name.startswith(".") and not e.name.startswith("$"):
                        entries.append(e.name)
                except OSError:
                    pass
    except PermissionError:
        return {"path": str(folder), "parent": str(folder.parent) if folder.parent != folder else None,
                "folders": [], "denied": True}
    entries.sort(key=str.casefold)
    return {"path": str(folder), "parent": str(folder.parent) if folder.parent != folder else None,
            "folders": entries[:2000], "denied": False}


def _handler(app: App):
    page = resources.files("im_looking_for").joinpath("static/index.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = f"im-looking-for/{__version__}"

        def log_message(self, *args) -> None:  # quiet
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _send(self, status: int, body: bytes, content_type: str, cache: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "private, max-age=600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _authorized(self, query: dict) -> bool:
            token = self.headers.get("X-ILF-Token") or query.get("token", [""])[0]
            return secrets.compare_digest(token, app.token)

        def _indexed(self, path: str) -> bool:
            return bool(path) and app.engine.store.file(path) is not None

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/":
                html = page.replace("__TOKEN__", app.token)
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if not self._authorized(query):
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            if url.path == "/api/status":
                return self._json(app.status())
            if url.path == "/api/search":
                q = query.get("q", [""])[0]
                kinds = set(query["kind"]) if query.get("kind") else None
                try:
                    results = app.engine.search(q, limit=int(query.get("n", ["40"])[0]), kinds=kinds)
                except Exception as e:
                    return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
                return self._json({"query": q, "results": [r.to_dict() for r in results]})
            if url.path == "/api/passages":
                path = query.get("path", [""])[0]
                if not self._indexed(path):
                    return self._json({"error": "not in the index"}, 404)
                loc = query.get("loc", [""])[0]
                return self._json({"path": path, "passages": app.engine.store.passages(
                    path, float(loc) if loc else None, 6)})
            if url.path == "/api/browse":
                try:
                    return self._json({**browse(query.get("path", [""])[0]), "places": places()})
                except OSError as e:
                    return self._json({"error": str(e)}, 400)
            if url.path == "/thumb":
                path = query.get("path", [""])[0]
                if not self._indexed(path):
                    return self._send(HTTPStatus.NOT_FOUND, b"not in the index", "text/plain")
                try:
                    size = min(int(query.get("size", ["360"])[0]), 1200)
                    body = app.thumbnail(path, float(query.get("loc", ["0"])[0]), size)
                except Exception:
                    return self._send(HTTPStatus.NOT_FOUND, b"no preview", "text/plain")
                return self._send(200, body, "image/jpeg", cache=True)
            return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            url = urlparse(self.path)
            if not self._authorized({}):
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(min(length, 1 << 20)) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad JSON"}, 400)
            if url.path == "/api/open":
                path = body.get("path", "")
                if not self._indexed(path):
                    return self._json({"error": "not in the index"}, 404)
                (opener.reveal if body.get("reveal") else opener.open_file)(path)
                return self._json({"ok": True})
            if url.path == "/api/folders":
                config = app.engine.config
                try:
                    if body.get("add"):
                        config.add_folder(body["add"])
                    if body.get("remove"):
                        config.remove_folder(body["remove"])
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                config.save()
                return self._json({"folders": config.folders})
            if url.path == "/api/index":
                if body.get("stop"):
                    app.stop.set()
                    return self._json({"ok": True})
                if not app.engine.config.folders:
                    return self._json({"error": "no folders"}, 400)
                return self._json({"started": app.start_index(None)})
            if url.path == "/api/star-asked":
                app.engine.config.star_asked = True
                app.engine.config.save()
                return self._json({"ok": True})
            if url.path == "/api/setup":
                backend = body.get("backend") or None
                if backend is not None and backend not in assets.backends():
                    return self._json({"error": f"unknown backend {backend}"}, 400)
                return self._json({"started": app.start_setup(backend)})
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(port: int = 8765, open_browser: bool = True, app_window: bool = True) -> int:
    app = App(Engine(), port)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(app))
    except OSError:  # the port is taken: any free one will do
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(app))
    if assets.ready():  # load the text model now, so the first search doesn't wait for it
        threading.Thread(target=app.warm, name="ilf-warm", daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"im-looking-for is at {url}  (Ctrl+C to quit)")
    if open_browser:
        opener.open_app(url, window=app_window)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        app.close()
    return 0
