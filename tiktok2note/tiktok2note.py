#!/usr/bin/env python3
"""
tiktok2note.py — Save a single TikTok URL as an Obsidian note.

Fetches metadata for the URL (expanding short links first), renders a note
from a markdown template, and writes it to the output folder.

  - Short links (vm.tiktok.com, tiktok.com/t/, m.tiktok.com, short codes)
    are expanded to their canonical /@author/video/<id> form.
  - Metadata comes from TikTok's oEmbed endpoint.
  - Photo slideshows (/photo/) have no audio and are embedded as images.
  - Private videos produce a placeholder note (or are skipped / reported).
  - The posted date is derived from the video ID (the upper 32 bits of the ID
    are a Unix timestamp), falling back to the HTTP Last-Modified header, then
    to today.

Transcription is handled separately (see tiktok2text.py / process_tiktoks.py).
New notes keep a {{transcription}} placeholder so those tools can fill it in.

Only dependency: requests

Usage:
  python tiktok2note.py https://vm.tiktok.com/abc123
  python tiktok2note.py https://www.tiktok.com/@x/video/1234567890123456789 -o "My vault/Tiktoks"

The note template defaults to tiktok2note.tpl.md (next to this script).
Template variables:

  {{author}}          author name (may include a leading @)
  {{date}}            note creation date (YYYY-MM-DD)
  {{posted}}          date the video was posted (YYYY-MM-DD)
  {{url}}             canonical video URL
  {{expanded_url}}    expanded URL (the same as {{url}} after expansion)
  {{videoId}}         numeric video ID
  {{description}}     caption with hashtag words removed
  {{hashtags}}        caption hashtags, e.g. "#fyp #viral"
  {{iframe}}          iframe embed HTML
  {{transcription}}   transcription text, a {{transcription}} placeholder for
                      later transcription, or nothing (slideshows / private)
  {{isSlideshow}}     "true" or "false"
  {{tag_list}}        YAML tag lines for the caption hashtags, meant for a
                      "tags:" block (nothing when there are no hashtags)
  {{title}}           cleaned description (hashtags removed, ≤80 chars); the
                      default template uses it for the frontmatter "title:"
"""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_FOLDER = "Tiktoks"
DEFAULT_TITLE_TEMPLATE = "{{date}}_{{videoId}}_{{title}}"
DEFAULT_TEMPLATE_FILE = "tiktok2note.tpl.md"

# TikTok ignores any origin other than its own; a desktop-like User-Agent is
# used for plain page fetches, and a lightweight one for the oEmbed API.
UA_OEMBED = "Mozilla/5.0 (compatible; TikTok-Metadata/1.0)"
UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class Settings:
    output_folder: str = DEFAULT_OUTPUT_FOLDER
    note_title_template: str = DEFAULT_TITLE_TEMPLATE
    content_template: str = ""  # path to the note template file ("" = default)

    handle_private_videos: str = "create-empty"  # 'create-empty' | 'skip' | 'show-error'
    duplicate_file_handling: str = "replace"     # 'replace' | 'duplicate' | 'skip'
    url_timeout: int = 10

    # Leave a {{transcription}} placeholder in new notes so the transcription tools can find and fill them in later.
    leave_transcription_placeholder: bool = True


# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

_TIKTOK_PATTERNS = [
    re.compile(r"^https?://(www\.)?(tiktok\.com|vm\.tiktok\.com)"),
    re.compile(r"^https?://tiktok\.com/t/"),
    re.compile(r"^https?://(www\.)?tiktok\.com/@[\w.-]+/video/\d+"),
]


def is_tiktok_url(url: str) -> bool:
    return any(p.match(url.strip()) for p in _TIKTOK_PATTERNS)


# ---------------------------------------------------------------------------
# URL expansion
# ---------------------------------------------------------------------------

def identify_short_url_pattern(url: str) -> tuple[bool, str]:
    if "vm.tiktok.com" in url:
        return True, "vm.tiktok.com"
    if "tiktok.com/t/" in url:
        return True, "/t/"
    if "m.tiktok.com/v/" in url:
        return True, "m.tiktok.com"
    if re.search(r"tiktok\.com/[a-zA-Z0-9]{4,12}/?$", url):
        return True, "short-code"
    return False, "none"


def is_valid_tiktok_video_url(url: str) -> bool:
    return (
        "tiktok.com" in url
        and ("/video/" in url or "/photo/" in url)
        and "/t/" not in url
        and "vm.tiktok.com" not in url
    )


# Ordered by reliability: canonical/og:url meta tags first, then JSON SEO
# fields, then a JS location redirect.
_FINAL_URL_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "canonical-tiktok-video",
        re.compile(
            r"""<link[^>]+rel=["']canonical["'][^>]+href=["'](https://(?:www\.)?tiktok\.com/@[^"'/]+/video/\d+[^"']*)["']""",
            re.IGNORECASE,
        ),
    ),
    (
        "og:url-tiktok-video",
        re.compile(
            r"""<meta[^>]+property=["']og:url["'][^>]+content=["'](https://(?:www\.)?tiktok\.com/@[^"'/]+/video/\d+[^"']*)["']""",
            re.IGNORECASE,
        ),
    ),
    (
        "canonical-href-first",
        re.compile(
            r"""<link[^>]+href=["'](https://(?:www\.)?tiktok\.com/@[^"'/]+/video/\d+[^"']*)["'][^>]+rel=["']canonical["']""",
            re.IGNORECASE,
        ),
    ),
    (
        "og:url-content-first",
        re.compile(
            r"""<meta[^>]+content=["'](https://(?:www\.)?tiktok\.com/@[^"'/]+/video/\d+[^"']*)["'][^>]+property=["']og:url["']""",
            re.IGNORECASE,
        ),
    ),
    (
        "seo-canonical-json",
        re.compile(
            r'''"canonicalHref":\s*"(https://(?:www\.)?tiktok\.com/@[^"/]+/video/\d+[^"]*)"''',
            re.IGNORECASE,
        ),
    ),
    (
        "canonical-url-json",
        re.compile(
            r'''"canonical(?:_url|Url)":\s*"(https://(?:www\.)?tiktok\.com/@[^"/]+/video/\d+[^"]*)"''',
            re.IGNORECASE,
        ),
    ),
    (
        "js-location-redirect",
        re.compile(
            r"""(?:window\.)?location(?:\.href)?\s*=\s*["'](https://(?:www\.)?tiktok\.com/@[^"'/]+/video/\d+[^"']*)["']""",
            re.IGNORECASE,
        ),
    ),
]


def extract_final_url_from_response(html: str, fallback_url: str) -> str:
    """Pull the canonical expanded URL out of a TikTok page, if present."""
    for _name, regex in _FINAL_URL_PATTERNS:
        m = regex.search(html)
        if not m:
            continue
        url = m.group(1).replace("\\u002F", "/").replace("\\", "")
        if (
            "tiktok.com" in url
            and ("/video/" in url or "/photo/" in url or "/@" in url)
            and url != fallback_url
            and "/t/" not in url
        ):
            return url
    return fallback_url


def expand_url(url: str, settings: Settings) -> str:
    """Expand a short TikTok URL to its canonical /@author/video/<id> form."""
    requires_expansion, _pattern = identify_short_url_pattern(url)
    if not requires_expansion:
        return url

    try:
        # requests follows redirects (short link -> video page); the final
        # page body then yields the canonical URL.
        resp = requests.get(
            url,
            headers={"user-agent": UA_DESKTOP},
            timeout=settings.url_timeout,
            allow_redirects=True,
        )

        # Primary path: extract the canonical URL from the final page HTML.
        extracted = extract_final_url_from_response(resp.text, url)
        if extracted != url and is_valid_tiktok_video_url(extracted):
            return extracted

        # Safety net: the redirect chain's final URL itself is a video URL.
        if resp.url != url and is_valid_tiktok_video_url(resp.url):
            return resp.url
    except requests.RequestException as exc:
        print(f"[debug] expansion failed for {url}: {exc}", file=sys.stderr)

    return url


# ---------------------------------------------------------------------------
# TikTok metadata
# ---------------------------------------------------------------------------

HASHTAG_RE = re.compile(r"#[\w\u00c0-\u024f\u1e00-\u1eff]+", re.IGNORECASE)
VIDEO_ID_RE = re.compile(r"/video/(\d+)")
AUTHOR_RE = re.compile(r"@([^/]+)")


def extract_video_id(url: str) -> str | None:
    m = VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def extract_author_from_url(url: str) -> str:
    m = AUTHOR_RE.search(url)
    return f"@{m.group(1)}" if m else "Unknown"


def extract_hashtags(text: str) -> list[str]:
    return HASHTAG_RE.findall(text)


def get_current_date_string() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def extract_tiktok_posted_date(video_id: str | None, url: str | None) -> str:
    """Posted date, derived from the video ID's upper 32 bits.

    TikTok video IDs are 64-bit numbers whose upper 32 bits are a Unix
    timestamp. Falls back to the HTTP Last-Modified header, then to today.
    """
    if video_id and len(video_id) >= 19:
        timestamp = int(video_id) >> 32
        # Plausible Unix range: Jan 1 2010 - Jan 1 2030
        if 1262304000 < timestamp < 1893456000:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

    if url:
        try:
            resp = requests.head(url, headers={"user-agent": UA_DESKTOP}, timeout=5)
            last_modified = resp.headers.get("last-modified")
            if last_modified:
                try:
                    dt = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z")
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass
        except requests.RequestException:
            pass

    return get_current_date_string()


def create_obsidian_compatible_embed(video_id: str | None, url: str) -> str:
    if video_id:
        return f'<iframe width="325" height="760" src="https://www.tiktok.com/embed/v2/{video_id}"></iframe>'
    return f'<p>Tiktok video: <a href="{url}" target="_blank">{url}</a></p>'


def handle_slideshow_url(url: str, video_id: str | None, settings: Settings) -> dict:
    """Photo slideshows have no audio; embed as a markdown image."""
    author_with_at = extract_author_from_url(url)
    author = author_with_at.replace("@", "")
    posted = extract_tiktok_posted_date(video_id, url)
    title = f"Tiktok photo slideshow by {author_with_at}"
    return {
        "author": author,
        "description": "Tiktok photo slideshow",
        "hashtags": [],
        "url": url,
        "expandedUrl": url,
        "embedHtml": f"![{title}]({url})",
        "videoId": video_id,
        "createdDate": get_current_date_string(),
        "postedDate": posted,
        "transcription": "",
        "oembedFailed": False,
        "isSlideshow": True,
        "isPrivate": False,
    }


class OEmbedError(Exception):
    def __init__(self, status: int):
        super().__init__(f"oEmbed request failed: {status}")
        self.status = status


def detect_private_video(error: Exception) -> bool:
    message = str(error).lower()
    if "403" in message or "forbidden" in message:
        return True
    if any(word in message for word in ("private", "not available", "access denied", "restricted")):
        return True
    if getattr(error, "status", None) == 403:
        return True
    return False


def handle_private_video(url: str, video_id: str | None, settings: Settings) -> dict | None:
    """create-empty | skip | show-error."""
    author = extract_author_from_url(url)
    posted = extract_tiktok_posted_date(video_id, url)
    mode = settings.handle_private_videos

    if mode == "skip":
        return None

    if mode == "show-error":
        return {
            "author": author,
            "description": "Private tiktok video - access denied",
            "hashtags": [],
            "url": url,
            "expandedUrl": url,
            "embedHtml": (
                "<p><strong>Private video</strong></p>"
                "<p>This tiktok video is private and cannot be accessed.</p>"
                f'<p>Original url: <a href="{url}" target="_blank">{url}</a></p>'
            ),
            "videoId": video_id,
            "createdDate": get_current_date_string(),
            "postedDate": posted,
            "transcription": "",
            "oembedFailed": True,
            "isPrivate": True,
            "isSlideshow": False,
        }

    # create-empty (default)
    return {
        "author": author,
        "description": "Private tiktok video",
        "hashtags": [],
        "url": url,
        "expandedUrl": url,
        "embedHtml": f'<p>Tiktok video (private): <a href="{url}" target="_blank">{url}</a></p>',
        "videoId": video_id,
        "createdDate": get_current_date_string(),
        "postedDate": posted,
        "transcription": "",
        "oembedFailed": True,
        "isPrivate": True,
        "isSlideshow": False,
    }


def fetch_tiktok_data(url: str, settings: Settings) -> dict | None:
    video_id = extract_video_id(url)

    if "/photo/" in url:
        return handle_slideshow_url(url, video_id, settings)

    try:
        oembed_url = f"https://www.tiktok.com/oembed?url={quote(url, safe='')}"
        print(f"[debug] oEmbed: {oembed_url}", file=sys.stderr)

        resp = requests.get(
            oembed_url,
            headers={"User-Agent": UA_OEMBED},
            timeout=settings.url_timeout,
        )
        if resp.status_code != 200:
            raise OEmbedError(resp.status_code)
        od = resp.json()

        # The oEmbed HTML carries the real video ID when URL parsing failed.
        final_video_id = video_id
        if not final_video_id and od.get("html"):
            m = re.search(r'data-video-id="(\d+)"', od.get("html", ""))
            if m:
                final_video_id = m.group(1)

        posted = extract_tiktok_posted_date(final_video_id, url)
        return {
            "author": od.get("author_name") or "Unknown",
            "description": od.get("title") or "Tiktok video",
            "hashtags": extract_hashtags(od.get("title") or ""),
            "url": url,
            "expandedUrl": url,
            "embedHtml": create_obsidian_compatible_embed(final_video_id, url),
            "thumbnailUrl": od.get("thumbnail_url"),
            "videoId": final_video_id,
            "createdDate": get_current_date_string(),
            "postedDate": posted,
            "transcription": "",
            "oembedFailed": False,
            "isSlideshow": False,
            "isPrivate": False,
        }
    except (OEmbedError, requests.RequestException, ValueError) as exc:
        print(f"[debug] oEmbed failed: {exc}", file=sys.stderr)

        if detect_private_video(exc):
            return handle_private_video(url, video_id, settings)

        # Fallback: author from the URL, a generic description, and an iframe
        # embed built from the video ID.
        posted = extract_tiktok_posted_date(video_id, url)
        author_with_at = extract_author_from_url(url)
        author = author_with_at.replace("@", "")

        if "/photo/" in url:
            title = f"Tiktok photo slideshow by {author_with_at}"
            return {
                "author": author,
                "description": "Tiktok photo slideshow",
                "hashtags": [],
                "url": url,
                "expandedUrl": url,
                "embedHtml": f"![{title}]({url})",
                "videoId": video_id,
                "createdDate": get_current_date_string(),
                "postedDate": posted,
                "transcription": "",
                "oembedFailed": True,
                "isSlideshow": True,
                "isPrivate": False,
            }

        return {
            "author": author,
            "description": "Tiktok post",
            "hashtags": [],
            "url": url,
            "expandedUrl": url,
            "embedHtml": create_obsidian_compatible_embed(video_id, url),
            "videoId": video_id,
            "createdDate": get_current_date_string(),
            "postedDate": posted,
            "transcription": "",
            "oembedFailed": True,
            "isSlideshow": False,
            "isPrivate": False,
        }


# ---------------------------------------------------------------------------
# Note generation
# ---------------------------------------------------------------------------

def sanitize_file_name(name: str) -> str:
    name = name.replace("|", "-")
    name = re.sub(r'[<>:"/\\?*]', "", name)
    return name.strip()


def clean_title(data: dict) -> str:
    """Cleaned caption (hashtag words removed, ≤80 chars) used for titles."""
    clean = HASHTAG_RE.sub("", data.get("description") or "Unknown").strip()
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > 80:
        clean = clean[:80].strip() + "..."
    return clean


def generate_note_title(data: dict, settings: Settings) -> str:
    clean = clean_title(data)

    title = settings.note_title_template
    title = title.replace("{{date}}", data.get("createdDate") or data.get("date") or get_current_date_string())
    title = title.replace("{{videoId}}", data.get("videoId") or "")
    title = title.replace("{{title}}", clean)
    title = title.replace("{{description}}", clean)
    title = title.replace("{{author}}", data.get("author") or "Unknown")
    return title


def generate_note_content(data: dict, settings: Settings, template_text: str) -> str:
    """Render the note template, substituting the {{...}} variables."""
    hashtags = data.get("hashtags", [])
    hashtag_str = " ".join(hashtags)

    # Strip hashtag words from the description (they live in the Hashtags
    # section and in the frontmatter tags instead).
    clean = data.get("description") or ""
    for tag in hashtags:
        clean = re.sub(re.escape(tag), "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"\s+", " ", clean).strip()

    if data.get("transcription") and data["transcription"].strip():
        transcription_content = f"## Transcription\n\n{data['transcription'].strip()}"
    elif (
        settings.leave_transcription_placeholder
        and not data.get("isSlideshow")
        and not data.get("isPrivate")
    ):
        # Leave the placeholder so the transcription tools fill it in later.
        transcription_content = "{{transcription}}"
    else:
        transcription_content = ""

    tag_list = "".join(f"  - {tag.lstrip('#')}\n" for tag in hashtags).rstrip("\n")

    values = {
        "{{author}}": data.get("author") or "",
        "{{date}}": data.get("createdDate") or data.get("date") or get_current_date_string(),
        "{{posted}}": data.get("postedDate")
        or data.get("createdDate")
        or data.get("date")
        or get_current_date_string(),
        "{{url}}": data.get("url") or "",
        "{{expanded_url}}": data.get("expandedUrl") or data.get("url") or "",
        "{{videoId}}": data.get("videoId") or "",
        "{{description}}": clean,
        "{{title}}": clean_title(data),
        "{{hashtags}}": hashtag_str,
        "{{iframe}}": data.get("embedHtml") or "Tiktok video embed not available",
        "{{transcription}}": transcription_content,
        "{{isSlideshow}}": "true" if data.get("isSlideshow") else "false",
        "{{tag_list}}": tag_list,
    }
    for key, value in values.items():
        template_text = template_text.replace(key, value)
    return template_text


def create_tiktok_note(data: dict, settings: Settings, template_text: str) -> dict:
    note_title = generate_note_title(data, settings)
    file_name = sanitize_file_name(note_title)
    note_content = generate_note_content(data, settings, template_text)

    folder = Path(settings.output_folder)
    folder.mkdir(parents=True, exist_ok=True)

    path = folder / f"{file_name}.md"

    if path.exists():
        mode = settings.duplicate_file_handling
        if mode == "skip":
            return {"success": False, "skipped": True, "fileName": file_name, "noteTitle": note_title}
        if mode == "duplicate":
            counter = 1
            while path.exists():
                path = folder / f"{file_name}-{counter}.md"
                counter += 1
        else:  # replace (default): overwrite
            path.unlink()

    path.write_text(note_content, encoding="utf-8")
    return {"success": True, "fileName": file_name, "noteTitle": note_title, "path": str(path)}


# ---------------------------------------------------------------------------
# Single-URL processing
# ---------------------------------------------------------------------------

def process_url(url: str, settings: Settings, template_text: str) -> dict:
    expanded = expand_url(url, settings)
    data = fetch_tiktok_data(expanded, settings)
    if data is None:  # private video with handle_private_videos='skip'
        return {"url": url, "success": False, "isPrivate": True}

    data.setdefault("isSlideshow", False)
    data.setdefault("isPrivate", False)
    data.setdefault("oembedFailed", False)

    note = create_tiktok_note(data, settings, template_text)
    return {
        "url": url,
        **note,
        "isSlideshow": data["isSlideshow"],
        "isPrivate": data["isPrivate"],
        "oembedFailed": data["oembedFailed"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    default_template = str(Path(__file__).resolve().parent / DEFAULT_TEMPLATE_FILE)

    parser = argparse.ArgumentParser(description="Save a TikTok URL as an Obsidian note")
    parser.add_argument("url", help="TikTok URL to process")
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_FOLDER,
        help=f"output folder (default: {DEFAULT_OUTPUT_FOLDER})",
    )
    parser.add_argument(
        "--title-template",
        default=DEFAULT_TITLE_TEMPLATE,
        help="note title template",
    )
    parser.add_argument(
        "--content-template",
        default=default_template,
        help=f"note template file (default: {default_template})",
    )
    args = parser.parse_args(argv)

    settings = Settings(
        output_folder=args.output,
        note_title_template=args.title_template,
        content_template=args.content_template,
    )

    url = args.url.strip()
    if not is_tiktok_url(url):
        print(f"Not a valid TikTok URL: {url}", file=sys.stderr)
        return 1

    try:
        template_text = Path(settings.content_template).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Cannot read template {settings.content_template}: {exc}", file=sys.stderr)
        return 1

    print(f"[debug] processing {url}", file=sys.stderr)
    try:
        result = process_url(url, settings, template_text)
    except Exception as exc:  # noqa: BLE001
        print(f"[debug] {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    if result.get("success"):
        print(f"Created: {result['path']}")
    elif result.get("isPrivate"):
        print("Skipped: private video")
    elif result.get("skipped"):
        print(f"Skipped: note already exists ({result['fileName']}.md)")
    else:
        print(f"Failed: {result.get('error', 'unknown error')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
