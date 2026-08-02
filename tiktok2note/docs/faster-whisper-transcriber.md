Faster-Whisper Transcriber - Server API Guide
===============================================

## 1. Starting the Server

1. Launch the Faster-Whisper Transcriber GUI.
2. Click the Settings (gear) icon.
3. In the Server Mode group box, flip the toggle from Off to On and set the Port (default: 8765).
4. Click Update Settings.
5. The status bar shows "... | server: on (8765)" and the voice recorder is disabled while running.

The server binds to 0.0.0.0, so it is accessible at http://127.0.0.1:8765 locally and at http://<your-ip>:8765 from other machines on your network.

This backend uses the faster-whisper library, which exposes the standard Whisper knobs (beam_size, vad_filter, condition_on_previous_text, word_timestamps, temperature, ...). The server surfaces the ones that matter for integration.

## 2. Endpoints

| Endpoint         | Method | Description                                              |
|------------------|--------|----------------------------------------------------------|
| /health          | GET    | Check if the server is running                           |
| /status          | GET    | Server status, queue depth, whether transcription active |
| /models          | GET    | List all models and whether they support translation     |
| /transcribe      | POST   | Transcribe audio from a file upload (multipart form)     |
| /transcribe/raw  | POST   | Transcribe audio from base64-encoded data (JSON body)    |

Interactive docs: http://127.0.0.1:8765/docs (Swagger) and http://127.0.0.1:8765/redoc (ReDoc)

## 3. Quick Start

```python
import requests

response = requests.post(
    "http://127.0.0.1:8765/transcribe",
    files={"audio": open("my_audio.mp3", "rb")},
)

print(response.json()["text"])
```

The server uses whatever model, quantization, task, and whisper params were configured in the GUI. Language defaults to auto-detect.

## 4. Accepted Audio Input Formats

### 4a. Audio Files (most common)
Supported: .mp3, .wav, .flac, .m4a, .ogg, .aac, .wma, .webm, .mp4, .mkv, .avi, .asf, .amr

```python
with open("recording.wav", "rb") as f:
    r = requests.post(
        "http://127.0.0.1:8765/transcribe",
        files={"audio": ("recording.wav", f, "audio/wav")},
    )
```

### 4b. NumPy Arrays
Serialize with np.save() and upload the .npy file. Pass sample_rate if different from 16000.

### 4c. PyTorch Tensors
Serialize with torch.save() and upload the .pt file.

### 4d. Raw PCM Bytes
```python
data = {"audio_format": "pcm", "sample_rate": "16000", "dtype": "float32"}
# dtype also supports: int16, int32, float64
```

### 4e. Base64-Encoded Data (JSON endpoint /transcribe/raw)
```python
r = requests.post(
    "http://127.0.0.1:8765/transcribe/raw",
    json={"audio_data": b64_string, "audio_format": "numpy", "sample_rate": 16000},
)
```

## 5. Settings You Can Control

Every setting is optional.

| Parameter                  | Type    | Description                                                                                                                       | Values                                                                 |
|----------------------------|---------|-----------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| model                      | string  | Whisper checkpoint name                                                                                                           | "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium",   |
|                            |         |                                                                                                                                   | "medium.en", "large-v3", "large-v3-turbo", "distil-whisper-large-v3",  |
|                            |         |                                                                                                                                   | "distil-whisper-medium.en", "distil-whisper-small.en"                  |
| quantization               | string  | CTranslate2 compute_type                                                                                                          | "float32", "float16", "bfloat16", "int8", "int8_float16", ...          |
| device                     | string  | CPU or GPU                                                                                                                        | "cuda", "cpu"                                                          |
| language                   | string  | ISO 639-1 code. Omit or empty to auto-detect.                                                                                     | "en", "fr", "es", "de", "zh", ... (99 Whisper languages)               |
| task_mode                  | string  | Transcribe or translate to English                                                                                                | "transcribe", "translate"                                              |
| include_timestamps         | bool    | Include segments with start/end times. False -> segments: []                                                                      | "true", "false"                                                        |
| word_timestamps            | bool    | Forwarded to faster-whisper (word-level timings inside segments)                                                                  | "true", "false"                                                        |
| beam_size                  | int     | Decoding beam width                                                                                                               | 1-20 (default 5)                                                       |
| vad_filter                 | bool    | Silero VAD preprocessing. Forced on when batch_size > 1.                                                                          | "true", "false"                                                        |
| condition_on_previous_text | bool    | Use previous segment output as context                                                                                            | "true", "false"                                                        |
| batch_size                 | int     | >1 uses BatchedInferencePipeline with tuned VAD                                                                                   | 1-128 (default 1)                                                      |
| audio_format               | string  | Override input format auto-detection                                                                                              | "auto", "file", "numpy", "tensor", "pcm"                               |
| sample_rate                | int     | Sample rate of raw audio input                                                                                                    | "16000", "22050", "44100", "48000"                                     |
| dtype                      | string  | Data type for raw PCM input                                                                                                       | "float32", "float64", "int16", "int32"                                 |

Important: When batch_size > 1 the server forces vad_filter=true and applies tuned VAD parameters required by BatchedInferencePipeline. You cannot disable VAD while batching.

### Example with Custom Settings

```python
with open("lecture.mp3", "rb") as f:
    r = requests.post(
        "http://127.0.0.1:8765/transcribe",
        files={"audio": ("lecture.mp3", f, "audio/mpeg")},
        data={
            "model": "large-v3",
            "quantization": "float16",
            "device": "cuda",
            "task_mode": "transcribe",
            "language": "en",
            "include_timestamps": "true",
            "beam_size": "5",
            "vad_filter": "true",
            "batch_size": "8",
        },
    )
```

## 6. Response Format

### 6a. Plain text (include_timestamps=false)
```json
{
    "text": "Good morning everyone...",
    "segments": [],
    "language": "en",
    "duration": 138.135,
    "task": "transcribe",
    "model_used": "large-v3 - float16",
    "processing_time_seconds": 2.418
}
```

### 6b. With timestamps (include_timestamps=true)
```json
{
    "text": "Good morning everyone. Today we'll be discussing...",
    "segments": [
        {"start": 0.081, "end": 4.862, "text": " Good morning everyone. Today we'll be discussing"},
        {"start": 4.862, "end": 8.241, "text": " the quarterly results..."}
    ],
    "language": "en",
    "duration": 138.135,
    "task": "transcribe",
    "model_used": "large-v3 - float16",
    "processing_time_seconds": 3.012
}
```

### 6c. Field Reference

| Field                   | Type   | Always | Description                                           |
|-------------------------|--------|--------|-------------------------------------------------------|
| text                    | string | Yes    | Full transcription as newline-joined string           |
| segments                | array  | Yes    | Whisper segments. Empty [] when timestamps off.       |
| segments[].start        | float  | -      | Segment start time in seconds                         |
| segments[].end          | float  | -      | Segment end time in seconds                           |
| segments[].text         | string | -      | Transcribed text (faster-whisper leaves leading space)|
| language                | string | Yes    | Detected or echoed ISO code                           |
| duration                | float  | Yes    | Duration of processed audio in seconds                |
| task                    | string | Yes    | "transcribe" or "translate"                           |
| model_used              | string | Yes    | Full model key, e.g. "large-v3 - float16"            |
| processing_time_seconds | float  | Yes    | How long the transcription took                       |

## 7. Model Notes

Uses faster-whisper with CTranslate2-converted checkpoints from HuggingFace under ctranslate2-4you/whisper-<model>-ct2-<quantization> (or distil-whisper-<model>-ct2-<quantization> for Distil variants).

| Model family                                 | English-only | Translation | Notes                                        |
|----------------------------------------------|--------------|-------------|----------------------------------------------|
| large-v3 / large-v3-turbo                    | No           | Yes         | Multilingual; turbo has fewer decoder layers |
| medium / small / base / tiny                 | No           | Yes         | Multilingual; smaller = faster               |
| medium.en / small.en / base.en / tiny.en     | Yes          | No          | English-only; pass language="en"             |
| distil-whisper-large-v3 / medium.en / small.en | Varies     | No          | Distilled variants: faster, English-focused  |

Important: .en models and all Distil variants DO NOT support translation. Requesting task_mode="translate" on one returns HTTP 500.

## 8. Checking Server Status

### Health Check
```python
r = requests.get("http://127.0.0.1:8765/health")  # -> {"status": "ok"}
```

### Server Status
```python
status = requests.get("http://127.0.0.1:8765/status").json()
# -> {"server_running": true, "queue_depth": 0, "transcription_active": false}
```

### List Models
```python
models = requests.get("http://127.0.0.1:8765/models").json()
# keyed by model name: {"large-v3": {"name": "large-v3", "supports_translation": true}, ...}
```

Note: Unlike the WhisperS2T sister project, this /models endpoint returns one entry per base model name, not per (name, quantization) pair. Use the quantization parameter on /transcribe to pick precision.

## 9. Request Queuing

The server processes one transcription at a time. Multiple concurrent requests are queued and served in order; each client blocks on its own result.

## 10. Using curl

```bash
curl http://127.0.0.1:8765/health
curl -F "audio=@my_audio.mp3" http://127.0.0.1:8765/transcribe
curl -F "audio=@my_audio.mp3" \
     -F "model=large-v3" \
     -F "quantization=float16" \
     -F "task_mode=transcribe" \
     -F "language=en" \
     -F "include_timestamps=true" \
     -F "beam_size=5" \
     http://127.0.0.1:8765/transcribe
```

## 11. Error Handling

| Code | detail Type | Meaning      | What To Do                                        |
|------|-------------|--------------|---------------------------------------------------|
| 200  | -           | Success      | Use result["text"] and result["segments"]         |
| 400  | string      | Bad input    | Fix model, language, task, or audio               |
| 422  | array       | Missing field| Check that audio is included                      |
| 500  | string      | Model error  | Check VRAM or model/task compatibility            |
| 503  | string      | Server stop  | Wait and retry                                    |

## 12. Complete Example

```python
import requests
from pathlib import Path

SERVER = "http://127.0.0.1:8765"
AUDIO_DIR = Path("./my_audio_files")

if requests.get(f"{SERVER}/health").status_code != 200:
    print("Server is not running!")
    exit(1)

for audio_file in sorted(AUDIO_DIR.glob("*.mp3")):
    print(f"Transcribing: {audio_file.name}...", end=" ", flush=True)
    with open(audio_file, "rb") as f:
        r = requests.post(
            f"{SERVER}/transcribe",
            files={"audio": (audio_file.name, f, "audio/mpeg")},
            data={"language": "en", "beam_size": "5"},
        )
    if r.status_code == 200:
        result = r.json()
        output_file = audio_file.with_suffix(".txt")
        output_file.write_text(result["text"], encoding="utf-8")
        print(f"Done ({result['duration']:.1f}s audio in {result['processing_time_seconds']:.1f}s)")
    else:
        print(f"Failed: {r.json().get('detail', 'Unknown error')}")
```
