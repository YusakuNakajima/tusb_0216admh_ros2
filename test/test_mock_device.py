import numpy as np
import pytest
from tusb_0216admh import constants as c
from tusb_0216admh import conversion
from tusb_0216admh.device import AdmhError
from tusb_0216admh.mock_device import MockTusbAdmhDevice, PC_BUFFER_SAMPLES_PER_CH


class FakeClock:
    def __init__(self):
        self.t_s = 100.0

    def __call__(self):
        return self.t_s


@pytest.fixture
def setup():
    clock = FakeClock()
    dev = MockTusbAdmhDevice(signal_frequency_hz=(1.0, 1.0),
                             signal_amplitude_v=(0.5, 0.25), clock=clock)
    dev.open()
    dev.select_clock(0, 199, 8)  # 3906.25 Hz
    yield dev, clock
    dev.close()


def test_rejects_calls_before_open():
    dev = MockTusbAdmhDevice()
    with pytest.raises(AdmhError) as e:
        dev.status()
    assert e.value.code == 7


def test_software_trigger_flow(setup):
    dev, clock = setup
    dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 0)
    clock.t_s += 1.0
    assert dev.status() == (c.STATUS_WAITING_TRIGGER, 0)
    assert dev.length()[:2] == (0, 0)  # nothing before the trigger

    dev.trigger()
    clock.t_s += 0.5
    assert dev.status() == (c.STATUS_SAMPLING, 0)
    n = int(0.5 * 3906.25)
    assert dev.length()[:2] == (n, n)

    first = dev.read(0, 100)
    assert first.dtype == np.uint16 and len(first) == 100
    assert dev.length()[0] == n - 100  # reading removes samples
    rest = dev.read(0, 10 ** 6)
    assert len(rest) == n - 100

    dev.stop()
    assert dev.status() == (c.STATUS_STOPPED, 0)


def test_samples_follow_the_configured_signal(setup):
    dev, clock = setup
    dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 0)
    dev.trigger()
    clock.t_s += 1.0
    volts = conversion.counts_to_volts(dev.read(0, 4000).astype(float), c.INPUT_TYPE_BIPOLAR)
    assert volts.max() == pytest.approx(0.5, abs=1e-3)
    assert volts.min() == pytest.approx(-0.5, abs=1e-3)


def test_ch1_only_has_no_ch2_data(setup):
    dev, clock = setup
    dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 1)
    dev.trigger()
    clock.t_s += 1.0
    ch1, ch2, _, _ = dev.length()
    assert ch1 > 0 and ch2 == 0


def test_overflow_when_not_drained(setup):
    dev, clock = setup
    dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 0)
    dev.trigger()
    clock.t_s += (PC_BUFFER_SAMPLES_PER_CH + 10) / 3906.25
    _, overflow = dev.status()
    assert overflow == c.OVERFLOW_CH1 | c.OVERFLOW_CH2


def test_settings_locked_while_running(setup):
    dev, _ = setup
    dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 0)
    with pytest.raises(AdmhError) as e:
        dev.select_clock(0, 199, 0)
    assert e.value.code == 11


def test_invalid_clock_is_parameter_error(setup):
    dev, _ = setup
    with pytest.raises(AdmhError) as e:
        dev.select_clock(0, 6, 0)
    assert e.value.code == 8


def test_pretrigger_is_not_simulated(setup):
    dev, _ = setup
    with pytest.raises(AdmhError) as e:
        dev.start(1, 100, c.TRIGGER_EXTERNAL, c.MODE_CONTINUOUS, 0)
    assert e.value.code == 8
