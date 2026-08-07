import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

WHISPER_SERVER_URL: str = os.getenv("WHISPER_SERVER_URL", "http://127.0.0.1:8080")

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

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
TRANSCRIPT_DIR = BASE_DIR / "data" / "transcripts"
