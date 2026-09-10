# Windows implementation review — follow-up

Reviewed: 2026-09-09.

Compared the updated working-tree implementation with [the first implementation review](windows-implementation-review.md). This document records findings only; no implementation fixes were made during this review.

## Summary and validation

The implementation is closer to the plan, but several reliability fixes remain incomplete. All **71 tests pass**, and lint and formatting checks pass. Windows hardware validation remains pending.

Resolved or added:

- Inactive streams now return failure.
- Duplicate exact loopback matches are rejected.
- Callbacks queue raw packets; downmixing and meters run in the worker.
- Alignment supports finalization with tail padding and has its own pending-frame limit.
- Exclusive destination creation and a conservative WAV size guard are present.
- README instructions distinguish recording readiness from transcription setup and include manual validation steps.

The presence of these mechanisms does not yet establish correct integration. In particular, the recording loop does not use the frozen stop boundary, combined buffering exceeds the intended limit, and file ownership and shutdown still have gaps.

Source line numbers below refer to the implementation reviewed on this date and may move after edits.

## Remaining findings

### 1. P1 — Finalization ignores the frozen stop position

**Pointer:** [src/recorder_windows.py](../src/recorder_windows.py), lines 458–463; also the capture-drain loop immediately above.

`freeze_stop()` records the requested end, but finalization uses `timeline.min_end()` on failure or `timeline.max_end()` on normal stop, then overwrites `session.stop_frame`. The writer also exits on failure before draining all accepted packets, discarding the longer channel’s tail.

Using the existing accelerated fake stream, a 0.111-second session successfully produced a 1.771-second WAV. This is a synthetic demonstration that the stop constraint is not enforced, not a measurement of Windows hardware timing.

**Required improvement:** Apply the frozen boundary to writes and finalization. Stop producers, drain accepted packets up to that boundary, pad the shorter source, and discard samples beyond the boundary. Preserve the original stop position instead of replacing it with the timeline position. Count successfully written frames separately.

**Regression coverage:** Exact end clipping through `record()`, unequal tails, failure with accepted packets still queued, and normal stop with buffered data extending beyond the end.

### 2. P1 — Capture overflow still reports success

**Pointer:** [src/recorder_windows.py](../src/recorder_windows.py), lines 389–391.

Nonzero capture status flags only generate warnings; affected packets are appended as contiguous audio. Injecting input-overflow flags into both fake streams still caused `record()` to return success.

**Required improvement:** Detect input discontinuity flags before accepting the packet, record a failure, and stop capture so missing audio cannot silently shift channel timing. Return the appropriate callback termination result once stopping or failing.

**Regression coverage:** Input overflow and underflow, failure return value, interruption message, and preservation of audio accepted before the discontinuity.

### 3. P1 — Startup interrupts bypass cleanup

**Pointer:** [src/recorder_windows.py](../src/recorder_windows.py), lines 504–515; resource initialization earlier in `record()` has related gaps.

The cleanup `finally` block begins after stream startup. Startup handlers catch `Exception`, which does not catch `KeyboardInterrupt`. Injecting Ctrl+C into `start_stream()` let the interrupt escape with both streams unclosed. PyAudio initialization and directory creation also remain outside comprehensive error handling.

**Required improvement:** Put the entire resource lifecycle under one cleanup path, including initialization, destination creation, partial stream opening, startup, worker startup, and recording. Handle Ctrl+C during startup explicitly and release every acquired resource even when a later cleanup operation fails.

**Regression coverage:** Ctrl+C during first and second stream startup, second-stream open failure, PyAudio initialization failure, directory creation failure, and cleanup failures.

### 4. P1 — Writer timeout permits concurrent file closure

**Pointer:** [src/recorder_windows.py](../src/recorder_windows.py), lines 551–556.

When the writer fails to finish within 15 seconds, the main thread records failure but still closes the WAV and marks it finalized. The worker may still be inside `wav.write()`. Closing concurrently is unsafe, and a finalized partial-file result has not been established.

**Required improvement:** Give one thread ownership of writing and closing. Require its completion result before reporting finalization. A timeout must report that finalization is unconfirmed and must not close a handle still being used by the worker. Apply the same ownership discipline to startup failure paths.

**Regression coverage:** A deliberately blocked writer, write failure, close failure, and verification that a timeout cannot produce a finalized-partial-file message or concurrent close.

### 5. P2 — Exclusive WAV helper leaves the underlying file open

**Pointer:** [src/wav.py](../src/wav.py), lines 9–15.

`SoundFile` does not take ownership of the supplied Python file object as the helper claims. A diagnostic retaining the underlying object verified that `fobj.closed` remains `False` after `wav.close()`. This affects both recording backends and leaves startup cleanup attempting to unlink an open file.

**Required improvement:** Explicitly manage both objects’ lifetimes, close them in the correct order on success and failure, and update the helper’s ownership documentation. Do not depend on garbage collection to release the underlying handle.

**Regression coverage:** Underlying handle closure after successful recording, stream startup failure, WAV initialization failure, write failure, and close failure.

### 6. P2 — Five-second limit is split across two buffers

**Pointer:** [src/recorder_windows.py](../src/recorder_windows.py), lines 310–313 and 424–425.

Each packet queue can hold roughly five seconds independently of the timeline’s five-second allowance. Combined outstanding audio therefore exceeds the planned limit. Queue capacity also counts packets rather than their actual frame counts.

**Required improvement:** Use one per-source frame budget covering queued and pending audio. Reserve capacity when accepting a packet and release it only when frames are written or deliberately discarded. Enforce the limit using actual frame counts, including variable packet sizes.

**Regression coverage:** One source stalls while the other continues, variable packet sizes, queued plus pending audio at the boundary, and capacity release after writing.

### 7. P2 — Timing checks cannot support the planned drift measurement

**Pointer:** [src/recorder_windows.py](../src/recorder_windows.py), lines 191–210.

NaN timestamps are accepted. The residual calculation uses the current packet’s frame count rather than the previous packet’s duration when comparing successive packet start times. Logs omit cumulative source positions and callback gaps. Isolated residual messages every ten seconds cannot establish accumulated inter-channel drift.

**Required improvement:** Validate finite timestamps, track previous packet duration and cumulative frames, and emit paired timing measurements suitable for the long-recording check. Keep fixed-offset alignment explicitly approximate and distinguish timing diagnostics from measured audio synchronization.

**Regression coverage:** Non-finite first and subsequent timestamps, variable packet sizes, regressing timing, discontinuities, and cumulative drift diagnostics with synthetic clock skew.

## Test coverage and completion status

The new lifecycle tests currently cover inactive streams, overwrite refusal, and basic successful output. The successful-output test checks file existence and minimum size, but does not verify duration, channel content, or stop clipping. These assertions are too weak to catch several findings above.

Before marking the first review plan complete:

1. Fix the P1 lifecycle, discontinuity, and stop-boundary issues.
2. Fix file ownership, the combined frame budget, and timing diagnostics.
3. Add the regression scenarios attached to each finding and strengthen the successful-recording test to inspect samples and duration.
4. Complete the planned fresh-process lazy-import, missing-Whisper recording, and simulated RIFF-boundary checks.
5. Run the full suite, lint, and formatting checks again.
6. Perform the Windows 11 x64/Python 3.13 manual checks: channels, delayed playback, silence/resumption, Ctrl+C during silence, headset removal, and a 30–60 minute timing measurement followed by Mac transcription.

Local test success means ready for hardware testing. Reliable Windows recording remains unverified until the intended hardware passes those checks.
