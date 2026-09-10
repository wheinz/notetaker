import math

import numpy as np

SILENCE_PEAK_THRESHOLD = 10 ** (-45 / 20)  # -45 dBFS


class Levels:
    def __init__(self):
        self.mic_rms = 0.0
        self.sys_rms = 0.0
        self.mic_peak = 0.0
        self.sys_peak = 0.0


def rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))


def db_scale(rms_value: float) -> float:
    db = 20 * math.log10(max(rms_value, 1e-9))
    return max(0.0, min(1.0, (db + 60.0) / 60.0))


def bar(level: float, width: int = 12) -> str:
    filled = round(level * width)
    return "█" * filled + "░" * (width - filled)


def meter_line(elapsed: float, levels: Levels) -> str:
    hours, rem = divmod(int(elapsed), 3600)
    minutes, secs = divmod(rem, 60)
    return (
        f"● REC {hours:02d}:{minutes:02d}:{secs:02d}  "
        f"Me {bar(db_scale(levels.mic_rms))}  "
        f"Others {bar(db_scale(levels.sys_rms))}"
    )
