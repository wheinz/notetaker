import logging
import math
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from . import config

logger = logging.getLogger(__name__)

SETUP_INSTRUCTIONS = """\
One-time audio routing setup:

  1. brew install blackhole-2ch
  2. Open "Audio MIDI Setup" -> '+' -> "Create Multi-Output Device":
     check your listening device (speakers or AirPods) AND BlackHole 2ch.
     Rebuild this if you switch listening devices — membership is static.
  3. "Audio MIDI Setup" -> '+' -> "Create Aggregate Device":
     check "MacBook Pro Microphone" AND "BlackHole 2ch",
     enable "Drift Correction" for BlackHole.
  4. System Settings -> Sound -> Output -> select the Multi-Output Device.

Then run `uv run main.py devices` to verify.
"""

SILENCE_PEAK_THRESHOLD = 10 ** (-45 / 20)  # -45 dBFS


@dataclass
class DeviceInfo:
    index: int
    name: str
    max_input_channels: int
    default_samplerate: float


@dataclass
class _Levels:
    mic_rms: float = 0.0
    sys_rms: float = 0.0
    mic_peak: float = 0.0
    sys_peak: float = 0.0


def find_input_device(match: str) -> DeviceInfo | None:
    for index, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and match.lower() in dev["name"].lower():
            return DeviceInfo(
                index,
                dev["name"],
                dev["max_input_channels"],
                dev["default_samplerate"],
            )
    return None


def blackhole_present() -> bool:
    return any(
        config.BLACKHOLE_DEVICE_MATCH.lower() in dev["name"].lower()
        for dev in sd.query_devices()
    )


def default_output_name() -> str:
    try:
        return sd.query_devices(sd.default.device[1])["name"]
    except (sd.PortAudioError, IndexError, TypeError):
        return "unknown"


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))


def _db_scale(rms: float) -> float:
    db = 20 * math.log10(max(rms, 1e-9))
    return max(0.0, min(1.0, (db + 60.0) / 60.0))


def _bar(level: float, width: int = 12) -> str:
    filled = round(level * width)
    return "█" * filled + "░" * (width - filled)


def _meter_line(elapsed: float, levels: _Levels) -> str:
    hours, rem = divmod(int(elapsed), 3600)
    minutes, secs = divmod(rem, 60)
    return (
        f"● REC {hours:02d}:{minutes:02d}:{secs:02d}  "
        f"Me {_bar(_db_scale(levels.mic_rms))}  "
        f"Others {_bar(_db_scale(levels.sys_rms))}"
    )


def record(name: str | None = None) -> Path | None:
    device = find_input_device(config.AGGREGATE_DEVICE_MATCH)
    if device is None:
        if not blackhole_present():
            print("BlackHole is not installed, and no aggregate device was found.\n")
        else:
            print(
                "BlackHole is installed, but no aggregate input device matching "
                f"'{config.AGGREGATE_DEVICE_MATCH}' was found.\n"
            )
        print(SETUP_INSTRUCTIONS)
        return None

    channels_needed = max(config.MIC_CHANNEL, *config.SYSTEM_CHANNELS) + 1
    if device.max_input_channels < channels_needed:
        print(
            f"Device '{device.name}' has {device.max_input_channels} input "
            f"channels, but the configured map needs {channels_needed} "
            f"(MIC_CHANNEL={config.MIC_CHANNEL}, "
            f"SYSTEM_CHANNELS={config.SYSTEM_CHANNELS}).\n"
            "Fix the aggregate device or override the map in .env."
        )
        return None

    output_name = default_output_name()
    if (
        "multi-output" not in output_name.lower()
        and config.BLACKHOLE_DEVICE_MATCH.lower() not in output_name.lower()
    ):
        print(
            f"WARNING: current output is '{output_name}', not a Multi-Output "
            "Device.\n         The 'Others' channel will be silent unless audio "
            "is routed through BlackHole.\n"
        )

    samplerate = int(device.default_samplerate)
    # Local wall-clock time is what you want in a meeting file name.
    stem = name or f"meeting_{datetime.now():%Y%m%d_%H%M%S}"  # noqa: DTZ005
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.RAW_DIR / f"{stem}.wav"

    blocks: queue.Queue[np.ndarray | None] = queue.Queue()
    levels = _Levels()
    mic_ch = config.MIC_CHANNEL
    sys_chs = list(config.SYSTEM_CHANNELS)

    def callback(indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("InputStream status: %s", status)
        blocks.put(indata.copy())
        levels.mic_rms = _rms(indata[:, mic_ch])
        levels.sys_rms = _rms(indata[:, sys_chs].mean(axis=1))
        levels.mic_peak = max(levels.mic_peak, levels.mic_rms)
        levels.sys_peak = max(levels.sys_peak, levels.sys_rms)

    def writer() -> None:
        with sf.SoundFile(
            dest, mode="w", samplerate=samplerate, channels=2, subtype="PCM_16"
        ) as wav:
            while True:
                block = blocks.get()
                if block is None:
                    break
                mic = block[:, mic_ch]
                system = block[:, sys_chs].mean(axis=1)
                wav.write(np.column_stack([mic, system]))

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()

    print(f"Recording '{device.name}' -> {dest}")
    print("Left = your microphone, right = meeting audio. Ctrl+C to stop.\n")
    started = time.monotonic()
    try:
        with sd.InputStream(
            device=device.index,
            channels=device.max_input_channels,
            samplerate=samplerate,
            callback=callback,
        ):
            while True:
                time.sleep(0.5)
                line = _meter_line(time.monotonic() - started, levels)
                sys.stdout.write("\r" + line + " " * 8)
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        blocks.put(None)
        thread.join(timeout=10)
        sys.stdout.write("\n\n")

    duration = time.monotonic() - started
    print(f"Saved {duration / 60:.1f} min to {dest}")
    if levels.sys_peak < SILENCE_PEAK_THRESHOLD:
        print(
            "\nWARNING: the 'Others' channel stayed silent for the whole "
            "recording.\n         Check that output is routed via the "
            "Multi-Output Device (see `uv run main.py devices`)."
        )
    if levels.mic_peak < SILENCE_PEAK_THRESHOLD:
        print(
            "\nWARNING: the microphone channel stayed silent for the whole "
            "recording.\n         Check the channel map in .env "
            "(MIC_CHANNEL / SYSTEM_CHANNELS)."
        )

    print(f"\nNext: uv run main.py transcribe {dest}")
    return dest
