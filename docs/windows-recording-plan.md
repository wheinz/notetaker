# Windows recording with PyAudioWPatch

Status: implemented (2026-09-09); pending Windows hardware validation. The code, conditional dependency, focused tests, and Windows instructions below are in place. The sections marked "assumption" (§4 rate, §5 shared clock / continuous silence) must be confirmed on the intended hardware before this is considered reliable.

## 1. Goal and chosen approach

Add Windows recording to the existing Python CLI using **PyAudioWPatch**, a Python package that exposes Windows WASAPI playback loopback. Preserve microphone on the left WAV channel, meeting/playback audio on the right, and the current transcription pipeline.

Develop source on Mac, push to GitHub, download/pull the code on a Windows PC, install Python dependencies, and test recording manually there. Windows hardware testing is a separate step after development. No Windows build artifact is needed.

Target Windows 11 x64 and initially test with 64-bit CPython 3.13. Capture all audio playing through one selected output. Keep Mac recording unchanged.

No VB-CABLE, BlackHole on Windows, virtual-driver installation, custom C++ helper, CMake, Windows build workflow, subprocess protocol, or audio-routing changes. PyAudioWPatch includes native library code in its prebuilt Python package; we are avoiding our own native build, not claiming this is a pure-Python dependency.

Approval, signing, installers, rollout, and formal IT handoff are outside this initial plan. If the target PC blocks the package or microphone, record the actual failure for later resolution; do not bypass its settings.

## 2. Dependencies and minimal file changes

### Dependency setup

Add this platform-specific dependency to `pyproject.toml` during implementation:

```toml
"PyAudioWPatch==0.2.12.8; sys_platform == 'win32'"
```

PyPI publishes a CPython 3.13 Windows x64 wheel for this version. Use Python 3.13 for the first Windows test, matching the project's existing `.python-version`. Keep the project's broader Python requirement unchanged; do not assume every future Python version or architecture has a wheel.

Regenerate `uv.lock` on Mac and verify the Windows dependency appears with its platform marker. Mac `uv sync` must not install/import PyAudioWPatch. On Windows use the prebuilt wheel; if dependency installation tries to compile it, check Python version/architecture instead of adding a compiler requirement.

Keep existing `sounddevice` and `soundfile` dependencies. The new backend uses NumPy and `soundfile` for sample processing and WAV writing. Declare NumPy directly since the project imports it already, rather than relying on `soundfile` to install it transitively. No new resampling or GUI package in the initial implementation.

### Python changes

1. Move the existing Mac implementation from `src/recorder.py` to `src/recorder_macos.py` without changing its capture algorithm.
2. Make `src/recorder.py` a small platform dispatcher preserving `record(name: str | None = None) -> Path | None`. Use lazy imports.
3. Add `src/recorder_windows.py` containing device selection, two PyAudioWPatch input streams, a small alignment/writer loop, and cleanup.
4. Make `main.py` device checks platform-aware. Import `sounddevice` and the Mac-only helpers (`SETUP_INSTRUCTIONS`, `find_input_device`, `blackhole_present`) only on the Mac path; those symbols, along with `DeviceInfo` and the meter/`SILENCE_PEAK_THRESHOLD` helpers, move to `recorder_macos.py` or a small shared module both backends import. The `devices` command currently hard-codes the BlackHole/aggregate checks and must branch on platform. Keep existing public commands, arguments, and 0/1 exit codes.
5. Add two optional settings to `src/config.py` and `.env.example`: `WINDOWS_MIC_DEVICE_MATCH` and `WINDOWS_OUTPUT_DEVICE_MATCH`.
6. Add Windows setup/test instructions to README and a few focused Python tests.

Use `import pyaudiowpatch as pyaudio` only inside the Windows backend. Do not import ordinary `pyaudio`, which is a different package. Mac tests should be able to import the dispatcher without loading the Windows extension.

Reuse existing meter calculations and labels where convenient; extract only those small helpers if both backends need them. Do not add a backend registry, shared options/results framework, new commands, or timed recording.

Leave transcription, merging, echo handling, and Whisper server behavior unchanged. The first Windows WAV can be copied to Mac for processing.

## 3. Device selection

Use one `pyaudio.PyAudio()` instance for both capture streams. Restrict selection to its WASAPI host API. Do not combine `sounddevice` device indexes with PyAudioWPatch indexes.

Default selection:

- Get the WASAPI default microphone with `get_default_wasapi_device(d_in=True)`.
- Get the WASAPI default playback device with `get_default_wasapi_device(d_out=True)`.
- Resolve playback to its loopback input by exact name: `f"{name} [Loopback]"`.

These are the defaults exposed by PortAudio. Do not describe them as guaranteed Windows communications-role defaults.

Override selection:

- `WINDOWS_MIC_DEVICE_MATCH`: case-insensitive substring of a non-loopback WASAPI capture-device name.
- `WINDOWS_OUTPUT_DEVICE_MATCH`: case-insensitive substring of a WASAPI playback-device name; resolve its loopback analogue after selection by exact `name + " [Loopback]"` match.
- An unset/empty setting uses the default. Zero or multiple matches produce a clear error and the candidate names; never pick an arbitrary match.
- Device indexes are used only within the current PyAudio instance. Display them for diagnostics but do not persist them as stable Windows endpoint IDs.
- Do not use `get_wasapi_loopback_analogue_by_dict(...)` for loopback resolution: it matches by substring (`info_dict["name"] in loopback["name"]`) and returns the first hit, so two outputs sharing a name prefix can resolve to the wrong loopback. Resolve by exact `name + " [Loopback]"` equality and error on missing or multiple matches.

Use `devices` to display WASAPI microphones, playback names, their loopback counterparts, and selected names. Show recording readiness separately from the existing Whisper check; readiness means both devices resolve and a common supported rate is found (see §4). Missing Whisper assets may still cause `devices` to exit 1 but must not prevent `record`.

The meeting application's selected output must match the recorder's output. Audio from other applications on that output is also recorded. No routing or meeting settings are changed automatically.

Resolve and pin devices at the start. Do not add COM device-notification code. For the initial library-based version, users stop recording before intentionally changing output devices; default changes are not guaranteed to be reported dynamically by PortAudio. If a selected stream becomes inactive/errors, stop and save. Automatic switching/reconnection remains out of scope. This is an explicit reduction from the native plan's default-change monitoring.

## 4. Capture format and streams

Retain the current naming convention, `config.RAW_DIR`, stereo WAV, and PCM16 encoding. Left is microphone; right is playback.

### Keep nominal-rate handling small

The initial backend requires a sample rate supported by both selected input streams. Probe candidates in this order, removing duplicates:

1. Loopback device's default sample rate.
2. Microphone's default sample rate.
3. 48,000 Hz.
4. 44,100 Hz.

Use `is_format_supported` separately for each input configuration. Use each device's advertised input channel count and request `paFloat32`. Both microphone and loopback are opened with `input=True`; the physical playback endpoint is not itself opened as an input stream.

Choose the first rate accepted by both and write the WAV at that rate. The existing transcriber reads the WAV's rate and converts to 16 kHz, so fixed 48 kHz is unnecessary. If none works, show both device names/rates and ask through the error message for compatible devices or matching Windows device-format settings. Do not silently mix incompatible rates or introduce a native resampler.

This is a deliberate first-version limitation. Validate it with the intended headset on Windows. General mismatched-rate support is additional work only if the real setup requires it; it is not silently assumed to work.

### Callback capture

Open two independent callback input streams with `start=False` and `frames_per_buffer=1024`, then start them in close succession. Do not perform alternating blocking reads: an idle loopback read could stall microphone recording or Ctrl+C.

Each callback only copies data and records its source, `frame_count`, `time_info`, status flags, and a monotonic receipt time into a bounded queue. Return `(None, pyaudio.paContinue)` normally. On stop/fatal callback error, signal shared state and return `paComplete`/`paAbort` as appropriate; do not raise unhandled exceptions from callbacks.

A writer worker converts float32 bytes to arrays using the actual channel count, downmixes each source by averaging its channels, aligns sources, and writes interleaved samples through `soundfile.SoundFile(..., subtype='PCM_16')`. Averaging assumes a stereo output; a 5.1/7.1 loopback (whose channel count mirrors the output) folds surround and LFE into the mono "Others" channel, acceptable for meeting capture but not surround-accurate. Do not write the file or print from callbacks.

Bound buffered data to five seconds per source. Queue overflow is an interruption, not permission to drop audio silently. Surface writer errors to the main thread.

## 5. Alignment and drift

Two streams at the same nominal rate still have separate start times. Distinguish a constant start offset from accumulating clock drift; WASAPI shared mode matters for both.

WASAPI shared mode runs both streams through the audio engine, which resamples everything onto a single mix clock. The app receives samples already on essentially the same engine clock, so residual drift is expected to be on the order of milliseconds per hour, not hundreds. The dominant real-world misalignment is a fixed start offset: the two `start_stream()` calls are sequential and the two paths have different buffering. Accumulating drift is only likely with exclusive-mode/ASIO access to independent hardware clocks, which this design does not use. **These are assumptions, not measured facts** — confirm via the drift log during the long recording (§7 step 7) before relying on them.

PyAudioWPatch exposes PortAudio callback timing, not raw WASAPI device frame positions/QPC timestamps. Timing is constructed from the host clock and buffering information; it must not be advertised as exact hardware synchronization.

First version — fixed-offset alignment only:

1. Capture a common `time.monotonic()` origin immediately before starting both streams, and record each stream's first-callback timestamp.
2. Compute one constant per-source offset from that origin and write each source at `origin + offset + frames / sample_rate`. Do not build a rolling median, residual estimator, or interpolation stage.
3. Advance each source by actual frame counts at the chosen rate. Fill a gap where a stream stops delivering (device loss/error) with zeros; if a source is inactive beyond a small threshold, stop and finalize rather than stretch the other channel.
4. Stop with a clear error on nonmonotonic/invalid timing, an unexplained larger overlap, or audio arriving behind the already-written position. Do not silently write misaligned speech.

Silence is not a special case: WASAPI loopback keeps delivering near-zero frames while nothing plays, so playback silence/resumption needs no separate machinery. **Assumption to verify** — if the selected output stops delivering frames entirely during silence, the no-progress timeout will report it as an interruption rather than silence.

Measurement gate before any drift correction: during the Windows test, log both streams' cumulative frame positions over the 30–60 minute recording and compute actual inter-channel drift. Only if it exceeds ~30 ms/hour (or echo cancellation is later enabled, since the NLMS reference needs stable alignment) add a small correction stage keyed to that observation. Until then, assume a shared engine clock.

Keep the alignment helper independent of PyAudioWPatch so synthetic packets can exercise it on Mac.

During the Windows test, specifically inspect delayed start and timing near the beginning/end of a longer recording. If callback timing makes fixed-offset alignment unreliable, report the limitation and fix this backend based on the observations. Do not silently reinstate a custom C++ helper, promise sample-accurate alignment, or declare long-meeting reliability based on a short recording.

## 6. Stop, errors, and current UI behavior

The main thread keeps the existing elapsed-time and "Me"/"Others" meter display, updated roughly twice per second. Preserve current whole-recording silence warnings and the -45 dBFS activity threshold. Silence is not itself a failure.

On Ctrl+C:

1. Freeze the intended recording end time and signal stop.
2. Stop/close both streams, including a partly initialized stream if startup failed.
3. Drain accepted queued audio up to the end time; pad genuine silence, but do not extend past stop.
4. Join the writer, close/finalize the WAV, and terminate PyAudio.
5. Return the path only after a successful normal stop and file finalization.

On device/capture/writer failure, stop both sources, finalize the shorter file when possible, print the error and saved path, and return `None` so the CLI exits 1. Never report a complete meeting after one channel stops. No automatic reconnection.

Check stream activity in the main loop; callback mode must remain stoppable during silence. Do not assume every native capture failure reaches Python as a detailed callback flag. Device-loss behavior is a required manual test.

Catch missing-library, unsupported-format, access/device, and file errors with readable messages. Refuse overwriting an existing destination in both backends: apply the same guard to the Mac recorder (it currently overwrites silently) so behavior is consistent. Write directly to the WAV as the current recorder does; no recovery/rename framework. A crash or write failure may leave an incomplete WAV, which must not be described as safely finalized.

Stop and finalize before reaching the RIFF data-size limit. Do not add a public duration option. Keep the PC awake during initial testing; suspend/resume support is deferred.

## 7. Mac development checks and Windows handoff

On Mac, run existing Python tests and focused tests with fake capture packets/devices for:

- Lazy dispatch without importing the Windows extension.
- Unique name matching, ambiguous/missing devices, and correct playback-to-loopback selection.
- Common-rate selection and unsupported combinations.
- Channel assignment, staggered starts (fixed start-offset alignment), and stream-gap zero-fill.
- Ctrl+C, partial startup, inactive streams, queue/writer failures, and cleanup.

Do not install PyAudioWPatch on Mac or add Windows CI just for this port. Local tests establish Python logic, not Windows capture behavior.

Update README and `.env.example`. Once implemented, the user pushes the source and updated lockfile. The Windows tester pulls/downloads the matching commit; there is no executable artifact or separate build step.

Manual Windows procedure:

1. Use a writable checkout with 64-bit Python 3.13 and the project's existing uv setup. Run `uv sync --python 3.13 --locked`.
2. Create `.env` from the example if needed. Run `uv run main.py devices`; set the two name-match settings only when defaults are wrong.
3. Run `uv run main.py record --name windows-check`, speak locally and play meeting audio, then press Ctrl+C after about 15 seconds.
4. Listen to channels separately and check duration: microphone left, playback right. Confirm the meeting could still use the microphone.
5. Repeat with silence before playback starts and a silent interval mid-recording. Returning speech must stay at the correct time. Stop while playback is silent too.
6. Unplug the selected headset. Verify an interruption is reported and the shorter WAV is readable. Do not expect automatic switching. For intentional output changes, stop first, then select/restart.
7. Make one representative 30–60 minute recording on the intended app/headset and inspect early/late timing, logging inter-channel drift over the recording (see §5). Report actual observations; short-test success does not prove long-recording synchronization.
8. Copy the WAV to Mac and process it using the existing transcribe command. Check "Me"/"Others" and timestamps.

Record commit, Python/package version, Windows version, selected devices/rate, observations, and console errors. Fix on Mac, push, pull, and repeat. Expand testing only for concrete failures or newly required hardware. No full app/hardware matrix or formal sign-off is required.

## 8. Completion and boundaries

Mac development handoff is complete when the Python implementation, conditional dependency/lockfile, focused tests, and Windows instructions are ready. Windows manual testing can remain pending at that point and must be labeled accordingly.

Initial Windows functionality is verified when dependencies install from wheels, both sources record on the intended devices, silence/stop behavior works, and the WAV passes through existing processing. State the longer recording's duration and timing result separately.

Keep out of scope: native helper/build pipeline, drivers, approval/signing, installers, fleet deployment, ARM64, Windows 10 qualification, remote desktops, app-only capture, timed recording, automatic rerouting/recovery, sleep support, and general device-rate conversion unless actual Windows testing requires it.

### References

- [PyAudioWPatch project](https://github.com/s0d3s/PyAudioWPatch) — loopback capture and device helpers.
- [PyAudioWPatch 0.2.12.8 files](https://pypi.org/project/PyAudioWPatch/0.2.12.8/#files) — prebuilt CPython 3.13 Windows x64 package.
- [Python wrapper source](https://github.com/s0d3s/PyAudioWPatch/blob/v0.2.12.8/src/pyaudiowpatch/__init__.py) — stream, callback, device-selection, and format-probing interfaces.
- [PortAudio callback time documentation](https://files.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html) — timing fields; do not confuse them with raw Windows timestamps.
- [WASAPI backend source](https://github.com/s0d3s/PyAudioWPatch/blob/v0.2.12.8/portaudio_v19/src/hostapi/wasapi/pa_win_wasapi.c) — host timing behavior to check when validating alignment.
