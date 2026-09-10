# Improve Windows recording reliability

Reviewed: 2026-09-09. Status: implementation review and follow-up plan; the improvements below have not been implemented.

## Review summary

The implementation follows the planned architecture: lazy platform dispatch, conditional PyAudioWPatch dependency, device overrides, common-rate selection, and stereo recording. However, the recording lifecycle and alignment safeguards are incomplete.

**Validation:** all 51 tests pass and lint checks pass. Formatting checks flag six files. Windows hardware behavior remains unverified. This review covers the working-tree implementation, including uncommitted files.

Priority findings:

- **P1 — Device loss can report success.** The inactive-stream branch exits without recording a failure, then prints “Saved” and returns a path. Writer completion is also not checked after the timed join. See [recording shutdown](../src/recorder_windows.py), starting around line 367.
- **P1 — Buffering is not bounded end to end.** Queues are bounded, but the writer transfers their contents into unlimited alignment deques. If one source stops delivering while remaining active, the other accumulates indefinitely. A synthetic check retained 354,176 microphone frames—over seven seconds at 48 kHz. See [alignment buffering](../src/alignment.py), starting around line 25.
- **P1 — Stop can discard captured audio.** Output ends at the shorter source’s received position. There is no final drain with padding, frozen stop position, or clipping to the requested end.
- **P1 — Timing and discontinuities are not checked.** Callbacks discard `time_info` and frame metadata, perform downmixing/meter calculations, and only log status flags. Later packets are assumed contiguous even after a capture interruption. See [callback handling](../src/recorder_windows.py), starting around line 247.
- **P2 — Remaining safeguards are missing.** Exact loopback matching returns the first duplicate; some initialization/device errors escape readable handling; no RIFF size guard exists; partial-file messages do not establish that a file was finalized.

## Implementation changes

### 1. Make recording outcomes and cleanup explicit

- Keep the public `record(name) -> Path | None` interface and existing CLI exit codes.
- Introduce one internal session state holding the first failure, stop position, acquired streams, and writer completion result.
- Enclose initialization, destination creation, stream opening, startup, recording, and cleanup in one lifecycle. Handle Ctrl+C during startup as well as during recording.
- Treat unexpected inactivity, capture errors, and writer failure as interruptions returning `None`.
- Make the writer’s startup wait stop-aware. Stop producers before the final drain, explicitly close acquired streams, and check writer completion. A timeout must never produce a success message.
- Print a saved path only after successful file closure; distinguish a finalized partial recording from an incomplete or missing file. Report duration from written frames.

### 2. Bound capture and preserve the timeline

- Queue packets containing source, copied bytes, frame count, callback timing, status flags, and monotonic receipt time. Move conversion, downmixing, meters, and logging into the worker.
- Enforce the five-second limit using actual outstanding frames across both queues and alignment buffers, separately per source.
- Track last callback receipt. Default to a five-second startup/no-progress timeout, independent of `is_active()`. Missing callbacks must produce a clear interruption; do not silently classify them as silence.
- Extend the private alignment interface with explicit finalization to an end frame. Preserve accepted audio up to that boundary, pad uncovered portions of either channel, and discard samples beyond it.
- Freeze the end frame immediately on Ctrl+C or the first failure. During capture, continue waiting for both sources instead of inserting speculative silence.
- Abort on malformed packets and reported input discontinuities. Return the appropriate callback stop/abort result without allowing exceptions to escape.

### 3. Make synchronization measurable

- Retain fixed-offset alignment for this version, explicitly described as an estimate. Preserve timing metadata and log initial offsets, cumulative frames, callback gaps, and timing residuals periodically.
- Do not directly subtract PortAudio timestamps from Python’s monotonic clock. PortAudio defines callback timestamps against the associated stream’s time base; its pinned WASAPI backend constructs timing from host time and buffering information. See [PortAudio timing documentation](https://files.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html) and the [pinned WASAPI source](https://raw.githubusercontent.com/s0d3s/PyAudioWPatch/v0.2.12.8/portaudio_v19/src/hostapi/wasapi/pa_win_wasapi.c).
- Reject invalid or regressing timing and discontinuities that make placement unreliable.
- Update the original plan’s shared-clock and continuous-silence claims to assumptions requiring measurement. Do not add drift correction until the intended hardware demonstrates a need.

### 4. Complete device, file, and documentation safeguards

- Require exactly one matching WASAPI loopback; list candidates for duplicate or missing matches.
- Normalize expected library, initialization, default-device, format, and filesystem failures into readable messages.
- Create destinations exclusively in both backends to make overwrite refusal reliable.
- Stop before PCM16 stereo output reaches the RIFF limit, using a conservative byte ceiling and an explicit size-limit interruption message.
- Update [the Windows plan](windows-recording-plan.md) to distinguish implemented work, outstanding fixes, and pending hardware validation.
- Expand README instructions with silence, unplugging, long-recording checks, output-device matching, and the distinction between recording readiness and missing Mac transcription assets.

## Test and acceptance plan

- Add fake-stream tests that invoke `record()` through normal stop, early Ctrl+C, partial startup, inactive streams, stalled callbacks, malformed packets, overflow, and writer/open/close failures.
- Verify failure exit behavior, cleanup, writer completion, and truthful saved-file messages.
- Add alignment tests for unequal tails, exact stop clipping, gap padding, variable packet sizes, and the combined buffer limit.
- Cover duplicate loopbacks, independent per-device rate support, missing defaults, overwrite refusal, and a simulated RIFF boundary.
- Test lazy imports in a fresh process and verify missing Whisper assets do not prevent recording.
- Run the full suite and lint checks; format touched implementation files.
- On Windows 11 x64/Python 3.13, verify wheel installation, separate channels, delayed playback, silence/resumption, Ctrl+C during silence, and headset removal. Follow with a 30–60 minute recording, early/late timing measurements, and Mac transcription.

## Assumptions and boundaries

Preserve the original library-based approach, Mac capture algorithm, commands, channel layout, and common-rate requirement. Keep automatic reconnection, resampling, native helpers, installers, and Windows CI outside this improvement pass. Completion of local tests means ready for Windows testing; reliable Windows recording requires the hardware checks above.
