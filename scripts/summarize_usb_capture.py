#!/usr/bin/env python3
"""Condense a capture into command/reply pairs, collapsing repeats, per API call.

    summarize_usb_capture.py capture.pcap calls.jsonl > summary.txt

The DLL polls status (0x50) and data (0x60) every ~15 ms, so the full listing
of analyze_usb_capture.py is long. Here each OUT is paired with the IN that
answers it, identical consecutive pairs become one line with a count, and data
replies are compared by length only. A table of reply lengths per opcode ends
the output.
"""

import argparse
import collections
import json

from tusb_0216admh.usb_capture import read_capture


def pair_transfers(packets):
    """Yield (time_s, out_bytes, in_bytes); an IN with no OUT before it gets b''."""
    pending = None
    for p in packets:
        if not p.is_in:
            pending = p
        else:
            yield p.time_s, pending.data if pending else b'', p.data
            pending = None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capture')
    parser.add_argument('markers', help='JSONL written by windows/capture_session.py')
    args = parser.parse_args()

    packets = [p for p in read_capture(args.capture)
               if p.transfer_type == 'bulk' and p.carries_payload]
    with open(args.markers, encoding='utf-8') as f:
        markers = [json.loads(line) for line in f if line.strip()]

    events = [(m['t_wall_s'], 'call', m) for m in markers]
    events += [(t, 'xfer', (o, i)) for t, o, i in pair_transfers(packets)]
    events.sort(key=lambda e: e[0])

    reply_lengths = collections.defaultdict(collections.Counter)
    run, last_key, last = 0, None, None

    def flush():
        if last is not None:
            o, i = last
            more = ' ...' if len(i) > 24 else ''
            print(f'    x{run:<5} OUT {o.hex(" ")} -> IN[{len(i)}] {i[:24].hex(" ")}{more}')

    for _, kind, value in events:
        if kind == 'call':
            flush()
            run, last_key, last = 0, None, None
            print(f'### {value["call"]}{tuple(value["args"])} -> {str(value["ret"])[:80]}')
            continue
        o, i = value
        reply_lengths[o[:1].hex() or '--'][len(i)] += 1
        key = (o, i) if len(i) <= 16 else (o, len(i))
        if key == last_key:
            run += 1
            continue
        flush()
        run, last_key, last = 1, key, value
    flush()

    print('\nopcode -> {reply length: count}  (-- = IN continuing a longer reply)')
    for opcode, lengths in sorted(reply_lengths.items()):
        print(f'  {opcode} {dict(lengths)}')


if __name__ == '__main__':
    main()
