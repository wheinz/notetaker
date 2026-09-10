import logging
import math
import queue
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config
from .alignment import AlignmentError, TimelineWriter
from .meter import SILENCE_PEAK_THRESHOLD, Levels, meter_line, rms
from .wav import open_wav_exclusive

logger = logging.getLogger(__name__)

SOURCE_MIC = "mic"
SOURCE_LOOPBACK = "loopback"
FRAMES_PER_BUFFER = 1024
QUEUE_SECONDS = 5.0
STARTUP_TIMEOUT = 5.0
NO_PROGRESS_TIMEOUT = 5.0
TIMING_JUMP_SECONDS = 1.0
MAX_WAV_DATA_BYTES = 3 * 1024**3


class _DeviceError(Exception):
    pass


@dataclass
class _Packet:
    source: str
    data: bytes
    frame_count: int
    adc_time: float | None
    status: int
    receipt: float


@dataclass
class _Session:
    failure: list[str] = field(default_factory=list)
    stop_frame: int | None = None
    frames: int = 0
    finalized: bool = False


@dataclass
class _Timing:
    last_adc: float | None = None
    last_log: float = 0.0


def _mark(ok: bool) -> str:
    return "ok " if ok else "MISSING"


def _device_names(infos) -> str:
    return ", ".join(f"'{i['name']}'" for i in infos)


def _wasapi_host_api(pa, pyaudio):
    for host in pa.get_host_api_info_generator():
        if host["type"] == pyaudio.paWASAPI:
            return host
    raise _DeviceError("WASAPI host API not found.")


def _wasapi_devices(pa, wasapi):
    return list(
        pa.get_device_info_generator_by_host_api(host_api_index=wasapi["index"])
    )


def _select_mic(pa, pyaudio, wasapi):
    match = config.WINDOWS_MIC_DEVICE_MATCH.strip()
    devices = [
        i
        for i in _wasapi_devices(pa, wasapi)
        if i["maxInputChannels"] > 0 and not i["isLoopbackDevice"]
    ]
    if not match:
        try:
            return pa.get_default_wasapi_device(d_in=True)
        except Exception as exc:
            raise _DeviceError(f"no default WASAPI input device: {exc}") from exc
    matches = [d for d in devices if match.lower() in d["name"].lower()]
    if not matches:
        raise _DeviceError(
            f"No WASAPI microphone matches '{match}'. Candidates: {_device_names(devices)}"
        )
    if len(matches) > 1:
        raise _DeviceError(
            f"Multiple WASAPI microphones match '{match}': {_device_names(matches)}"
        )
    return matches[0]


def _select_output(pa, pyaudio, wasapi):
    match = config.WINDOWS_OUTPUT_DEVICE_MATCH.strip()
    devices = [
        i
        for i in _wasapi_devices(pa, wasapi)
        if i["maxOutputChannels"] > 0 and not i["isLoopbackDevice"]
    ]
    if not match:
        try:
            return pa.get_default_wasapi_device(d_out=True)
        except Exception as exc:
            raise _DeviceError(f"no default WASAPI output device: {exc}") from exc
    matches = [d for d in devices if match.lower() in d["name"].lower()]
    if not matches:
        raise _DeviceError(
            f"No WASAPI output matches '{match}'. Candidates: {_device_names(devices)}"
        )
    if len(matches) > 1:
        raise _DeviceError(
            f"Multiple WASAPI outputs match '{match}': {_device_names(matches)}"
        )
    return matches[0]


def _resolve_loopback(pa, output):
    target = f"{output['name']} [Loopback]"
    matches = [
        i for i in pa.get_loopback_device_info_generator() if i["name"] == target
    ]
    if not matches:
        raise _DeviceError(
            f"No loopback device found for '{output['name']}' (expected '{target}')."
        )
    if len(matches) > 1:
        raise _DeviceError(f"Multiple loopback devices match '{target}'.")
    return matches[0]


def _select_rate(pa, pyaudio, mic, loopback):
    mic_ch = mic["maxInputChannels"]
    loop_ch = loopback["maxInputChannels"]

    candidates = []
    for dev in (loopback, mic):
        rate = int(dev["defaultSampleRate"])
        if rate not in candidates:
            candidates.append(rate)
    for rate in (48000, 44100):
        if rate not in candidates:
            candidates.append(rate)

    def supported(rate):
        for device, channels in ((mic, mic_ch), (loopback, loop_ch)):
            try:
                pa.is_format_supported(
                    rate,
                    input_device=device["index"],
                    input_channels=channels,
                    input_format=pyaudio.paFloat32,
                )
            except ValueError:
                return False
        return True

    for rate in candidates:
        if supported(rate):
            return rate, mic_ch, loop_ch

    raise _DeviceError(
        f"No common sample rate supported by '{mic['name']}' "
        f"({mic['defaultSampleRate']} Hz) and '{loopback['name']}' "
        f"({loopback['defaultSampleRate']} Hz)."
    )


def _resolve_setup(pa, pyaudio):
    try:
        wasapi = _wasapi_host_api(pa, pyaudio)
        mic = _select_mic(pa, pyaudio, wasapi)
        output = _select_output(pa, pyaudio, wasapi)
        loopback = _resolve_loopback(pa, output)
        rate, mic_channels, loopback_channels = _select_rate(pa, pyaudio, mic, loopback)
        return mic, output, loopback, rate, mic_channels, loopback_channels
    except _DeviceError:
        raise
    except Exception as exc:
        raise _DeviceError(f"could not resolve devices: {exc}") from exc


def _check_timing(pkt: _Packet, tstate: _Timing, rate: int) -> str | None:
    """Return an error message if the packet's timing is unusable, else None."""
    if pkt.adc_time is None:
        return None
    if not math.isfinite(pkt.adc_time):
        return f"{pkt.source} non-finite timing ({pkt.adc_time})"
    if tstate.last_adc is None:
        tstate.last_adc = pkt.adc_time
        return None
    d_adc = pkt.adc_time - tstate.last_adc
    tstate.last_adc = pkt.adc_time
    if d_adc < -1e-3:
        return f"{pkt.source} timing regressed ({d_adc:.4f}s)"
    if d_adc <= 1e-6:
        return None
    residual = d_adc - pkt.frame_count / rate
    if abs(residual) > TIMING_JUMP_SECONDS:
        return f"{pkt.source} timing discontinuity ({residual:+.4f}s)"
    now = time.monotonic()
    if now - tstate.last_log > 10.0:
        tstate.last_log = now
        logger.info("%s timing residual %+.4fs", pkt.source, residual)
    return None


def print_devices() -> bool:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        print("PyAudioWPatch is not installed. Run `uv sync` on Windows.")
        return False

    pa = pyaudio.PyAudio()
    try:
        try:
            wasapi = _wasapi_host_api(pa, pyaudio)
        except _DeviceError as exc:
            print(f"[{_mark(False)}] WASAPI: {exc}")
            return False

        print("WASAPI devices:")
        for info in _wasapi_devices(pa, wasapi):
            tag = " [Loopback]" if info["isLoopbackDevice"] else ""
            print(
                f"  [{info['index']}] {info['name']}{tag} "
                f"(in:{info['maxInputChannels']} out:{info['maxOutputChannels']})"
            )
        print()

        ok = True
        mic = None
        loopback = None
        try:
            mic = _select_mic(pa, pyaudio, wasapi)
        except _DeviceError as exc:
            print(f"[{_mark(False)}] Microphone: {exc}")
            ok = False
        else:
            print(f"[{_mark(True)}] Microphone -> '{mic['name']}'")

        try:
            output = _select_output(pa, pyaudio, wasapi)
            loopback = _resolve_loopback(pa, output)
        except _DeviceError as exc:
            print(f"[{_mark(False)}] Output/loopback: {exc}")
            ok = False
        else:
            print(
                f"[{_mark(True)}] Output -> '{output['name']}' "
                f"(loopback '{loopback['name']}')"
            )

        if mic is not None and loopback is not None:
            try:
                rate, mic_ch, loop_ch = _select_rate(pa, pyaudio, mic, loopback)
            except _DeviceError as exc:
                print(f"[{_mark(False)}] Common rate: {exc}")
                ok = False
            else:
                print(
                    f"[{_mark(True)}] Common rate {rate} Hz "
                    f"(mic {mic_ch}ch, loopback {loop_ch}ch)"
                )
        return ok
    finally:
        pa.terminate()


def record(name: str | None = None) -> Path | None:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        print("PyAudioWPatch is not installed on this Windows machine.")
        print("Install it via `uv sync` (Python 3.13 x64) and retry.")
        return None

    pa = pyaudio.PyAudio()
    try:
        mic, output, loopback, rate, mic_channels, loopback_channels = _resolve_setup(
            pa, pyaudio
        )
    except _DeviceError as exc:
        print(f"Device setup failed: {exc}")
        pa.terminate()
        return None

    stem = name or f"meeting_{datetime.now():%Y%m%d_%H%M%S}"  # noqa: DTZ005
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.RAW_DIR / f"{stem}.wav"

    try:
        wav = open_wav_exclusive(dest, rate, 2)
    except FileExistsError:
        print(f"Refusing to overwrite existing file: {dest}")
        pa.terminate()
        return None
    except OSError as exc:
        print(f"Could not create {dest}: {exc}")
        pa.terminate()
        return None

    max_blocks = int(QUEUE_SECONDS * rate / FRAMES_PER_BUFFER) + 1
    queue_frames = int(QUEUE_SECONDS * rate)
    mic_q: queue.Queue[_Packet] = queue.Queue(maxsize=max_blocks)
    loop_q: queue.Queue[_Packet] = queue.Queue(maxsize=max_blocks)
    levels = Levels()
    session = _Session()
    stop_event = threading.Event()
    streams_stopped = threading.Event()
    writer_done = threading.Event()
    first_times = {SOURCE_MIC: None, SOURCE_LOOPBACK: None}
    last_receipt = {SOURCE_MIC: 0.0, SOURCE_LOOPBACK: 0.0}
    timing = {SOURCE_MIC: _Timing(), SOURCE_LOOPBACK: _Timing()}
    channels = {SOURCE_MIC: mic_channels, SOURCE_LOOPBACK: loopback_channels}
    t0 = None

    def fail(message: str) -> None:
        if not session.failure:
            session.failure.append(message)
        if session.stop_frame is None and t0 is not None:
            session.stop_frame = max(0, round((time.monotonic() - t0) * rate))
        stop_event.set()

    def freeze_stop() -> None:
        if session.stop_frame is None and t0 is not None:
            session.stop_frame = max(0, round((time.monotonic() - t0) * rate))
        stop_event.set()

    def make_callback(source: str):
        target_q = mic_q if source == SOURCE_MIC else loop_q

        def callback(in_data, frame_count, time_info, status):
            try:
                adc = time_info.get("input_buffer_adc_time") if time_info else None
                pkt = _Packet(
                    source, bytes(in_data), frame_count, adc, status, time.monotonic()
                )
            except Exception:  # noqa: BLE001
                fail(f"{source} callback failed")
                return (None, pyaudio.paAbort)
            if status & (pyaudio.paInputOverflow | pyaudio.paInputUnderflow):
                fail(f"{source} input discontinuity (status={status})")
                return (None, pyaudio.paAbort)
            if first_times[source] is None:
                first_times[source] = pkt.receipt
            last_receipt[source] = pkt.receipt
            if stop_event.is_set():
                return (None, pyaudio.paComplete)
            try:
                target_q.put_nowait(pkt)
            except queue.Full:
                fail(f"{source} buffer overflow")
                return (None, pyaudio.paAbort)
            return (None, pyaudio.paContinue)

        return callback

    def process_packet(pkt: _Packet, timeline: TimelineWriter) -> bool:
        ch = channels[pkt.source]
        try:
            samples = np.frombuffer(pkt.data, dtype=np.float32).reshape(
                pkt.frame_count, ch
            )
            mono = samples.mean(axis=1).astype(np.float32, copy=False)
        except Exception as exc:  # noqa: BLE001
            fail(f"{pkt.source} malformed packet: {exc}")
            return False
        problem = _check_timing(pkt, timing[pkt.source], rate)
        if problem:
            fail(problem)
            return False
        try:
            timeline.add(pkt.source, mono)
        except AlignmentError as exc:
            fail(str(exc))
            return False
        value = rms(mono)
        if pkt.source == SOURCE_MIC:
            levels.mic_rms = value
            levels.mic_peak = max(levels.mic_peak, value)
        else:
            levels.sys_rms = value
            levels.sys_peak = max(levels.sys_peak, value)
        if pkt.status:
            logger.warning("%s stream status flags: %s", pkt.source, pkt.status)
        return True

    def write_block(block: np.ndarray) -> bool:
        frames = block.shape[0]
        if (wav.tell() + frames) * 4 > MAX_WAV_DATA_BYTES:
            fail("reached WAV size limit; recording stopped")
            return False
        wav.write(block)
        return True

    def writer() -> None:
        try:
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                if stop_event.is_set():
                    return
                if any(first_times[source] is not None for source in first_times):
                    break
                time.sleep(0.01)
            else:
                fail("neither capture stream delivered audio within startup timeout")
                return

            # Some WASAPI loopback drivers do not issue callbacks while the output
            # device is completely idle. Start the timeline as soon as either
            # source is alive and represent a dormant source as silence until its
            # first callback arrives.
            offsets = {
                source: (
                    max(0, round((first_times[source] - t0) * rate))
                    if first_times[source] is not None
                    else 0
                )
                for source in (SOURCE_MIC, SOURCE_LOOPBACK)
            }
            mic_off = offsets[SOURCE_MIC]
            loop_off = offsets[SOURCE_LOOPBACK]
            logger.info(
                "alignment offsets: mic=%d frames, loopback=%d frames",
                mic_off,
                loop_off,
            )
            timeline = TimelineWriter(
                mic_off, loop_off, max_pending_frames=queue_frames
            )
            received_frames = {SOURCE_MIC: 0, SOURCE_LOOPBACK: 0}
            real_started = {
                source: first_times[source] is not None
                for source in (SOURCE_MIC, SOURCE_LOOPBACK)
            }

            def pad_dormant_source(source: str) -> None:
                if real_started[source]:
                    return
                first = first_times[source]
                target_time = first if first is not None else time.monotonic()
                target_end = max(0, round((target_time - t0) * rate))
                current_end = offsets[source] + received_frames[source]
                missing = target_end - current_end
                room = timeline.room(source)
                if room is not None:
                    missing = min(missing, room)
                if missing > 0:
                    timeline.add(source, np.zeros(missing, dtype=np.float32))
                    received_frames[source] += missing

            while True:
                pulled = False
                for source, q in ((SOURCE_MIC, mic_q), (SOURCE_LOOPBACK, loop_q)):
                    before = received_frames[source]
                    pad_dormant_source(source)
                    if received_frames[source] != before:
                        pulled = True
                    while True:
                        room = timeline.room(source)
                        if room is not None and room <= 0:
                            break
                        try:
                            pkt = q.get_nowait()
                        except queue.Empty:
                            break
                        pulled = True
                        if process_packet(pkt, timeline):
                            received_frames[source] += pkt.frame_count
                            real_started[source] = True
                out = timeline.write_available(session.stop_frame)
                if out is not None:
                    pulled = True
                    if not write_block(out):
                        break
                if streams_stopped.is_set():
                    if not pulled:
                        break
                    continue
                if not pulled:
                    time.sleep(0.005)

            stop = (
                session.stop_frame
                if session.stop_frame is not None
                else timeline.min_end()
            )
            final = timeline.finalize(stop)
            if final is not None:
                write_block(final)
            session.frames = timeline.out_frame
        except Exception as exc:  # noqa: BLE001
            fail(f"writer failed: {exc}")
        finally:
            try:
                wav.close()
                session.finalized = True
            except Exception as exc:  # noqa: BLE001
                fail(f"failed to finalize file: {exc}")
            writer_done.set()

    mic_cb = make_callback(SOURCE_MIC)
    loop_cb = make_callback(SOURCE_LOOPBACK)

    try:
        mic_stream = pa.open(
            format=pyaudio.paFloat32,
            channels=mic_channels,
            rate=rate,
            input=True,
            input_device_index=mic["index"],
            frames_per_buffer=FRAMES_PER_BUFFER,
            start=False,
            stream_callback=mic_cb,
        )
        loop_stream = pa.open(
            format=pyaudio.paFloat32,
            channels=loopback_channels,
            rate=rate,
            input=True,
            input_device_index=loopback["index"],
            frames_per_buffer=FRAMES_PER_BUFFER,
            start=False,
            stream_callback=loop_cb,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to open capture streams: {exc}")
        wav.close()
        dest.unlink(missing_ok=True)
        pa.terminate()
        return None

    t0 = time.monotonic()
    writer_thread = threading.Thread(target=writer, daemon=True)
    writer_thread.start()

    try:
        mic_stream.start_stream()
        loop_stream.start_stream()
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to start capture streams: {exc}")
        stop_event.set()
        streams_stopped.set()
        writer_thread.join(timeout=5)
        dest.unlink(missing_ok=True)
        pa.terminate()
        return None

    print(f"Recording '{output['name']}' -> {dest}")
    print("Left = microphone, right = meeting audio. Ctrl+C to stop.\n")
    started = time.monotonic()
    try:
        while True:
            time.sleep(0.5)
            if session.failure:
                break
            now = time.monotonic()
            for source in (SOURCE_MIC, SOURCE_LOOPBACK):
                if (
                    first_times[source] is not None
                    and now - last_receipt[source] > NO_PROGRESS_TIMEOUT
                ):
                    fail(f"{source} stopped delivering audio")
                    break
            if session.failure:
                break
            if not (mic_stream.is_active() and loop_stream.is_active()):
                fail("a capture stream became inactive")
                break
            line = meter_line(now - started, levels)
            sys.stdout.write("\r" + line + " " * 8)
            sys.stdout.flush()
    except KeyboardInterrupt:
        freeze_stop()
    finally:
        stop_event.set()
        for stream in (mic_stream, loop_stream):
            with suppress(Exception):
                stream.stop_stream()
            with suppress(Exception):
                stream.close()
        streams_stopped.set()
        writer_thread.join(timeout=15)
        if not writer_done.is_set():
            fail("writer did not finish; finalization unconfirmed")
        pa.terminate()
        sys.stdout.write("\n\n")

    if session.failure:
        print(f"Recording failed: {session.failure[0]}")
        if session.finalized:
            print(f"Saved partial file to {dest}")
        return None

    duration = session.frames / rate
    print(f"Saved {duration / 60:.1f} min to {dest}")
    if levels.sys_peak < SILENCE_PEAK_THRESHOLD:
        print(
            "\nWARNING: the 'Others' channel stayed silent for the whole "
            "recording.\n         Check that meeting audio plays through the "
            "selected output device."
        )
    if levels.mic_peak < SILENCE_PEAK_THRESHOLD:
        print(
            "\nWARNING: the microphone channel stayed silent for the whole "
            "recording.\n         Check the microphone device and "
            "WINDOWS_MIC_DEVICE_MATCH."
        )

    print(f"\nNext: uv run main.py transcribe {dest}")
    return dest
