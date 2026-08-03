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

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
TRANSCRIPT_DIR = BASE_DIR / "data" / "transcripts"
