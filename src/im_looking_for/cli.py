"""`ilf` (also `im-looking-for`): describe what you're looking for, or manage what gets searched.

    ilf                                  open the app (the search window)
    ilf a dog running on the beach       search: anything that isn't a command is a description
    ilf search index cards               search for words that start like a command
    ilf setup | add | remove | folders | index | status | serve | mcp

Every command takes ``--json`` for programs and agents. Exit codes: 0 done, 1 no results (empty index or filters),
2 bad input or error, 3 not set up yet (``ilf setup``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

from . import __version__, assets, status
from .config import Config
from .server import ServerUnavailable

COMMANDS = {"setup", "add", "remove", "folders", "index", "search", "status", "serve", "gui", "mcp"}
KINDS = ["image", "pdf", "doc", "audio", "video"]

NOT_FOUND, FAILED, NOT_READY = 1, 2, 3


def _emit(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


class _Bar:
    """A one-line download/progress meter on stderr, only on a terminal."""

    def __init__(self, enabled: bool):
        self.enabled = enabled and sys.stderr.isatty()
        self.last = 0.0

    def download(self, name: str, have: int, total: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self.last < 0.25 and have < total:
            return
        self.last = now
        share = have / total if total else 1
        sys.stderr.write(f"\r\x1b[K  {name}  {share:6.1%}  {have / 1e6:7.1f} / {total / 1e6:.1f} MB")
        if have >= total:
            sys.stderr.write("\n")
        sys.stderr.flush()

    def index(self, p) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self.last < 0.5 and p.current:
            return
        self.last = now
        sys.stderr.write(f"\r\x1b[K  {p.done + p.failed}/{p.total}  {p.current[-70:] if p.current else ''}")
        sys.stderr.flush()


def cmd_setup(args) -> int:
    config = Config.load()
    backend = args.backend or config.backend or assets.default_backend()
    if not args.json:
        print(f"llama.cpp {assets.LLAMA_TAG} ({backend}) and EmbeddingGemma 2 (Q8_0, 865 MB)")
    done = assets.install(backend, _Bar(not args.json).download)
    config.backend = backend
    config.gpu_failed = None
    config.save()
    report = {**done, "ready": assets.ready()}
    if args.json:
        _emit(report)
    else:
        print("Ready." if report["ready"] else "Something is still missing; run `ilf status`.")
    return 0 if report["ready"] else FAILED


def cmd_add(args) -> int:
    config = Config.load()
    added = [config.add_folder(f) for f in args.folders]
    config.save()
    if args.json:
        _emit({"added": added, "folders": config.folders})
    else:
        for folder in added:
            print(f"+ {folder}")
        print("Run `ilf index` to read them.")
    return 0


def cmd_remove(args) -> int:
    config = Config.load()
    removed = [f for f in args.folders if config.remove_folder(f)]
    config.save()
    if args.json:
        _emit({"removed": removed, "folders": config.folders})
    else:
        for folder in args.folders:
            print(("- " if folder in removed else "not on the list: ") + folder)
        print("Run `ilf index` to forget their files.")
    return 0


def cmd_folders(args) -> int:
    folders = Config.load().folders
    if args.json:
        _emit(folders)
    else:
        print("\n".join(folders) if folders else "No folders yet: `ilf add <folder>`.")
    return 0


def cmd_index(args) -> int:
    from .engine import Engine

    stop = threading.Event()
    bar = _Bar(not args.json)
    with Engine() as engine:
        try:
            progress = engine.index(args.folders or None, on_progress=bar.index, stop=stop)
        except KeyboardInterrupt:
            stop.set()
            print("\nStopped; the next run continues from here.", file=sys.stderr)
            return 130
    if bar.enabled:
        sys.stderr.write("\n")
    report = {"read": progress.done, "unchanged": progress.skipped, "forgotten": progress.removed,
              "unreadable": progress.failed, "seconds": round(time.time() - progress.started, 1),
              "errors": [{"path": p, "error": e} for p, e in progress.errors]}
    if args.json:
        _emit(report)
    else:
        print(f"Read {report['read']} files, {report['unchanged']} unchanged, {report['forgotten']} forgotten, "
              f"{report['unreadable']} unreadable ({report['seconds']:.0f} s).")
        for error in report["errors"][:20]:
            print(f"  ! {error['path']}: {error['error']}")
    return 0


def cmd_search(args) -> int:
    from .engine import Engine

    query = " ".join(args.query)
    with Engine() as engine:
        results = engine.search(query, limit=args.limit, kinds=set(args.kind) if args.kind else None)
    if args.json:
        _emit({"query": query, "results": [r.to_dict() for r in results]})
    elif not results:
        print("Nothing found.")
    else:
        for n, r in enumerate(results, 1):
            where = r.where()
            print(f"{n:2}. {r.score:.3f}  [{r.kind}{' ' + where if where else ''}]  {r.path}")
            if r.snippet:
                print(f"      {r.snippet[:160]}")
    if results and args.open:
        from .opener import open_file

        open_file(results[min(args.open, len(results)) - 1].path)
    return 0 if results else NOT_FOUND


def cmd_status(args) -> int:
    report = status.describe()
    if args.json:
        _emit(report)
        return 0
    files = ", ".join(f"{n} {k}" for k, n in sorted(report["index"]["files"].items())) or "none"
    print(f"im-looking-for {report['version']}")
    print(f"Data folder: {report['data_dir']}")
    print(f"llama.cpp:   {report['runtime'] or 'not installed'}")
    if report["gpu_failed"]:
        print(f"             running on the processor; the GPU failed ({report['gpu_failed']}). "
              "`ilf setup --backend <name>` tries again.")
    print("Model:       " + ("installed" if not report["missing_models"]
                             else "missing " + ", ".join(report["missing_models"])))
    print("Folders:     " + (", ".join(report["folders"]) or "none"))
    index = report["index"]
    print(f"Index:       {files}; {index['vectors']} vectors, {index['errors']} unreadable, "
          f"{index['bytes'] / 1e6:.1f} MB")
    if not report["ready"]:
        print("Run `ilf setup` first.")
    return 0


def cmd_serve(args) -> int:
    from .web import serve

    return serve(port=args.port, open_browser=not args.no_browser, app_window=not args.browser_tab)


def cmd_mcp(args) -> int:
    from .agent import run

    run()
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ilf", description="Search your files by what's in them. `ilf <description>` searches; "
                                "`ilf` alone opens the app.")
    parser.add_argument("--version", action="version", version=f"im-looking-for {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name, help, run, aliases=()):
        p = sub.add_parser(name, help=help, aliases=list(aliases))
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.set_defaults(run=run)
        return p

    p = command("setup", "download llama.cpp and the model (~900 MB, once)", cmd_setup)
    p.add_argument("--backend", choices=sorted({b for (_, _, b) in assets._RUNTIMES}),
                   help="llama.cpp build: cpu, vulkan (GPU on Windows/Linux) or metal (Apple Silicon)")
    command("add", "add folders to search", cmd_add).add_argument("folders", nargs="+")
    command("remove", "take folders off the list", cmd_remove).add_argument("folders", nargs="+")
    command("folders", "list the folders searched", cmd_folders)
    command("index", "read new and changed files (all folders, or the ones given)",
            cmd_index).add_argument("folders", nargs="*")
    p = command("search", "describe what you're looking for", cmd_search)
    p.add_argument("query", nargs="+")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.add_argument("-k", "--kind", action="append", choices=KINDS, help="only this kind of file (repeatable)")
    p.add_argument("--open", type=int, metavar="N", help="open the Nth result")
    p.set_defaults(command="search")
    parser.search_parser = p  # words and options in any order: `ilf red car -k image`
    command("status", "what's installed and indexed", cmd_status)
    p = command("serve", "the app: a search window in your browser", cmd_serve, aliases=["gui"])
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open a window")
    p.add_argument("--browser-tab", action="store_true", help="open a normal browser tab, not an app window")
    command("mcp", "run as an MCP server on stdio, for AI agents", cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]
    elif argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv = ["search", *argv]
    elif argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv = ["search", *argv]  # `ilf -k image red car`
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = _parser()
    if argv[0] == "search":
        args = parser.search_parser.parse_intermixed_args(argv[1:])
    else:
        args = parser.parse_args(argv)
    try:
        return args.run(args)
    except BrokenPipeError:  # `ilf ... | head`: the reader left, which isn't an error
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except ServerUnavailable as e:
        return _fail(args, str(e), NOT_READY)
    except (RuntimeError, ValueError, OSError) as e:
        return _fail(args, str(e), FAILED)


def _fail(args, message: str, code: int) -> int:
    if getattr(args, "json", False):
        _emit({"error": message, "code": code})
    else:
        print(f"ilf: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
