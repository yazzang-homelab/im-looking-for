# AGENTS.md

Guidance for AI coding agents (and people) changing im-looking-for. To *use* it from an agent, see
[docs/agents.md](docs/agents.md) and [skills/im-looking-for/SKILL.md](skills/im-looking-for/SKILL.md).

## Layout

| Path | What |
|---|---|
| `src/im_looking_for/cli.py` | `ilf` / `im-looking-for`: bare words search, subcommands, `--json`, exit codes |
| `src/im_looking_for/agent.py` | MCP server (`ilf mcp`) and the background index job shared with the app |
| `src/im_looking_for/web.py`, `static/index.html` | the app: loopback HTTP server + one page (setup wizard, folder browser, search, library) |
| `src/im_looking_for/engine.py` | index + llama-server lifecycle; the one object CLI, app and MCP use |
| `src/im_looking_for/indexer.py`, `extract.py`, `media.py`, `rules.py` | which files, read into segments, embedded |
| `src/im_looking_for/search.py`, `store.py` | scoring and the SQLite index (float16 vectors + FTS5 trigram) |
| `src/im_looking_for/assets.py`, `server.py`, `embed.py` | pinned llama.cpp + model downloads, the helper process, its HTTP API |
| `src/im_looking_for/status.py` | the status dict every surface reports |
| `tests/` | unit tests use `FakeEmbedder` (no model); `test_integration.py` needs the real model |
| `scripts/` | testbed + eval, screenshots (`shots.py`), PyInstaller entry |

## Rules

- **One JSON shape per thing.** `Result.to_dict()` and `status.describe()` are the contract for the CLI, the app's API
  and the MCP tools, documented in `docs/agents.md` (+ `.ko.md`). Change them together or not at all.
- **Pinned downloads.** llama.cpp tag, model revision, sizes and SHA-256 live in `assets.py`. Changing the model or the
  prompts means bumping `VECTOR_VERSION` (`embed.py`) so old indexes are rebuilt instead of mixed.
- **The media marker is per-run**: read it from `GET /props` (`media_marker`); a fixed `<__media__>` breaks.
- **Read-only on user files.** Nothing writes, moves or uploads user files. The app serves previews, passages and
  "open" only for paths already in the index, binds to 127.0.0.1, checks `Host` and a per-run token. Keep it that way.
- **stdout is for results.** Progress goes to stderr, and only on a terminal; `--json` output must stay parseable.
- **Both languages.** UI strings live in the `T` table in `index.html` (`en`, `ko`); docs come in `*.md` + `*.ko.md`.
  Korean docs use the formal written style (합니다체).
- **Measure claims.** Speed, quality and score numbers in the docs come from real runs (`scripts/eval.py`,
  `ilf ... --json`); update them when they change, don't estimate.

## Check

```sh
pip install -e ".[dev]"
pytest -q                                         # ~40 tests, no model needed
ruff check --line-length 120 src tests scripts    # remaining BLE001 etc. are deliberate
ILF_INTEGRATION=1 ILF_REAL_HOME=<data dir after `ilf setup`> pytest tests/test_integration.py
python scripts/eval.py scripts/testbed_eval.json  # needs the testbed (scripts/make_testbed.py) and the model
```

For UI changes, look at the result: `python scripts/shots.py /tmp/shots --lang en` (and `--lang ko`) drives the real app
with Playwright and saves the main screens.
