from pathlib import Path

import pytest

from src import whisper_server


def _runtime_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    binary = tmp_path / "whisper-server"
    model = tmp_path / "ggml-large-v3-turbo.bin"
    vad = tmp_path / "ggml-silero-v6.2.0.bin"
    binary.touch()
    model.touch()
    vad.touch()
    return binary, model, vad


def test_server_command_uses_isolated_port_and_vad(tmp_path):
    binary, model, vad = _runtime_files(tmp_path)

    command = whisper_server.server_command(
        "turbo",
        server_bin=binary,
        models_dir=tmp_path,
        vad_model=vad,
        host="127.0.0.1",
        port=9090,
    )

    assert command[0] == str(binary)
    assert command[command.index("-m") + 1] == str(model)
    assert command[command.index("-vm") + 1] == str(vad)
    assert command[command.index("--port") + 1] == "9090"
    assert command[command.index("-l") + 1] == "auto"


def test_missing_model_raises(tmp_path):
    with pytest.raises(whisper_server.WhisperServerError, match="not found"):
        whisper_server.model_path("turbo", models_dir=tmp_path)


def test_temporary_server_stops_process(tmp_path, monkeypatch):
    binary, _, vad = _runtime_files(tmp_path)

    class FakeProcess:
        returncode = None

        def __init__(self, *args, **kwargs):
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    processes = []

    def fake_popen(*args, **kwargs):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(whisper_server, "server_is_ready", lambda: False)
    monkeypatch.setattr(whisper_server.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(whisper_server, "wait_until_ready", lambda process: None)

    with whisper_server.temporary_server(
        "turbo",
        server_bin=binary,
        models_dir=tmp_path,
        vad_model=vad,
        log_path=tmp_path / "server.log",
    ):
        assert not processes[0].terminated

    assert processes[0].terminated


def test_temporary_server_rejects_occupied_port(monkeypatch):
    monkeypatch.setattr(whisper_server, "server_is_ready", lambda: True)
    with (
        pytest.raises(whisper_server.WhisperServerError, match="already serving"),
        whisper_server.temporary_server(),
    ):
        pass
