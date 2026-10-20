"""Native Linux backend for the TUSB-0216ADMH over libusb (pyusb).

Turtle Industry ships only a Windows driver (TUSBADMH.DLL) and does not publish
the USB protocol. This module provides the USB transport (find, claim, bulk
read/write) that has been checked against the real unit; the commands behind
each Tusbadmh_* call still have to be recovered from a USB capture of the
official driver (docs/CAPTURE_GUIDE.md). Until then they raise
NotImplementedError instead of sending guessed bytes to the device.
"""

from tusb_0216admh import constants as c
from tusb_0216admh.device import AdmhError, TusbAdmhDevice

PROTOCOL_TODO = (
    'the TUSB-0216ADMH USB protocol has not been analysed yet; '
    'capture the official driver as described in docs/CAPTURE_GUIDE.md')


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


class UsbTusbAdmhDevice(TusbAdmhDevice):
    """Backend 'usb'.

    How the DLL maps the rear ID switch (device_id) to a USB device is not known
    yet, so the unit is picked by usb_index among the attached VID/PID matches.
    """

    def __init__(self, device_id=0, usb_index=0, timeout_ms=1000):
        super().__init__(device_id)
        self._usb_index = usb_index
        self._timeout_ms = timeout_ms
        self._transport = None

    def open(self):
        if self._transport is not None:
            raise AdmhError(3)
        devices = find_usb_devices()
        if self._usb_index >= len(devices):
            raise AdmhError(6, f'{len(devices)} unit(s) attached, usb_index={self._usb_index}')
        transport = UsbTransport(devices[self._usb_index], self._timeout_ms)
        transport.open()
        self._transport = transport

    def close(self):
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def dio_read(self):
        raise NotImplementedError(PROTOCOL_TODO)

    def dio_write(self, bits):
        raise NotImplementedError(PROTOCOL_TODO)

    def set_input_type(self, ch1_type, ch2_type):
        raise NotImplementedError(PROTOCOL_TODO)

    def get_input_type(self):
        raise NotImplementedError(PROTOCOL_TODO)

    def select_clock(self, clock_source, clock_divider, averaging_exponent):
        raise NotImplementedError(PROTOCOL_TODO)

    def set_trigger_level(self, level_counts, noise_level_counts):
        raise NotImplementedError(PROTOCOL_TODO)

    def set_transfer_limit(self, limit_samples):
        raise NotImplementedError(PROTOCOL_TODO)

    def start(self, cycle_length, pretrigger_length, trigger, mode, ch1_only):
        raise NotImplementedError(PROTOCOL_TODO)

    def stop(self):
        raise NotImplementedError(PROTOCOL_TODO)

    def trigger(self):
        raise NotImplementedError(PROTOCOL_TODO)

    def status(self):
        raise NotImplementedError(PROTOCOL_TODO)

    def length(self):
        raise NotImplementedError(PROTOCOL_TODO)

    def read(self, channel, max_samples):
        raise NotImplementedError(PROTOCOL_TODO)


def create_device(backend, device_id=0, **kwargs):
    """Factory used by the node: backend is 'usb' or 'mock'."""
    if backend == 'usb':
        return UsbTusbAdmhDevice(device_id, **kwargs)
    if backend == 'mock':
        from tusb_0216admh.mock_device import MockTusbAdmhDevice
        return MockTusbAdmhDevice(device_id)
    raise ValueError(f"backend must be 'usb' or 'mock', got {backend!r}")
