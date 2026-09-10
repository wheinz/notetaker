import os
from pathlib import Path

import soundfile as sf


def open_wav_exclusive(path: Path, samplerate: int, channels: int) -> sf.SoundFile:
    """Open a new stereo PCM16 WAV for writing, refusing to overwrite.

    Raises ``FileExistsError`` if ``path`` already exists. The file descriptor is
    passed to libsndfile as a raw fd so that ``SoundFile.close()`` releases it
    deterministically (soundfile ignores ``closefd`` for file objects).
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        return sf.SoundFile(
            fd,
            mode="w",
            samplerate=samplerate,
            channels=channels,
            format="WAV",
            subtype="PCM_16",
        )
    except Exception:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
