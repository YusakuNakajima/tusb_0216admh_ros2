"""Drive the official Windows driver through a fixed scenario while USBPcap records.

Run on the Windows PC with the Turtle driver installed, next to the vendor's
TUSBADMH.py (from ADMHSmplPy.zip; not redistributed here):

    py -3 capture_session.py --id 0 --log calls.jsonl

Every Tusbadmh_* call is logged with its wall-clock time, arguments and return
value, and calls are spaced by --gap-s so that each one stands out in the
capture. analyze_usb_capture.py merges this log with the capture.

Only the ADC inputs and the 4 digital outputs are touched. The digital output
pattern walks 0x0..0xF: disconnect DIGITAL I/O first if anything is wired to it.
"""

import argparse
import json
import time

import TUSBADMH  # vendor module, loads TUSBADMH.DLL


class CallLog:
    def __init__(self, path, gap_s):
        self._f = open(path, 'w', encoding='utf-8')
        self._gap_s = gap_s

    def call(self, name, *args):
        time.sleep(self._gap_s)
        t_wall_s = time.time()
        ret = getattr(TUSBADMH, name)(*args)
        entry = {'t_wall_s': t_wall_s, 'call': name, 'args': list(args), 'ret': ret}
        self._f.write(json.dumps(entry) + '\n')
        self._f.flush()
        print(f'{name}{args} -> {_short(ret)}')
        return ret

    def note(self, text):
        entry = {'t_wall_s': time.time(), 'call': '#' + text, 'args': [], 'ret': None}
        self._f.write(json.dumps(entry) + '\n')
        print('#', text)

    def close(self):
        self._f.close()


def _short(ret):
    """Keep huge Data_Get lists out of the console."""
    if isinstance(ret, tuple) and len(ret) == 2 and isinstance(ret[1], list):
        return (ret[0], f'<{len(ret[1])} samples: {ret[1][:8]}...>')
    return ret


def acquire(log, dev_id, n_polls, ch1_only):
    """Software-triggered continuous acquisition, read with Length/Data_Get."""
    log.call('Tusbadmh_Adc_Start', dev_id, 1, 0, 3, 0, ch1_only)
    log.call('Tusbadmh_Status_Get', dev_id)
    log.call('Tusbadmh_Trigger', dev_id)
    for _ in range(n_polls):
        log.call('Tusbadmh_Status_Get', dev_id)
        ret = log.call('Tusbadmh_Length', dev_id)
        if ret[0] == 0:
            for ch, n in ((0, ret[1]), (1, ret[2])):
                if n > 0:
                    log.call('Tusbadmh_Data_Get', dev_id, ch, min(n, 1000))
    log.call('Tusbadmh_Adc_Stop', dev_id)
    log.call('Tusbadmh_Status_Get', dev_id)


def scenario_start(log, dev_id):
    """Vary each Adc_Start argument alone, then force a FIFO overflow."""
    log.note('external clock (only set, nothing is acquired with it)')
    for div in (0, 24):
        log.call('Tusbadmh_Clock_Select', dev_id, 5, div, 0)

    log.note('Adc_Start arguments: (CycLen, PreLen, TrgSel, Mode, Ch1Only)')
    log.call('Tusbadmh_InputType', dev_id, 0, 0)
    log.call('Tusbadmh_Clock_Select', dev_id, 0, 199, 8)
    for cyc, pre, trg, mode, ch1 in ((1, 0, 3, 0, 0), (2, 0, 3, 0, 0), (0x12345, 0, 3, 0, 0),
                                     (1048576, 0, 3, 0, 0), (1, 1, 3, 0, 0),
                                     (1, 0x6789A, 3, 0, 0), (1, 1048576, 3, 0, 0),
                                     (1, 0, 0, 0, 0), (1, 0, 1, 0, 0), (1, 0, 2, 0, 0),
                                     (1, 0, 3, 1, 0), (1000, 0, 3, 1, 0), (1, 0, 3, 0, 1)):
        log.call('Tusbadmh_Adc_Start', dev_id, cyc, pre, trg, mode, ch1)
        log.call('Tusbadmh_Status_Get', dev_id)
        log.call('Tusbadmh_Adc_Stop', dev_id)

    log.note('overflow: 2 ch at 200 MHz / 8 = 25 MHz, far above what USB can carry')
    log.call('Tusbadmh_Clock_Select', dev_id, 0, 7, 0)
    log.call('Tusbadmh_Adc_Start', dev_id, 1, 0, 3, 0, 0)
    log.call('Tusbadmh_Trigger', dev_id)
    for _ in range(3):
        log.call('Tusbadmh_Status_Get', dev_id)
        log.call('Tusbadmh_Length', dev_id)
    log.call('Tusbadmh_Adc_Stop', dev_id)
    log.call('Tusbadmh_Status_Get', dev_id)
    log.call('Tusbadmh_Clock_Select', dev_id, 0, 199, 8)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', type=int, default=0, help='rear ID switch value')
    parser.add_argument('--log', default='calls.jsonl')
    parser.add_argument('--gap-s', type=float, default=1.0)
    parser.add_argument('--scenario', choices=('basic', 'start'), default='basic',
                        help="'start': Adc_Start encoding and FIFO overflow")
    args = parser.parse_args()
    dev_id = args.id
    log = CallLog(args.log, args.gap_s)
    try:
        log.note('open')
        if log.call('Tusbadmh_Device_Open', dev_id) != 0:
            return
        if args.scenario == 'start':
            try:
                scenario_start(log, dev_id)
            finally:
                log.note('close')
                log.call('Tusbadmh_Device_Close', dev_id)
            return
        try:
            log.note('digital I/O: read, then walk outputs 0x0..0xF')
            log.call('Tusbadmh_Dio_Read', dev_id)
            for bits in (0x0, 0x1, 0x2, 0x4, 0x8, 0xF, 0x0):
                log.call('Tusbadmh_Dio_Write', dev_id, bits)
                log.call('Tusbadmh_Dio_Read', dev_id)

            log.note('input range: every combination')
            for t1, t2 in ((0, 0), (1, 0), (0, 1), (1, 1), (0, 0)):
                log.call('Tusbadmh_InputType', dev_id, t1, t2)
                log.call('Tusbadmh_CheckInputType', dev_id)

            log.note('clock: vary ClkSel, Div and Ave one at a time')
            for clk, div, ave in ((0, 199, 0), (0, 7, 0), (0, 199, 1), (0, 199, 8),
                                  (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0),
                                  (0, 99, 0), (0, 199, 4)):
                log.call('Tusbadmh_Clock_Select', dev_id, clk, div, ave)

            log.note('analog trigger level / noise level')
            for level, noise in ((32768, 800), (1, 0), (65534, 3277), (0x1234, 0x0567)):
                log.call('Tusbadmh_ThLevel_Set', dev_id, level, noise)

            log.note('transfer limit')
            for limit in (100, 1000, 50000, 100000):
                log.call('Tusbadmh_TransLimit', dev_id, limit)

            log.note('acquisition: 2 ch, 1 MHz / 2**8 = 3906.25 Hz, bipolar')
            log.call('Tusbadmh_InputType', dev_id, 0, 0)
            log.call('Tusbadmh_Clock_Select', dev_id, 0, 199, 8)
            acquire(log, dev_id, n_polls=5, ch1_only=0)

            log.note('acquisition: ch1 only')
            acquire(log, dev_id, n_polls=3, ch1_only=1)

            log.note('acquisition: unipolar, 1 MHz / 2**4 = 62.5 kHz')
            log.call('Tusbadmh_InputType', dev_id, 1, 1)
            log.call('Tusbadmh_Clock_Select', dev_id, 0, 199, 4)
            acquire(log, dev_id, n_polls=3, ch1_only=0)
        finally:
            log.note('close')
            log.call('Tusbadmh_Device_Close', dev_id)
    finally:
        log.close()


if __name__ == '__main__':
    main()
