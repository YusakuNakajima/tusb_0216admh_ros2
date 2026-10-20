"""Native Linux backend for the TUSB-0216ADMH over libusb (pyusb).

Turtle Industry ships only a Windows driver (TUSBADMH.DLL) and does not publish
the USB protocol. The commands below were read off a USBPcap capture of the
official driver (docs/CAPTURE_GUIDE.md, 2026-10-20). Each command is one bulk
OUT write whose first byte is the opcode; the reply on bulk IN starts with the
same opcode. Multi-byte values are big endian.
"""

import numpy as np

from tusb_0216admh import constants as c
from tusb_0216admh.device import AdmhError, check_range, TusbAdmhDevice

# Opcodes (first byte of every OUT transfer and of its reply)
CMD_DIO_READ = 0x10  # -> [op, bits]
CMD_DIO_WRITE = 0x20  # [op, bits] -> [op]
CMD_ADC_START = 0x30  # [op, CycLen (u24), PreLen (u24), TrgSel, Mode] -> [op]
CMD_ADC_STOP = 0x40  # -> [op]
CMD_STATUS = 0x50  # -> [op, state, ch1 count (u24), ch2 count (u24)]
CMD_DATA = 0x60  # [op, count (u24), channel] -> count big-endian u16 samples
CMD_CLOCK = 0x70  # [op, 1 << ClkSel, Div, Ave] -> [op]
CMD_TH_LEVEL = 0x80  # [op, level (u16), noise level (u16)] -> [op]
CMD_INPUT_TYPE = 0x90  # [op, ch1, ch2] -> [op]
CMD_TRIGGER = 0xA0  # -> [op]
CMD_CHECK_INPUT_TYPE = 0xB0  # [op, 0, 0] -> [op, ch1, ch2]
CMD_IDENTIFY = 0xF0  # -> [op, rear ID switch]; sent by Device_Open

# State byte of the CMD_STATUS reply
STATE_RUNNING = 0x01  # between Adc_Start and Adc_Stop
STATE_TRIGGERED = 0x02
STATE_OVERFLOW_SHIFT = 2  # bit 2 ch1, bit 3 ch2; sampling halts once set
STATE_KNOWN_BITS = 0x0F

# Samples per CMD_DATA request. The DLL was seen asking for up to 896 at once;
# stay inside what has been observed.
READ_CHUNK_SAMPLES = 512


def _import_usb():
    try:
        import usb.core
        import usb.util
    except ImportError as e:
        raise AdmhError(2, 'pyusb is not installed (pip install pyusb)') from e
    return usb


def find_usb_devices():
    """Return every attached unit with the TUSB ADM VID/PID."""
    usb = _import_usb()
    return list(usb.core.find(find_all=True, idVendor=c.USB_VENDOR_ID,
                              idProduct=c.USB_PRODUCT_ID))


def describe_usb_device(dev):
    """One-line description that does not require opening the device."""
    return (f'bus {dev.bus:03d} address {dev.address:03d} '
            f'{dev.idVendor:04x}:{dev.idProduct:04x}')


class UsbTransport:
    """Claims the vendor interface and moves raw bytes on the bulk endpoints."""

    def __init__(self, dev, timeout_ms=1000):
        self._usb = _import_usb()
        self._dev = dev
        self.timeout_ms = timeout_ms
        self._claimed = False
        self._detached_kernel_driver = False

    def open(self):
        usb = self._usb
        try:
            if self._dev.is_kernel_driver_active(c.USB_INTERFACE):
                self._dev.detach_kernel_driver(c.USB_INTERFACE)
                self._detached_kernel_driver = True
            usb.util.claim_interface(self._dev, c.USB_INTERFACE)
        except usb.core.USBError as e:
            raise AdmhError(5, f'{e} (missing udev rule? see udev/)') from e
        self._claimed = True

    def close(self):
        if not self._claimed:
            return
        usb = self._usb
        try:
            usb.util.release_interface(self._dev, c.USB_INTERFACE)
            if self._detached_kernel_driver:
                self._dev.attach_kernel_driver(c.USB_INTERFACE)
        except usb.core.USBError:
            pass  # unplugged; nothing left to release
        finally:
            usb.util.dispose_resources(self._dev)
            self._claimed = False

    def string(self, index):
        """Read a string descriptor, or None if the index is 0."""
        if not index:
            return None
        return self._usb.util.get_string(self._dev, index)

    def write(self, data):
        try:
            return self._dev.write(c.USB_EP_OUT, bytes(data), self.timeout_ms)
        except self._usb.core.USBError as e:
            raise AdmhError(9, str(e)) from e

    def read(self, size, timeout_ms=None):
        """Read up to size bytes from the bulk IN endpoint; b'' on timeout."""
        usb = self._usb
        try:
            data = self._dev.read(c.USB_EP_IN, size,
                                  self.timeout_ms if timeout_ms is None else timeout_ms)
        except usb.core.USBTimeoutError:
            return b''
        except usb.core.USBError as e:
            raise AdmhError(9, str(e)) from e
        return bytes(data)


# Replies are queued on bulk IN until read, so a process that dies between a
# command and its reply leaves the reply behind and every later reply of a new
# process is off by one (seen on Linux, 2026-10-20). open() drops what is left.
DRAIN_TIMEOUT_MS = 20
DRAIN_MAX_READS = 64  # a whole CMD_DATA reply is at most 2 * 512 B = 16 packets


def _drain(transport):
    """Discard stale bulk IN data and return the number of bytes dropped."""
    dropped = 0
    for _ in range(DRAIN_MAX_READS):
        data = transport.read(64, timeout_ms=DRAIN_TIMEOUT_MS)
        if not data:
            break
        dropped += len(data)
    return dropped


def _exchange(transport, out, reply_len):
    """Send one command and return its reply, checked against the opcode."""
    transport.write(bytes(out))
    reply = transport.read(64)
    if len(reply) != reply_len or reply[0] != out[0]:
        raise AdmhError(9, f'command {bytes(out).hex(" ")}: reply {reply.hex(" ")}')
    return reply


class UsbTusbAdmhDevice(TusbAdmhDevice):
    """Backend 'usb'.

    Unlike the DLL, which drains the device FIFO into a PC buffer from a
    background thread, this backend reads the device FIFO directly: length()
    reports the samples waiting in the device and read() fetches them.

    The unit is picked like the DLL does it: every attached VID/PID match is
    asked for its rear ID switch (CMD_IDENTIFY) and the one equal to device_id
    is kept.
    """

    def __init__(self, device_id=0, timeout_ms=1000, transport=None):
        super().__init__(device_id)
        self._timeout_ms = timeout_ms
        self._transport = transport  # injected by tests
        self._is_open = False
        self._transfer_limit = c.TRANSFER_LIMIT_DEFAULT
        self._ch1_only = False

    def open(self):
        if self._is_open:
            raise AdmhError(3)
        if self._transport is not None:
            transports = [self._transport]
        else:
            transports = (UsbTransport(dev, self._timeout_ms) for dev in find_usb_devices())
        found = []
        for transport in transports:
            try:
                if transport is not self._transport:
                    transport.open()
                _drain(transport)
                id_switch = _exchange(transport, [CMD_IDENTIFY], 2)[1]
            except AdmhError as e:
                found.append(f'unusable ({e})')  # e.g. claimed by another process
                transport.close()
                continue
            if id_switch == self.device_id:
                self._transport = transport
                self._is_open = True
                return
            found.append(f'ID {id_switch}')
            transport.close()
        raise AdmhError(6, f'no unit with ID switch {self.device_id}; attached: {found}')

    def close(self):
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        self._is_open = False

    def _command(self, out, reply_len):
        if not self._is_open:
            raise AdmhError(7)
        return _exchange(self._transport, out, reply_len)

    def dio_read(self):
        return self._command([CMD_DIO_READ], 2)[1]

    def dio_write(self, bits):
        check_range('bits', bits, 0, 15)
        self._command([CMD_DIO_WRITE, bits], 1)

    def set_input_type(self, ch1_type, ch2_type):
        check_range('ch1_type', ch1_type, 0, 1)
        check_range('ch2_type', ch2_type, 0, 1)
        self._command([CMD_INPUT_TYPE, ch1_type, ch2_type], 1)

    def get_input_type(self):
        reply = self._command([CMD_CHECK_INPUT_TYPE, 0, 0], 3)
        return reply[1], reply[2]

    def select_clock(self, clock_source, clock_divider, averaging_exponent):
        check_range('clock_source', clock_source, 0, c.CLOCK_SOURCE_EXTERNAL)
        check_range('clock_divider', clock_divider, 0,
                    c.CLOCK_DIVIDER_MAX_EXTERNAL if clock_source == c.CLOCK_SOURCE_EXTERNAL
                    else c.CLOCK_DIVIDER_MAX)
        check_range('averaging_exponent', averaging_exponent, 0, c.AVERAGING_EXPONENT_MAX)
        self._command([CMD_CLOCK, 1 << clock_source, clock_divider, averaging_exponent], 1)

    def set_trigger_level(self, level_counts, noise_level_counts):
        check_range('level_counts', level_counts, c.TRIGGER_LEVEL_MIN, c.TRIGGER_LEVEL_MAX)
        check_range('noise_level_counts', noise_level_counts, 0, c.TRIGGER_NOISE_LEVEL_MAX)
        self._command([CMD_TH_LEVEL, *level_counts.to_bytes(2, 'big'),
                       *noise_level_counts.to_bytes(2, 'big')], 1)

    def set_transfer_limit(self, limit_samples):
        # The DLL sends nothing for this: it only caps its own reads.
        check_range('limit_samples', limit_samples,
                    c.TRANSFER_LIMIT_MIN, c.TRANSFER_LIMIT_MAX)
        self._transfer_limit = limit_samples

    def start(self, cycle_length, pretrigger_length, trigger, mode, ch1_only):
        check_range('pretrigger_length', pretrigger_length, 0, c.PRETRIGGER_LENGTH_MAX)
        check_range('trigger', trigger, 0, 3)
        check_range('mode', mode, 0, 1)
        check_range('ch1_only', ch1_only, 0, 1)
        if mode == c.MODE_REPEAT:
            check_range('cycle_length', cycle_length, 1, c.CYCLE_LENGTH_MAX)
        else:
            cycle_length = 0  # the DLL sends 0 in continuous mode
        self._command([CMD_ADC_START, *cycle_length.to_bytes(3, 'big'),
                       *pretrigger_length.to_bytes(3, 'big'), trigger, mode], 1)
        # Ch1Only never reaches the device, which keeps filling the ch2 FIFO.
        self._ch1_only = bool(ch1_only)

    def stop(self):
        self._command([CMD_ADC_STOP], 1)

    def trigger(self):
        self._command([CMD_TRIGGER], 1)

    def _raw_status(self):
        reply = self._command([CMD_STATUS], 8)
        state = reply[1]
        if state & ~STATE_KNOWN_BITS:
            raise AdmhError(99, f'unknown status byte 0x{state:02x}')
        counts = (int.from_bytes(reply[2:5], 'big'), int.from_bytes(reply[5:8], 'big'))
        return state, counts

    def status(self):
        state, _ = self._raw_status()
        overflow = (state >> STATE_OVERFLOW_SHIFT) & (c.OVERFLOW_CH1 | c.OVERFLOW_CH2)
        if self._ch1_only:
            overflow &= ~c.OVERFLOW_CH2
        if not state & STATE_RUNNING:
            return c.STATUS_STOPPED, 0
        if state & STATE_TRIGGERED:
            return c.STATUS_SAMPLING, overflow
        return c.STATUS_WAITING_TRIGGER, overflow

    def length(self):
        """Return the samples waiting in the device FIFO; with ch1_only, drop ch2 here."""
        _, (n1, n2) = self._raw_status()
        if self._ch1_only:
            self._fetch(1, n2)
            n2 = 0
        return (n1, n2, n1 * 100 // c.DEVICE_FIFO_SAMPLES_PER_CH,
                n2 * 100 // c.DEVICE_FIFO_SAMPLES_PER_CH)

    def read(self, channel, max_samples):
        """Read up to max_samples from the device FIFO (never more than it holds)."""
        check_range('channel', channel, 0, 1)
        if channel == 1 and self._ch1_only:
            return np.zeros(0, dtype=np.uint16)
        _, counts = self._raw_status()
        return self._fetch(channel, min(max_samples, counts[channel]))

    def _fetch(self, channel, n):
        chunks = []
        while n > 0:
            k = min(n, READ_CHUNK_SAMPLES, self._transfer_limit)
            self._transport.write(bytes([CMD_DATA, *k.to_bytes(3, 'big'), channel]))
            data = b''
            while len(data) < 2 * k:
                part = self._transport.read(2 * k - len(data))
                if not part:
                    raise AdmhError(9, f'ch{channel + 1}: got {len(data)} of {2 * k} bytes')
                data += part
            chunks.append(np.frombuffer(data, dtype='>u2'))
            n -= k
        if not chunks:
            return np.zeros(0, dtype=np.uint16)
        return np.concatenate(chunks).astype(np.uint16)


def create_device(backend, device_id=0, **kwargs):
    """Factory used by the node: backend is 'usb' or 'mock'."""
    if backend == 'usb':
        return UsbTusbAdmhDevice(device_id, **kwargs)
    if backend == 'mock':
        from tusb_0216admh.mock_device import MockTusbAdmhDevice
        return MockTusbAdmhDevice(device_id)
    raise ValueError(f"backend must be 'usb' or 'mock', got {backend!r}")
