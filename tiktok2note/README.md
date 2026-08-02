# tiktok2note

TikTok URL to Obsidian note pipeline. 

From a TikTok URL to a formatted Markdown note — caption, hashtags, embed, posted date — plus, for regular videos, a full text transcription via the Faster Whisper Transcriber.


## Pipeline overview

| Phase | Script | What it does |
|---|---|---|
| 1. Create the note | `tiktok2note.py <url>` | Expands short links, fetches oEmbed metadata, renders `tiktok2note.tpl.md`, writes the note to an output folder |
| 2. Transcribe | `process_tiktoks.py <folder>` | Reads `url:` from each note's frontmatter, downloads the audio (yt-dlp), transcribes (Faster Whisper), fills the note in |

`tiktok2text.py <url>` is the single-URL variant of phase 2: it writes a bare `<videoId>.txt` transcript next to the script instead of editing notes.

## Prerequisites

Assumed up and running:

- **Python 3.10+** with `requests` — `pip install requests`
- **yt-dlp on PATH** — needs a 2026+ build for built-in impersonation: `winget install yt-dlp.yt-dlp`
- **ffmpeg on PATH** — `winget install Gyan.FFmpeg`
- **Faster Whisper Transcriber GUI server** on `http://127.0.0.1:8765` — a separate GUI app (Settings → Server Mode → On → port 8765). Verify with `curl http://127.0.0.1:8765/health`. It processes one job at a time and queues the rest; both transcribe scripts wait up to 600 s per request. Model `small` is available.

## Workflow: TikTok URL → Markdown note with transcript

```bash
# 1) Create the note: metadata, embed, hashtags, frontmatter (transcript placeholder)
python tiktok2note.py "https://www.tiktok.com/@user/video/1234567890123456789" -o "Tiktoks"

# 2) Fill in the transcript (model small; slideshows/private are skipped automatically)
python process_tiktoks.py "Tiktoks" --model small
```

That's it. After step 2 the note has a complete `## Transcription` section. Re-run step 2 any time to process notes added since; already-transcribed notes are skipped (use `--force` to redo).

### Step 1 — `tiktok2note.py` in detail

1. **Expand short links** — `vm.tiktok.com`, `tiktok.com/t/`, `m.tiktok.com`, and 4-12 char short codes are followed to the canonical `https://www.tiktok.com/@author/video/<id>` form.
2. **Fetch metadata** — from TikTok's oEmbed endpoint: author name, caption (`description`), hashtags, video id.
3. **Posting date** — decoded from the video ID (its upper 32 bits are a Unix timestamp), falling back to the HTTP `Last-Modified` header, then to today.
4. **Render the template** — `tiktok2note.tpl.md` (or `--content-template`); a fixed `.replace()` list substitutes the variables in the table below.
5. **Write the note** — `Tiktoks/<date>_<videoId>_<title>.md` (title = cleaned caption, ≤80 chars). Existing files are overwritten by default.

**Slideshows** (`/photo/` URLs) have no audio: they're embedded as a markdown image, flagged `isSlideshow: true` in frontmatter, and get **no transcription placeholder** — so they never reach phase 2. **Private videos** get a placeholder note flagged `isPrivate: true`.

Resulting note structure:

```markdown
---
author: "calebwritescode"
created: 2026-08-01
posted: 2025-08-30
url: https://www.tiktok.com/@calebwritescode/video/7544261247022255373
isSlideshow: false
tags: 
title: "Diffusion Models: from autoencoder to VAE to GAN to Diffusion. ..."
---

# Content

## Description
<caption with hashtag words removed>

## Video
<iframe embed>

## Hashtags
  - ai
  - llm
  ...

## Transcription
{{transcription}}        ← placeholder; step 2 replaces this
```

### Step 2 — `process_tiktoks.py` in detail

For every `.md` file in the folder (`--recursive` for subfolders):

1. **Read the URL** from the `url:` frontmatter field; skip files without one.
2. **Skip un-transcribable notes** — frontmatter `isSlideshow: true` or `isPrivate: true` (no download attempted).
3. **Skip done notes** — if the note already has a real transcription. Fresh notes from step 1 still carry the literal `{{transcription}}` placeholder, so they are *processed*, not skipped (`--force` re-transcribes anything).
4. **Download audio** — yt-dlp to `~/.cache/tiktok2text/<key>.wav` (a dedup cache keyed by video id — already-downloaded videos are reused across folders), then copy (or `--symlink`) it to `_tiktok_assets/<key>.wav` next to the note.
5. **Transcribe** — POST the wav to `http://127.0.0.1:8765/transcribe` with `--model small` (default `base`) and `--lang en`. Save the transcript to `_tiktok_assets/<key>.txt`.
6. **Fill the note** — replace the placeholder under `## Transcription` with the transcript text (`--heading` changes the section name).

## Usage reference

### `tiktok2note.py`

```
python tiktok2note.py <url> [-o FOLDER] [--title-template T] [--content-template FILE]
```

| Option | Default | Notes |
|---|---|---|
| `<url>` | — | Short or canonical TikTok URL |
| `-o, --output` | `Tiktoks/` (relative to CWD) | Output folder |
| `--title-template` | `{{date}}_{{videoId}}_{{title}}` | Note filename template |
| `--content-template` | `tiktok2note.tpl.md` | Note body template |

Template variables: `{{author}}`, `{{date}}`, `{{posted}}`, `{{url}}`, `{{expanded_url}}`, `{{videoId}}`, `{{description}}` (hashtags removed), `{{hashtags}}`, `{{iframe}}`, `{{transcription}}`, `{{isSlideshow}}`, `{{tag_list}}`, `{{title}}` (cleaned description, ≤80 chars). Anything else in a custom template stays literal.

### `process_tiktoks.py`

```
python process_tiktoks.py <folder> [--recursive] [--force] [--heading H]
    [--model small|base|tiny|...] [--lang en]
    [--assets-dirname _tiktok_assets] [--global-cache ~/.cache/tiktok2text] [--symlink]
    [--cookies-file FILE] [--limit-rate 1M] [--retries N] [--fragment-retries N] ...
```

| Option | Default | Notes |
|---|---|---|
| `<folder>` | — | Folder of `.md` notes to process |
| `--recursive` | off | Recurse into subfolders |
| `--force` | off | Re-transcribe even if a transcription already exists |
| `--heading` | `Transcription` | Section heading to fill in the note |
| `--model` / `--lang` | `base` / `en` | Whisper model and language (server-side; `small` recommended) |
| `--assets-dirname` | `_tiktok_assets` | Per-note folder for wav/txt |
| `--global-cache` | `~/.cache/tiktok2text` | Cross-folder audio dedup cache |
| `--symlink` | off | Symlink cache → assets instead of copying |
| `--cookies-file` | — | `cookies.txt` for yt-dlp (private-ish videos) |
| `--limit-rate` | — | e.g. `1M` to throttle downloads |

### `tiktok2text.py`

```
python tiktok2text.py <url> [-m small] [-l en] [-o OUTDIR]
```

Transcript-only: downloads the audio and writes `<videoId>.txt` (default: next to the script). Refuses `/photo/` slideshows (exit 2) — they have no audio.

## Worked example (tested end-to-end)

URL: `https://www.tiktok.com/@calebwritescode/video/7544261247022255373`

```
$ python tiktok2note.py "<url>" -o "Tiktoks"
Created: Tiktoks/2026-08-01_7544261247022255373_Diffusion Models from autoencoder to VAE to GAN to Diffusion. How AI matured it....md

$ python process_tiktoks.py "Tiktoks" --model small
[1/1] ...md — downloading → cache/7544261247022255373.wav
[1/1] ...md — copied audio into _tiktok_assets/
[1/1] ...md — transcribing via Faster Whisper (small) …
[1/1] ...md — ✅ done | download 12s • transcribe 4m 50s • update 0s • total 5m 03s
```

Notes:
- The wav lives both in `Tiktoks/_tiktok_assets/` and `~/.cache/tiktok2text/` (dedup cache). Deleting the note folder leaves the cache untouched, so re-processing the same video skips the download.
- A 5-minute clip takes ~5 minutes to transcribe with `small` on CPU — transcription is serial (one job at a time on the server).
- The second run skips this note (`already has Transcription`); `--force` re-transcribes.

## Storage layout

```
Tiktoks/
└── 2026-08-01_7544261247022255373_....md      ← the note
    └── _tiktok_assets/
        ├── 7544261247022255373.wav            ← audio (copy or symlink)
        └── 7544261247022255373.txt            ← transcript
~/.cache/tiktok2text/
    └── 7544261247022255373.wav                ← global dedup cache
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Faster Whisper Transcriber not reachable` (exit 4) | Start the GUI and enable server mode on port 8765; `curl http://127.0.0.1:8765/health` |
| `yt-dlp failed; check URL or connection` | URL removed/private or network issue; retry. Private content may need `--cookies-file` (Chrome browser cookies don't work with yt-dlp on Windows — only a cookies.txt file) |
| Note never gets a transcription | It's a slideshow (`/photo/`) or private video — by design, these are never transcribed |
| Want to re-transcribe a note | `process_tiktoks.py <folder> --force` |
| Download too slow | `--limit-rate 1M` won't help; that throttles. Slow is usually the Whisper CPU transcription |
| Transcript off language | `--lang <code>` (e.g. `--lang fr`) |
