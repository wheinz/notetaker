import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src import config
from src.recorder import record
from src.transcriber import transcribe_meeting
from src.whisper_server import WhisperServerError, server_command, temporary_server

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _check_mark(ok: bool) -> str:
    return "ok " if ok else "MISSING"


def _devices_command(args: argparse.Namespace) -> int:
    if sys.platform == "win32":
        from src.recorder_windows import print_devices

        recording_ok = print_devices()
        setup_instructions = None
    else:
        from src.recorder_macos import SETUP_INSTRUCTIONS, print_devices

        recording_ok = print_devices()
        setup_instructions = SETUP_INSTRUCTIONS

    server_ok = False
    try:
        server_command("turbo")
        server_ok = True
    except WhisperServerError:
        pass
    print(
        f"[{_check_mark(server_ok)}] on-demand whisper.cpp server "
        f"({config.WHISPER_SERVER_URL})"
    )

    if not (recording_ok and server_ok):
        if setup_instructions:
            print()
            print(setup_instructions)
        return 1
    print("\nAll checks passed.")
    return 0


def _record_command(args: argparse.Namespace) -> int:
    return 0 if record(name=args.name) is not None else 1


def _transcribe_command(args: argparse.Namespace) -> int:
    wav = Path(args.audio)
    if not wav.is_file():
        print(f"No such file: {wav}")
        return 1
    try:
        with temporary_server(args.model or "turbo"):
            output = asyncio.run(transcribe_meeting(wav, language=args.language))
        print(f"Transcript saved to {output}")
        return 0
    except WhisperServerError as exc:
        print(f"Whisper server error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="notetaker",
        description=(
            "Dual-channel meeting note taker: mic on the left channel, "
            "meeting audio on the right."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "devices",
        help="List audio devices and verify setup (routing, server)",
    )

    record_parser = subparsers.add_parser(
        "record", help="Record until Ctrl+C (left=mic, right=system audio)"
    )
    record_parser.add_argument(
        "--name", help="Output file stem (default: meeting_<timestamp>)"
    )

    transcribe_parser = subparsers.add_parser(
        "transcribe", help="Split a stereo recording and transcribe both channels"
    )
    transcribe_parser.add_argument("audio", help="Path to the stereo WAV file")
    transcribe_parser.add_argument(
        "--language", help="Whisper language code (default: auto-detect)"
    )
    transcribe_parser.add_argument(
        "--model",
        choices=("small", "medium", "turbo"),
        help="Whisper model for this run (default: turbo)",
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "devices": _devices_command,
        "record": _record_command,
        "transcribe": _transcribe_command,
    }
    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
