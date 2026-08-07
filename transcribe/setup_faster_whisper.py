#!/usr/bin/env python3
"""
Set up a Python virtual environment with faster-whisper installed.

Creates a venv (default: .faster-whisper-venv next to this script),
upgrades pip, and installs faster-whisper. Optionally pre-downloads a
model so the first transcription run doesn't have to fetch it.

Usage:
    python setup_faster_whisper.py
    python setup_faster_whisper.py --model base
    python setup_faster_whisper.py --venv-dir /path/to/venv
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


def get_script_dir() -> Path:
    """Get the directory where this script is located."""
    return Path(__file__).resolve().parent


def get_venv_path(venv_dir: Optional[str]) -> Path:
    """Get path to the Python venv."""
    if venv_dir:
        return Path(venv_dir).resolve()
    return get_script_dir() / ".faster-whisper-venv"


def get_python_executable(venv_path: Path) -> Path:
    """Get path to the Python executable inside the venv."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def ensure_venv(venv_path: Path) -> Path:
    """Ensure the venv exists with faster-whisper installed. Returns the venv's python executable."""
    python_exe = get_python_executable(venv_path)

    if not python_exe.exists():
        print(f"Creating Python virtual environment at {venv_path}")
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)

        print("Upgrading pip...")
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-U", "pip", "wheel", "setuptools"],
            check=True,
            stdout=subprocess.DEVNULL,
        )

    result = subprocess.run([str(python_exe), "-c", "import faster_whisper"], capture_output=True)
    if result.returncode != 0:
        print("Installing faster-whisper...")
        subprocess.run(
            [str(python_exe), "-m", "pip", "install", "-q", "faster-whisper>=1.0.0"],
            check=True,
        )
        print("faster-whisper installed successfully")
    else:
        print("faster-whisper is already installed")

    return python_exe


def download_model(python_exe: Path, model_name: str, model_dir: Path) -> None:
    """Pre-download a faster-whisper model so it's cached for later use."""
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nDownloading '{model_name}' model to {model_dir}...")
    download_script = f"""
from faster_whisper import WhisperModel
import sys

try:
    WhisperModel("{model_name}", device="cpu", compute_type="int8", download_root=r"{model_dir}")
    print("Model downloaded and verified successfully!")
except Exception as e:
    print(f"Error downloading model: {{e}}")
    sys.exit(1)
"""
    result = subprocess.run([str(python_exe), "-c", download_script], capture_output=False)
    if result.returncode != 0:
        print(f"Failed to download model '{model_name}'", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up a faster-whisper Python environment")
    parser.add_argument("--venv-dir", default=None, help="Where to create the venv (default: ./.faster-whisper-venv)")
    parser.add_argument("--model-dir", default=None, help="Where to cache downloaded models (default: ./.models)")
    parser.add_argument("--model", default=None,
                        choices=["tiny", "base", "small", "medium", "large"],
                        help="Optionally pre-download a model")
    args = parser.parse_args()

    venv_path = get_venv_path(args.venv_dir)
    model_dir = Path(args.model_dir).resolve() if args.model_dir else get_script_dir() / ".models"

    python_exe = ensure_venv(venv_path)

    if args.model:
        download_model(python_exe, args.model, model_dir)

    print(f"\n✓ Environment ready: {python_exe}")
    print(f"  Run transcriptions with:")
    print(f'  "{python_exe}" transcribe.py <audio_file> <model_name>')


if __name__ == "__main__":
    main()
