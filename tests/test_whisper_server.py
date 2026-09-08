import plistlib

import pytest

from src import whisper_server


def _write_agent(path, model):
    data = {
        "Label": "com.whisper.cpp.server",
        "ProgramArguments": [
            "/tmp/whisper-server",
            "-m",
            str(model),
            "-cm",
            "/tmp/correction.gguf",
        ],
    }
    with path.open("wb") as f:
        plistlib.dump(data, f)


def test_current_model_path_reads_launch_agent(tmp_path):
    small = tmp_path / "ggml-small.bin"
    small.touch()
    agent = tmp_path / "agent.plist"
    _write_agent(agent, small)

    assert whisper_server.current_model_path(agent) == small


def test_temporary_model_switches_and_restores(tmp_path, monkeypatch):
    small = tmp_path / "ggml-small.bin"
    medium = tmp_path / "ggml-medium.bin"
    small.touch()
    medium.touch()
    agent = tmp_path / "agent.plist"
    _write_agent(agent, small)
    restarts = []

    monkeypatch.setattr(
        whisper_server, "restart_launch_agent", lambda launch_agent=None: restarts.append(launch_agent)
    )
    monkeypatch.setattr(whisper_server, "wait_until_ready", lambda: None)

    with whisper_server.temporary_model(
        "medium",
        launch_agent=agent,
        models_dir=tmp_path,
    ):
        assert whisper_server.current_model_path(agent) == medium

    assert whisper_server.current_model_path(agent) == small
    assert restarts == [agent, agent]


def test_temporary_model_restores_after_error(tmp_path, monkeypatch):
    small = tmp_path / "ggml-small.bin"
    medium = tmp_path / "ggml-medium.bin"
    small.touch()
    medium.touch()
    agent = tmp_path / "agent.plist"
    _write_agent(agent, small)

    monkeypatch.setattr(whisper_server, "restart_launch_agent", lambda launch_agent=None: None)
    monkeypatch.setattr(whisper_server, "wait_until_ready", lambda: None)

    with pytest.raises(ValueError, match="boom"), whisper_server.temporary_model(
        "medium",
        launch_agent=agent,
        models_dir=tmp_path,
    ):
        raise ValueError("boom")

    assert whisper_server.current_model_path(agent) == small


def test_temporary_model_does_not_restart_when_already_target(tmp_path, monkeypatch):
    medium = tmp_path / "ggml-medium.bin"
    medium.touch()
    agent = tmp_path / "agent.plist"
    _write_agent(agent, medium)
    restarts = []

    monkeypatch.setattr(
        whisper_server, "restart_launch_agent", lambda launch_agent=None: restarts.append(launch_agent)
    )
    monkeypatch.setattr(whisper_server, "wait_until_ready", lambda: None)

    with whisper_server.temporary_model(
        "medium",
        launch_agent=agent,
        models_dir=tmp_path,
    ):
        assert whisper_server.current_model_path(agent) == medium

    assert restarts == []


def test_missing_model_raises(tmp_path):
    with pytest.raises(whisper_server.WhisperServerError, match="not found"):
        whisper_server.model_path("medium", models_dir=tmp_path)
