# AGENTS.md

TikTok → Obsidian note pipeline (Windows). Three standalone scripts in this folder; no package, no tests, no linter, no build config. Only pip dependency is `requests`.

## The two-phase pipeline

1. `tiktok2note.py <url>` — expand short links, fetch oEmbed metadata, render `tiktok2note.tpl.md`, write a note to the output folder (default `Tiktoks/`, relative to CWD). New notes keep a literal `{{transcription}}` placeholder under a `## Transcription` heading (unless the video is a slideshow or private).
2. `process_tiktoks.py <folder>` — batch tool: reads `url:` from each note's YAML frontmatter, downloads audio, transcribes, and fills in the note. With `--apply-existing` it re-applies already-extracted transcripts offline (no download, no transcription server).

`tiktok2text.py <url>` is the single-URL variant of step 2 (writes `<videoId>.txt` next to the script instead of editing notes).

## External dependencies (none live in this repo)

- `requests` — the only pip dependency.
- `yt-dlp` on PATH — needs a 2026+ build for built-in impersonation; `winget install yt-dlp.yt-dlp`.
- `ffmpeg` on PATH — `winget install Gyan.FFmpeg`.
- **Faster Whisper Transcriber GUI server running at `http://127.0.0.1:8765`** — a separate GUI app; the repo only POSTs to `/transcribe`. Check with `curl http://127.0.0.1:8765/health`. It processes one job at a time (queues the rest); both transcribe scripts use a 600s request timeout.
- Python 3.10+ (`tiktok2text.py` uses `str | None` annotations without `from __future__ import annotations`).

## Gotchas (verified from code)

- **Fresh notes are transcribed, done notes are skipped**: `tiktok2note.py` leaves a literal `{{transcription}}` placeholder under a `## Transcription` heading; `process_tiktoks.py` fills it in on the next run. Notes whose transcription is already filled (no placeholder) are skipped unless `--force` is passed.
- **Slideshows and private videos are never transcribed**: `/photo/` slideshows have no audio and are embedded as markdown images; `process_tiktoks.py` skips notes with `isSlideshow: true` / `isPrivate: true` in frontmatter (before any network call or asset-folder creation), and `tiktok2text.py` refuses `/photo/` URLs outright.
- **Template substitution is a fixed `.replace()` list**: only the variables listed in `tiktok2note.py`'s docstring are substituted — including `{{title}}` (cleaned description, hashtags removed, ≤80 chars). Any other `{{...}}` in a custom template stays literal.
- **Most `Settings` fields are hardcoded defaults, not CLI flags**: duplicate handling (default `replace`), `handle_private_videos` (`create-empty`), `leave_transcription_placeholder`, `url_timeout` only exist on the `Settings` dataclass. The CLI exposes only `url`, `-o`, `--title-template`, `--content-template`.
- **yt-dlp quirks**: format `b[vcodec^=h264]/ba/b` deliberately avoids TikTok h265 (bytevc1) streams, which often declare audio but ship none. `--browser` is ignored — impersonation (`--impersonate chrome`) is used instead; Chrome's DPAPI cookie encryption doesn't work with yt-dlp on Windows, so only `--cookies-file` works.
- **Posted date** is decoded from the video ID (upper 32 bits are a Unix timestamp; only for ≥19-digit IDs), falling back to the HTTP `Last-Modified` header, then today.
- **Offline re-apply (`--apply-existing`)**: maps note filenames `<date>_<videoId>_<title>.md` → `_tiktok_assets/<videoId>.txt` (frontmatter URL key as fallback) and fills the `{{transcription}}` placeholder without downloading or transcribing. Missing transcript files are skipped, not failed.
- **Batch storage**: per-note `_tiktok_assets/<videoId>.wav|.txt` next to the note; dedup cache at `~/.cache/tiktok2text/<key>.wav` (key = video ID from URL, else yt-dlp probe `-O %(id)s`, else SHA-1 of URL). `--symlink` links cache → assets instead of copying.
- Debug lines go to stderr as `[debug] ...`; status/results go to stdout.

## Verification

No test suite. Verify changes by running the script against a live TikTok URL (requires network + the Whisper server for transcription scripts).
