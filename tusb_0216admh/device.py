"""Device API of the TUSB-0216ADMH, shared by every backend.

The methods mirror the vendor DLL (Tusbadmh_*), with exceptions instead of
return codes and raw counts as numpy arrays. Settings stay in device units
(ClkSel/Div/Ave, raw counts); conversion to SI lives in conversion.py.
"""

import abc

from tusb_0216admh import constants as c


class AdmhError(RuntimeError):
    """Error reported by the device, carrying the vendor error code."""

    def __init__(self, code, detail=''):
        self.code = code
        message = c.ERROR_MESSAGES.get(code, 'unknown error')
        super().__init__(f'[{code}] {message}' + (f': {detail}' if detail else ''))


def check_range(name, value, low, high):
    """Raise AdmhError(8) like the vendor wrapper when value is out of range."""
    if not low <= value <= high:
        raise AdmhError(8, f'{name}={value} not in {low}..{high}')


class TusbAdmhDevice(abc.ABC):
    """One TUSB-0216ADMH unit."""

    def __init__(self, device_id=0):
        check_range('device_id', device_id, c.DEVICE_ID_MIN, c.DEVICE_ID_MAX)
        self.device_id = device_id

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    @abc.abstractmethod
    def open(self):
        """Tusbadmh_Device_Open."""

    @abc.abstractmethod
    def close(self):
        """Tusbadmh_Device_Close. Must be safe to call twice."""

    @abc.abstractmethod
    def dio_read(self):
        """Tusbadmh_Dio_Read: bits 0-3 inputs, bits 4-7 current outputs."""

    @abc.abstractmethod
    def dio_write(self, bits):
        """Tusbadmh_Dio_Write: bits 0-3 drive PO0-PO3."""

    @abc.abstractmethod
    def set_input_type(self, ch1_type, ch2_type):
        """Tusbadmh_InputType: 0 bipolar (+-1 V), 1 unipolar (0-2 V)."""

    @abc.abstractmethod
    def get_input_type(self):
        """Tusbadmh_CheckInputType -> (ch1_type, ch2_type)."""

    @abc.abstractmethod
    def select_clock(self, clock_source, clock_divider, averaging_exponent):
        """Tusbadmh_Clock_Select (ClkSel, Div, Ave)."""

    @abc.abstractmethod
    def set_trigger_level(self, level_counts, noise_level_counts):
        """Tusbadmh_ThLevel_Set, both in raw counts."""

    @abc.abstractmethod
    def set_transfer_limit(self, limit_samples):
        """Tusbadmh_TransLimit."""

    @abc.abstractmethod
    def start(self, cycle_length, pretrigger_length, trigger, mode, ch1_only):
        """Tusbadmh_Adc_Start."""

    @abc.abstractmethod
    def stop(self):
        """Tusbadmh_Adc_Stop."""

    @abc.abstractmethod
    def trigger(self):
        """Tusbadmh_Trigger (software trigger)."""

    @abc.abstractmethod
    def status(self):
        """Tusbadmh_Status_Get -> (status, overflow_bits)."""

    @abc.abstractmethod
    def length(self):
        """Tusbadmh_Length -> (ch1_len, ch2_len, ch1_fifo_pct, ch2_fifo_pct)."""

    @abc.abstractmethod
    def read(self, channel, max_samples):
        """Tusbadmh_Data_Get: channel 0 = ch1, 1 = ch2 -> uint16 array of counts."""
