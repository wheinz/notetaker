import sys
import threading
import time
import types
from pathlib import Path

import numpy as np
import soundfile as sf

from src import config
from src import recorder_windows as rw
from src.recorder_windows import FRAMES_PER_BUFFER

RATE = 48000
CALLBACKS = 10


def _setup(pa, pyaudio):
    mic = {"index": 0, "name": "Mic"}
    output = {"index": 1, "name": "Speakers"}
    loopback = {"index": 2, "name": "Speakers [Loopback]"}
    return mic, output, loopback, RATE, 1, 2


def _fake_module(stream_factory):
    mod = types.ModuleType("pyaudiowpatch")
    mod.paWASAPI = 13
    mod.paFloat32 = 1
    mod.paContinue = 0
    mod.paAbort = 2
    mod.paComplete = 1
    mod.paInputOverflow = 4
    mod.paInputUnderflow = 8

    class PyAudio:
        def __init__(self):
            self._opened = []

        def open(self, **kwargs):
            stream = stream_factory(kwargs)
            self._opened.append(stream)
            return stream

        def terminate(self):
            for stream in self._opened:
                stream.close()

    mod.PyAudio = PyAudio
    return mod


class _InactiveStream:
    def start_stream(self):
        pass

    def stop_stream(self):
        pass

    def close(self):
        pass

    def is_active(self):
        return False


class _PacedStream:
    """Delivers a fixed number of real-time-paced callbacks with a constant value."""

    def __init__(self, kwargs, value, done):
        self.callback = kwargs["stream_callback"]
        self.channels = kwargs["channels"]
        self.value = value
        self._done = done
        self._active = False
        self._thread = None

    def start_stream(self):
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        n = 0
        while self._active and n < CALLBACKS:
            data = (
                np.full(
                    (FRAMES_PER_BUFFER, self.channels), self.value, dtype=np.float32
                )
            ).tobytes()
            info = {"input_buffer_adc_time": n * FRAMES_PER_BUFFER / RATE}
            self.callback(data, FRAMES_PER_BUFFER, info, 0)
            n += 1
            time.sleep(FRAMES_PER_BUFFER / RATE)
        self._done.append(1)

    def stop_stream(self):
        self._active = False

    def close(self):
        self._active = False
        if self._thread:
            self._thread.join(timeout=2)

    def is_active(self):
        return self._active


class _OverflowStream:
    """Delivers callbacks that always carry an input-overflow status flag."""

    def __init__(self, kwargs):
        self.callback = kwargs["stream_callback"]
        self.channels = kwargs["channels"]
        self._active = False
        self._thread = None

    def start_stream(self):
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        n = 0
        while self._active:
            data = b"\x00" * (FRAMES_PER_BUFFER * self.channels * 4)
            info = {"input_buffer_adc_time": n * FRAMES_PER_BUFFER / RATE}
            self.callback(data, FRAMES_PER_BUFFER, info, 4)  # paInputOverflow
            n += 1
            time.sleep(0.001)

    def stop_stream(self):
        self._active = False

    def close(self):
        self._active = False
        if self._thread:
            self._thread.join(timeout=1)

    def is_active(self):
        return self._active


def test_record_inactive_stream_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rw, "_resolve_setup", _setup)
    monkeypatch.setitem(
        sys.modules, "pyaudiowpatch", _fake_module(lambda _: _InactiveStream())
    )

    real_sleep = rw.time.sleep
    monkeypatch.setattr(
        rw.time, "sleep", lambda s: real_sleep(0.001 if s >= 0.5 else s)
    )

    assert rw.record(name="inactive") is None


def test_record_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rw, "_resolve_setup", _setup)
    monkeypatch.setitem(
        sys.modules, "pyaudiowpatch", _fake_module(lambda _: _InactiveStream())
    )

    dest = tmp_path / "exists.wav"
    dest.write_bytes(b"already here")

    assert rw.record(name="exists") is None
    assert dest.read_bytes() == b"already here"


def test_record_input_overflow_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rw, "_resolve_setup", _setup)
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", _fake_module(_OverflowStream))

    real_sleep = rw.time.sleep
    monkeypatch.setattr(
        rw.time, "sleep", lambda s: real_sleep(0.001 if s >= 0.5 else s)
    )

    assert rw.record(name="overflow") is None


def test_record_normal_stop_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    monkeypatch.setattr(rw, "_resolve_setup", _setup)

    done = []

    def factory(kwargs):
        value = 0.5 if kwargs["channels"] == 1 else -0.5
        return _PacedStream(kwargs, value, done)

    monkeypatch.setitem(sys.modules, "pyaudiowpatch", _fake_module(factory))

    real_sleep = rw.time.sleep

    def interrupt_sleep(seconds):
        if seconds >= 0.5:
            while len(done) < 2:
                real_sleep(0.001)
            raise KeyboardInterrupt
        real_sleep(seconds)

    monkeypatch.setattr(rw.time, "sleep", interrupt_sleep)

    result = rw.record(name="normal")
    assert result == tmp_path / "normal.wav"
    assert isinstance(result, Path)

    data, sr = sf.read(result)
    assert sr == RATE
    assert data.ndim == 2 and data.shape[1] == 2
    delivered = CALLBACKS * FRAMES_PER_BUFFER
    assert len(data) >= delivered
    assert len(data) < delivered + RATE
    assert float(np.mean(data[:, 0])) > 0.2
    assert float(np.mean(data[:, 1])) < -0.2
