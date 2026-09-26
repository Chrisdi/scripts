# Local-first podcast transcript resolver

This is a **Python skeleton**, not a finished universal scraper. It is designed to make the transcript provenance and fallback order explicit:

| Priority | Source | Behaviour |
|---:|---|---|
| 1 | Podcast Addict / episode-page metadata | Collect title, show, description, and safe source hints. For a Podcast Addict input, provide `--feed-url` until you add a publisher-specific feed resolver. |
| 2 | Publisher website and canonical RSS feed | Use an explicitly linked transcript or the RSS `podcast:transcript` tag. This is the preferred outcome. |
| 3 | Official YouTube URL | Retrieve a published caption track without downloading audio. Manual caption tracks are preferred over generated ones. |
| 4 | Local faster-whisper | Only runs when `--transcribe` is passed and the prior stages produce no usable transcript. |

The script writes `result.json` for provenance and, when text is found/generated, a readable Markdown file. `source_kind` is always one of `publisher_rss`, `publisher_website`, `youtube_manual`, `youtube_generated`, `local_faster_whisper`, or `unresolved`.

## Install

Use your existing faster-whisper environment if possible. Otherwise create a virtual environment and install the core packages:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install `yt-dlp` only if you want the optional final route that extracts audio from a supplied, permitted official YouTube URL:

```bash
pip install yt-dlp
```

## Typical use

The safest Podcast Addict invocation gives the resolver the canonical RSS feed and, where known, the official YouTube upload:

```bash
python podcast_resolver.py \
  'https://podcastaddict.com/encore-heureux/episode/223501658' \
  --feed-url 'https://YOUR-PUBLISHER.example/podcast.rss' \
  --youtube-url 'https://youtu.be/-V_9fKvEkn0' \
  --language fr \
  --output-dir results/aidants
```

The command above **does not transcribe audio**. It stops with a publisher or YouTube transcript when one exists, or exits with code `2` and a structured `unresolved` result.

To allow the final local fallback, add `--transcribe`:

```bash
python podcast_resolver.py URL \
  --feed-url RSS_URL \
  --language fr \
  --transcribe \
  --whisper-model large-v3 \
  --vocabulary-hint 'Camille Teste; Vincent Valinducq; Binge Audio' \
  --output-dir results/episode
```

If the only authorized audio source you choose is a supplied official YouTube URL, also add `--allow-youtube-audio`. This is deliberately an explicit consent flag.

## How the key parts work

The RSS implementation parses XML directly so an episode-level `podcast:transcript` tag can expose publisher-provided HTML, text, WebVTT, JSON, or SRT resources. A successful asset is written as publisher-provided text; it is never overwritten by faster-whisper.

The YouTube step uses `youtube-transcript-api` only to inspect and retrieve available caption tracks. It first prefers the selected language’s manually created track, then a generated one. Captions may be absent or access can be blocked, which is reported as a normal fallback condition.

The final `transcribe_locally()` function is intentionally small. Replace its `WhisperModel(...)` options with the device, compute type, VAD parameters, batch mode, model cache, and diarization procedure used by your existing faster-whisper setup.

## Extension points you should implement

| Function/area | Why it is incomplete | Suggested next change |
|---|---|---|
| `inspect_podcast_addict()` | Podcast Addict may not reveal the canonical feed to a basic HTTP client and download links can be transient. | Add a browser-rendering or a Podcast Index/publisher lookup resolver, then set `Episode.rss_url` and `Episode.website_url`. |
| `inspect_generic_episode_page()` | Generic HTML cannot reliably tell a full transcript from arbitrary show notes. | Add site adapters for your most-used publishers, matching their stable transcript selectors/URLs. |
| `choose_rss_episode()` | It scores title, show, and duration, but dates and external GUIDs are not yet used. | Add date tolerance, publisher identifiers, and a manual review state for scores below your threshold. |
| YouTube discovery | The skeleton checks a **known** official YouTube URL only. | Implement an official-channel allowlist or a YouTube search adapter that requires a title/date/channel-confidence threshold. |
| JSON transcript normalization | Podcast transcript JSON has no single universal structure. | Add normalizers for hosts you use, and retain the original response in `*.source.txt`. |

## Safety and data retention

The resolver treats a transcript URL as public data but does not automatically archive full audio. Temporary audio downloaded for local transcription is held in a temporary directory and removed at completion. Do not enable the final audio stage unless you have the right to download and process the selected source.

## Quick manual test sequence

1. Run the script with a direct RSS feed that contains an episode with `podcast:transcript`; confirm `source_kind` is `publisher_rss`.
2. Run with a known YouTube URL that has captions; confirm `source_kind` is `youtube_manual` or `youtube_generated`.
3. Run a known no-caption/no-transcript episode without `--transcribe`; confirm the result is `unresolved`.
4. Repeat with `--transcribe` and your local configuration; confirm `source_kind` is `local_faster_whisper`.

## References

[Podcast Namespace: transcript tag](https://podcasting2.org/docs/podcast-namespace/tags/transcript) describes the episode-level RSS asset this resolver checks first. [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) documents the caption retrieval component. [faster-whisper](https://github.com/SYSTRAN/faster-whisper) documents the local transcription engine.
