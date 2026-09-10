import numpy as np
import pytest
import soundfile as sf

from src import wav as wav_mod
from src.wav import open_wav_exclusive


def test_open_wav_exclusive_refuses_overwrite(tmp_path):
    path = tmp_path / "x.wav"
    path.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        open_wav_exclusive(path, 48000, 2)
    assert path.read_bytes() == b"existing"


def test_open_wav_exclusive_writes(tmp_path):
    path = tmp_path / "x.wav"
    wav = open_wav_exclusive(path, 48000, 2)
    wav.write(np.zeros((10, 2), dtype=np.float32))
    wav.close()

    data, sr = sf.read(path)
    assert data.shape == (10, 2)
    assert sr == 48000


def test_open_wav_exclusive_passes_raw_fd(tmp_path, monkeypatch):
    captured = {}
    real_soundfile = sf.SoundFile

    def fake_soundfile(file, **kwargs):
        captured["file"] = file
        return real_soundfile(file, **kwargs)

    monkeypatch.setattr(wav_mod.sf, "SoundFile", fake_soundfile)

    path = tmp_path / "x.wav"
    wav = open_wav_exclusive(path, 48000, 2)
    wav.close()

    assert isinstance(captured["file"], int)
