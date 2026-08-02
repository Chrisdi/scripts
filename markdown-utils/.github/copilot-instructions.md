# Copilot Instructions for this repository

## What this repo is

A growing collection of small, standalone markdown utility scripts (not a single application).
It currently contains:
- `md_merge_headers.py` — a standalone CLI script for merging two sections (identified by
  markdown `#` headers) within markdown files into one.
- `remove_section.py` — a standalone CLI script for removing a section (a `#` header and its
  content, up to the next header of the same or shallower level) from markdown files.
- `md_utils.py` — shared stdlib-only helpers used by the scripts above: `get_header_level`,
  `find_header_block`, `remove_empty_lines`, `find_markdown_files`,
  `resolve_markdown_targets` (file-or-directory input resolution), and `preserve_mtime`
  (context manager for timestamp preservation). New scripts should reuse these instead of
  reimplementing them.
- `data/` — example/test markdown files used to exercise the scripts (Obsidian-style daily
  journal notes, one per day, named `YYYY-MM-DD.md`, with YAML frontmatter and `#`-level
  section headers like `# Summary`, `# Events`, `# Log`, etc.). Not application data — treat
  it as fixtures for manual validation, and feel free to add more sample files as needed.

There is no build system, package manifest, test suite, or CI configuration — just Python 3
scripts (stdlib only: `sys`, `re`, `os`).

## Project conventions for new utilities

- Each markdown utility should stay a **simple, standalone Python 3 script** (stdlib only
  where possible) so it runs identically on Linux and Windows without setup/install steps.
  Avoid adding a package manifest, framework, or third-party dependency unless truly
  necessary.
- Prefer one script per distinct utility/CLI entry point rather than a single monolithic
  tool. Shared logic (header parsing, file-or-directory resolution, mtime preservation) lives
  in `md_utils.py` — import from it rather than copy-pasting into new scripts.
- Use `data/` for example/test fixtures when adding or validating a new script.
- **Every script must accept either a single file or a directory as its input path.** Use
  `md_utils.resolve_markdown_targets(path)` to resolve the CLI path argument into a list of
  `.md` files (it handles both the single-file case and recursive directory traversal via
  `find_markdown_files`/`os.walk`).
- **Every script that edits an existing file in place must preserve its last-modification
  timestamp.** Use the `md_utils.preserve_mtime(file_path)` context manager around the
  read-modify-write, rather than reimplementing the `os.stat`/`os.utime` dance.

## Running the scripts

```
python md_merge_headers.py <markdown_file_or_directory> <header1> <header2> <output_header>
python remove_section.py <markdown_file_or_directory> <header>
```

- If given a single `.md` file, the target file is modified in place.
- If given a directory, all `*.md` files found recursively are processed the same way.
- No test runner exists — validate changes manually, e.g. by running a script against a copy
  of a file in `data/` and diffing the result, or with a `python -c` snippet that calls the
  script's core function (e.g. `modify_markdown(...)`, `remove_section(...)`) directly on a
  temp file.

## How the merge logic works (`md_merge_headers.py`)

1. `find_header_block(lines, header_text)` locates a header line matching `header_text`
   exactly (ignoring leading `#`s and surrounding whitespace) and returns its index, its
   header level (number of `#` characters), and the index where its block ends — defined as
   the next header line of **equal or shallower** level (or end of file).
2. `modify_markdown` then rebuilds the file as: content before `header1`, a new header line
   (`output_header`, same level as `header1`), `header1`'s block content, `header2`'s block
   content appended immediately after, then any content between `header1`'s block end and
   `header2`'s start (preserving intermediate headers), then everything after `header2`'s
   block.
3. `remove_empty_lines` strips blank lines from both header1's and header2's block content
   before recombining — this is intentional and applies to both merged sections.
4. File modification time (`st_mtime`/`st_atime`) is preserved via `md_utils.preserve_mtime`
   after writing — keep this behavior if you modify the write path, since these are dated
   journal files where mtime matters.
5. `header2` must appear **after** `header1` in the file for the search order used by
   `find_header_block` (it searches header1 from index 0, header2 also from index 0, but the
   rebuild logic assumes `header1_idx < header2_idx`); merging in the reverse order will
   produce incorrect output.

## How `remove_section.py` works

`find_header_block` locates the target header and its block end (next header of equal or
shallower level, or end of file); the script then simply drops `lines[header_idx:block_end]`
— i.e. the header line plus all of its content, including any trailing blank lines up to the
next header — and preserves mtime via `md_utils.preserve_mtime`.

## Conventions

- Headers/headings are matched by exact text after the `#` markers (regex-escaped). Heading
  CLI arguments **must** include leading `#` markers to pin the match to a specific level —
  e.g. `"# Vault todos"` matches only a level-1 heading with that text, `"### Vault todos"`
  matches only level-3. A heading argument without `#` markers is rejected with an error (see
  `md_utils.parse_header_arg`/`find_header_block`), since journal files reuse the same heading
  text at different levels/notes.
- The heading text itself (after the `#` markers) must still match exactly, including any
  trailing punctuation/emoji present in the source (e.g. `Today's Plan ✔️`).
- The output header is written at `header1`'s original level, not header2's.
- Keep the script dependency-free (stdlib only) unless there's a strong reason to add a
  dependency.
