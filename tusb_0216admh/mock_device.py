"""Simulated TUSB-0216ADMH for testing the ROS side without the hardware.

Produces a sine wave on each channel at the configured sample rate, with the
same buffering behaviour as the driver: samples accumulate in a PC buffer of
2 Mi samples per channel after the trigger, and reading removes them.
"""

import math
import time

import numpy as np

from tusb_0216admh import constants as c
from tusb_0216admh import conversion
from tusb_0216admh.device import AdmhError, check_range, TusbAdmhDevice

PC_BUFFER_SAMPLES_PER_CH = 2 << 20  # manual 6.4.1


class MockTusbAdmhDevice(TusbAdmhDevice):
    """Backend 'mock'. Only software and external triggers are simulated."""

    def __init__(self, device_id=0, signal_frequency_hz=(10.0, 3.0),
                 signal_amplitude_v=(0.5, 0.25), clock=time.monotonic):
        super().__init__(device_id)
        self._signal_frequency_hz = signal_frequency_hz
        self._signal_amplitude_v = signal_amplitude_v
        self._clock = clock
        self._is_open = False
        self._dio_out = 0
        self._input_type = [c.INPUT_TYPE_BIPOLAR, c.INPUT_TYPE_BIPOLAR]
        self._rate_hz = conversion.sample_rate_hz(0, 199, 0)
        self._running = False
        self._ch1_only = False
        self._trigger_time = None
        self._consumed = [0, 0]

    def _require_open(self):
        if not self._is_open:
            raise AdmhError(7)

    def _require_stopped(self):
        if self._running:
            raise AdmhError(11)

    def open(self):
        if self._is_open:
            raise AdmhError(3)
        self._is_open = True

    def close(self):
        self._running = False
        self._is_open = False

    def dio_read(self):
        self._require_open()
        return (self._dio_out << 4) & 0xF0

    def dio_write(self, bits):
        self._require_open()
        check_range('bits', bits, 0, 15)
        self._dio_out = bits

    def set_input_type(self, ch1_type, ch2_type):
        self._require_open()
        check_range('ch1_type', ch1_type, 0, 1)
        check_range('ch2_type', ch2_type, 0, 1)
        self._input_type = [ch1_type, ch2_type]

    def get_input_type(self):
        self._require_open()
        return tuple(self._input_type)

    def select_clock(self, clock_source, clock_divider, averaging_exponent):
        self._require_open()
        self._require_stopped()
        if clock_source == c.CLOCK_SOURCE_EXTERNAL:
            raise AdmhError(8, 'the mock has no external clock')
        try:
            self._rate_hz = conversion.sample_rate_hz(
                clock_source, clock_divider, averaging_exponent)
        except ValueError as e:
            raise AdmhError(8, str(e)) from e

    def set_trigger_level(self, level_counts, noise_level_counts):
        self._require_open()
        check_range('level_counts', level_counts,
                    c.TRIGGER_LEVEL_MIN, c.TRIGGER_LEVEL_MAX)
        check_range('noise_level_counts', noise_level_counts,
                    0, c.TRIGGER_NOISE_LEVEL_MAX)

    def set_transfer_limit(self, limit_samples):
        self._require_open()
        check_range('limit_samples', limit_samples,
                    c.TRANSFER_LIMIT_MIN, c.TRANSFER_LIMIT_MAX)

    def start(self, cycle_length, pretrigger_length, trigger, mode, ch1_only):
        self._require_open()
        self._require_stopped()
        check_range('trigger', trigger, 0, 3)
        check_range('mode', mode, 0, 1)
        if trigger in (c.TRIGGER_RISING, c.TRIGGER_FALLING):
            raise AdmhError(8, 'the mock does not simulate analog triggers')
        if mode != c.MODE_CONTINUOUS:
            raise AdmhError(8, 'the mock only simulates continuous mode')
        self._running = True
        self._ch1_only = bool(ch1_only)
        self._consumed = [0, 0]
        # External trigger: pretend the pulse arrives immediately.
        self._trigger_time = self._clock() if trigger == c.TRIGGER_EXTERNAL else None

    def stop(self):
        self._require_open()
        self._running = False

    def trigger(self):
        self._require_open()
        if not self._running:
            raise AdmhError(13)
        if self._trigger_time is None:
            self._trigger_time = self._clock()

    def _produced(self):
        if self._trigger_time is None:
            return 0
        return int((self._clock() - self._trigger_time) * self._rate_hz)

    def _available(self, channel):
        if channel == 1 and self._ch1_only:
            return 0
        return min(self._produced() - self._consumed[channel],
                   PC_BUFFER_SAMPLES_PER_CH)

    def status(self):
        self._require_open()
        if not self._running:
            return c.STATUS_STOPPED, 0
        overflow = 0
        for ch, bit in ((0, c.OVERFLOW_CH1), (1, c.OVERFLOW_CH2)):
            if self._produced() - self._consumed[ch] > PC_BUFFER_SAMPLES_PER_CH:
                if not (ch == 1 and self._ch1_only):
                    overflow |= bit
        if self._trigger_time is None:
            return c.STATUS_WAITING_TRIGGER, overflow
        return c.STATUS_SAMPLING, overflow

    def length(self):
        self._require_open()
        return self._available(0), self._available(1), 0, 0

    def read(self, channel, max_samples):
        self._require_open()
        check_range('channel', channel, 0, 1)
        n = max(0, min(max_samples, self._available(channel)))
        start = self._consumed[channel]
        self._consumed[channel] += n
        t_s = (start + np.arange(n)) / self._rate_hz
        volts = self._signal_amplitude_v[channel] * np.sin(
            2.0 * math.pi * self._signal_frequency_hz[channel] * t_s)
        offset_v = c.INPUT_TYPE_OFFSET_V[self._input_type[channel]]
        if self._input_type[channel] == c.INPUT_TYPE_UNIPOLAR:
            volts = volts + 1.0  # centre the sine in the 0..2 V range
        counts = np.round((volts - offset_v) * c.ADC_FULL_SCALE_COUNTS / c.INPUT_SPAN_V)
        return np.clip(counts, 0, c.ADC_FULL_SCALE_COUNTS - 1).astype(np.uint16)
