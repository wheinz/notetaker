import os
import plistlib
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from . import config

MODEL_FILES = {
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    "turbo": "ggml-large-v3-turbo.bin",
}


class WhisperServerError(RuntimeError):
    pass


def default_launch_agent() -> Path:
    return config.WHISPER_LAUNCH_AGENT


def default_models_dir() -> Path:
    return config.WHISPER_MODELS_DIR


def model_path(model: str, models_dir: Path | None = None) -> Path:
    if model not in MODEL_FILES:
        choices = ", ".join(sorted(MODEL_FILES))
        raise WhisperServerError(f"Unknown Whisper model '{model}' (choose: {choices})")
    path = (models_dir or default_models_dir()) / MODEL_FILES[model]
    if not path.is_file():
        raise WhisperServerError(f"Whisper model not found: {path}")
    return path


def _read_plist(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return plistlib.load(f)
    except FileNotFoundError as exc:
        raise WhisperServerError(f"Whisper LaunchAgent not found: {path}") from exc


def _write_plist(path: Path, data: dict) -> None:
    with path.open("wb") as f:
        plistlib.dump(data, f, sort_keys=False)


def current_model_path(launch_agent: Path | None = None) -> Path:
    plist = _read_plist(launch_agent or default_launch_agent())
    args = plist.get("ProgramArguments", [])
    try:
        return Path(args[args.index("-m") + 1])
    except (ValueError, IndexError) as exc:
        raise WhisperServerError("Whisper LaunchAgent has no '-m <model>' argument") from exc


def set_model_path(model: Path, launch_agent: Path | None = None) -> Path:
    path = launch_agent or default_launch_agent()
    plist = _read_plist(path)
    args = list(plist.get("ProgramArguments", []))
    try:
        model_index = args.index("-m") + 1
    except ValueError as exc:
        raise WhisperServerError("Whisper LaunchAgent has no '-m <model>' argument") from exc

    previous = Path(args[model_index])
    args[model_index] = str(model)
    plist["ProgramArguments"] = args
    _write_plist(path, plist)
    return previous


def restart_launch_agent(launch_agent: Path | None = None) -> None:
    path = launch_agent or default_launch_agent()
    domain = f"gui/{os.getuid()}"
    bootout = subprocess.run(
        ["launchctl", "bootout", domain, str(path)],
        capture_output=True,
        check=False,
        text=True,
    )
    if bootout.returncode not in (0, 36):
        raise WhisperServerError(f"launchctl bootout failed: {bootout.stderr.strip()}")

    bootstrap = subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)],
        capture_output=True,
        check=False,
        text=True,
    )
    if bootstrap.returncode != 0:
        raise WhisperServerError(
            f"launchctl bootstrap failed: {bootstrap.stderr.strip()}"
        )


def wait_until_ready(
    url: str = config.WHISPER_SERVER_URL,
    timeout_seconds: float = 300.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/health", timeout=3)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(1)
    raise WhisperServerError(f"Whisper server did not become ready: {last_error}")


def switch_model(
    model: str,
    launch_agent: Path | None = None,
    models_dir: Path | None = None,
) -> Path:
    target = model_path(model, models_dir=models_dir)
    previous = set_model_path(target, launch_agent=launch_agent)
    if previous != target:
        restart_launch_agent(launch_agent=launch_agent)
        wait_until_ready()
    return previous


@contextmanager
def temporary_model(
    model: str,
    launch_agent: Path | None = None,
    models_dir: Path | None = None,
) -> Iterator[None]:
    target = model_path(model, models_dir=models_dir)
    previous = set_model_path(target, launch_agent=launch_agent)
    changed = previous != target
    try:
        if changed:
            restart_launch_agent(launch_agent=launch_agent)
            wait_until_ready()
        yield
    finally:
        if changed:
            set_model_path(previous, launch_agent=launch_agent)
            restart_launch_agent(launch_agent=launch_agent)
            wait_until_ready()
