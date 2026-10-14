"""llama.cpp's ``llama-server`` as a helper process, on a free loopback port, for as long as Rummage needs vectors.

It only ever listens on 127.0.0.1 and only ever reads the two pinned model files. With ``media=False`` it loads just
the text model (~310 MB), which is all a search needs.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import assets, paths

# One input holds at most this many tokens: a 30 s audio window is 750, an image 280, a text chunk ~600.
CONTEXT = 8192


class ServerError(RuntimeError):
    """llama-server refused one input (the input's problem, not the server's)."""


class ServerUnavailable(RuntimeError):
    """llama-server can't be reached or isn't installed: nothing can be embedded until that's fixed."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LlamaServer:
    def __init__(self, media: bool = True, image_tokens: int = 280, threads: int | None = None,
                 gpu_layers: int = 99, startup_timeout: float = 180.0):
        server = assets.find_server()
        if server is None:
            raise ServerUnavailable("llama.cpp isn't installed; run `rummage setup`")
        missing = [m.name for m in assets.MODELS if (media or m is assets.TEXT_MODEL)
                   and not assets.model_path(m).is_file()]
        if missing:
            raise ServerUnavailable(f"model files missing ({', '.join(missing)}); run `rummage setup`")
        self.media = media
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        args = [str(server), "--host", "127.0.0.1", "--port", str(self.port),
                "-m", str(assets.model_path(assets.TEXT_MODEL)),
                "--embeddings", "--pooling", "mean",
                "-c", str(CONTEXT), "-b", str(CONTEXT), "-ub", str(CONTEXT),
                "-np", "1", "-ngl", str(gpu_layers), "--no-webui"]
        if media:
            args += ["--mmproj", str(assets.model_path(assets.MEDIA_MODEL)),
                     "--image-min-tokens", str(image_tokens), "--image-max-tokens", str(image_tokens)]
        else:
            args += ["--no-mmproj"]
        if threads:
            args += ["-t", str(threads)]
        self.args = args
        self.startup_timeout = startup_timeout
        self.process: subprocess.Popen | None = None
        self.media_marker: str | None = None
        self._log = None

    def __enter__(self) -> LlamaServer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        self._log = open(paths.log_file(), "ab")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = dict(os.environ)
        # The Linux and macOS builds look for their shared libraries next to the executable.
        lib_dir = str(Path(self.args[0]).parent)
        if sys.platform == "darwin":
            env["DYLD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("DYLD_LIBRARY_PATH", "")
        elif sys.platform.startswith("linux"):
            env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        self.process = subprocess.Popen(self.args, stdin=subprocess.DEVNULL, stdout=self._log,
                                        stderr=subprocess.STDOUT, env=env, creationflags=flags)
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ServerUnavailable(f"llama-server exited with {self.process.returncode}; "
                                        f"see {paths.log_file()}")
            try:
                with urllib.request.urlopen(f"{self.base}/health", timeout=2) as r:
                    healthy = r.status == 200
                if healthy:
                    # the server picks a random media marker per run; inputs must use it
                    with urllib.request.urlopen(f"{self.base}/props", timeout=10) as r:
                        self.media_marker = json.loads(r.read()).get("media_marker")
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(0.3)
        self.stop()
        raise ServerUnavailable(f"llama-server didn't start within {self.startup_timeout:.0f} s; see {paths.log_file()}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None
        if self._log:
            self._log.close()
            self._log = None

    def post(self, route: str, body: dict, timeout: float = 600.0) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base + route, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code >= 500 and self.process is not None and self.process.poll() is not None:
                raise ServerUnavailable(f"llama-server stopped; see {paths.log_file()}") from None
            raise ServerError(f"{route}: {e.code} {e.read()[:500].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise ServerUnavailable(f"llama-server can't be reached: {e}") from None
