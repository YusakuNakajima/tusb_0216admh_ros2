#!/usr/bin/env python3
"""Print the TUSB-0216ADMH traffic of a USB capture, aligned with API calls.

    analyze_usb_capture.py capture.pcapng [--markers calls.jsonl] [--device N]

--markers takes the JSONL log written by windows/capture_session.py; each
logged Tusbadmh_* call is printed between the packets it caused.
"""

import argparse
import collections
import json
import struct
import sys

from tusb_0216admh import constants as c
from tusb_0216admh.usb_capture import describe_setup, read_capture


def find_devices(packets):
    """Map (bus, device) -> (packet count, 'vid:pid' or None)."""
    counts = collections.Counter((p.bus, p.device) for p in packets)
    ids = {}
    for p in packets:
        # Completion of GET_DESCRIPTOR(DEVICE): 18 bytes starting 0x12 0x01
        if (p.transfer_type == 'control' and p.from_device and len(p.data) >= 18
                and p.data[0] == 0x12 and p.data[1] == 0x01):
            vid, pid = struct.unpack_from('<HH', p.data, 8)
            ids[(p.bus, p.device)] = (vid, pid)
    return {key: (n, ids.get(key)) for key, n in counts.items()}


def pick_device(devices, bus, device):
    if device is not None:
        matches = [k for k in devices if k[1] == device and (bus is None or k[0] == bus)]
        if len(matches) != 1:
            sys.exit(f'--device {device} matches {matches}; add --bus')
        return matches[0]
    turtle = [k for k, (_, ids) in devices.items()
              if ids == (c.USB_VENDOR_ID, c.USB_PRODUCT_ID)]
    if len(turtle) == 1:
        return turtle[0]
    sys.exit('could not identify the TUSB device (no device descriptor in the capture); '
             'pass --device from the list above')


def load_markers(path):
    markers = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                markers.append(json.loads(line))
    return markers


def format_packet(p, t0, max_bytes):
    kind = 'IN ' if p.is_in else 'OUT'
    side = 'cmpl' if p.from_device else 'subm'
    text = (f'{p.time_s - t0:+12.6f} {kind} ep{p.endpoint:02x} {p.transfer_type:<9}'
            f' {side} st=0x{p.status:x} len={len(p.data)}')
    if p.setup is not None:
        text += f' [{describe_setup(p.setup)}]'
    if p.data:
        shown = p.data[:max_bytes].hex(' ')
        text += ' : ' + shown + (' ...' if len(p.data) > max_bytes else '')
    return text


def format_marker(m, t0):
    args = ', '.join(repr(a) for a in m.get('args', []))
    return f'{m["t_wall_s"] - t0:+12.6f} ### {m["call"]}({args}) -> {m.get("ret")!r}'


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capture')
    parser.add_argument('--markers', help='JSONL written by windows/capture_session.py')
    parser.add_argument('--bus', type=int)
    parser.add_argument('--device', type=int, help='USB device address in the capture')
    parser.add_argument('--all-packets', action='store_true',
                        help='also print URB halves that carry no payload')
    parser.add_argument('--max-bytes', type=int, default=64,
                        help='payload bytes to print per packet')
    parser.add_argument('--marker-offset-s', type=float, default=0.0,
                        help='added to marker times if the clocks differ')
    args = parser.parse_args()

    packets = read_capture(args.capture)
    devices = find_devices(packets)
    print('devices in capture (bus, address): packets, vid:pid')
    for (bus, dev), (n, ids) in sorted(devices.items()):
        id_text = f'{ids[0]:04x}:{ids[1]:04x}' if ids else '?'
        print(f'  ({bus}, {dev}): {n}, {id_text}')
    bus, dev = pick_device(devices, args.bus, args.device)
    print(f'showing bus {bus} address {dev}\n')

    selected = [p for p in packets if (p.bus, p.device) == (bus, dev)
                and (args.all_packets or p.carries_payload)]
    events = [(p.time_s, 1, p) for p in selected]
    if args.markers:
        for m in load_markers(args.markers):
            m['t_wall_s'] += args.marker_offset_s
            events.append((m['t_wall_s'], 0, m))
    if not events:
        return
    events.sort(key=lambda e: (e[0], e[1]))
    t0 = events[0][0]
    for _, is_packet, item in events:
        if is_packet:
            print(format_packet(item, t0, args.max_bytes))
        else:
            print(format_marker(item, t0))


if __name__ == '__main__':
    main()
