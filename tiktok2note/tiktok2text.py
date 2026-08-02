#!/usr/bin/env python3
"""
TikTok to Text — downloads TikTok audio via yt-dlp and transcribes via
the Faster Whisper Transcriber server (http://127.0.0.1:8765).

Only dependencies:
  - yt-dlp   (system-installed, 2026+ for built-in impersonation)
  - ffmpeg   (for audio extraction)
  - requests (pip-installable)
  - Faster Whisper Transcriber server running locally (port 8765)
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import requests


FASTER_WHISPER_URL = "http://127.0.0.1:8765/transcribe"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def check_dependencies():
    """Ensure ffmpeg is on PATH (yt-dlp is checked at call time)."""
    which = "where" if platform.system() == "Windows" else "which"
    for cmd, label in [("ffmpeg", "ffmpeg")]:
        try:
            ret = subprocess.run([which, cmd], capture_output=True, check=False)
            if ret.returncode != 0:
                raise FileNotFoundError(cmd)
        except FileNotFoundError:
            print(f"Missing dependency: {label}", file=sys.stderr)
            print("Install with: winget install Gyan.FFmpeg", file=sys.stderr)
            sys.exit(2)


def check_ytdlp():
    """Fail early if yt-dlp is not on PATH."""
    if not _which("yt-dlp"):
        print("yt-dlp not found. Install with: winget install yt-dlp.yt-dlp", file=sys.stderr)
        sys.exit(2)


def _which(cmd: str) -> str | None:
    """Return full path of *cmd* or None."""
    try:
        ret = subprocess.run(
            ["where" if platform.system() == "Windows" else "which", cmd],
            capture_output=True, text=True, check=False,
        )
        return ret.stdout.strip().splitlines()[0] if ret.returncode == 0 else None
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_audio(url: str, workdir: str) -> Path:
    """Download a TikTok video and extract its audio as WAV to *workdir*.

    Returns the path to the WAV file.
    """
    cmd = [
        "yt-dlp",
        url,
        "--extract-audio",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "--no-playlist",
        "--impersonate", "chrome",
        "--referer", "https://www.tiktok.com/",
        # TikTok's bytevc1 (h265) formats often lack audio despite claiming
        # aac, so prefer h264, then audio-only, then anything else.
        "-f", "b[vcodec^=h264]/ba/b",
        "-o", "%(id)s.%(ext)s",
    ]

    ret = subprocess.run(cmd, cwd=workdir)
    if ret.returncode != 0:
        print("yt-dlp download failed.", file=sys.stderr)
        sys.exit(3)

    wavs = list(Path(workdir).glob("*.wav"))
    if not wavs:
        print("No WAV file produced by yt-dlp.", file=sys.stderr)
        sys.exit(3)
    return wavs[0]


# ---------------------------------------------------------------------------
# Transcription (API call)
# ---------------------------------------------------------------------------

def transcribe(audio_path: Path, model: str = "base", language: str = "en") -> str:
    """Send *audio_path* to the Faster Whisper Transcriber server and return the transcript."""
    with open(audio_path, "rb") as fh:
        try:
            r = requests.post(
                FASTER_WHISPER_URL,
                files={"audio": (audio_path.name, fh, "audio/wav")},
                data={"model": model, "language": language},
                timeout=600,
            )
        except requests.exceptions.RequestException as exc:
            # Covers ConnectionError and ReadTimeout (the server queues jobs
            # one at a time, so a long queue can outlast the 600s timeout).
            print(
                "Faster Whisper Transcriber not reachable or timed out at"
                f" {FASTER_WHISPER_URL}: {exc}",
                file=sys.stderr,
            )
            sys.exit(4)

    if r.status_code != 200:
        detail = r.text[:500]
        print(f"Faster Whisper error ({r.status_code}): {detail}", file=sys.stderr)
        sys.exit(4)

    result = r.json()
    return result.get("text", "").strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    # Windows consoles default to cp1252, which can't encode the … used in
    # status output; force UTF-8 so prints never crash on encoding.
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="TikTok to Text — download audio & transcribe via Faster Whisper Transcriber server"
    )
    parser.add_argument("url", help="TikTok URL to transcribe")
    parser.add_argument(
        "-b", "--browser", default=None,
        help="Ignored (yt-dlp impersonation is used; cookies not needed)",
    )
    parser.add_argument(
        "-m", "--model", default="base",
        choices=["tiny", "tiny.en", "base", "base.en", "small", "small.en",
                 "medium", "medium.en", "large-v3", "large-v3-turbo"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "-l", "--language", default="en",
        help="Language code (default: en)",
    )
    parser.add_argument(
        "-o", "--outdir", default=None,
        help="Output directory (default: same directory as this script)",
    )

    args = parser.parse_args()

    # Photo slideshows have no audio track — nothing to transcribe.
    if "/photo/" in args.url:
        print("TikTok photo slideshow: no audio to transcribe.", file=sys.stderr)
        sys.exit(2)

    script_dir = Path(__file__).resolve().parent
    outdir = Path(args.outdir) if args.outdir else script_dir
    outdir.mkdir(parents=True, exist_ok=True)

    check_dependencies()
    check_ytdlp()

    with tempfile.TemporaryDirectory(prefix="tiktok2text_") as workdir:
        audio = download_audio(args.url, workdir)
        base = audio.stem
        outpath = outdir / f"{base}.txt"

        print(f"Transcribing via Faster Whisper ({args.model}) …", file=sys.stderr)
        text = transcribe(audio, args.model, args.language)

        outpath.write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"Saved: {outpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
