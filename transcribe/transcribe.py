#!/usr/bin/env python3
"""
Transcribe an audio file using faster-whisper.

Usage:
    python transcribe.py <audio_file> <model_name> [options]

Example:
    python transcribe.py speech.wav base
    python transcribe.py speech.wav small --language en --output out.txt

Requires faster-whisper to be installed (see setup_faster_whisper.py).
"""

import argparse
import sys
from pathlib import Path
from typing import Optional


def transcribe(audio_path: Path, model_name: str, compute_type: str = "int8",
                language: Optional[str] = None, model_dir: Optional[Path] = None,
                device: str = "cpu") -> str:
    """Run faster-whisper transcription and return the full text."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "faster-whisper is not installed. Run setup_faster_whisper.py first, "
            "or install it with: pip install faster-whisper",
            file=sys.stderr,
        )
        sys.exit(1)

    if model_dir:
        model_dir.mkdir(parents=True, exist_ok=True)

    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=str(model_dir) if model_dir else None,
    )

    segments, _info = model.transcribe(str(audio_path), language=language)
    return "".join(segment.text.strip() + " " for segment in segments).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe an audio file with faster-whisper")
    parser.add_argument("audio_file", help="Path to the audio file to transcribe")
    parser.add_argument("model_name", help="Whisper model name (e.g. tiny, base, small, medium, large)")
    parser.add_argument("-l", "--language", default=None, help="Language code (e.g. en). Auto-detected if omitted")
    parser.add_argument("-c", "--compute-type", default="int8", help="Compute type for inference (default: int8)")
    parser.add_argument("-d", "--device", default="cpu", help="Device to run on (default: cpu)")
    parser.add_argument("--model-dir", default=None, help="Directory to cache/load models from (default: ./.models)")
    parser.add_argument("-o", "--output", default=None, help="Write transcription to this file in addition to stdout")

    args = parser.parse_args()

    audio_path = Path(args.audio_file).resolve()
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    model_dir = Path(args.model_dir).resolve() if args.model_dir else Path(__file__).resolve().parent / ".models"

    text = transcribe(
        audio_path,
        args.model_name,
        compute_type=args.compute_type,
        language=args.language,
        model_dir=model_dir,
        device=args.device,
    )

    print(text)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(text + "\n", encoding="utf-8")
        print(f"Saved: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
