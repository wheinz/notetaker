import asyncio

import httpx
import pytest

from src import config, transcriber
from src.merger import Segment
from src.transcriber import (
    parse_segments,
    title_from_stem,
    transcribe_file,
    transcribe_meeting,
)

VERBOSE_JSON = {
    "task": "transcribe",
    "language": "english",
    "duration": 4.0,
    "text": " hello world again",
    "segments": [
        {"id": 0, "text": " hello world", "start": 0.0, "end": 1.5},
        {"id": 1, "text": " again", "start": 2.0, "end": 4.0},
        {"id": 2, "text": "   ", "start": 4.0, "end": 4.5},
    ],
}


def test_parse_segments_strips_and_skips_empty():
    segments = parse_segments(VERBOSE_JSON)
    assert segments == [
        Segment(start=0.0, end=1.5, text="hello world"),
        Segment(start=2.0, end=4.0, text="again"),
    ]


def test_parse_segments_handles_missing_key():
    assert parse_segments({"text": "no segments"}) == []


def test_title_from_stem_parses_default_pattern():
    assert title_from_stem("meeting_20260728_143000") == "Meeting 2026-07-28 14:30"


def test_title_from_stem_falls_back_to_stem():
    assert title_from_stem("standup_notes") == "standup notes"


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
        timeout=httpx.Timeout(None),
    )


def test_transcribe_file_posts_verbose_json_and_language(tmp_path):
    wav = tmp_path / "left.wav"
    wav.write_bytes(b"RIFFfake")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json=VERBOSE_JSON)

    async def run():
        async with _mock_client(handler) as client:
            return await transcribe_file(
                client, wav, language="en", base_url="http://testserver"
            )

    segments = asyncio.run(run())
    assert seen["url"] == "http://testserver/inference"
    assert b'name="response_format"' in seen["body"]
    assert b"verbose_json" in seen["body"]
    assert b'name="language"' in seen["body"]
    assert b'"en"' in seen["body"] or b'name="language"\r\n\r\nen' in seen["body"]
    assert segments[0].text == "hello world"


def test_transcribe_meeting_merges_channels(tmp_path, monkeypatch):
    stereo = tmp_path / "meeting_20260728_143000.wav"
    stereo.write_bytes(b"RIFFfake")

    def fake_extract(wav, channel, dest):
        dest.write_bytes(f"channel-{channel}".encode())
        return dest

    async def fake_transcribe(
        client, wav, language, base_url=config.WHISPER_SERVER_URL
    ):
        if "left" in wav.name:
            return [Segment(1.0, 2.0, "from me")]
        return [Segment(0.0, 1.0, "from others")]

    monkeypatch.setattr(transcriber, "extract_channel", fake_extract)
    monkeypatch.setattr(transcriber, "transcribe_file", fake_transcribe)
    monkeypatch.setattr(config, "TRANSCRIPT_DIR", tmp_path / "transcripts")

    output = asyncio.run(transcribe_meeting(stereo))

    assert output == tmp_path / "transcripts" / "meeting_20260728_143000.md"
    body = [line for line in output.read_text().splitlines() if line.startswith("**")]
    assert body == [
        "**[00:00:00] Others:** from others",
        "**[00:00:01] Me:** from me",
    ]


def test_transcribe_meeting_raises_for_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        asyncio.run(transcribe_meeting(tmp_path / "nope.wav"))
