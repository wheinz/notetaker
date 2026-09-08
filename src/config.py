import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

WHISPER_SERVER_URL: str = os.getenv("WHISPER_SERVER_URL", "http://127.0.0.1:8080")
WHISPER_LAUNCH_AGENT: Path = Path(
    os.getenv(
        "WHISPER_LAUNCH_AGENT",
        Path.home() / "Library/LaunchAgents/com.whisper.cpp.server.plist",
    )
).expanduser()
WHISPER_MODELS_DIR: Path = Path(
    os.getenv("WHISPER_MODELS_DIR", Path.home() / "Documents/Github/whisper.cpp/models")
).expanduser()

# Audio device identification (case-insensitive substring match)
AGGREGATE_DEVICE_MATCH: str = os.getenv("AGGREGATE_DEVICE_MATCH", "aggregate")
BLACKHOLE_DEVICE_MATCH: str = os.getenv("BLACKHOLE_DEVICE_MATCH", "blackhole")

# Channel map within the aggregate device (as built in Audio MIDI Setup):
# channel 0 = microphone, channels 1..2 = BlackHole L/R
MIC_CHANNEL: int = int(os.getenv("MIC_CHANNEL", "0"))
SYSTEM_CHANNELS: tuple[int, ...] = tuple(
    int(c) for c in os.getenv("SYSTEM_CHANNELS", "1,2").split(",")
)

# Echo cancellation: subtracts speaker output captured by the microphone
# using the system audio channel as reference (NLMS adaptive filter).
ECHO_CANCEL_ENABLED: bool = os.getenv("ECHO_CANCEL_ENABLED", "").lower() in (
    "1", "true", "yes",
)
ECHO_CANCEL_FILTER_LENGTH: int = int(os.getenv("ECHO_CANCEL_FILTER_LENGTH", "128"))
ECHO_CANCEL_MU: float = float(os.getenv("ECHO_CANCEL_MU", "0.1"))

# Transcript-level echo deduplication: if mic and system-audio segments overlap,
# remove mic segments whose text is very similar to the system-audio segment.
ECHO_DEDUP_ENABLED: bool = os.getenv("ECHO_DEDUP_ENABLED", "true").lower() in (
    "1", "true", "yes",
)
ECHO_DEDUP_SIMILARITY: float = float(os.getenv("ECHO_DEDUP_SIMILARITY", "0.72"))
ECHO_DEDUP_OVERLAP_PADDING: float = float(os.getenv("ECHO_DEDUP_OVERLAP_PADDING", "0.75"))
ECHO_DEDUP_MIN_WORDS: int = int(os.getenv("ECHO_DEDUP_MIN_WORDS", "4"))

# Repetition deduplication: Whisper sometimes hallucinates the same phrase
# repeatedly on silence. Collapse consecutive near-identical segments within
# a single channel, keeping only the first occurrence.
REPETITION_DEDUP_ENABLED: bool = os.getenv(
    "REPETITION_DEDUP_ENABLED", "true"
).lower() in ("1", "true", "yes")
REPETITION_DEDUP_SIMILARITY: float = float(
    os.getenv("REPETITION_DEDUP_SIMILARITY", "0.85")
)

# Silence filtering: drop segments whose no_speech_prob is at or above this
# threshold. whisper.cpp reports this per segment in verbose_json output.
NO_SPEECH_FILTER_ENABLED: bool = os.getenv(
    "NO_SPEECH_FILTER_ENABLED", "true"
).lower() in ("1", "true", "yes")
NO_SPEECH_THRESHOLD: float = float(os.getenv("NO_SPEECH_THRESHOLD", "0.6"))

# Voice activity detection: when enabled, the whisper.cpp server skips
# non-speech audio entirely (requires a Silero VAD model on the server).
VAD_ENABLED: bool = os.getenv("VAD_ENABLED", "true").lower() in (
    "1", "true", "yes",
)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
TRANSCRIPT_DIR = BASE_DIR / "data" / "transcripts"
