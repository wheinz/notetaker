import numpy as np
import pytest

from src.echo_cancel import apply_echo_cancellation


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def _sine(freq: float, samplerate: int, duration: float) -> np.ndarray:
    t = np.arange(int(samplerate * duration), dtype=np.float64) / samplerate
    return np.sin(2 * np.pi * freq * t, dtype=np.float64)


def test_apply_echo_cancellation_reduces_echo_energy():
    sr = 16000
    duration = 2.0
    delay = 100  # samples

    rng = np.random.default_rng(42)
    ref = _sine(440, sr, duration) * 0.6 + rng.normal(0, 0.05, int(sr * duration))
    clean_voice = _sine(1200, sr, duration) * 0.1 + rng.normal(0, 0.02, int(sr * duration))

    echo = np.zeros_like(ref)
    echo[delay:] = ref[:-delay] * 0.4

    mic = clean_voice + echo

    cleaned = apply_echo_cancellation(mic, ref, filter_length=256, mu=0.05)

    echo_energy_before = _rms(echo[256:])
    residual = cleaned[256:] - clean_voice[256:]
    echo_energy_after = _rms(residual)

    assert echo_energy_after < echo_energy_before * 0.5


def test_apply_echo_cancellation_rejects_identical_signals():
    """If mic equals ref, output should be near zero after convergence."""
    sr = 16000
    duration = 2.0
    rng = np.random.default_rng(7)

    ref = _sine(440, sr, duration) * 0.5 + rng.normal(0, 0.02, int(sr * duration))
    mic = ref.copy()

    cleaned = apply_echo_cancellation(mic, ref, filter_length=128, mu=0.1)

    energy_in = _rms(mic[256:])
    energy_out = _rms(cleaned[256:])
    assert energy_out < energy_in * 0.3


def test_apply_echo_cancellation_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        apply_echo_cancellation(
            np.zeros(100, dtype=np.float64),
            np.zeros(200, dtype=np.float64),
        )
