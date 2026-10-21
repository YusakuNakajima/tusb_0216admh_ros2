"""Unit conversion and parameter validation for the TUSB-0216ADMH.

Raw counts and register-style settings (ClkSel/Div/Ave) are converted to SI
units here and nowhere else, so the rest of the package handles volts and Hz.
"""

from tusb_0216admh import constants as c


def counts_to_volts(raw_counts, input_type):
    """Convert raw ADC counts (0..65535) to volts.

    Straight offset binary, manual 5.7:
        V = raw * 2.0 V / 65536 + offset_v
    with offset_v = -1.0 V (bipolar) or 0.0 V (unipolar), so 0x8000 is
    0.0 V bipolar / 1.0 V unipolar. Works on scalars and numpy arrays.
    """
    offset_v = c.INPUT_TYPE_OFFSET_V[input_type]
    return raw_counts * (c.INPUT_SPAN_V / c.ADC_FULL_SCALE_COUNTS) + offset_v


def volts_to_counts(volts, input_type):
    """Convert volts to the nearest raw count, clamped to 0..65535."""
    offset_v = c.INPUT_TYPE_OFFSET_V[input_type]
    raw = round((volts - offset_v) * c.ADC_FULL_SCALE_COUNTS / c.INPUT_SPAN_V)
    return max(0, min(c.ADC_FULL_SCALE_COUNTS - 1, raw))


def trigger_level_counts(level_v, noise_level_v, input_type):
    """Convert the analog trigger level and noise band (V) to raw counts.

    Raises ValueError instead of clamping: a level the device cannot represent
    would silently trigger on a different event. The level is referred to the
    ch1 input range; the noise band is a width, so it has no offset.
    """
    lsb_v = c.INPUT_SPAN_V / c.ADC_FULL_SCALE_COUNTS
    offset_v = c.INPUT_TYPE_OFFSET_V[input_type]
    level = round((level_v - offset_v) / lsb_v)
    noise = round(noise_level_v / lsb_v)
    if not c.TRIGGER_LEVEL_MIN <= level <= c.TRIGGER_LEVEL_MAX:
        raise ValueError(
            f'trigger_level_v {level_v} V is outside '
            f'{c.TRIGGER_LEVEL_MIN * lsb_v + offset_v:.5f}..'
            f'{c.TRIGGER_LEVEL_MAX * lsb_v + offset_v:.5f} V for the ch1 input range')
    if not 0 <= noise <= c.TRIGGER_NOISE_LEVEL_MAX:
        raise ValueError(
            f'trigger_noise_level_v {noise_level_v} V is outside '
            f'0..{c.TRIGGER_NOISE_LEVEL_MAX * lsb_v:.5f} V')
    return level, noise


def input_type_from_name(name):
    """Map 'bipolar' / 'unipolar' to the Tusbadmh_InputType value."""
    names = {
        'bipolar': c.INPUT_TYPE_BIPOLAR,
        'unipolar': c.INPUT_TYPE_UNIPOLAR,
    }
    if name not in names:
        raise ValueError(f'input range must be one of {sorted(names)}, got {name!r}')
    return names[name]


def sample_rate_hz(clock_source, clock_divider, averaging_exponent,
                   external_clock_hz=None):
    """Return the per-channel sample rate in Hz and validate the settings.

    Manual 6.5 (Tusbadmh_Clock_Select):
        conversion clock = source / (Div + 1), must be 1..25 MHz
        sample rate      = conversion clock / 2**Ave
    """
    if clock_source == c.CLOCK_SOURCE_EXTERNAL:
        if external_clock_hz is None:
            raise ValueError('external_clock_hz is required for the external clock')
        source_hz = float(external_clock_hz)
        divider_max = c.CLOCK_DIVIDER_MAX_EXTERNAL
    elif clock_source in c.CLOCK_SOURCE_HZ:
        source_hz = c.CLOCK_SOURCE_HZ[clock_source]
        divider_max = c.CLOCK_DIVIDER_MAX
    else:
        raise ValueError(f'clock_source must be 0..5, got {clock_source}')

    if not 0 <= clock_divider <= divider_max:
        raise ValueError(f'clock_divider must be 0..{divider_max}, got {clock_divider}')
    if not 0 <= averaging_exponent <= c.AVERAGING_EXPONENT_MAX:
        raise ValueError(
            f'averaging_exponent must be 0..{c.AVERAGING_EXPONENT_MAX}, '
            f'got {averaging_exponent}')

    conversion_clock_hz = source_hz / (clock_divider + 1)
    if not (c.CONVERSION_CLOCK_MIN_HZ <= conversion_clock_hz
            <= c.CONVERSION_CLOCK_MAX_HZ):
        raise ValueError(
            f'conversion clock {conversion_clock_hz / 1e6:.4g} MHz is outside 1..25 MHz '
            f'(source {source_hz / 1e6:.4g} MHz / {clock_divider + 1})')
    return conversion_clock_hz / (1 << averaging_exponent)


def continuous_rate_limit_hz(ch1_only):
    """Rate the manual expects to sustain in continuous mode, in Hz."""
    if ch1_only:
        return c.CONTINUOUS_RATE_LIMIT_1CH_HZ
    return c.CONTINUOUS_RATE_LIMIT_2CH_HZ
