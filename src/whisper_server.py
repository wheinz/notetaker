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


def model_path(model: str, models_dir: Path | None = None) -> Path:
    if model not in MODEL_FILES:
        choices = ", ".join(sorted(MODEL_FILES))
        raise WhisperServerError(f"Unknown Whisper model '{model}' (choose: {choices})")
    path = (models_dir or config.WHISPER_MODELS_DIR) / MODEL_FILES[model]
    if not path.is_file():
        raise WhisperServerError(f"Whisper model not found: {path}")
    return path


def server_command(
    model: str,
    server_bin: Path | None = None,
    models_dir: Path | None = None,
    vad_model: Path | None = None,
    host: str = config.WHISPER_SERVER_HOST,
    port: int = config.WHISPER_SERVER_PORT,
) -> list[str]:
    binary = server_bin or config.WHISPER_SERVER_BIN
    vad = vad_model or config.WHISPER_VAD_MODEL
    if not binary.is_file():
        raise WhisperServerError(f"whisper-server not found: {binary}")
    if not vad.is_file():
        raise WhisperServerError(f"Whisper VAD model not found: {vad}")
    return [
        str(binary),
        "-m",
        str(model_path(model, models_dir=models_dir)),
        "-vm",
        str(vad),
        "--host",
        host,
        "--port",
        str(port),
        "-l",
        "auto",
    ]


def server_is_ready(url: str = config.WHISPER_SERVER_URL) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def wait_until_ready(
    process: subprocess.Popen,
    url: str = config.WHISPER_SERVER_URL,
    timeout_seconds: float = 300.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise WhisperServerError(
                f"whisper-server exited during startup with code {process.returncode}"
            )
        if server_is_ready(url):
            return
        time.sleep(0.5)
    raise WhisperServerError("whisper-server did not become ready in time")


@contextmanager
def temporary_server(
    model: str = "turbo",
    *,
    server_bin: Path | None = None,
    models_dir: Path | None = None,
    vad_model: Path | None = None,
    log_path: Path | None = None,
) -> Iterator[None]:
    if server_is_ready():
        raise WhisperServerError(
            f"Port {config.WHISPER_SERVER_PORT} is already serving another Whisper process"
        )

    command = server_command(
        model,
        server_bin=server_bin,
        models_dir=models_dir,
        vad_model=vad_model,
    )
    output = log_path or config.WHISPER_SERVER_LOG
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("a", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        except OSError as exc:
            raise WhisperServerError(f"Could not start whisper-server: {exc}") from exc

        try:
            wait_until_ready(process)
            yield
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
