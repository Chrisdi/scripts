# faster-whisper transcription scripts

Two standalone scripts for transcribing audio with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## 1. Set up the environment

```bash
python setup_faster_whisper.py
```

Creates a venv (`.faster-whisper-venv`) and installs `faster-whisper` into it.

Optionally pre-download a model:

```bash
python setup_faster_whisper.py --model base
```

Available models: `tiny`, `base`, `small`, `medium`, `large`.

## 2. Transcribe an audio file

```bash
python transcribe.py <audio_file> <model_name>
```

Example:

```bash
python transcribe.py speech.wav base
```

Prints the transcription to stdout.

### Options

- `-l, --language` — language code (e.g. `en`); auto-detected if omitted
- `-c, --compute-type` — inference compute type (default: `int8`)
- `-d, --device` — `cpu` or `cuda` (default: `cpu`)
- `--model-dir` — where models are cached/loaded from (default: `./.models`)
- `-o, --output` — also write the transcription to a file

### Note

Run `transcribe.py` with the venv's Python (created by `setup_faster_whisper.py`) so `faster-whisper` is available, e.g. on Windows:

```powershell
.faster-whisper-venv\Scripts\python.exe transcribe.py speech.wav base
```
