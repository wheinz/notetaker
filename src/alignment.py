from collections import deque

import numpy as np


class AlignmentError(Exception):
    pass


class TimelineWriter:
    """Interleave two mono float32 sources into a stereo timeline.

    Each source has a fixed start offset (in frames) from a common origin.
    Output frame 0 is that origin; a source contributes zeros for frames
    before its offset. During capture the writer only advances to the point
    where both sources have data, so it never stretches audio or inserts
    speculative silence to conceal drift. ``finalize`` writes up to an
    explicit end frame, zero-padding a short source and discarding anything
    beyond it.

    Buffering is bounded: ``max_pending_frames`` caps the number of received
    but not-yet-written frames per source.
    """

    def __init__(self, mic_offset: int, loopback_offset: int, max_pending_frames=None):
        if mic_offset < 0 or loopback_offset < 0:
            raise AlignmentError("offsets must be non-negative")
        self.offsets = {"mic": mic_offset, "loopback": loopback_offset}
        self.max_pending = max_pending_frames
        self._pending = {"mic": deque(), "loopback": deque()}
        self._pending_frames = {"mic": 0, "loopback": 0}
        self._received = {"mic": 0, "loopback": 0}
        self.out_frame = 0
        self._finalized = False

    def add(self, source: str, samples: np.ndarray) -> None:
        if source not in self.offsets:
            raise AlignmentError(f"unknown source: {source}")
        if samples.ndim != 1:
            raise AlignmentError("samples must be 1-D mono")
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32, copy=False)
        n = len(samples)
        if (
            self.max_pending is not None
            and self._pending_frames[source] + n > self.max_pending
        ):
            raise AlignmentError(f"{source} buffered beyond {self.max_pending} frames")
        self._pending[source].append(samples)
        self._pending_frames[source] += n
        self._received[source] += n

    def room(self, source: str):
        """Frames that can still be buffered for ``source`` (None = unlimited)."""
        if self.max_pending is None:
            return None
        return max(0, self.max_pending - self._pending_frames[source])

    def available(self, limit: int | None = None) -> int:
        ends = [self.offsets[s] + self._received[s] for s in self.offsets]
        n = min(ends) - self.out_frame
        if limit is not None:
            n = min(n, limit - self.out_frame)
        return max(0, n)

    def min_end(self) -> int:
        return min(self.offsets[s] + self._received[s] for s in self.offsets)

    def max_end(self) -> int:
        return max(self.offsets[s] + self._received[s] for s in self.offsets)

    def write_available(self, limit: int | None = None) -> np.ndarray | None:
        if self._finalized:
            return None
        n = self.available(limit)
        if n <= 0:
            return None
        out = np.empty((n, 2), dtype=np.float32)
        for col, source in enumerate(("mic", "loopback")):
            out[:, col] = self._drain(source, n)
        self.out_frame += n
        return out

    def finalize(self, end_frame: int) -> np.ndarray | None:
        if self._finalized:
            return None
        self._finalized = True
        n = end_frame - self.out_frame
        if n <= 0:
            self._discard()
            return None
        out = np.empty((n, 2), dtype=np.float32)
        for col, source in enumerate(("mic", "loopback")):
            out[:, col] = self._drain(source, n)
        self.out_frame = end_frame
        self._discard()
        return out

    def _discard(self) -> None:
        for source in ("mic", "loopback"):
            self._pending[source].clear()
            self._pending_frames[source] = 0

    def _drain(self, source: str, n: int) -> np.ndarray:
        offset = self.offsets[source]
        src_start = self.out_frame - offset
        src_stop = src_start + n
        result = np.zeros(n, dtype=np.float32)

        lo = max(src_start, 0)
        hi = min(src_stop, self._received[source])
        if hi > lo:
            result[lo - src_start : hi - src_start] = self._take(source, hi - lo)
        return result

    def _take(self, source: str, count: int) -> np.ndarray:
        chunks = []
        remaining = count
        while remaining > 0:
            block = self._pending[source][0]
            take = min(len(block), remaining)
            chunks.append(block[:take])
            if take == len(block):
                self._pending[source].popleft()
            else:
                self._pending[source][0] = block[take:]
            remaining -= take
        self._pending_frames[source] -= count
        if len(chunks) == 1:
            return chunks[0]
        return np.concatenate(chunks)
