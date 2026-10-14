"""The search page: a small HTTP server on 127.0.0.1 and one HTML file.

Only this computer can reach it. Every API call and preview carries a token the page got when it loaded, the Host
header must be the loopback address (no DNS rebinding), and previews and "open" only work for files in the index,
so another web page can't use it to read or launch anything.
"""

from __future__ import annotations

import io
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from . import __version__, assets, media
from .engine import Engine
from .indexer import Progress


class App:
    def __init__(self, engine: Engine, port: int):
        self.engine = engine
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.progress: Progress | None = None
        self.indexing: threading.Thread | None = None
        self.stop = threading.Event()
        self.error: str | None = None

    def start_index(self) -> bool:
        if self.indexing and self.indexing.is_alive():
            return False
        self.stop.clear()
        self.error = None

        def run() -> None:
            try:
                self.engine.index(on_progress=lambda p: setattr(self, "progress", p), stop=self.stop)
            except Exception as e:  # shown on the page
                self.error = f"{type(e).__name__}: {e}"

        self.indexing = threading.Thread(target=run, name="rummage-index", daemon=True)
        self.indexing.start()
        return True

    def status(self) -> dict:
        p = self.progress
        running = bool(self.indexing and self.indexing.is_alive())
        return {
            "version": __version__,
            "ready": assets.find_server() is not None and not assets.missing_models(),
            "folders": self.engine.config.folders,
            "index": self.engine.store.stats(),
            "indexing": running,
            "progress": None if p is None else {"total": p.total, "done": p.done, "failed": p.failed,
                                                "skipped": p.skipped, "current": p.current},
            "error": self.error,
        }

    def thumbnail(self, path: str, segment: str, loc: float, size: int = 360) -> bytes:
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


def _handler(app: App):
    page = resources.files("rummage").joinpath("static/index.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = f"Rummage/{__version__}"

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
            token = self.headers.get("X-Rummage-Token") or query.get("token", [""])[0]
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
                return self._json([{**r.__dict__, "where": r.where(), "name": Path(r.path).name} for r in results])
            if url.path == "/thumb":
                path = query.get("path", [""])[0]
                if not self._indexed(path):
                    return self._send(HTTPStatus.NOT_FOUND, b"not in the index", "text/plain")
                try:
                    body = app.thumbnail(path, query.get("segment", [""])[0], float(query.get("loc", ["0"])[0]))
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
                from .opener import open_file, reveal

                (reveal if body.get("reveal") else open_file)(path)
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
                return self._json({"started": app.start_index()})
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(port: int = 8765, open_browser: bool = True) -> int:
    engine = Engine()
    app = App(engine, port)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(app))
    except OSError:  # the port is taken: any free one will do
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(app))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Rummage is at {url}  (Ctrl+C to quit)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        httpd.server_close()
        engine.close()
    return 0
