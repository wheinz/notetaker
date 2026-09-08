import asyncio
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import httpx
import soundfile as sf

from . import config
from .echo_cancel import apply_echo_cancellation
from .merger import Segment, remove_echo_duplicates, remove_repetitions, render_markdown

logger = logging.getLogger(__name__)

# whisper.cpp serializes inference behind a global mutex, so the two POSTs
# below run concurrently client-side but queue on the server. To parallelize
# for real, restart whisper-server with `-np 2` (whisper_full_parallel).


def extract_channel(wav: Path, channel: int, dest: Path) -> Path:
    """Extract one channel of a stereo WAV to 16 kHz mono via ffmpeg."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(wav),
        "-af",
        f"pan=mono|c0=c{channel}",
        "-ar",
        "16000",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed extracting channel {channel} from {wav}:\n"
            f"{result.stderr.decode(errors='replace')[-500:]}"
        )
    return dest


def parse_segments(payload: dict) -> list[Segment]:
    segments = []
    for raw in payload.get("segments", []):
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        segments.append(
            Segment(
                start=float(raw["start"]),
                end=float(raw["end"]),
                text=text,
                no_speech_prob=float(raw.get("no_speech_prob", 0.0)),
            )
        )
    return segments


def filter_non_speech(
    segments: list[Segment], threshold: float = config.NO_SPEECH_THRESHOLD
) -> list[Segment]:
    return [seg for seg in segments if seg.no_speech_prob < threshold]


async def transcribe_file(
    client: httpx.AsyncClient,
    wav: Path,
    language: str | None = None,
    base_url: str = config.WHISPER_SERVER_URL,
) -> list[Segment]:
    data = {"response_format": "verbose_json", "temperature": "0.0"}
    if language:
        data["language"] = language
    if config.VAD_ENABLED:
        data["vad"] = "true"
    content = await asyncio.to_thread(wav.read_bytes)
    response = await client.post(
        f"{base_url}/inference",
        files={"file": (wav.name, content, "audio/wav")},
        data=data,
    )
    response.raise_for_status()
    return parse_segments(response.json())


def title_from_stem(stem: str) -> str:
    try:
        # The stem carries local wall-clock time; tz is irrelevant here.
        dt = datetime.strptime(stem, "meeting_%Y%m%d_%H%M%S")  # noqa: DTZ007
        return f"Meeting {dt:%Y-%m-%d %H:%M}"
    except ValueError:
        return stem.replace("_", " ")


async def transcribe_meeting(wav: Path, language: str | None = None) -> Path:
    wav = wav.resolve()
    config.TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        left = extract_channel(wav, 0, Path(tmp) / "left.wav")
        right = extract_channel(wav, 1, Path(tmp) / "right.wav")

        if config.ECHO_CANCEL_ENABLED:
            mic_data, sr = await asyncio.to_thread(sf.read, left)
            ref_data, _ = await asyncio.to_thread(sf.read, right)
            cleaned = await asyncio.to_thread(
                apply_echo_cancellation,
                mic_data,
                ref_data,
                config.ECHO_CANCEL_FILTER_LENGTH,
                config.ECHO_CANCEL_MU,
            )
            await asyncio.to_thread(sf.write, left, cleaned, sr)
            logger.info(
                "Echo cancellation applied: filter_length=%d, mu=%.3f",
                config.ECHO_CANCEL_FILTER_LENGTH,
                config.ECHO_CANCEL_MU,
            )

        timeout = httpx.Timeout(None, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            me, others = await asyncio.gather(
                transcribe_file(client, left, language),
                transcribe_file(client, right, language),
            )

    if config.NO_SPEECH_FILTER_ENABLED:
        me = filter_non_speech(me)
        others = filter_non_speech(others)

    if config.REPETITION_DEDUP_ENABLED:
        before = len(me) + len(others)
        me = remove_repetitions(
            me, similarity_threshold=config.REPETITION_DEDUP_SIMILARITY
        )
        others = remove_repetitions(
            others, similarity_threshold=config.REPETITION_DEDUP_SIMILARITY
        )
        removed = before - (len(me) + len(others))
        if removed:
            logger.info("Removed %d repeated hallucination segments", removed)

    if config.ECHO_DEDUP_ENABLED:
        before = len(me)
        me = remove_echo_duplicates(
            me,
            others,
            similarity_threshold=config.ECHO_DEDUP_SIMILARITY,
            overlap_padding=config.ECHO_DEDUP_OVERLAP_PADDING,
            min_words=config.ECHO_DEDUP_MIN_WORDS,
        )
        removed = before - len(me)
        if removed:
            logger.info("Removed %d likely mic echo duplicate segments", removed)

    markdown = render_markdown(me, others, title=title_from_stem(wav.stem))
    output = config.TRANSCRIPT_DIR / f"{wav.stem}.md"
    output.write_text(markdown, encoding="utf-8")
    logger.info(
        "Transcribed %s: %d segments from you, %d from others",
        wav.name,
        len(me),
        len(others),
    )
    return output
