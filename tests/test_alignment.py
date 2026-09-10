import numpy as np
import pytest

from src.alignment import AlignmentError, TimelineWriter


def test_zero_fill_before_later_source_offset():
    w = TimelineWriter(mic_offset=0, loopback_offset=4)
    w.add("mic", np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.float32))
    w.add("loopback", np.array([10, 11, 12], dtype=np.float32))

    out = w.write_available()
    assert out.shape == (7, 2)
    assert list(out[:, 0]) == [1, 2, 3, 4, 5, 6, 7]
    assert list(out[:, 1]) == [0, 0, 0, 0, 10, 11, 12]
    assert w.available() == 0


def test_mic_later_than_loopback():
    w = TimelineWriter(mic_offset=5, loopback_offset=0)
    w.add("loopback", np.array([10, 11, 12, 13, 14, 15], dtype=np.float32))
    w.add("mic", np.array([1, 2, 3], dtype=np.float32))

    out = w.write_available()
    assert out.shape == (6, 2)
    assert list(out[:, 1]) == [10, 11, 12, 13, 14, 15]
    assert list(out[:, 0]) == [0, 0, 0, 0, 0, 1]


def test_incremental_matches_single_write():
    mic = np.arange(100, dtype=np.float32)
    loop = np.arange(100, 200, dtype=np.float32)

    w1 = TimelineWriter(0, 10)
    w1.add("mic", mic)
    w1.add("loopback", loop)
    full = w1.write_available()

    w2 = TimelineWriter(0, 10)
    outs = []
    for i in range(0, 100, 10):
        w2.add("mic", mic[i : i + 10])
        w2.add("loopback", loop[i : i + 10])
        chunk = w2.write_available()
        if chunk is not None:
            outs.append(chunk)
    combined = np.concatenate(outs) if outs else np.zeros((0, 2), dtype=np.float32)

    assert np.array_equal(full, combined)


def test_waits_for_later_source_at_its_offset():
    w = TimelineWriter(mic_offset=0, loopback_offset=100)
    w.add("mic", np.arange(200, dtype=np.float32))

    out = w.write_available()
    assert out.shape == (100, 2)
    assert list(out[:, 1]) == [0.0] * 100
    assert list(out[:, 0]) == list(range(100))
    assert w.available() == 0

    w.add("loopback", np.arange(50, dtype=np.float32))
    out2 = w.write_available()
    assert out2.shape == (50, 2)
    assert list(out2[:, 1]) == list(range(50))
    assert list(out2[:, 0]) == list(range(100, 150))


def test_unknown_source_raises():
    w = TimelineWriter(0, 0)
    with pytest.raises(AlignmentError):
        w.add("bogus", np.zeros(3, dtype=np.float32))


def test_2d_samples_rejected():
    w = TimelineWriter(0, 0)
    with pytest.raises(AlignmentError):
        w.add("mic", np.zeros((3, 2), dtype=np.float32))


def test_int_samples_casted_to_float32():
    w = TimelineWriter(0, 0)
    w.add("mic", np.array([1, 2, 3], dtype=np.int16))
    w.add("loopback", np.array([4, 5, 6], dtype=np.int16))
    out = w.write_available()
    assert out.dtype == np.float32
    assert list(out[:, 0]) == [1, 2, 3]


def test_variable_packet_sizes():
    w = TimelineWriter(0, 2)
    w.add("mic", np.array([1, 2, 3, 4, 5], dtype=np.float32))
    w.add("loopback", np.array([10, 11], dtype=np.float32))
    w.add("loopback", np.array([12, 13, 14], dtype=np.float32))

    out = w.write_available()
    assert out.shape == (5, 2)
    assert list(out[:, 0]) == [1, 2, 3, 4, 5]
    assert list(out[:, 1]) == [0, 0, 10, 11, 12]


def test_finalize_pads_unequal_tails():
    w = TimelineWriter(0, 0)
    w.add("mic", np.arange(10, dtype=np.float32))
    w.add("loopback", np.arange(6, dtype=np.float32))

    out = w.write_available()
    assert out.shape == (6, 2)

    final = w.finalize(w.max_end())
    assert final.shape == (4, 2)
    assert list(final[:, 0]) == [6.0, 7.0, 8.0, 9.0]
    assert list(final[:, 1]) == [0.0, 0.0, 0.0, 0.0]
    assert w.out_frame == 10


def test_finalize_clips_to_end():
    w = TimelineWriter(0, 0)
    w.add("mic", np.arange(10, dtype=np.float32))
    w.add("loopback", np.arange(10, 20, dtype=np.float32))

    final = w.finalize(5)
    assert final.shape == (5, 2)
    assert list(final[:, 0]) == [0, 1, 2, 3, 4]
    assert list(final[:, 1]) == [10, 11, 12, 13, 14]
    assert w.out_frame == 5


def test_finalize_after_write_flushes_remainder():
    w = TimelineWriter(0, 0)
    w.add("mic", np.arange(8, dtype=np.float32))
    w.add("loopback", np.arange(8, 16, dtype=np.float32))

    out = w.write_available()
    assert out.shape == (8, 2)
    assert w.write_available() is None
    assert w.finalize(8) is None


def test_write_available_respects_limit():
    w = TimelineWriter(0, 0)
    w.add("mic", np.arange(10, dtype=np.float32))
    w.add("loopback", np.arange(10, 20, dtype=np.float32))

    out = w.write_available(limit=4)
    assert out.shape == (4, 2)
    assert list(out[:, 0]) == [0, 1, 2, 3]
    assert list(out[:, 1]) == [10, 11, 12, 13]
    assert w.out_frame == 4
    assert w.available() == 6


def test_max_pending_enforced():
    w = TimelineWriter(0, 100, max_pending_frames=5)
    w.add("mic", np.zeros(5, dtype=np.float32))
    with pytest.raises(AlignmentError):
        w.add("mic", np.zeros(1, dtype=np.float32))


def test_room_reflects_pending():
    w = TimelineWriter(0, 0, max_pending_frames=10)
    assert w.room("mic") == 10
    w.add("mic", np.zeros(4, dtype=np.float32))
    assert w.room("mic") == 6
    w.add("loopback", np.zeros(4, dtype=np.float32))
    assert w.write_available().shape == (4, 2)
    assert w.room("mic") == 10


def test_unbounded_by_default():
    w = TimelineWriter(0, 0)
    w.add("mic", np.zeros(100_000, dtype=np.float32))
    assert w.room("mic") is None
