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

To suppress hallucinated segments on silence, enable voice activity detection by
downloading the Silero VAD model and passing it to the server:

```bash
bash ./models/download-vad-model.sh silero-v6.2.0
./whisper-server -m models/ggml-base.en.bin -vm models/ggml-silero-v6.2.0.bin
```

The notetaker requests VAD per transcription when `VAD_ENABLED=true` (default).
If you run the server via launchd, add `-vm /path/to/ggml-silero-v6.2.0.bin` to
its `ProgramArguments` and `launchctl kickstart -k gui/$(id -u)/<label>`.

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

For higher-quality meeting transcription, temporarily switch the launchd-managed
`whisper-server` to a larger local model for just this run:

```bash
uv run main.py transcribe data/raw/meeting_20260730_135948.wav --model medium
```

After the transcript is written, the CLI restores the model that was active
before the command started. This expects `ggml-medium.bin` to exist in
`~/Documents/Github/whisper.cpp/models/`, unless `WHISPER_MODELS_DIR` points
somewhere else. The LaunchAgent path can be overridden with
`WHISPER_LAUNCH_AGENT`.

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
| `WHISPER_SERVER_URL` | `http://127.0.0.1:8080` | URL of the whisper.cpp server |
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
2. **Transcription**: `ffmpeg` splits the stereo WAV into two 16 kHz mono files, then both are sent to the whisper.cpp `/inference` endpoint in parallel.
3. **Merging**: Timestamped segments from both channels are interleaved by start time and rendered as Markdown, after filtering silence, collapsing hallucinated repetitions, and removing echo duplicates.
