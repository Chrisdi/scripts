#!/usr/bin/env python3
"""
TikTok to Text — downloads TikTok audio via yt-dlp and transcribes it with
the local transcribe.py script.

Only dependencies:
  - yt-dlp   (system-installed, 2026+ for built-in impersonation)
  - ffmpeg   (for audio extraction)
    - faster-whisper in the Python environment used to run transcribe.py
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

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
# Transcription (local script)
# ---------------------------------------------------------------------------

def transcribe(audio_path: Path, args) -> str:
    """Run transcribe.py and return its stdout transcript."""
    script = Path(args.transcribe_script).resolve()
    cmd = [sys.executable, str(script), str(audio_path), args.model]
    if args.language:
        cmd += ["-l", args.language]
    if args.compute_type:
        cmd += ["-c", args.compute_type]
    if args.model_dir:
        cmd += ["--model-dir", str(Path(args.model_dir).expanduser().resolve())]

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        cmd,
        cwd=str(script.parent),
        stdout=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
    )
    output, _ = process.communicate()
    if process.returncode != 0:
        print(f"{script.name} failed with exit code {process.returncode}", file=sys.stderr)
        sys.exit(process.returncode)
    return (output or "").strip()


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
        description="TikTok to Text — download audio and transcribe with transcribe.py"
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
    default_transcribe_script = Path(__file__).resolve().parent.parent / "transcribe" / "transcribe.py"
    parser.add_argument(
        "--transcribe-script", default=str(default_transcribe_script),
        help="Path to transcribe.py (default: ../transcribe/transcribe.py)",
    )
    parser.add_argument("--compute-type", default=None, help="faster-whisper compute type (default: int8)")
    parser.add_argument("--model-dir", default=None, help="Model cache directory for faster-whisper")

    args = parser.parse_args()

    transcribe_script = Path(args.transcribe_script).expanduser().resolve()
    if not transcribe_script.is_file():
        parser.error(f"--transcribe-script not found: {transcribe_script}")
    args.transcribe_script = str(transcribe_script)

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

        print(f"Transcribing via {transcribe_script.name} ({args.model}) …", file=sys.stderr)
        text = transcribe(audio, args)

        outpath.write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"Saved: {outpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
