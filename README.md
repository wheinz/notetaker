# notetaker

Dual-channel meeting note taker: records your microphone (left channel) and system/meeting audio via BlackHole (right channel) into a stereo WAV file, then transcribes both channels through a [whisper.cpp](https://github.com/ggerganov/whisper.cpp) server and produces a combined, timestamped Markdown transcript.

## Prerequisites

- **Python 3.13+** (managed via [uv](https://docs.astral.sh/uv/))
- **ffmpeg** — available on PATH
- **BlackHole** (macOS only) — virtual audio driver for capturing system audio
- **whisper.cpp server** — running locally with a model loaded

## Installation

### 1. Clone the repo

```bash
git clone git@github.com:thomaswever/notetaker.git
cd notetaker
```

### 2. Install Python dependencies

```bash
uv sync
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` if your whisper.cpp server is running on a different host or port:

```
WHISPER_SERVER_URL=http://127.0.0.1:8080
```

### 4. Install BlackHole

```bash
brew install blackhole-2ch
```

### 5. Set up audio routing (one-time macOS setup)

1. Open **Audio MIDI Setup** (Applications > Utilities).
2. Click **+** → **Create Multi-Output Device**:
   - Check your listening device (speakers or AirPods) **and** BlackHole 2ch.
   - Rebuild this if you switch listening devices — membership is static.
3. Click **+** → **Create Aggregate Device**:
   - Check your microphone (e.g., MacBook Pro Microphone) **and** BlackHole 2ch.
   - Enable **Drift Correction** for BlackHole.
4. Go to **System Settings > Sound > Output** and select the Multi-Output Device.

### 6. Build and run whisper.cpp server

```bash
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
make whisper-server
bash ./models/download-ggml-model.sh base.en
./whisper-server -m models/ggml-base.en.bin
```

For parallel transcription of both audio channels, start the server with:

```bash
./whisper-server -m models/ggml-base.en.bin -np 2
```

## Usage

### Verify your setup

```bash
uv run main.py devices
```

This lists available audio devices, checks for BlackHole, and tests the whisper.cpp server connection.

### Record a meeting

```bash
uv run main.py record
```

Press **Ctrl+C** to stop recording. Files are saved to `data/raw/`.

To specify a custom filename:

```bash
uv run main.py record --name standup
```

### Transcribe a recording

```bash
uv run main.py transcribe data/raw/meeting_20260730_135948.wav
```

Optionally specify a language:

```bash
uv run main.py transcribe data/raw/meeting_20260730_135948.wav --language en
```

Transcripts are written to `data/transcripts/`.

### Run tests

```bash
uv run pytest
```

## Output format

Transcripts are Markdown files with interleaved, timestamped segments from both channels:

```markdown
# Meeting 2026-07-30 13:59

**[00:00:05] Me:** I think we should prioritize the API work.
**[00:00:10] Others:** Agreed, let's scope it for the next sprint.
**[00:00:18] Me:** I'll start on the design doc tomorrow.
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `WHISPER_SERVER_URL` | `http://127.0.0.1:8080` | URL of the whisper.cpp server |
| `AGGREGATE_DEVICE_MATCH` | `aggregate` | Substring to find the aggregate input device |
| `BLACKHOLE_DEVICE_MATCH` | `blackhole` | Substring to find BlackHole |
| `MIC_CHANNEL` | `0` | Channel index for microphone |
| `SYSTEM_CHANNELS` | `1,2` | Channel indices for system audio |

## How it works

1. **Recording**: `sounddevice` captures from the aggregate device — mic on channel 0, system audio on channels 1–2. Averages the system channels and writes a stereo WAV (left = mic, right = system).
2. **Transcription**: `ffmpeg` splits the stereo WAV into two 16 kHz mono files, then both are sent to the whisper.cpp `/inference` endpoint in parallel.
3. **Merging**: Timestamped segments from both channels are interleaved by start time and rendered as Markdown.
