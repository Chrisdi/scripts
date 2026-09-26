# A Practical Workflow for Podcast Metadata and Transcripts

**Prepared by Manus AI**  
**Date:** 12 August 2026

## Recommendation in brief

Yes—this is feasible, but it should be treated as a **source-resolution problem first** and a transcription problem second. The most reliable workflow is to start from a Podcast Addict episode URL, resolve the original RSS feed and publisher resources, then look for an existing transcript in the feed or on the official site. Only if those sources fail should the workflow try a matching official YouTube upload, a cloud speech-to-text service, or local transcription.

> **Recommended default:** preserve the publisher’s transcript whenever it exists; otherwise use local `faster-whisper` for a free, privacy-preserving fallback. Use a cloud API such as Groq only as an opt-in speed fallback for audio that you are permitted to send to a third party.

The Podcast Addict and YouTube URLs supplied are a useful illustration. Podcast Addict identifies the show, episode, description, publication date, duration, publisher/host context, and a download route, but does not show a transcript or a publisher episode URL. The matching official Binge Audio YouTube video is easy to identify, but its current player reports that captions are unavailable. Therefore, for this episode, the correct automated path is **RSS/publisher lookup → no transcript found → use the authorized audio source for transcription**, not “YouTube transcript.” [1] [2]

| Source | What it is good for | Reliability for a full transcript | Recommended role |
|---|---|---:|---|
| Original RSS feed | Canonical episode identity, enclosure URL, and standardized transcript tags | Very high when the episode exposes `podcast:transcript` | **First choice** |
| Publisher episode page | Human-readable show notes, embedded text, speakers, chapters, direct transcript links | High, but site-specific | **Second choice** |
| Official YouTube upload | Existing captions/subtitles and a convenient matching audio/video source | High only when a caption track is actually available | **Third choice** |
| Apple Podcasts transcript | Accessible in Apple’s client for many episodes/languages | Useful for manual reading, not a stable extraction dependency | Manual fallback only |
| Cloud speech-to-text | Fast transcript generation with timestamps | Good, subject to audio and service limits | Opt-in fallback |
| Local speech-to-text | Free at marginal cost, offline, and reproducible | Good; dependent on hardware and post-editing | **Preferred final fallback** |

## Why the RSS feed should come first

Podcasting’s `podcast:transcript` element is specifically designed to link an episode to a transcript or captions file. It can expose one or more files in formats including plain text, HTML, WebVTT, JSON, and SRT, with optional language and caption semantics. When it is present in the matched RSS `<item>`, the workflow can download and normalize the transcript directly rather than generating a new, potentially inferior version. [3]

Apple’s podcast ecosystem also recognizes the RSS transcript tag, and Apple produces transcripts for supported languages—including French—for listening in its application. However, Apple describes this as an end-user/app experience and does not provide a documented public mechanism for exporting a full transcript for arbitrary third-party shows. It is therefore a valuable manual check, not a safe cornerstone for automation. [4]

A resolver should first obtain or discover the original feed. Podcast Addict pages are suitable input pages, but a basic non-browser HTTP fetch of the supplied example returned no usable HTML in testing, while its browser-rendered page contained the metadata and download link. The implementation should therefore support a normal HTTP request **and** a browser-rendered/manual fallback; it must not assume that every Podcast Addict page is server-scrapeable. Avoid treating a temporary download token as a permanent podcast identity.

## The recommended resolution pipeline

The following sequence balances correctness, speed, cost, and respect for original publication sources. It deliberately separates **discovery** from **transcription**, so an expensive or privacy-sensitive transcription happens only when needed.

| Stage | Action | Save | Stop condition |
|---|---|---|---|
| 1. Ingest | Accept a Podcast Addict, publisher, RSS, YouTube, or direct-audio URL. Canonicalize it and retain the original URL. | Input URL and retrieval timestamp | Never stop |
| 2. Extract episode facts | Capture title, podcast name, description, date, duration, artwork, hosting/publisher clues, download link, and any outbound links. | A structured episode record | Continue |
| 3. Resolve canonical feed | Look for a feed URL on the page/site; otherwise search a podcast index using the show title and then match the episode. | Feed URL, RSS item GUID, enclosure URL | Continue |
| 4. Match carefully | Score candidates using normalized title, show, date, duration, description keywords, and—where legitimate—the audio URL/hash. | Candidate scores and reason | Require review below a confidence threshold |
| 5. Find an existing transcript | Parse `podcast:transcript`; inspect the publisher page for transcript/captions/show-note links; convert HTML/VTT/SRT/JSON to a common format. | Source URL, transcript type, language, text, timecodes | Stop if a satisfactory transcript is found |
| 6. Check official YouTube | Search only the official channel or a strongly matched upload. Retrieve a caption transcript only when a real caption track is available. | Video ID, channel, caption status, transcript if available | Stop if successful |
| 7. Transcribe authorized audio | Fetch the RSS enclosure or approved download route, transcribe, and quality-flag uncertain regions. | Generated transcript, timecodes, engine/model/version | Stop |
| 8. Deliver and retain | Return metadata, transcript, provenance, confidence, and deep links. Keep audio only as long as necessary. | JSON plus readable Markdown/VTT/SRT | Completed |

A podcast-index service can improve step 3 when the feed is not visible on the input page. The Podcast Index API documentation describes feed search based on title, author, or owner; it should be used only to discover and validate the canonical feed, not as a substitute for confirming the episode itself. [5]

### Matching rules matter

Never match a YouTube video or an RSS item by title alone. In the supplied example, Podcast Addict shows **“Qui aide les aidant•es ?”** and 58 minutes, while the official YouTube page shows **“Qui pour aider les aidant·es ?”** and 55:32. The description, show identity, subject, guest, release timing, and publisher all support a match, but the title and duration differ. [1] [2]

A practical scoring rule is to accept a candidate automatically only when the show is an exact/near-exact match, the publication dates are close, the title terms substantially overlap, and duration is plausibly close. If there is a conflict—such as different guests, an ambiguous title, or a large duration difference—the tool should display its candidate links and request confirmation rather than returning a confidently wrong transcript.

## YouTube: useful, but conditional

YouTube is worth checking because subtitle tracks are often already timestamped, searchable, and free to access in the player. But the system must first confirm that a caption track is available. YouTube states that automatic captions may be absent or delayed, and can be inaccurate because of pronunciation, accents, dialects, poor audio, overlapping speakers, or other complexity. [6]

For the Binge Audio example, the visible player reports **“Subtitles/closed captions unavailable.”** The correct result for this branch is therefore `captions_unavailable`, not an empty transcript and not an attempt to infer one from the description. This should fall through to authorized-audio transcription. [2]

Implementing YouTube extraction should use an established caption-retrieval component with defensive error handling, and should record the caption language and whether it is creator-provided or auto-generated when that information is available. It should not rely on undocumented scraping as the only path, and it should never bypass access controls or download material contrary to the relevant terms or rights.

## Cloud transcription: a useful opt-in fallback

A cloud service is an effective last-mile convenience tool, but it is not truly “free forever.” Free allocations, trials, file-size limits, and rate limits change. Build the cloud provider behind a small adapter so that it can be enabled, disabled, or replaced without changing the rest of the workflow.

| Option | Verified capabilities | Practical implication |
|---|---|---|
| **Groq Speech-to-Text** | OpenAI-compatible transcription endpoint; multilingual Whisper models; direct file or URL input; text, JSON, and timestamped `verbose_json` responses. The free tier documentation specifies a 25 MB direct-upload cap, while URLs can be supplied for larger audio; the published base limits show 7,200 audio seconds per hour and 28,800 per day for each listed Whisper model. [7] [8] | Good for fast, occasional use. A 55-minute MP3 may exceed 25 MB, so compress/chunk it or use a permitted stable audio URL. Obtain the user’s consent before sending private audio externally. |
| **Deepgram** | The pricing page currently advertises a no-card $200 credit and lists multilingual STT plus optional speaker diarization. It also describes an EU endpoint. [9] | Good for evaluation and features such as diarization, but this is introductory credit rather than a durable zero-cost tier. Check current pricing before production use. |
| **Self-hosted/local engine** | No per-minute vendor charge and no audio transfer to a third party. [10] [11] | Prefer where privacy, predictable cost, or frequent processing matter more than immediate speed. |

For high-quality cloud output, request timestamped JSON rather than plain text, pass `fr` when the language is known, and provide a short vocabulary prompt with guest names, show name, institutions, and uncommon terms. Groq documents language, prompt, timestamp granularity, and response-format controls for this purpose. [7]

## Local transcription should not be dismissed as impractical

Local transcription is the most dependable genuinely free fallback after the initial model download. It also avoids sending private or unpublished audio to a service provider. The better framing is not “slow last resort,” but **privacy-first, unlimited fallback**.

`faster-whisper` is a practical choice for a personal automation. It supports CPU `int8` execution, GPU modes, voice-activity filtering, segment-level and word-level timestamps, and Whisper large-v3 models. Its project benchmarks show meaningful efficiency improvements over the reference implementation, though actual performance depends strongly on the user’s hardware, model size, and settings. [10]

For a simple, portable command-line path, `whisper.cpp` supports CPU-only inference and multiple hardware accelerators. Its documentation also provides a practical MP3-to-16 kHz mono WAV conversion approach and supports timestamped output. [11]

For multi-speaker podcasts where readable speaker turns matter, WhisperX adds word-level alignment and speaker diarization. It supports French alignment models, but its documentation warns that overlapping speech is difficult and diarization is not perfect; speaker labels should therefore be treated as `SPEAKER_00`, `SPEAKER_01` unless names are manually confirmed from the episode description. [12]

| Need | Suggested local configuration | Output |
|---|---|---|
| Fast, no-frills French transcript | `faster-whisper`, `small` or `medium`, CPU `int8`, `language=fr` | Markdown/text plus segment timecodes |
| Better accuracy for a valuable episode | `faster-whisper`, `large-v3`, GPU if available, vocabulary prompt | Transcript plus word/segment timestamps |
| Speaker turns and subtitle-quality timing | WhisperX with French alignment and diarization | JSON plus SRT/VTT; review speaker labels |
| Minimal-dependency portable setup | `whisper.cpp` with a multilingual model | Text/SRT/VTT with timestamps |

## A useful output contract

The tool should return **provenance as well as text**. This makes it clear whether the transcript is publisher-provided, caption-derived, or machine-generated, and enables a future re-run when a better source appears.

```json
{
  "input_url": "https://podcastaddict.com/...",
  "podcast": "Encore heureux",
  "episode_title": "Qui aide les aidant·es ?",
  "published_at": "2026-05-09",
  "duration_seconds": 3480,
  "canonical_feed_url": "https://…",
  "audio_url": "https://…",
  "transcript": {
    "status": "generated",
    "source_kind": "local_faster_whisper",
    "language": "fr",
    "timecoded": true,
    "speaker_labels": "unverified",
    "source_url": null,
    "model": "large-v3",
    "generated_at": "2026-08-12T…Z"
  },
  "match_confidence": 0.94,
  "warnings": ["YouTube captions unavailable"]
}
```

Store the human-readable transcript as Markdown and the timed version as VTT or SRT, alongside a JSON metadata record. Cache successful RSS/publisher/YouTube lookups, but do not retain audio by default. A source URL, retrieval time, model version, and transcript type are sufficient for reproducibility while minimizing unnecessary storage.

## What I would build

For your use case, I would build a small **“paste a podcast URL” resolver** with a transparent status page. It would perform the first five steps automatically and return either a verified publisher transcript or a clearly labelled fallback choice. When no source transcript exists, it would offer: **“Transcribe locally”** as the default and **“Use cloud transcription”** only after displaying the provider, file transfer implications, and current quota/expected cost.

The initial version should be intentionally conservative: one episode at a time, official sources only, no bulk downloading, no permanent audio archive, and a manual confirmation step for ambiguous matches. This will be much more reliable than trying to force every Podcast Addict link through a single transcript service.

## References

[1]: https://podcastaddict.com/encore-heureux/episode/223501658 "Podcast Addict — Qui aide les aidant•es ?"
[2]: https://www.youtube.com/watch?v=-V_9fKvEkn0 "Binge Audio — Qui pour aider les aidant·es ?"
[3]: https://podcasting2.org/docs/podcast-namespace/tags/transcript "Podcast Namespace — podcast:transcript"
[4]: https://podcasters.apple.com/support/5316-transcripts-on-apple-podcasts "Apple Podcasters — Transcripts on Apple Podcasts"
[5]: https://podcastindex-org.github.io/docs-api/ "Podcast Index — API documentation"
[6]: https://support.google.com/youtube/answer/6373554 "YouTube Help — Automatic captions"
[7]: https://console.groq.com/docs/speech-to-text "Groq — Speech to Text"
[8]: https://console.groq.com/docs/rate-limits "Groq — Rate limits"
[9]: https://deepgram.com/pricing "Deepgram — Pricing"
[10]: https://github.com/SYSTRAN/faster-whisper "SYSTRAN — faster-whisper"
[11]: https://github.com/ggml-org/whisper.cpp "ggml-org — whisper.cpp"
[12]: https://github.com/m-bain/whisperX "WhisperX — Word-level timestamps and diarization"
