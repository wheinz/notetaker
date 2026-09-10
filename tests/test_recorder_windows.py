import pytest

from src import config
from src import recorder_windows as rw


class FakePyaudio:
    paWASAPI = 13
    paFloat32 = 0x01


def make_devices():
    return [
        {
            "index": 0,
            "name": "Headset Microphone (USB)",
            "maxInputChannels": 1,
            "maxOutputChannels": 0,
            "isLoopbackDevice": False,
            "defaultSampleRate": 48000.0,
        },
        {
            "index": 1,
            "name": "Microphone Array (Realtek)",
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
            "isLoopbackDevice": False,
            "defaultSampleRate": 48000.0,
        },
        {
            "index": 2,
            "name": "Speakers (Realtek)",
            "maxInputChannels": 0,
            "maxOutputChannels": 2,
            "isLoopbackDevice": False,
            "defaultSampleRate": 48000.0,
        },
        {
            "index": 3,
            "name": "Headphones (USB)",
            "maxInputChannels": 0,
            "maxOutputChannels": 2,
            "isLoopbackDevice": False,
            "defaultSampleRate": 48000.0,
        },
        {
            "index": 4,
            "name": "Speakers (Realtek) [Loopback]",
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
            "isLoopbackDevice": True,
            "defaultSampleRate": 48000.0,
        },
        {
            "index": 5,
            "name": "Headphones (USB) [Loopback]",
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
            "isLoopbackDevice": True,
            "defaultSampleRate": 48000.0,
        },
    ]


class FakePa:
    def __init__(self, devices):
        self._devices = devices

    def get_device_info_generator_by_host_api(
        self, host_api_index=None, host_api_type=None
    ):
        return iter(self._devices)

    def get_loopback_device_info_generator(self):
        return (d for d in self._devices if d["isLoopbackDevice"])

    def get_default_wasapi_device(self, d_in=False, d_out=False):
        for d in self._devices:
            if d_out and d["maxOutputChannels"] > 0 and not d["isLoopbackDevice"]:
                return d
        for d in self._devices:
            if d_in and d["maxInputChannels"] > 0 and not d["isLoopbackDevice"]:
                return d
        raise OSError("no default")


def test_select_mic_default(monkeypatch):
    monkeypatch.setattr(config, "WINDOWS_MIC_DEVICE_MATCH", "")
    pa = FakePa(make_devices())
    mic = rw._select_mic(pa, FakePyaudio, {"index": 0})
    assert mic["name"] == "Headset Microphone (USB)"


def test_select_mic_by_match(monkeypatch):
    monkeypatch.setattr(config, "WINDOWS_MIC_DEVICE_MATCH", "realtek")
    pa = FakePa(make_devices())
    mic = rw._select_mic(pa, FakePyaudio, {"index": 0})
    assert mic["name"] == "Microphone Array (Realtek)"


def test_select_mic_ambiguous(monkeypatch):
    monkeypatch.setattr(config, "WINDOWS_MIC_DEVICE_MATCH", "microphone")
    pa = FakePa(make_devices())
    with pytest.raises(rw._DeviceError):
        rw._select_mic(pa, FakePyaudio, {"index": 0})


def test_select_mic_missing(monkeypatch):
    monkeypatch.setattr(config, "WINDOWS_MIC_DEVICE_MATCH", "does-not-exist")
    pa = FakePa(make_devices())
    with pytest.raises(rw._DeviceError):
        rw._select_mic(pa, FakePyaudio, {"index": 0})


def test_select_output_by_match(monkeypatch):
    monkeypatch.setattr(config, "WINDOWS_OUTPUT_DEVICE_MATCH", "headphones")
    pa = FakePa(make_devices())
    output = rw._select_output(pa, FakePyaudio, {"index": 0})
    assert output["name"] == "Headphones (USB)"


def test_resolve_loopback_exact_name():
    pa = FakePa(make_devices())
    output = {
        "name": "Speakers (Realtek)",
        "index": 2,
        "maxOutputChannels": 2,
        "isLoopbackDevice": False,
    }
    loopback = rw._resolve_loopback(pa, output)
    assert loopback["name"] == "Speakers (Realtek) [Loopback]"


def test_resolve_loopback_missing():
    pa = FakePa(make_devices())
    output = {
        "name": "Does Not Exist",
        "index": 9,
        "maxOutputChannels": 2,
        "isLoopbackDevice": False,
    }
    with pytest.raises(rw._DeviceError):
        rw._resolve_loopback(pa, output)


class RatePa(FakePa):
    def __init__(self, devices, supported_rates):
        super().__init__(devices)
        self.supported_rates = set(supported_rates)

    def is_format_supported(self, rate, **kwargs):
        if rate not in self.supported_rates:
            raise ValueError("unsupported")
        return True


def test_select_rate_picks_first_common():
    devices = make_devices()
    mic = devices[0]
    loopback = devices[4]
    pa = RatePa(devices, {48000, 44100})
    rate, mic_ch, loop_ch = rw._select_rate(pa, FakePyaudio, mic, loopback)
    assert rate == 48000
    assert mic_ch == 1
    assert loop_ch == 2


def test_select_rate_falls_back():
    devices = make_devices()
    mic = dict(devices[0], defaultSampleRate=96000.0)
    loopback = dict(devices[4], defaultSampleRate=96000.0)
    pa = RatePa(devices, {44100})
    rate, _, _ = rw._select_rate(pa, FakePyaudio, mic, loopback)
    assert rate == 44100


def test_select_rate_none_supported():
    devices = make_devices()
    mic = devices[0]
    loopback = devices[4]
    pa = RatePa(devices, set())
    with pytest.raises(rw._DeviceError):
        rw._select_rate(pa, FakePyaudio, mic, loopback)


def test_resolve_loopback_duplicate():
    devices = make_devices() + [
        {
            "index": 6,
            "name": "Speakers (Realtek) [Loopback]",
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
            "isLoopbackDevice": True,
            "defaultSampleRate": 48000.0,
        },
    ]
    pa = FakePa(devices)
    output = {
        "name": "Speakers (Realtek)",
        "index": 2,
        "maxOutputChannels": 2,
        "isLoopbackDevice": False,
    }
    with pytest.raises(rw._DeviceError, match="Multiple loopback"):
        rw._resolve_loopback(pa, output)


def test_select_mic_default_lookup_error(monkeypatch):
    monkeypatch.setattr(config, "WINDOWS_MIC_DEVICE_MATCH", "")

    class BrokenPa:
        def get_device_info_generator_by_host_api(
            self, host_api_index=None, host_api_type=None
        ):
            return iter([])

        def get_default_wasapi_device(self, d_in=False, d_out=False):
            raise OSError("no default input device")

    with pytest.raises(rw._DeviceError):
        rw._select_mic(BrokenPa(), FakePyaudio, {"index": 0})


class PerDeviceRatePa:
    def __init__(self, support_map):
        self.support_map = support_map

    def is_format_supported(self, rate, **kwargs):
        if not self.support_map.get((kwargs["input_device"], rate), False):
            raise ValueError("unsupported")
        return True


def test_select_rate_respects_per_device_support():
    devices = make_devices()
    mic = devices[0]
    loopback = devices[4]
    pa = PerDeviceRatePa({(0, 44100): True, (4, 44100): True, (4, 48000): True})
    rate, _, _ = rw._select_rate(pa, FakePyaudio, mic, loopback)
    assert rate == 44100


def test_check_timing_initial():
    t = rw._Timing()
    pkt = rw._Packet("mic", b"", 1024, 0.0, 0, 0.0)
    assert rw._check_timing(pkt, t, 48000) is None
    assert t.last_adc == 0.0


def test_check_timing_regression():
    t = rw._Timing(last_adc=1.0)
    pkt = rw._Packet("mic", b"", 1024, 0.5, 0, 0.0)
    assert "regressed" in rw._check_timing(pkt, t, 48000)


def test_check_timing_discontinuity():
    t = rw._Timing(last_adc=1.0)
    pkt = rw._Packet("mic", b"", 1024, 4.0, 0, 0.0)
    assert "discontinuity" in rw._check_timing(pkt, t, 48000)


def test_check_timing_ok():
    t = rw._Timing(last_adc=1.0)
    pkt = rw._Packet("mic", b"", 1024, 1.0 + 1024 / 48000, 0, 0.0)
    assert rw._check_timing(pkt, t, 48000) is None


def test_check_timing_missing_adc():
    t = rw._Timing()
    pkt = rw._Packet("mic", b"", 1024, None, 0, 0.0)
    assert rw._check_timing(pkt, t, 48000) is None
    assert t.last_adc is None


def test_check_timing_non_finite():
    t = rw._Timing()
    for bad in (float("nan"), float("inf"), float("-inf")):
        pkt = rw._Packet("mic", b"", 1024, bad, 0, 0.0)
        assert "non-finite" in rw._check_timing(pkt, t, 48000)
    assert t.last_adc is None
