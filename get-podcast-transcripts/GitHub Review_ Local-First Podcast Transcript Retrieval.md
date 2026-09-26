# GitHub Review: Local-First Podcast Transcript Retrieval

**Prepared by Manus AI**  
**Date:** 12 August 2026

## Executive conclusion

I found **one close end-to-end project**—[`timf34/podscript`](https://github.com/timf34/podscript)—but no mature project that fully implements your desired chain: **Podcast Addict episode URL → canonical publisher/RSS episode → publisher transcript asset → official YouTube captions → local faster-whisper**.

The strongest solution is therefore a **small local-first resolver built from well-maintained components**, rather than adopting an all-in-one project wholesale. In particular, use [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) to retrieve an already-published YouTube caption track, [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) only when audio must be fetched for the existing local faster-whisper setup, and a standard RSS parser plus a small `podcast:transcript` extractor for the publisher-first stage. [1] [2] [3]

> **Do not start transcription until the resolver has established that no publisher-provided transcript and no usable official YouTube caption track exists.** This is the principal feature missing from the closest all-in-one candidates.

| Recommendation | Why |
|---|---|
| **Build a small adapter around your existing faster-whisper setup.** | It keeps your current model/settings and adds only source discovery and transcript preference. |
| **Borrow the input-resolution design of Podscript, not its full workflow.** | It already handles Apple Podcast links, direct RSS feeds, and YouTube URLs, but it immediately moves to transcription rather than harvesting existing transcripts. [4] |
| **Use `youtube-transcript-api` for the YouTube branch.** | It lists tracks, differentiates manual from auto-generated captions, supplies timestamps, supports language preference, and exports common formats. [1] |
| **Use `yt-dlp` only as an authorized-audio fallback.** | It is a very widely adopted, actively maintained extractor, but it is not a podcast-transcript resolver. [2] |

## Best-fit projects

| Project | Fit to your workflow | Evidence of quality as checked | Recommendation |
|---|---|---|---|
| [`timf34/podscript`](https://github.com/timf34/podscript) | The closest command-line foundation. Accepts Apple Podcasts links, RSS feeds, and YouTube URLs; it can run local faster-whisper and optionally diarize speakers. [4] | MIT licensed; 46 stars; last code push recorded 17 Feb 2026. [5] | **Best prototype / fork candidate**, but it needs important additions. |
| [`jdepoix/youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) | Exactly fits the “YouTube if a transcript exists” stage. It can enumerate tracks, prefer manual captions, retrieve auto-generated captions, preserve timings, and render JSON/VTT/SRT/text. [1] | MIT licensed; ~8.0k stars; last code push recorded 19 May 2026. [6] | **Use directly** as a component. |
| [`yt-dlp/yt-dlp`](https://github.com/yt-dlp/yt-dlp) | Reliable metadata and authorized media/subtitle retrieval for YouTube and many other sites. [2] | ~184k stars; last code push recorded 4 Aug 2026; regular stable/nightly releases. [7] | **Use directly**, but only after prior transcript checks fail. |
| [`wendy7756/podcast-transcriber`](https://github.com/wendy7756/podcast-transcriber) | A small web interface with RSS/feed discovery, direct audio, and local faster-whisper. [8] | 247 stars; 30 forks; last code push recorded 12 Apr 2026. The repository’s license is marked `NOASSERTION`, despite its README referring to Apache 2.0. [9] | **Useful UI reference**, but not my first foundation because it includes cloud LLM integration and needs licensing clarification. |
| [`cfinke/Dropseeker`](https://github.com/cfinke/Dropseeker) | Downloads a feed, transcribes episodes, searches transcripts, and extracts matching clips. [10] | 8 stars; last code push recorded 3 Dec 2025. [11] | **Nice post-transcription idea**, not a base for this resolver. |
| [`mattdanielmurphy/apple-podcast-transcript-extractor`](https://github.com/mattdanielmurphy/apple-podcast-transcript-extractor) | Mac-only tool that exports Apple Podcasts TTML transcript cache after an episode has been downloaded in Apple Podcasts. [12] | 94 stars; last code push recorded 13 Jan 2026; no stated license in GitHub metadata. [13] | **Optional manual Mac fallback**, not a portable automation dependency. |

## The closest project: Podscript

`podscript` is unusually close to the local-first portion of your request. It resolves an Apple Podcasts episode URL to a podcast RSS feed, can list/search/select episodes from RSS, accepts YouTube URLs, downloads audio, and invokes local faster-whisper when `--local` is selected. It can output Markdown with timestamps and optionally runs pyannote diarization when a Hugging Face token is supplied. [4]

However, its public source currently parses RSS enclosures for audio and then transcribes. It does **not** parse the episode’s `podcast:transcript` element, does **not** inspect publisher show notes for transcript links, does **not** accept Podcast Addict URLs, and—when given YouTube—downloads audio for transcription rather than first attempting to retrieve the existing caption track. [14]

That means Podscript is worth a quick local trial, but not as-is if your main objective is minimizing unnecessary transcription. If you like its CLI output and episode-selection behavior, a fork or a wrapper would be quite small: insert a “published transcript resolver” before its `transcribe()` call, and make the YouTube caption branch precede `download_youtube_audio()`.

## The recommended local stack

The stack below is deliberately modest. It adds just enough code to cover your missing first stages and preserves your existing transcription environment.

| Pipeline stage | Local component | Behaviour |
|---|---|---|
| Accept input | A small Python CLI wrapper | Accept Podcast Addict, RSS, publisher, Apple Podcasts, YouTube, or local audio URLs. Persist the original URL. |
| Resolve canonical episode | `requests`/Playwright as needed, `feedparser`, and optionally a podcast-index lookup | Extract metadata from an input page, find the canonical RSS feed, and match the RSS item using normalized title/date/duration/description. |
| Use publisher transcript | Custom `podcast:transcript` parser plus publisher-page link checks | Return transcript assets in HTML, text, JSON, VTT, or SRT before touching audio. The standard permits a transcript URL, MIME type, language, and multiple representations. [3] |
| Use YouTube captions | `youtube-transcript-api` | First list tracks. Prefer French manual captions; otherwise French generated captions; then consider an explicitly requested translation. Store the original language/type and timestamps. [1] |
| Retrieve audio only if needed | RSS enclosure directly, or `yt-dlp` for a permitted official YouTube source | Fetch only after the prior stages return no usable text. Ensure source usage is authorized. [2] |
| Transcribe locally | Your present faster-whisper setup | Generate the transcript, preserve timestamps, label output as machine-generated, and remove temporary audio by default. |

This is a **better fit than Podscript alone**, because existing transcripts and captions are returned with clear provenance. The source type should be part of every result: `rss_publisher`, `publisher_page`, `youtube_manual`, `youtube_generated`, or `local_faster_whisper`.

## One likely implementation shape

The resolver can be a small command-line program with a single output record per request. It need not be a server initially.

```text
paste URL
  │
  ├─ Podcast Addict / publisher / Apple / RSS → resolve canonical feed and episode
  │                                               │
  │                                               ├─ podcast:transcript found → normalize and return
  │                                               ├─ publisher transcript link found → normalize and return
  │                                               └─ none
  │
  ├─ official YouTube candidate → list caption tracks
  │                                 │
  │                                 ├─ captions found → return SRT/VTT/Markdown
  │                                 └─ none
  │
  └─ authorized enclosure/video audio → existing faster-whisper → return generated transcript
```

The matching component should conservatively score the podcast/show name, normalized episode title, date, duration, and guest/description terms. Your earlier example demonstrates why: Podcast Addict and YouTube use slightly different titles and durations for the same episode. An ambiguous match should be presented for confirmation rather than silently transcribed.

## Important practical cautions

`youtube-transcript-api` uses an undocumented web-client interface. Its README explicitly notes that it can stop working if YouTube changes implementation and that heavy/self-hosted usage can encounter IP blocks. For individual, low-volume local use it is still the best direct component I found, but the code should treat errors such as unavailable captions and request blocks as normal fall-through conditions—not failures that halt the pipeline. [1]

`yt-dlp` is substantial and changes rapidly because platform extractors break as websites evolve. Keep it current; its own project recommends its nightly channel for regular users needing current site compatibility. [2]

The Apple extractor is technically interesting but should stay an optional, manual Mac route. It depends on local Podcasts.app cache/database layout, requires the episode to be downloaded in Apple Podcasts first, and is not suited to a general URL resolver. [12]

## Practical next step

I would start with **a small wrapper, not a full fork**:

1. Point it at your existing faster-whisper command/function.
2. Add RSS resolution and `podcast:transcript` handling.
3. Add `youtube-transcript-api` as a no-audio YouTube caption check.
4. Add Podcast Addict URL extraction and a manual confirmation option for uncertain canonical-feed matches.
5. Only then add a simple local web interface if you find yourself using it frequently.

If you prefer a working CLI immediately, trial `podscript` locally in `--local` mode for direct RSS, Apple Podcasts, and YouTube URLs. Treat it as a baseline for output and source resolution, while reserving a small wrapper for the publisher-transcript and YouTube-caption-first logic that it lacks.

## References

[1]: https://github.com/jdepoix/youtube-transcript-api "jdepoix/youtube-transcript-api — README"
[2]: https://github.com/yt-dlp/yt-dlp "yt-dlp/yt-dlp — README"
[3]: https://podcasting2.org/docs/podcast-namespace/tags/transcript "Podcast Namespace — podcast:transcript"
[4]: https://github.com/timf34/podscript "timf34/podscript — README"
[5]: https://api.github.com/repos/timf34/podscript "GitHub API — timf34/podscript repository metadata"
[6]: https://api.github.com/repos/jdepoix/youtube-transcript-api "GitHub API — jdepoix/youtube-transcript-api repository metadata"
[7]: https://api.github.com/repos/yt-dlp/yt-dlp "GitHub API — yt-dlp/yt-dlp repository metadata"
[8]: https://github.com/wendy7756/podcast-transcriber "wendy7756/podcast-transcriber — README"
[9]: https://api.github.com/repos/wendy7756/podcast-transcriber "GitHub API — wendy7756/podcast-transcriber repository metadata"
[10]: https://github.com/cfinke/Dropseeker "cfinke/Dropseeker — README"
[11]: https://api.github.com/repos/cfinke/Dropseeker "GitHub API — cfinke/Dropseeker repository metadata"
[12]: https://github.com/mattdanielmurphy/apple-podcast-transcript-extractor "mattdanielmurphy/apple-podcast-transcript-extractor — README"
[13]: https://api.github.com/repos/mattdanielmurphy/apple-podcast-transcript-extractor "GitHub API — repository metadata"
[14]: https://raw.githubusercontent.com/timf34/podscript/main/podscript.py "Podscript source — input handling, RSS parsing, and transcription path"
