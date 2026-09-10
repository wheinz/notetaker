import sys

import src.recorder as rec


def test_record_is_callable():
    assert callable(rec.record)


def test_recorder_windows_imports_without_native_extension():
    import importlib

    importlib.import_module("src.recorder_windows")


def test_dispatches_to_macos_on_non_win32(monkeypatch):
    import src.recorder_macos as macos

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(macos, "record", lambda name=None: "MAC")
    assert rec.record() == "MAC"


def test_dispatches_to_windows_on_win32(monkeypatch):
    import src.recorder_windows as win

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(win, "record", lambda name=None: "WIN")
    assert rec.record() == "WIN"
