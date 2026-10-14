---
name: im-looking-for
description: Find files on the user's computer by what's in them (photos, PDFs and scans, documents, voice memos and other audio, video) with the local `ilf` command. Use when the user wants a file they can describe but can't name or locate ("the photo of the whiteboard", "the PDF that mentions pets", "that recording about the dentist", "내가 찍은 영수증 사진").
---

# Finding files by content with im-looking-for

`ilf` searches an on-device index of the folders the user chose. It understands pictures, sound and text in 100+
languages. Nothing leaves the computer.

## Steps

1. **Check it's usable**: `ilf status --json`.
   - `ready: false` → tell the user to run `ilf` (the app walks them through setup) or `ilf setup`. Don't download the
     ~900 MB model for them unless they asked.
   - `folders: []` → ask which folders hold the files, then `ilf add <folder> --json` and `ilf index --json` (this can
     take minutes; it only reads new and changed files on later runs).
2. **Search** with a description of the content, in the user's language or English:
   `ilf <description> --json -n 10`, adding `-k image|pdf|doc|audio|video` when the user said what kind of file it is.
   If the description starts with a command word (`setup`, `add`, `index`, `status`, `search`, …) use
   `ilf search <description> --json`.
3. **Judge the results**. Search always returns the nearest files, even when nothing matches, so scores only mean
   something relative to each other: a result clearly ahead of the rest, or whose `snippet` says what was asked, is a
   match; a flat list of similar scores means it's probably not indexed.
4. **Confirm before answering**: read the `snippet`; for documents and PDFs the MCP tool `read_passages` (or opening the
   file) shows more. For pictures, look at the file if you can view images.
5. **Answer with the path** (and `where`, the page or timestamp). Open it only if asked: `ilf <description> --open 1`.

## Exit codes

`0` results · `1` no results (empty index or filtered out) · `2` error (`{"error": ...}` on stdout with `--json`) ·
`3` not set up.

## Don't

- Don't say a file doesn't exist because it wasn't found: its folder may not be added, it may be HEIC or code (not
  read), or the text may be inside a photo (no OCR).
- Don't search for file names alone; describe what the file shows or says. Names are matched as keywords anyway.
- Don't remove folders or re-index everything without being asked.

If an MCP client is available, `ilf mcp` exposes the same functions as tools (`search`, `read_passages`, `status`,
`add_folder`, `remove_folder`, `index`, `stop_indexing`). Details: `docs/agents.md` in the im-looking-for repository.
