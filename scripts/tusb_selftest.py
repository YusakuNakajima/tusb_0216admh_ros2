#!/usr/bin/env python3
"""Run a short software-triggered acquisition on a real unit and check the result.

    tusb_selftest.py [--id 0] [--seconds 2]

Uses the usb backend exactly as the node does: bipolar inputs, 1 MHz / 2**8
= 3906.25 Hz per channel, both channels. The digital outputs are not touched.
Leave the BNC inputs open (or within +-1 V) while it runs.
"""

import argparse
import sys
import time

import numpy as np

from tusb_0216admh import constants as c
from tusb_0216admh import conversion
from tusb_0216admh.usb_device import UsbTusbAdmhDevice


def check(ok, text):
    print(('PASS ' if ok else 'FAIL ') + text)
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--id', type=int, default=0, help='rear ID switch value')
    parser.add_argument('--seconds', type=float, default=2.0)
    args = parser.parse_args()
    rate_hz = conversion.sample_rate_hz(0, 199, 8)
    ok = True

    with UsbTusbAdmhDevice(args.id) as dev:
        print(f'opened unit with ID switch {args.id}, DIO 0x{dev.dio_read():02x}')
        n1, n2, _, _ = dev.length()
        dev.read(0, n1)  # leftovers from an earlier run
        dev.read(1, n2)
        dev.set_input_type(c.INPUT_TYPE_BIPOLAR, c.INPUT_TYPE_BIPOLAR)
        ok &= check(dev.get_input_type() == (0, 0), 'input type reads back as bipolar')
        dev.select_clock(0, 199, 8)
        dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 0)
        try:
            ok &= check(dev.status() == (c.STATUS_WAITING_TRIGGER, 0), 'waiting for trigger')
            dev.trigger()
            t0 = time.monotonic()
            chunks = ([], [])
            while time.monotonic() - t0 < args.seconds:
                time.sleep(0.05)
                status = dev.status()
                n1, n2, _, _ = dev.length()
                n = min(n1, n2)
                for ch in (0, 1):
                    chunks[ch].append(dev.read(ch, n))
            elapsed_s = time.monotonic() - t0
            ok &= check(status == (c.STATUS_SAMPLING, 0), f'sampling without overflow {status}')
        finally:
            dev.stop()
        ok &= check(dev.status()[0] == c.STATUS_STOPPED, 'stopped')
        n1, n2, _, _ = dev.length()
        dev.read(0, n1)
        dev.read(1, n2)

    for ch in (0, 1):
        counts = np.concatenate(chunks[ch])
        measured_hz = len(counts) / elapsed_s
        volts = conversion.counts_to_volts(counts.astype(np.float64), c.INPUT_TYPE_BIPOLAR)
        print(f'ch{ch + 1}: {len(counts)} samples, mean {volts.mean() * 1e3:+.2f} mV, '
              f'std {volts.std() * 1e3:.3f} mV')
        # The last poll lags the trigger by up to one poll period, hence the slack.
        ok &= check(abs(measured_hz / rate_hz - 1) < 0.05,
                    f'ch{ch + 1} rate {measured_hz:.0f} Hz (expected {rate_hz:.2f} Hz)')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
