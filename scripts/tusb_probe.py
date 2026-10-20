#!/usr/bin/env python3
"""List attached TUSB ADM units and check USB access from Linux. Read-only.

    tusb_probe.py                 # descriptors of every unit
    tusb_probe.py --claim         # also claim the interface (checks permissions)
    tusb_probe.py --listen-s 2.0  # claim, then read the bulk IN endpoint

Nothing is ever written to the device: with the protocol unknown, the only
safe operations are reading descriptors and listening on the IN endpoint.
"""

import argparse
import time

from tusb_0216admh import constants as c
from tusb_0216admh.device import AdmhError
from tusb_0216admh.usb_device import describe_usb_device, find_usb_devices, UsbTransport


def print_descriptors(dev):
    print(f'  bcdUSB 0x{dev.bcdUSB:04x}  bcdDevice 0x{dev.bcdDevice:04x}  '
          f'class {dev.bDeviceClass}  ep0 {dev.bMaxPacketSize0} B')
    for cfg in dev:
        print(f'  configuration {cfg.bConfigurationValue}: '
              f'{cfg.bMaxPower * 2} mA, {cfg.bNumInterfaces} interface(s)')
        for intf in cfg:
            print(f'    interface {intf.bInterfaceNumber} alt {intf.bAlternateSetting}: '
                  f'class {intf.bInterfaceClass}/{intf.bInterfaceSubClass}/'
                  f'{intf.bInterfaceProtocol}')
            for ep in intf:
                direction = 'IN ' if ep.bEndpointAddress & 0x80 else 'OUT'
                kind = ('control', 'iso', 'bulk', 'interrupt')[ep.bmAttributes & 0x3]
                print(f'      ep 0x{ep.bEndpointAddress:02x} {direction} {kind} '
                      f'{ep.wMaxPacketSize} B')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--claim', action='store_true', help='claim the interface')
    parser.add_argument('--listen-s', type=float, default=0.0,
                        help='read the bulk IN endpoint for this many seconds')
    args = parser.parse_args()

    devices = find_usb_devices()
    print(f'{len(devices)} unit(s) with {c.USB_VENDOR_ID:04x}:{c.USB_PRODUCT_ID:04x}')
    for index, dev in enumerate(devices):
        print(f'[usb_index {index}] {describe_usb_device(dev)}')
        print_descriptors(dev)
        if not (args.claim or args.listen_s > 0):
            continue
        transport = UsbTransport(dev, timeout_ms=200)
        try:
            transport.open()
        except AdmhError as e:
            print(f'  claim failed: {e}')
            continue
        try:
            print('  claimed interface 0')
            for name, index_ in (('manufacturer', dev.iManufacturer),
                                 ('product', dev.iProduct),
                                 ('serial', dev.iSerialNumber)):
                print(f'  {name}: {transport.string(index_)!r}')
            deadline = time.monotonic() + args.listen_s
            received = 0
            while time.monotonic() < deadline:
                data = transport.read(64, timeout_ms=200)
                if data:
                    received += len(data)
                    print(f'  IN {len(data)} B: {data.hex(" ")}')
            if args.listen_s > 0:
                print(f'  listened {args.listen_s:.1f} s, {received} B unsolicited')
        finally:
            transport.close()


if __name__ == '__main__':
    main()
