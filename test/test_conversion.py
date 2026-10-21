import numpy as np
import pytest
from tusb_0216admh import constants as c
from tusb_0216admh import conversion


@pytest.mark.parametrize('raw, bipolar_v, unipolar_v', [
    # Manual 5.7 table
    (0x0000, -1.0, 0.0),
    (0x4000, -0.5, 0.5),
    (0x8000, 0.0, 1.0),
    (0xC000, 0.5, 1.5),
])
def test_counts_to_volts_matches_manual_table(raw, bipolar_v, unipolar_v):
    assert conversion.counts_to_volts(raw, c.INPUT_TYPE_BIPOLAR) == pytest.approx(bipolar_v)
    assert conversion.counts_to_volts(raw, c.INPUT_TYPE_UNIPOLAR) == pytest.approx(unipolar_v)


def test_full_scale_is_one_lsb_below_range_end():
    lsb_v = 2.0 / 65536
    assert conversion.counts_to_volts(0xFFFF, c.INPUT_TYPE_BIPOLAR) == pytest.approx(1.0 - lsb_v)


def test_counts_to_volts_accepts_arrays():
    volts = conversion.counts_to_volts(np.array([0, 0x8000], dtype=np.float32),
                                       c.INPUT_TYPE_BIPOLAR)
    np.testing.assert_allclose(volts, [-1.0, 0.0])


def test_volts_to_counts_round_trip_and_clamp():
    assert conversion.volts_to_counts(0.0, c.INPUT_TYPE_BIPOLAR) == 0x8000
    assert conversion.volts_to_counts(1.0, c.INPUT_TYPE_UNIPOLAR) == 0x8000
    assert conversion.volts_to_counts(5.0, c.INPUT_TYPE_BIPOLAR) == 0xFFFF
    assert conversion.volts_to_counts(-5.0, c.INPUT_TYPE_BIPOLAR) == 0


def test_input_type_from_name():
    assert conversion.input_type_from_name('bipolar') == c.INPUT_TYPE_BIPOLAR
    assert conversion.input_type_from_name('unipolar') == c.INPUT_TYPE_UNIPOLAR
    with pytest.raises(ValueError):
        conversion.input_type_from_name('10V')


def test_sample_rate_manual_example():
    # Manual: ClkSel 0 (200 MHz), Div 7 -> 25 MHz
    assert conversion.sample_rate_hz(0, 7, 0) == pytest.approx(25e6)


def test_sample_rate_with_averaging():
    assert conversion.sample_rate_hz(0, 199, 8) == pytest.approx(1e6 / 256)


def test_sample_rate_external_clock():
    assert conversion.sample_rate_hz(5, 1, 0, external_clock_hz=10e6) == pytest.approx(5e6)
    with pytest.raises(ValueError):
        conversion.sample_rate_hz(5, 0, 0)
    with pytest.raises(ValueError):
        conversion.sample_rate_hz(5, 25, 0, external_clock_hz=25e6)


@pytest.mark.parametrize('args', [
    (0, 6, 0),    # 28.6 MHz, above 25 MHz
    (4, 1, 0),    # 0.96 MHz, below 1 MHz
    (0, 200, 0),  # Div out of range
    (0, 199, 9),  # Ave out of range
    (6, 0, 0),    # no such ClkSel
])
def test_sample_rate_rejects_invalid_settings(args):
    with pytest.raises(ValueError):
        conversion.sample_rate_hz(*args)


def test_continuous_rate_limit():
    assert conversion.continuous_rate_limit_hz(False) == 100e3
    assert conversion.continuous_rate_limit_hz(True) == 200e3


def test_trigger_level_counts_converts_volts():
    assert conversion.trigger_level_counts(0.0, 0.0244, c.INPUT_TYPE_BIPOLAR) == (0x8000, 800)
    assert conversion.trigger_level_counts(1.0, 0.0, c.INPUT_TYPE_UNIPOLAR) == (0x8000, 0)


@pytest.mark.parametrize('level_v, noise_v, input_type', [
    (2.0, 0.0, c.INPUT_TYPE_BIPOLAR),     # above +1 V: would have been clamped
    (-1.0, 0.0, c.INPUT_TYPE_BIPOLAR),    # count 0, below TRIGGER_LEVEL_MIN
    (-0.1, 0.0, c.INPUT_TYPE_UNIPOLAR),
    (0.0, -0.01, c.INPUT_TYPE_BIPOLAR),   # negative noise band
    (0.0, 0.2, c.INPUT_TYPE_BIPOLAR),     # above 3277 counts (~0.1 V)
])
def test_trigger_level_counts_rejects_unrepresentable_settings(level_v, noise_v, input_type):
    with pytest.raises(ValueError):
        conversion.trigger_level_counts(level_v, noise_v, input_type)
