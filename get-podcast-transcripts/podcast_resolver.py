#!/usr/bin/env python3
"""Local-first podcast transcript resolver.

Priority order
--------------
1. Read input metadata, including a Podcast Addict episode page when supplied.
2. Look for a publisher-provided transcript on the episode site or in its RSS item
   (`podcast:transcript`).
3. Check a supplied official YouTube URL for an existing caption track.
4. Only if no published text is available, download an authorised audio enclosure
   and run local faster-whisper.

This is intentionally a *skeleton*. The generic RSS and transcript paths are
implemented, but Podcast Addict-to-publisher/RSS resolution is host-dependent.
When it cannot discover the canonical feed automatically, pass --feed-url.

The default behaviour is non-destructive: it performs metadata/transcript checks
only. Add --transcribe to permit the final audio-download + local transcription
fallback.

Example
-------
python podcast_resolver.py \
  'https://podcastaddict.com/encore-heureux/episode/223501658' \
  --feed-url 'https://publisher.example/feed.xml' \
  --youtube-url 'https://youtu.be/-V_9fKvEkn0' \
  --language fr \
  --output-dir results/aidants

Dependencies
------------
pip install requests beautifulsoup4 feedparser youtube-transcript-api
# Only for the final local fallback:
pip install faster-whisper
# Optional, only when YouTube audio must be downloaded for local transcription:
pip install yt-dlp

The program returns structured provenance in result.json. A successful published
transcript is never silently replaced with a generated transcript.
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "LocalPodcastTranscriptResolver/0.1 (personal, local use)"
REQUEST_TIMEOUT_SECONDS = 25
MAX_TRANSCRIPT_BYTES = 8_000_000
PODCAST_NS = "https://podcastindex.org/namespace/1.0"
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


class SourceKind(str, Enum):
    PUBLISHER_RSS = "publisher_rss"
    PUBLISHER_WEBSITE = "publisher_website"
    YOUTUBE_MANUAL = "youtube_manual"
    YOUTUBE_GENERATED = "youtube_generated"
    LOCAL_FASTER_WHISPER = "local_faster_whisper"
    UNRESOLVED = "unresolved"


@dataclass
class TranscriptAsset:
    """A transcript/captions file declared by the publisher or feed."""

    url: str
    mime_type: str = ""
    language: str = ""
    relation: str = ""
    discovered_from: str = ""


@dataclass
class Episode:
    """Normalized facts collected from an input page or an RSS item."""

    title: str = ""
    podcast_name: str = ""
    description: str = ""
    published: str = ""
    duration_seconds: Optional[int] = None
    guid: str = ""
    website_url: str = ""
    rss_url: str = ""
    audio_url: str = ""
    youtube_url: str = ""
    transcript_assets: list[TranscriptAsset] = field(default_factory=list)
    source_url: str = ""


@dataclass
class TranscriptResult:
    status: str
    source_kind: SourceKind
    text: str = ""
    raw_text: str = ""
    transcript_url: str = ""
    language: str = ""
    is_timecoded: bool = False
    is_machine_generated: Optional[bool] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ResolverResult:
    input_url: str
    checked_at: str
    episode: Episode
    transcript: TranscriptResult
    warnings: list[str] = field(default_factory=list)


class ResolverError(RuntimeError):
    """An expected source-resolution error; catch and report instead of crashing."""


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def fetch(url: str, *, accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8") -> requests.Response:
    """Fetch a public resource with a clear user agent and bounded timeout."""
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def normalize(text: str) -> str:
    """Normalize titles for conservative episode matching."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def first_nonempty(*values: Optional[str]) -> str:
    return next((value.strip() for value in values if value and value.strip()), "")


def parse_duration(value: str | int | float | None) -> Optional[int]:
    """Handle seconds or HH:MM:SS duration strings without assuming a format."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    value = str(value).strip()
    if value.isdigit():
        return int(value)
    parts = value.split(":")
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(float(part))
        return seconds
    except ValueError:
        return None


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def is_podcast_addict_url(url: str) -> bool:
    return "podcastaddict.com" in (urlparse(url).hostname or "").lower()


def looks_like_feed(url: str) -> bool:
    suffix = urlparse(url).path.lower()
    return suffix.endswith((".rss", ".xml", ".atom")) or "/feed" in suffix or "/rss" in suffix


def youtube_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return query_id
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
        return parts[1]
    return ""


def choose_language(assets: Iterable[TranscriptAsset], preferred_language: str) -> Optional[TranscriptAsset]:
    """Prefer the requested language, then a non-caption/plain-text asset."""
    candidates = list(assets)
    if not candidates:
        return None

    preferred_language = (preferred_language or "").lower()

    def score(asset: TranscriptAsset) -> tuple[int, int, int]:
        language_match = int(bool(preferred_language) and asset.language.lower().startswith(preferred_language))
        readable = int(asset.mime_type.lower() in {"text/plain", "text/html", "text/vtt", "application/x-subrip"})
        non_captions = int(asset.relation.lower() != "captions")
        return language_match, readable, non_captions

    return max(candidates, key=score)


# ---------------------------------------------------------------------------
# Input-page inspection: Podcast Addict and generic publisher pages
# ---------------------------------------------------------------------------


def meta_content(soup: BeautifulSoup, *properties: str) -> str:
    for prop in properties:
        element = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if element and element.get("content"):
            return clean_text(element["content"])
    return ""


def extract_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"])
        label = clean_text(anchor.get_text(" ", strip=True))
        links.append((href, label))
    return links


def inspect_podcast_addict(url: str) -> tuple[Episode, list[str]]:
    """Extract only stable page hints; do not treat signed download tokens as identities."""
    warnings: list[str] = []
    response = fetch(url)
    soup = BeautifulSoup(response.text, "html.parser")
    links = extract_links(soup, response.url)

    title = meta_content(soup, "og:title", "twitter:title")
    h1 = soup.find("h1")
    if h1:
        title = first_nonempty(clean_text(h1.get_text(" ", strip=True)), title)

    show_link = soup.select_one("#episode-podcast-link")
    podcast_name = clean_text(show_link.get_text(" ", strip=True)) if show_link else ""
    description = meta_content(soup, "og:description", "description")

    # This route may be a short-lived signed wrapper. It is a last-resort audio
    # hint only and should be re-resolved immediately before an authorised download.
    download_hint = next((href for href, _ in links if "episode_download.php" in href), "")

    candidate = Episode(
        title=title,
        podcast_name=podcast_name,
        description=description,
        audio_url=download_hint,
        source_url=response.url,
    )
    if not title:
        warnings.append("Podcast Addict page did not expose a usable title to this HTTP client.")
    warnings.append(
        "Podcast Addict did not expose a canonical publisher/RSS URL. Supply --feed-url "
        "or implement a host-specific resolver if feed discovery is required."
    )
    return candidate, warnings


def inspect_generic_episode_page(url: str) -> tuple[Episode, list[str]]:
    """Inspect a publisher page for RSS links and transcript links.

    This intentionally accepts only explicitly labelled transcript/caption links;
    it does not mistake regular episode show notes for a full transcript.
    """
    response = fetch(url)
    soup = BeautifulSoup(response.text, "html.parser")
    links = extract_links(soup, response.url)

    rss_url = ""
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel", []))
        mime_type = (link.get("type") or "").lower()
        if "alternate" in rel and ("rss" in mime_type or "atom" in mime_type):
            rss_url = urljoin(response.url, link["href"])
            break
    if not rss_url:
        rss_url = next((href for href, label in links if looks_like_feed(href) or "rss" in label.lower()), "")

    transcript_assets: list[TranscriptAsset] = []
    transcript_pattern = re.compile(r"\b(transcript|transcription|captions?|sous[- ]?titres?)\b", re.I)
    for href, label in links:
        if transcript_pattern.search(label) or transcript_pattern.search(href):
            transcript_assets.append(
                TranscriptAsset(
                    url=href,
                    mime_type="text/html" if href.lower().endswith((".html", ".htm")) else "",
                    discovered_from=response.url,
                )
            )

    audio_url = meta_content(soup, "og:audio", "twitter:player:stream")
    episode = Episode(
        title=meta_content(soup, "og:title", "twitter:title"),
        description=meta_content(soup, "og:description", "description"),
        website_url=response.url,
        rss_url=rss_url,
        audio_url=audio_url,
        transcript_assets=transcript_assets,
        source_url=response.url,
    )
    return episode, []


# ---------------------------------------------------------------------------
# RSS parsing and canonical-episode matching
# ---------------------------------------------------------------------------


def parse_rss(feed_url: str) -> tuple[str, list[Episode]]:
    """Parse RSS directly so `podcast:transcript` attributes are preserved."""
    response = fetch(feed_url, accept="application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise ResolverError(f"Could not parse RSS XML: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        # Basic Atom fallback: feedparser still gives useful entries, but the
        # Podcasting 2.0 transcript element is usually RSS-based.
        try:
            import feedparser
        except ImportError as exc:
            raise ResolverError("Install feedparser to use Atom-feed fallback parsing.") from exc
        parsed = feedparser.parse(response.content)
        title = getattr(parsed.feed, "title", "")
        return title, []

    podcast_name = channel.findtext("title", default="").strip()
    episodes: list[Episode] = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        transcript_assets: list[TranscriptAsset] = []
        for transcript in item.findall(f"{{{PODCAST_NS}}}transcript"):
            transcript_url = transcript.attrib.get("url", "").strip()
            if transcript_url:
                transcript_assets.append(
                    TranscriptAsset(
                        url=transcript_url,
                        mime_type=transcript.attrib.get("type", ""),
                        language=transcript.attrib.get("language", ""),
                        relation=transcript.attrib.get("rel", ""),
                        discovered_from=response.url,
                    )
                )

        itunes_duration = item.findtext(f"{{{ITUNES_NS}}}duration", default="")
        episodes.append(
            Episode(
                title=item.findtext("title", default="").strip(),
                podcast_name=podcast_name,
                description=clean_text(item.findtext("description", default="")),
                published=first_nonempty(item.findtext("pubDate", default=""), item.findtext("date", default="")),
                duration_seconds=parse_duration(itunes_duration),
                guid=item.findtext("guid", default="").strip(),
                audio_url=(enclosure.attrib.get("url", "").strip() if enclosure is not None else ""),
                rss_url=response.url,
                transcript_assets=transcript_assets,
                source_url=response.url,
            )
        )
    return podcast_name, episodes


def candidate_score(target: Episode, candidate: Episode) -> float:
    """Conservative score; tune it for your library before auto-selecting at scale."""
    score = 0.0
    target_title = normalize(target.title)
    candidate_title = normalize(candidate.title)
    if target_title and candidate_title:
        if target_title == candidate_title:
            score += 0.70
        elif target_title in candidate_title or candidate_title in target_title:
            score += 0.50
        else:
            target_words = set(target_title.split())
            candidate_words = set(candidate_title.split())
            if target_words:
                score += 0.40 * len(target_words & candidate_words) / len(target_words)
    if target.podcast_name and normalize(target.podcast_name) == normalize(candidate.podcast_name):
        score += 0.15
    if target.duration_seconds and candidate.duration_seconds:
        difference = abs(target.duration_seconds - candidate.duration_seconds)
        if difference <= 120:
            score += 0.10
        elif difference <= 300:
            score += 0.05
    return min(score, 1.0)


def choose_rss_episode(target: Episode, episodes: list[Episode]) -> tuple[Optional[Episode], float]:
    if not episodes:
        return None, 0.0
    scored = [(candidate_score(target, episode), episode) for episode in episodes]
    score, best = max(scored, key=lambda item: item[0])
    return best, score


# ---------------------------------------------------------------------------
# Published-transcript retrieval and normalisation
# ---------------------------------------------------------------------------


def strip_caption_markup(raw_text: str) -> str:
    """Create readable plain text while retaining raw VTT/SRT separately."""
    lines: list[str] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.upper() == "WEBVTT" or "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(html.unescape(line))
    return "\n".join(lines).strip()


def download_transcript_asset(asset: TranscriptAsset, preferred_language: str) -> TranscriptResult:
    response = fetch(asset.url, accept="text/plain,text/html,text/vtt,application/json,application/x-subrip,*/*;q=0.5")
    if len(response.content) > MAX_TRANSCRIPT_BYTES:
        raise ResolverError("Transcript asset exceeds the configured safety limit.")

    content_type = (response.headers.get("content-type") or asset.mime_type).lower()
    raw_text = response.text
    if "html" in content_type or asset.url.lower().endswith((".html", ".htm")):
        text = clean_text(raw_text)
        timecoded = False
    elif "json" in content_type or asset.url.lower().endswith(".json"):
        # Keep source JSON in raw_text. Add a site-specific JSON parser here if
        # the publisher uses a known timed-transcript schema.
        try:
            payload = response.json()
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        except ValueError:
            text = raw_text
        timecoded = True
    else:
        text = strip_caption_markup(raw_text)
        timecoded = "vtt" in content_type or "subrip" in content_type or asset.url.lower().endswith((".vtt", ".srt"))

    if not text:
        raise ResolverError("Transcript asset was empty after normalisation.")
    return TranscriptResult(
        status="found",
        source_kind=SourceKind.PUBLISHER_RSS if asset.discovered_from.lower().endswith((".rss", ".xml")) else SourceKind.PUBLISHER_WEBSITE,
        text=text,
        raw_text=raw_text,
        transcript_url=response.url,
        language=asset.language or preferred_language,
        is_timecoded=timecoded,
        is_machine_generated=None,
        notes=[f"Publisher-declared asset: {asset.mime_type or content_type}"],
    )


def try_published_transcript(episode: Episode, language: str, warnings: list[str]) -> Optional[TranscriptResult]:
    asset = choose_language(episode.transcript_assets, language)
    if not asset:
        return None
    try:
        return download_transcript_asset(asset, language)
    except (requests.RequestException, ResolverError) as exc:
        warnings.append(f"Publisher transcript asset could not be retrieved: {exc}")
        return None


# ---------------------------------------------------------------------------
# YouTube caption stage
# ---------------------------------------------------------------------------


def captions_to_text(snippets: Iterable[object]) -> str:
    rows: list[str] = []
    for snippet in snippets:
        # youtube-transcript-api returns FetchedTranscriptSnippet objects in
        # recent versions and dicts in older examples.
        if isinstance(snippet, dict):
            start, text = float(snippet.get("start", 0)), str(snippet.get("text", ""))
        else:
            start, text = float(getattr(snippet, "start", 0)), str(getattr(snippet, "text", ""))
        minutes, seconds = divmod(int(start), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        rows.append(f"[{stamp}] {html.unescape(text).strip()}")
    return "\n".join(row for row in rows if row.strip())


def try_youtube_captions(youtube_url: str, language: str, warnings: list[str]) -> Optional[TranscriptResult]:
    """Use published YouTube tracks only; no audio download happens here."""
    video_id = youtube_video_id(youtube_url)
    if not video_id:
        warnings.append("Could not identify a YouTube video ID.")
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import CouldNotRetrieveTranscript
    except ImportError:
        warnings.append("Install youtube-transcript-api to enable the YouTube caption stage.")
        return None

    try:
        api = YouTubeTranscriptApi()
        tracks = api.list(video_id)
        language_preferences = [language] if language else []
        language_preferences += ["fr", "en"] if language not in {"fr", "en"} else []

        track = None
        generated = None
        for candidate in tracks:
            if candidate.language_code.lower().startswith(tuple(lang.lower() for lang in language_preferences)):
                if not candidate.is_generated:
                    track = candidate
                    break
                generated = generated or candidate
        track = track or generated
        if track is None:
            warnings.append("No matching YouTube caption track is available.")
            return None

        fetched = track.fetch()
        snippets = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
        text = captions_to_text(snippets)
        if not text:
            warnings.append("The selected YouTube caption track was empty.")
            return None
        return TranscriptResult(
            status="found",
            source_kind=SourceKind.YOUTUBE_GENERATED if track.is_generated else SourceKind.YOUTUBE_MANUAL,
            text=text,
            raw_text=json.dumps(snippets, ensure_ascii=False, indent=2),
            transcript_url=youtube_url,
            language=track.language_code,
            is_timecoded=True,
            is_machine_generated=bool(track.is_generated),
            notes=[f"YouTube caption track: {track.language} ({'generated' if track.is_generated else 'manual'})"],
        )
    except Exception as exc:  # Library error classes vary across releases.
        warnings.append(f"YouTube captions unavailable or could not be retrieved: {exc}")
        return None


# ---------------------------------------------------------------------------
# Local audio and faster-whisper final fallback
# ---------------------------------------------------------------------------


def download_authorised_audio(episode: Episode, work_dir: Path, allow_youtube_audio: bool) -> Path:
    """Download the feed enclosure, or optionally extract official YouTube audio.

    Ensure you have permission to download and process the selected audio. Do not
    use a transient Podcast Addict token as a long-term audio URL.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    if episode.audio_url and not is_youtube_url(episode.audio_url):
        response = fetch(episode.audio_url, accept="audio/*,*/*;q=0.8")
        suffix = Path(urlparse(response.url).path).suffix or ".audio"
        destination = work_dir / f"input{suffix}"
        destination.write_bytes(response.content)
        return destination

    if episode.youtube_url and allow_youtube_audio:
        executable = shutil.which("yt-dlp")
        if not executable:
            raise ResolverError("yt-dlp is required for optional YouTube audio extraction.")
        destination_template = str(work_dir / "input.%(ext)s")
        subprocess.run(
            [executable, "--no-playlist", "-x", "--audio-format", "mp3", "-o", destination_template, episode.youtube_url],
            check=True,
        )
        matches = list(work_dir.glob("input.*"))
        if matches:
            return matches[0]
        raise ResolverError("yt-dlp did not create an audio file.")

    raise ResolverError(
        "No stable authorised audio URL is available. Supply --feed-url so the RSS enclosure can be used, "
        "or set --allow-youtube-audio for a permitted official YouTube source."
    )


def transcribe_locally(audio_path: Path, *, model_name: str, language: str, vocabulary_hint: str) -> TranscriptResult:
    """Minimal faster-whisper integration; replace with your existing runner if preferred."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ResolverError("Install faster-whisper or replace transcribe_locally() with your existing runner.") from exc

    # Keep this intentionally simple. Point the constructor at your existing
    # model cache, device, compute type, VAD policy, and beam size as needed.
    model = WhisperModel(model_name, device="auto", compute_type="auto")
    segments, info = model.transcribe(
        str(audio_path),
        language=language or None,
        word_timestamps=False,
        vad_filter=True,
        initial_prompt=vocabulary_hint or None,
    )

    rows: list[str] = []
    for segment in segments:
        minutes, seconds = divmod(int(segment.start), 60)
        hours, minutes = divmod(minutes, 60)
        stamp = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"
        rows.append(f"[{stamp}] {segment.text.strip()}")

    text = "\n".join(rows).strip()
    if not text:
        raise ResolverError("faster-whisper returned no text.")
    return TranscriptResult(
        status="generated",
        source_kind=SourceKind.LOCAL_FASTER_WHISPER,
        text=text,
        raw_text=text,
        language=getattr(info, "language", "") or language,
        is_timecoded=True,
        is_machine_generated=True,
        notes=[f"Generated locally with faster-whisper model '{model_name}'."],
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def merge_episode(primary: Episode, fallback: Episode) -> Episode:
    """Keep stronger input-page facts while adding missing RSS/publisher fields."""
    result = dataclasses.replace(primary)
    for name in ("title", "podcast_name", "description", "published", "guid", "website_url", "rss_url", "audio_url", "youtube_url", "source_url"):
        if not getattr(result, name):
            setattr(result, name, getattr(fallback, name))
    if result.duration_seconds is None:
        result.duration_seconds = fallback.duration_seconds
    result.transcript_assets = [*result.transcript_assets, *fallback.transcript_assets]
    return result


def resolve(args: argparse.Namespace) -> ResolverResult:
    warnings: list[str] = []
    input_url = args.url

    # Step 1 — normalise the input into an Episode candidate.
    if is_youtube_url(input_url):
        episode = Episode(source_url=input_url, youtube_url=input_url)
    elif looks_like_feed(input_url):
        episode = Episode(source_url=input_url, rss_url=input_url)
    elif is_podcast_addict_url(input_url):
        try:
            episode, input_warnings = inspect_podcast_addict(input_url)
            warnings.extend(input_warnings)
        except requests.RequestException as exc:
            episode = Episode(source_url=input_url)
            warnings.append(f"Podcast Addict page could not be fetched: {exc}")
    else:
        try:
            episode, input_warnings = inspect_generic_episode_page(input_url)
            warnings.extend(input_warnings)
        except requests.RequestException as exc:
            episode = Episode(source_url=input_url)
            warnings.append(f"Publisher page could not be fetched: {exc}")

    if args.feed_url:
        episode.rss_url = args.feed_url
    if args.website_url:
        episode.website_url = args.website_url
    if args.youtube_url:
        episode.youtube_url = args.youtube_url

    # Step 2 — publisher website transcript is checked first when known.
    if episode.website_url and episode.website_url != episode.source_url:
        try:
            website_episode, website_warnings = inspect_generic_episode_page(episode.website_url)
            warnings.extend(website_warnings)
            episode = merge_episode(episode, website_episode)
        except requests.RequestException as exc:
            warnings.append(f"Publisher website could not be inspected: {exc}")

    transcript = try_published_transcript(episode, args.language, warnings)
    if transcript:
        return ResolverResult(input_url, datetime.now(timezone.utc).isoformat(), episode, transcript, warnings)

    # RSS gives access to canonical enclosure URLs and standard transcript tags.
    if episode.rss_url:
        try:
            podcast_name, rss_episodes = parse_rss(episode.rss_url)
            if not episode.podcast_name:
                episode.podcast_name = podcast_name
            matched, score = choose_rss_episode(episode, rss_episodes)
            if matched and (not episode.title or score >= args.match_threshold):
                episode = merge_episode(episode, matched)
                transcript = try_published_transcript(episode, args.language, warnings)
                if transcript:
                    transcript.notes.append(f"RSS episode match confidence: {score:.2f}")
                    return ResolverResult(input_url, datetime.now(timezone.utc).isoformat(), episode, transcript, warnings)
            elif episode.title:
                warnings.append(
                    f"No RSS episode met the match threshold ({args.match_threshold:.2f}); "
                    "review the feed or lower --match-threshold deliberately."
                )
        except (requests.RequestException, ResolverError) as exc:
            warnings.append(f"RSS resolution failed: {exc}")

    # Step 3 — YouTube captions. This stage never downloads audio.
    if episode.youtube_url:
        transcript = try_youtube_captions(episode.youtube_url, args.language, warnings)
        if transcript:
            return ResolverResult(input_url, datetime.now(timezone.utc).isoformat(), episode, transcript, warnings)
    else:
        warnings.append("No official YouTube URL supplied; automatic web search is intentionally left as a plug-in step.")

    # Step 4 — optional, explicit local transcription fallback.
    if args.transcribe:
        with tempfile.TemporaryDirectory(prefix="podcast-resolver-") as temp_dir:
            try:
                audio_path = download_authorised_audio(episode, Path(temp_dir), args.allow_youtube_audio)
                transcript = transcribe_locally(
                    audio_path,
                    model_name=args.whisper_model,
                    language=args.language,
                    vocabulary_hint=args.vocabulary_hint,
                )
                return ResolverResult(input_url, datetime.now(timezone.utc).isoformat(), episode, transcript, warnings)
            except (ResolverError, requests.RequestException, subprocess.CalledProcessError) as exc:
                warnings.append(f"Local transcription fallback failed: {exc}")

    return ResolverResult(
        input_url=input_url,
        checked_at=datetime.now(timezone.utc).isoformat(),
        episode=episode,
        transcript=TranscriptResult(
            status="not_found",
            source_kind=SourceKind.UNRESOLVED,
            notes=["No publisher transcript, usable YouTube caption track, or completed local fallback was available."],
        ),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Output and command line
# ---------------------------------------------------------------------------


def safe_filename(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", value.strip(), flags=re.UNICODE)
    return value.strip(".-")[:100] or "transcript"


def write_output(result: ResolverResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.joinpath("result.json").write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if result.transcript.text:
        stem = safe_filename(result.episode.title or "transcript")
        header = [
            f"# {result.episode.title or 'Transcript'}",
            "",
            f"- **Podcast:** {result.episode.podcast_name or 'Unknown'}",
            f"- **Source:** `{result.transcript.source_kind.value}`",
            f"- **Language:** {result.transcript.language or 'Unknown'}",
            f"- **Machine-generated:** {result.transcript.is_machine_generated}",
            f"- **Input URL:** {result.input_url}",
        ]
        if result.transcript.transcript_url:
            header.append(f"- **Transcript URL:** {result.transcript.transcript_url}")
        output_dir.joinpath(f"{stem}.md").write_text("\n".join(header) + "\n\n---\n\n" + result.transcript.text + "\n", encoding="utf-8")
        if result.transcript.raw_text and result.transcript.raw_text != result.transcript.text:
            output_dir.joinpath(f"{stem}.source.txt").write_text(result.transcript.raw_text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve published podcast transcripts before local transcription.")
    parser.add_argument("url", help="Podcast Addict, publisher page, RSS, YouTube, or direct episode URL.")
    parser.add_argument("--feed-url", help="Canonical publisher RSS feed; strongly recommended for Podcast Addict inputs.")
    parser.add_argument("--website-url", help="Canonical publisher episode page to inspect for a transcript link.")
    parser.add_argument("--youtube-url", help="Known official YouTube upload to check for existing captions.")
    parser.add_argument("--language", default="fr", help="Preferred BCP-47/ISO language code (default: fr).")
    parser.add_argument("--match-threshold", type=float, default=0.65, help="Minimum RSS match score when title is known (default: 0.65).")
    parser.add_argument("--transcribe", action="store_true", help="Permit the final local faster-whisper fallback.")
    parser.add_argument("--whisper-model", default="large-v3", help="Your faster-whisper model name (default: large-v3).")
    parser.add_argument("--vocabulary-hint", default="", help="Names/terms to pass as a faster-whisper initial prompt.")
    parser.add_argument("--allow-youtube-audio", action="store_true", help="Allow yt-dlp audio extraction only for a permitted supplied YouTube URL.")
    parser.add_argument("--output-dir", type=Path, default=Path("podcast-result"), help="Directory for result.json and transcript files.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = resolve(args)
    write_output(result, args.output_dir)
    print(f"Status: {result.transcript.status}")
    print(f"Source: {result.transcript.source_kind.value}")
    print(f"Output: {args.output_dir.resolve()}")
    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0 if result.transcript.status in {"found", "generated"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
