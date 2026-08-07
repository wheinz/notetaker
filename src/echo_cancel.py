import numpy as np


def apply_echo_cancellation(
    mic: np.ndarray,
    ref: np.ndarray,
    filter_length: int = 128,
    mu: float = 0.1,
    eps: float = 1e-6,
) -> np.ndarray:
    """Apply NLMS echo cancellation to mic using ref as reference signal.

    Assumes both arrays are 1-D float64 mono at the same sample rate.
    Returns the cleaned mic signal.
    """
    mic = np.asarray(mic, dtype=np.float64)
    ref = np.asarray(ref, dtype=np.float64)

    if len(mic) != len(ref):
        raise ValueError(
            f"mic and ref must have the same length ({len(mic)} vs {len(ref)})"
        )

    w = np.zeros(filter_length, dtype=np.float64)
    clean = mic.copy()

    for i in range(filter_length, len(mic)):
        x = ref[i - filter_length:i][::-1]
        y = float(np.dot(w, x))
        e = mic[i] - y
        power = float(np.dot(x, x)) + eps
        w += mu * e * x / power
        clean[i] = e

    return clean
