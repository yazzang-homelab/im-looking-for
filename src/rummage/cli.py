"""``rummage``: set up, choose folders, index, search, and run the web UI."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

from . import __version__, assets, paths
from .config import Config


def _bar(name: str, have: int, total: int, state: dict) -> None:
    now = time.monotonic()
    if now - state.get("t", 0) < 0.25 and have < total:
        return
    state["t"] = now
    share = have / total if total else 1
    sys.stderr.write(f"\r  {name}  {share:6.1%}  {have / 1e6:7.1f} / {total / 1e6:.1f} MB")
    if have >= total:
        sys.stderr.write("\n")
    sys.stderr.flush()


def cmd_setup(args) -> int:
    config = Config.load()
    backend = args.backend or config.backend or assets.default_backend()
    state: dict = {}
    progress = lambda name, have, total: _bar(name, have, total, state)
    current = assets.installed_runtime()
    wanted = assets.runtime_asset(backend).name
    if current != wanted or assets.find_server() is None:
        print(f"llama.cpp {assets.LLAMA_TAG} ({backend})")
        assets.install_runtime(backend, progress)
    else:
        print(f"llama.cpp: {current} (installed)")
    if assets.missing_models():
        print("EmbeddingGemma 2 (Q8_0): text model and image/audio encoders")
        assets.install_models(progress)
    else:
        print("EmbeddingGemma 2: installed")
    config.backend = backend
    config.save()
    print(f"Ready. Data folder: {paths.data_dir()}")
    return 0


def cmd_add(args) -> int:
    config = Config.load()
    for folder in args.folders:
        print(f"+ {config.add_folder(folder)}")
    config.save()
    return 0


def cmd_remove(args) -> int:
    config = Config.load()
    for folder in args.folders:
        print(("- " if config.remove_folder(folder) else "not on the list: ") + folder)
    config.save()
    print("Run `rummage index` to forget their files.")
    return 0


def cmd_folders(args) -> int:
    for folder in Config.load().folders:
        print(folder)
    return 0


def cmd_index(args) -> int:
    from .engine import Engine

    stop = threading.Event()
    last = {"t": 0.0}

    def show(p) -> None:
        now = time.monotonic()
        if now - last["t"] < 0.5 and p.current:
            return
        last["t"] = now
        current = p.current[-70:] if p.current else ""
        sys.stderr.write(f"\r\x1b[K  {p.done + p.failed}/{p.total}  {current}")
        sys.stderr.flush()

    with Engine() as engine:
        try:
            progress = engine.index(args.folders or None, on_progress=show, stop=stop)
        except KeyboardInterrupt:
            stop.set()
            print("\nStopped; the next run continues from here.")
            return 130
    sys.stderr.write("\n")
    seconds = time.time() - progress.started
    print(f"Read {progress.done} files, {progress.skipped} unchanged, {progress.removed} forgotten, "
          f"{progress.failed} unreadable ({seconds:.0f} s).")
    for path, error in progress.errors[:20]:
        print(f"  ! {path}: {error}")
    return 0


def cmd_search(args) -> int:
    from .engine import Engine

    query = " ".join(args.query)
    kinds = set(args.kind) if args.kind else None
    with Engine() as engine:
        results = engine.search(query, limit=args.limit, kinds=kinds)
    if args.json:
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2))
        return 0
    if not results:
        print("Nothing found.")
        return 1
    for n, r in enumerate(results, 1):
        where = r.where()
        print(f"{n:2}. {r.score:.3f}  [{r.kind}{' ' + where if where else ''}]  {r.path}")
        if r.snippet:
            print(f"      {r.snippet[:160]}")
    if args.open:
        from .opener import open_file

        open_file(results[args.open - 1].path)
    return 0


def cmd_status(args) -> int:
    from .store import Store

    config = Config.load()
    print(f"Data folder: {paths.data_dir()}")
    print(f"llama.cpp:   {assets.installed_runtime() or 'not installed'}")
    missing = assets.missing_models()
    print(f"Model:       {'installed' if not missing else 'missing ' + ', '.join(m.name for m in missing)}")
    print("Folders:     " + (", ".join(config.folders) or "none"))
    if paths.index_file().exists():
        store = Store(paths.index_file())
        stats = store.stats()
        store.close()
        files = ", ".join(f"{n} {k}" for k, n in sorted(stats["files"].items())) or "none"
        print(f"Index:       {files}; {stats['vectors']} vectors, {stats['errors']} unreadable, "
              f"{stats['bytes'] / 1e6:.1f} MB")
    return 0


def cmd_serve(args) -> int:
    from .web import serve

    return serve(port=args.port, open_browser=not args.no_browser)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rummage", description="Search your files by what's in them.")
    parser.add_argument("--version", action="version", version=f"rummage {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="download llama.cpp and the model (~900 MB, once)")
    p.add_argument("--backend", choices=sorted({b for (_, _, b) in assets._RUNTIMES}),
                   help="llama.cpp build: cpu, vulkan (GPU on Windows/Linux) or metal (Apple Silicon)")
    p.set_defaults(run=cmd_setup)

    p = sub.add_parser("add", help="add folders to search")
    p.add_argument("folders", nargs="+")
    p.set_defaults(run=cmd_add)

    p = sub.add_parser("remove", help="take folders off the list")
    p.add_argument("folders", nargs="+")
    p.set_defaults(run=cmd_remove)

    p = sub.add_parser("folders", help="list the folders searched")
    p.set_defaults(run=cmd_folders)

    p = sub.add_parser("index", help="read new and changed files (all folders, or the ones given)")
    p.add_argument("folders", nargs="*")
    p.set_defaults(run=cmd_index)

    p = sub.add_parser("search", help="describe what you're looking for")
    p.add_argument("query", nargs="+")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.add_argument("-k", "--kind", action="append", choices=["image", "pdf", "doc", "audio", "video"])
    p.add_argument("--json", action="store_true")
    p.add_argument("--open", type=int, metavar="N", help="open the Nth result")
    p.set_defaults(run=cmd_search)

    p = sub.add_parser("status", help="what's installed and indexed")
    p.set_defaults(run=cmd_status)

    p = sub.add_parser("serve", help="the search page in your browser (http://127.0.0.1:PORT)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(run=cmd_serve)

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return args.run(args)
    except (RuntimeError, ValueError) as e:
        print(f"rummage: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
