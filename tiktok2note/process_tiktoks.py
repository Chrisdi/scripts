#!/usr/bin/env python3
"""
Batch processor: download + transcribe TikTok URLs found in Obsidian markdown
frontmatter, then append a "## Transcription" section to each file.

With --apply-existing it works fully offline: fresh note templates
(<date>_<videoId>_<title>.md) are filled from existing
_tiktok_assets/<videoId>.txt transcripts — no download, no transcription.

With --transcribe-script <path to transcribe.py> it runs that script as a
subprocess against the downloaded audio instead of calling the API — no
server needed. The subprocess runs with the script's own base directory as
its working directory, and only the given path is relied on, so the
transcribe folder can live anywhere / be moved freely.

Only dependencies:
  - yt-dlp   (system-installed, 2026+ for built-in impersonation)
  - ffmpeg   (for audio extraction)
  - requests (pip-installable)
  - API mode:      Faster Whisper Transcriber server running locally (port 8765)
  - script mode:   faster-whisper in the interpreter's env (see transcribe.py)
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

FASTER_WHISPER_URL = "http://127.0.0.1:8765/transcribe"

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def fmt_secs(s: float) -> str:
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    if h: return f"{h:d}h {m:02d}m {s:02d}s"
    if m: return f"{m:d}m {s:02d}s"
    return f"{s:d}s"


def sh(cmd, cwd=None) -> int:
    """Run a command, inherit stdout/stderr for live progress."""
    return subprocess.Popen(cmd, cwd=str(cwd) if cwd else None).wait()


# ═══════════════════════════════════════════════════════════════════════════
# yt-dlp
# ═══════════════════════════════════════════════════════════════════════════

_YTDLP_CACHE = None

def ytdlp_cmd():
    """Return (cmd_list, can_impersonate).  System yt-dlp 2026+ has built-in
    impersonation, so we always use it directly."""
    global _YTDLP_CACHE
    if _YTDLP_CACHE is None:
        _YTDLP_CACHE = (["yt-dlp"], True)
    return _YTDLP_CACHE


# ═══════════════════════════════════════════════════════════════════════════
# Markdown helpers
# ═══════════════════════════════════════════════════════════════════════════

def extract_url_from_frontmatter(md_path: Path):
    txt = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"^---\s*\n(.*?\n)---\s*\n", txt, flags=re.DOTALL)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if re.match(r"^\s*url\s*:", line):
            val = line.split(":", 1)[1].strip()
            if len(val) >= 2 and val[0] in "'\"" and val[-1] == val[0]:
                val = val[1:-1]
            return val or None
    return None


def frontmatter_flags(md_path: Path) -> dict:
    """Return frontmatter flags set to true (isSlideshow, isPrivate, ...)."""
    txt = md_path.read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"^---\s*\n(.*?\n)---\s*\n", txt, flags=re.DOTALL)
    block = m.group(1) if m else ""
    flags = {}
    for name in ("isSlideshow", "isPrivate"):
        if re.search(rf"^\s*{re.escape(name)}\s*:\s*true\b", block, flags=re.M | re.I):
            flags[name] = True
    return flags


def ensure_transcription_section(md_text: str, transcript: str, heading="Transcription") -> str:
    if not md_text.endswith("\n"):
        md_text += "\n"
    pattern = re.compile(
        rf"(^##\s*{re.escape(heading)}\s*$)(.*?)(?=^\s*#{1,6}\s+\S|\Z)", re.M | re.S
    )
    block = f"## {heading}\n\n{transcript.strip()}\n"
    if pattern.search(md_text):
        return pattern.sub(lambda _: block, md_text, count=1)
    return md_text + ("\n" if not md_text.endswith("\n\n") else "") + block


def video_id_from_filename(name: str) -> str | None:
    """Extract the video ID from a note named <date>_<videoId>_<title>.md
    (tiktok2note.py's default {{date}}_{{videoId}}_{{title}} title template).
    Returns None when the name doesn't match the pattern."""
    m = re.match(r"^\d{4}-\d{2}-\d{2}_(\d{15,25})(?=_|\.md$)", name)
    return m.group(1) if m else None


def tiktok_key(url: str) -> str:
    # Prefer the canonical /video/<id> if present
    m = re.search(r"/video/(\d+)", url)
    if m:
        return m.group(1)

    # Try to resolve the real video id via yt-dlp (no download)
    ytdlp, can_impersonate = ytdlp_cmd()
    probe_cmd = ytdlp + (["--impersonate", "chrome"] if can_impersonate else []) + ["-O", "%(id)s", url]
    code, out, _ = sh_capture(probe_cmd)
    vid = (out or "").strip()
    if code == 0 and vid:
        return vid

    # Fallback: stable hash of the URL without query/fragment
    base = url.split("?", 1)[0].split("#", 1)[0]
    import hashlib
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def sh_capture(cmd, cwd=None):
    p = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out, err = p.communicate()
    return p.returncode, out, err


# ═══════════════════════════════════════════════════════════════════════════
# Transcription (API call or --transcribe-script subprocess)
# ═══════════════════════════════════════════════════════════════════════════

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
            # Covers ConnectionError and ReadTimeout (server queues jobs one
            # at a time, so a long queue can outlast the 600s request timeout).
            raise RuntimeError(
                f"Faster Whisper Transcriber not reachable or timed out at {FASTER_WHISPER_URL}: {exc}"
            ) from exc

    if r.status_code != 200:
        raise RuntimeError(f"Faster Whisper error ({r.status_code}): {r.text[:500]}")

    result = r.json()
    return result.get("text", "").strip()


def transcribe_via_script(audio_path: Path, args) -> str:
    """Run transcribe.py (--transcribe-script) on *audio_path* and return the text.

    The subprocess runs with the script's own base directory as cwd, so the
    script's relative model cache follows it wherever it lives. Only the
    given script path is relied on — nothing about the original location."""
    script = Path(args.transcribe_script).resolve()
    cmd = [sys.executable, str(script), str(audio_path), args.model]
    if args.lang:
        cmd += ["-l", args.lang]
    if args.compute_type:
        cmd += ["-c", args.compute_type]
    if args.model_dir:
        cmd += ["--model-dir", str(Path(args.model_dir).expanduser().resolve())]

    # Force UTF-8 on the child's stdout: on Windows a piped stdout defaults to
    # cp1252, which would crash transcribe.py's print() on non-Latin text.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.Popen(
        cmd, cwd=str(script.parent), stdout=subprocess.PIPE,
        env=env, text=True, encoding="utf-8",
    )
    out, _ = p.communicate()  # stderr inherited → live faster-whisper progress
    if p.returncode != 0:
        # transcribe.py's own error message was already shown on stderr.
        raise RuntimeError(f"{script.name} failed with exit code {p.returncode}")
    return (out or "").strip()


def transcribe_audio(audio_path: Path, args) -> str:
    """Dispatch to the API or the --transcribe-script subprocess."""
    if args.transcribe_script:
        return transcribe_via_script(audio_path, args)
    return transcribe(audio_path, args.model, args.lang)


# ═══════════════════════════════════════════════════════════════════════════
# Download
# ═══════════════════════════════════════════════════════════════════════════

def download_wav(url: str, out_path: Path, args) -> bool:
    """Download to *out_path*; show yt-dlp live progress."""
    if out_path.exists():
        return True
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ytdlp, can_impersonate = ytdlp_cmd()
    cmd = ytdlp + [
        url,
        "--extract-audio", "--audio-format", "wav", "--audio-quality", "0",
        # TikTok's bytevc1 (h265) formats often lack audio despite claiming
        # aac, so prefer h264, then audio-only, then anything else.
        "-f", "b[vcodec^=h264]/ba/b",
        "--no-playlist",
        "--referer", "https://www.tiktok.com/",
        "--user-agent", args.user_agent,
        "--concurrent-fragments", "1",
        "--retries", str(args.retries),
        "--fragment-retries", str(args.fragment_retries),
        "--retry-sleep", str(args.retry_sleep),
        "--sleep-requests", str(args.sleep_requests),
    ]
    if args.limit_rate:
        cmd += ["--limit-rate", str(args.limit_rate)]
    cmd += ["-o", str(out_path.with_suffix(".%(ext)s"))]

    if can_impersonate:
        cmd += ["--impersonate", "chrome"]

    # Cookies: --cookies-file takes precedence; browser cookies are skipped
    # because Chrome's DPAPI encryption doesn't work with yt-dlp on Windows.
    if args.cookies_file:
        cmd += ["--cookies", args.cookies_file]

    return sh(cmd) == 0 and out_path.exists()


# ═══════════════════════════════════════════════════════════════════════════
# Per-file processing
# ═══════════════════════════════════════════════════════════════════════════

def process_one(md_path: Path, args, idx: int, total: int):
    name = md_path.name
    t_start = time.perf_counter()
    print(f"\n[{idx}/{total}] {name} — scanning")

    url = extract_url_from_frontmatter(md_path)
    if args.apply_existing:
        # Offline re-apply: fill fresh templates from existing transcripts
        # only — no download, no transcription server.
        return process_reapply(md_path, args, idx, total, name, url, t_start)
    if not url or "tiktok.com" not in url:
        print(f"[{idx}/{total}] {name} — no TikTok url; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    # Notes created by tiktok2note.py carry isSlideshow / isPrivate in the
    # frontmatter. Slideshows have no audio and private videos can't be
    # downloaded — never attempt to transcribe them (checked before any
    # network call or asset-folder creation).
    flags = frontmatter_flags(md_path)
    if flags.get("isSlideshow"):
        print(f"[{idx}/{total}] {name} — slideshow; no audio to transcribe; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start
    if flags.get("isPrivate"):
        print(f"[{idx}/{total}] {name} — private video; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    key = tiktok_key(url)
    md_dir = md_path.parent
    assets_dir = md_dir / args.assets_dirname
    assets_dir.mkdir(exist_ok=True)

    global_cache = Path(args.global_cache).expanduser().resolve()
    global_cache.mkdir(parents=True, exist_ok=True)
    cache_wav = global_cache / f"{key}.wav"
    local_wav = assets_dir / f"{key}.wav"
    local_txt = assets_dir / f"{key}.txt"

    md_text = md_path.read_text(encoding="utf-8", errors="ignore")

    # Skip notes that already have a real transcription. Fresh notes from
    # tiktok2note.py keep a literal {{transcription}} placeholder instead,
    # so those are processed (placeholder gets replaced) unless --force.
    if (not args.force) and "{{transcription}}" not in md_text and re.search(
        r"^##\s*Transcription\s*$", md_text, flags=re.M
    ):
        print(f"[{idx}/{total}] {name} — already has Transcription (use --force to redo); skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    # ── Download (with timing) ──────────────────────────────────────────
    t_dl = 0.0
    if not cache_wav.exists():
        print(f"[{idx}/{total}] {name} — downloading → cache/{cache_wav.name}")
        dl_start = time.perf_counter()
        ok = download_wav(url, cache_wav, args)
        t_dl = time.perf_counter() - dl_start
        if not ok:
            print(f"[{idx}/{total}] {name} — yt-dlp failed; check URL or connection")
            return "failed", t_dl, 0, 0, time.perf_counter() - t_start
    else:
        print(f"[{idx}/{total}] {name} — using cached audio {cache_wav.name}")

    if not local_wav.exists():
        if args.symlink:
            os.symlink(cache_wav, local_wav)
            print(f"[{idx}/{total}] {name} — symlinked audio into {assets_dir.name}/")
        else:
            shutil.copy2(cache_wav, local_wav)
            print(f"[{idx}/{total}] {name} — copied audio into {assets_dir.name}/")

    # ── Transcribe (API or --transcribe-script) ─────────────────────────
    t_tr = 0.0
    if local_txt.exists() and not args.force:
        transcript = local_txt.read_text(encoding="utf-8").strip()
        print(f"[{idx}/{total}] {name} — reused existing transcript file")
    else:
        engine = Path(args.transcribe_script).name if args.transcribe_script else "Faster Whisper"
        print(f"[{idx}/{total}] {name} — transcribing via {engine} ({args.model}) …")
        tr_start = time.perf_counter()
        try:
            transcript = transcribe_audio(local_wav, args)
        except RuntimeError as e:
            print(f"[{idx}/{total}] {name} — {e}")
            return "failed", t_dl, 0, 0, time.perf_counter() - t_start
        t_tr = time.perf_counter() - tr_start
        local_txt.write_text(transcript + "\n", encoding="utf-8")

    # ── Update MD ───────────────────────────────────────────────────────
    t_md = 0.0
    mdw_start = time.perf_counter()
    new_md = ensure_transcription_section(md_text, transcript, heading=args.heading)
    md_path.write_text(new_md, encoding="utf-8")
    t_md = time.perf_counter() - mdw_start
    t_total = time.perf_counter() - t_start

    print(
        f"[{idx}/{total}] {name} — ✅ done"
        f" | download {fmt_secs(t_dl)} • transcribe {fmt_secs(t_tr)}"
        f" • update {fmt_secs(t_md)} • total {fmt_secs(t_total)}"
    )
    return "ok", t_dl, t_tr, t_md, t_total


# ═══════════════════════════════════════════════════════════════════════════
# Offline re-apply (--apply-existing)
# ═══════════════════════════════════════════════════════════════════════════

def process_reapply(md_path: Path, args, idx: int, total: int, name: str,
                    url: str | None, t_start: float):
    """Fill fresh note templates from already-extracted transcripts, offline.

    The video ID is taken from the note filename (<date>_<videoId>_<title>.md,
    tiktok2note.py's default title template), falling back to the frontmatter
    URL; the transcript is read from _tiktok_assets/<videoId>.txt.  No
    download, no transcription server, no network."""
    flags = frontmatter_flags(md_path)
    if flags.get("isSlideshow"):
        print(f"[{idx}/{total}] {name} — slideshow; no audio; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start
    if flags.get("isPrivate"):
        print(f"[{idx}/{total}] {name} — private video; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    key = video_id_from_filename(name)
    if not key and url:
        key = tiktok_key(url)
    if not key:
        print(f"[{idx}/{total}] {name} — no video id in filename or url; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    local_txt = md_path.parent / args.assets_dirname / f"{key}.txt"
    if not local_txt.exists():
        print(f"[{idx}/{total}] {name} — no transcript file {local_txt.name}; skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    md_text = md_path.read_text(encoding="utf-8", errors="ignore")
    # Same "already has a real transcription" guard as the main path: fresh
    # notes keep the literal {{transcription}} placeholder, so they are
    # processed; filled notes are skipped unless --force.
    if (not args.force) and "{{transcription}}" not in md_text and re.search(
        r"^##\s*Transcription\s*$", md_text, flags=re.M
    ):
        print(f"[{idx}/{total}] {name} — already has Transcription (use --force to redo); skipped")
        return "skipped", 0, 0, 0, time.perf_counter() - t_start

    t_md = time.perf_counter()
    transcript = local_txt.read_text(encoding="utf-8").strip()
    new_md = ensure_transcription_section(md_text, transcript, heading=args.heading)
    md_path.write_text(new_md, encoding="utf-8")
    t_md = time.perf_counter() - t_md
    t_total = time.perf_counter() - t_start

    print(
        f"[{idx}/{total}] {name} — ✅ applied {local_txt.name}"
        f" | update {fmt_secs(t_md)} • total {fmt_secs(t_total)}"
    )
    return "ok", 0, 0, t_md, t_total


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    # Windows consoles default to cp1252, which can't encode the → / … used
    # in progress output; force UTF-8 so prints never crash on encoding.
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc not in ("utf-8", "utf8"):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(
        description="Download+transcribe TikTok URLs found in MD frontmatter"
        " and append '## Transcription'. With --apply-existing, instead"
        " re-apply existing _tiktok_assets/<videoId>.txt transcripts to fresh"
        " note templates offline."
    )
    p.add_argument("folder", help="Folder with .md files")
    p.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    p.add_argument("--force", action="store_true", help="Redo even if transcription exists")
    p.add_argument("--apply-existing", action="store_true",
                    help="Offline: re-apply existing _tiktok_assets/<videoId>.txt"
                         " transcripts to fresh note templates (<date>_<videoId>_<title>.md);"
                         " no download, no transcription")
    p.add_argument("--heading", default="Transcription")

    # Download
    p.add_argument("--browser", default="chrome",
                    help="Ignored (yt-dlp impersonation is used; cookies not needed)")
    p.add_argument("--cookies-file", default=None, help="cookies.txt for yt-dlp")
    p.add_argument("--limit-rate", default=None, help="e.g., 1M or 500K")
    p.add_argument("--retries", type=int, default=20)
    p.add_argument("--fragment-retries", type=int, default=20)
    p.add_argument("--retry-sleep", type=int, default=2)
    p.add_argument("--sleep-requests", type=int, default=1)
    p.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    )

    # Storage
    p.add_argument("--assets-dirname", default="_tiktok_assets",
                    help="Per-note folder for wav/txt")
    p.add_argument("--global-cache", default="~/.cache/tiktok2text",
                    help="Global cache for dedup across folders")
    p.add_argument("--symlink", action="store_true",
                    help="Symlink cache -> local assets (instead of copy)")

    # Transcription (Faster Whisper Transcriber)
    p.add_argument("--model", default="base",
                    help="tiny|tiny.en|base|base.en|small|small.en|medium|medium.en|large-v3|large-v3-turbo")
    p.add_argument("--lang", default="en")
    p.add_argument("--transcribe-script", default=None,
                    help="Path to transcribe/transcribe.py; when set, run that"
                         " script from its own base directory (cwd = script dir)"
                         " against the audio instead of calling the Faster Whisper"
                         " API. Only the given path is used, so the transcribe"
                         " folder can live anywhere")

    # Backward-compat flags (no-ops unless --transcribe-script is used)
    p.add_argument("--venv-dir", help="Ignored (no venv needed)")
    p.add_argument("--model-dir",
                    help="Model cache dir for faster-whisper; only used with"
                         " --transcribe-script (the API server manages its own models)")
    p.add_argument("--compute-type",
                    help="faster-whisper compute type; only used with"
                         " --transcribe-script (default int8)")

    args = p.parse_args()
    folder = Path(args.folder).expanduser().resolve()
    if not folder.exists():
        print(f"Folder not found: {folder}", file=sys.stderr)
        sys.exit(2)

    if args.transcribe_script:
        ts = Path(args.transcribe_script).expanduser().resolve()
        if not ts.is_file():
            print(f"--transcribe-script not found: {ts}", file=sys.stderr)
            sys.exit(2)
        args.transcribe_script = str(ts)

    md_files = list(folder.rglob("*.md") if args.recursive else folder.glob("*.md"))
    if not md_files:
        print("No .md files found.")
        return

    total = len(md_files)
    print(f"Found {total} .md files in {folder}")
    if args.apply_existing:
        print("Mode: --apply-existing (offline re-apply from _tiktok_assets/<videoId>.txt)")
    elif args.transcribe_script:
        print(f"Mode: transcribe via script {args.transcribe_script} (cwd = its base dir)")
    overall_start = time.perf_counter()
    ok = sk = fail = 0
    tdl = ttr = tmd = ttot = 0.0

    # Handle Ctrl+C gracefully
    def handle_sigint(sig, frame):
        elapsed = fmt_secs(time.perf_counter() - overall_start)
        print(
            f"\n\nInterrupted. Partial summary after {elapsed}:"
            f" processed={ok + sk + fail}, ok={ok}, skipped={sk}, failed={fail}"
        )
        sys.exit(1)
    signal.signal(signal.SIGINT, handle_sigint)

    for i, md in enumerate(md_files, 1):
        status, dl, tr, mdw, tot = process_one(md, args, i, total)
        if status == "ok":
            ok += 1
            tdl += dl; ttr += tr; tmd += mdw; ttot += tot
        elif status == "skipped":
            sk += 1
        else:
            fail += 1

    overall = time.perf_counter() - overall_start
    print("\nSummary:")
    print(f"  Processed: {total}  (ok={ok}, skipped={sk}, failed={fail})")
    print(
        f"  Time (sum over ok files):"
        f" download {fmt_secs(tdl)} • transcribe {fmt_secs(ttr)}"
        f" • update {fmt_secs(tmd)} • total {fmt_secs(ttot)}"
    )
    print(f"  Wall time: {fmt_secs(overall)}")


if __name__ == "__main__":
    main()
