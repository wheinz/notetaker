# notetaker

Dual-channel meeting note taker: records your microphone (left channel) and system/meeting audio via BlackHole (right channel) into a stereo WAV file, then transcribes both channels through a [whisper.cpp](https://github.com/ggerganov/whisper.cpp) server and produces a combined, timestamped Markdown transcript.

## Prerequisites

- **Python 3.13+** (managed via [uv](https://docs.astral.sh/uv/))
- **ffmpeg** — available on PATH
- **BlackHole** (macOS only) — virtual audio driver for capturing system audio
- A locally built **whisper.cpp** checkout with the turbo and VAD models

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

The notetaker starts a temporary server on port 8082. Override paths or the
port in `.env` only if your checkout differs from the defaults:

```
WHISPER_SERVER_BIN=~/Documents/Github/whisper.cpp/build/bin/whisper-server
WHISPER_MODELS_DIR=~/Documents/Github/whisper.cpp/models
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

### 6. Build stock whisper.cpp and download models

```bash
git clone https://github.com/ggerganov/whisper.cpp.git
cd whisper.cpp
cmake -B build
cmake --build build --config Release -j --target whisper-server
bash ./models/download-ggml-model.sh large-v3-turbo
bash ./models/download-vad-model.sh silero-v6.2.0
```

The CLI starts this server only while transcribing, using the turbo model and
VAD. It runs on port 8082 so it does not interfere with
the persistent small-model server used by the separate dictation project.

## Usage

### Verify your setup

```bash
uv run main.py devices
```

This lists available audio devices, checks for BlackHole, and verifies the
on-demand Whisper binary and models.

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

Meeting transcription uses `large-v3-turbo` by default. A different installed
model can be selected explicitly:

```bash
uv run main.py transcribe data/raw/meeting_20260730_135948.wav --model medium
```

The temporary server is stopped after the transcript is written, including when
transcription fails.

Transcripts are written to `data/transcripts/`.

By default, transcription removes likely speaker echo duplicates from the
microphone channel only when a mic segment overlaps system audio and the text is
very similar. Tune or disable this with `ECHO_DEDUP_*` settings in `.env`.

Whisper occasionally hallucinates the same phrase repeatedly on silence (a
"looping" failure). Two safeguards are on by default: segments with a high
`no_speech_prob` are dropped, and consecutive near-identical segments within a
channel are collapsed to a single occurrence. Tune these with the
`NO_SPEECH_FILTER_*` and `REPETITION_DEDUP_*` settings.

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
| `WHISPER_SERVER_PORT` | `8082` | Port for the temporary meeting-transcription server |
| `WHISPER_SERVER_BIN` | `~/Documents/Github/whisper.cpp/build/bin/whisper-server` | Stock server binary |
| `WHISPER_MODELS_DIR` | `~/Documents/Github/whisper.cpp/models` | Whisper model directory |
| `AGGREGATE_DEVICE_MATCH` | `aggregate` | Substring to find the aggregate input device |
| `BLACKHOLE_DEVICE_MATCH` | `blackhole` | Substring to find BlackHole |
| `MIC_CHANNEL` | `0` | Channel index for microphone |
| `SYSTEM_CHANNELS` | `1,2` | Channel indices for system audio |
| `ECHO_DEDUP_ENABLED` | `true` | Remove likely speaker echo duplicates from mic transcript segments |
| `ECHO_DEDUP_SIMILARITY` | `0.72` | Minimum text similarity for echo deduplication |
| `REPETITION_DEDUP_ENABLED` | `true` | Collapse consecutive near-identical hallucinated segments per channel |
| `REPETITION_DEDUP_SIMILARITY` | `0.85` | Minimum text similarity for repetition deduplication |
| `NO_SPEECH_FILTER_ENABLED` | `true` | Drop segments with high `no_speech_prob` |
| `NO_SPEECH_THRESHOLD` | `0.6` | `no_speech_prob` cutoff for the silence filter |
| `VAD_ENABLED` | `true` | Request voice activity detection from the whisper.cpp server |

## How it works

1. **Recording**: `sounddevice` captures from the aggregate device — mic on channel 0, system audio on channels 1–2. Averages the system channels and writes a stereo WAV (left = mic, right = system).
2. **Transcription**: the CLI starts an isolated stock whisper.cpp server with `large-v3-turbo`; `ffmpeg` splits the stereo WAV into two 16 kHz mono files, then both are sent to `/inference` in parallel.
3. **Merging**: Timestamped segments from both channels are interleaved by start time and rendered as Markdown, after filtering silence, collapsing hallucinated repetitions, and removing echo duplicates.
