# im-looking-for for AI agents

**English** · [한국어](agents.ko.md)

im-looking-for lets an agent find a file on the user's computer by what's in it — "the photo of the whiteboard from the
offsite", "the PDF where the lease talks about pets", "the voice memo about the dentist" — across photos, scans,
slides, documents, audio and video, in 100+ languages. Everything runs locally.

There are two ways in: the **MCP server** (`ilf mcp`) and the **CLI with `--json`**. Both report the same JSON shapes.

## Connect

| Client | How |
|---|---|
| Claude Code | `claude mcp add im-looking-for -- ilf mcp` |
| Codex CLI | `codex mcp add im-looking-for -- ilf mcp` |
| Claude Desktop, Cursor, others | `{"mcpServers": {"im-looking-for": {"command": "ilf", "args": ["mcp"]}}}` |
| No MCP | run `ilf <query> --json` in a shell |

If `ilf` isn't on the agent's `PATH`, use the absolute path. The app's Library panel shows the exact command for this
install, with a Copy button.

The user has to run setup once (`ilf`, or `ilf setup`) and add folders before there is anything to search. An agent
can add folders and start indexing itself (`add_folder`, `index`), but the ~900 MB model download is left to the user.

## MCP tools

| Tool | Arguments | Returns | Side effects |
|---|---|---|---|
| `search` | `query`, `limit` = 10 (1–50), `kinds` = all (`image`, `pdf`, `doc`, `audio`, `video`) | `{query, results: [Result]}` | starts the model on first use |
| `read_passages` | `path` (from a result), `loc` = start, `limit` = 10 | `{path, passages: [{kind, modality, loc, loc_end, text}]}` | none |
| `status` | — | Status (below) plus `indexing`, `progress`, `index_error` | none |
| `add_folder` | `folder` | `{added, folders}` | edits the config |
| `remove_folder` | `folder` | `{removed, folders}` | edits the config; files leave the index on the next full run |
| `index` | `folders` = all | `{started, queued}` | reads files in the background; while a run is going, queues another one after it |
| `stop_indexing` | — | `{stopping}` | stops after the current file |

`index` returns at once. Poll `status` until `indexing` is false; `progress` has `total`, `read`, `unchanged`,
`unreadable` and the `current` file. Searching works during indexing, over what's been read so far.

Read-only tools carry `readOnlyHint`; `remove_folder` carries `destructiveHint` (it only edits the folder list, never
files on disk).

## Result

```json
{
  "path": "/home/you/Documents/lease_2026.pdf",
  "name": "lease_2026.pdf",
  "kind": "pdf",
  "score": 0.7765,
  "match": "page",
  "loc": 1.0,
  "loc_end": null,
  "where": "p.1",
  "snippet": "주택 임대차 계약서 제 1 조 (목적) …"
}
```

| Field | Meaning |
|---|---|
| `kind` | `image`, `pdf`, `doc`, `audio`, `video` |
| `match` | what matched: `image`, `page` (PDF text), `page_image` (PDF page read as a picture), `chunk` (a stretch of a document), `audio`, `frame` (a video frame), `name` (file or folder name) |
| `loc`, `loc_end` | page number for PDFs, stretch number (from 0) for documents, seconds for audio and video |
| `where` | `loc` for people: `p.3`, `0:42`; empty for pictures, documents and names |
| `snippet` | the matching text; empty for pictures and sound |

One result per file, best match first.

## Reading scores

A search **always returns the nearest files**, even when nothing matches. Measured on the demo folder:
`lease termination` → the lease PDF at 0.78, then unrelated files at 0.59; the nonsense query `xyzzy-nothing-here`
still returns a video at 0.61. So:

- A score means something only next to the others. A result well ahead of the rest (here 0.78 vs 0.59) is a match;
  a flat run of similar scores means "probably not here".
- Check before you claim: read the `snippet`, or call `read_passages` with the result's `path` and `loc`.
- Never tell the user a file doesn't exist because search didn't find it. Its folder may not be added or indexed
  (`status`), it may be a format that isn't read (HEIC, code), or the words may be inside a photo (no OCR).

## Writing queries

- Describe content, not names: `a cat sleeping on a red sofa`, not `IMG_2041`. The file name is searched too, as a
  keyword, so a known name still helps.
- Any language works, and languages mix: an English query finds a Korean PDF.
- Use `kinds` when the user said what it is ("the recording…", "that PDF…").
- Exact words count: a word that appears literally in a document lifts it, which helps with names, codes and numbers.

## CLI with `--json`

```sh
ilf invoice from march --json            # same as: ilf search invoice from march --json
ilf -k image -n 5 whiteboard --json
ilf status --json
ilf add ~/Scans --json && ilf index --json
```

| Exit code | Meaning |
|---|---|
| 0 | done (for search: at least one result) |
| 1 | search returned nothing: the index is empty or no file passes `--kind` |
| 2 | error; with `--json`, stdout is `{"error": "...", "code": 2}` |
| 3 | not set up: llama.cpp or the model is missing (`ilf setup`) |

`ilf index --json` blocks until done and prints `{read, unchanged, forgotten, unreadable, seconds, errors}`.
Progress goes to stderr only on a terminal, so stdout stays clean JSON.

## Status

```json
{
  "version": "0.1.0",
  "ready": true,
  "data_dir": "/home/you/.local/share/im-looking-for",
  "runtime": "llama-b11461-bin-ubuntu-x64.tar.gz",
  "backend": "cpu",
  "gpu_failed": null,
  "backends": ["cpu", "vulkan"],
  "missing_models": [],
  "download_bytes": 0,
  "folders": ["/home/you/Pictures", "/home/you/Documents"],
  "excluded_folders": [],
  "excluded_extensions": [],
  "index": {"files": {"image": 6, "pdf": 1, "doc": 3}, "errors": 0, "vectors": 17, "bytes": 98304}
}
```

## Privacy

Nothing leaves the computer: the model runs in a local llama.cpp process and the index is a local SQLite file.
`read_passages` returns only text from files already in the index, which the user chose by adding their folders.
