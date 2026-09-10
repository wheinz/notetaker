import sys
from pathlib import Path


def record(name: str | None = None) -> Path | None:
    if sys.platform == "win32":
        from .recorder_windows import record as _record
    else:
        from .recorder_macos import record as _record
    return _record(name)
