"""UsbTusbAdmhDevice against byte sequences taken from a capture of the DLL."""

import numpy as np
import pytest
from tusb_0216admh import constants as c
from tusb_0216admh.device import AdmhError
from tusb_0216admh.usb_device import UsbTusbAdmhDevice


class ScriptedTransport:
    """Expects the given OUT transfers in order and answers each with its IN replies."""

    def __init__(self, script, stale=()):
        self.script = list(script)
        self.replies = [bytes.fromhex(r) for r in stale]  # left by an earlier process
        self.closed = False

    def write(self, data):
        expected, replies = self.script.pop(0)
        assert data.hex(' ') == expected
        assert not self.replies, 'command sent before the previous reply was read'
        self.replies = [bytes.fromhex(r) for r in replies]

    def read(self, size, timeout_ms=None):
        if not self.replies:
            return b''  # timeout
        reply = self.replies.pop(0)
        assert len(reply) <= size
        return reply

    def close(self):
        self.closed = True


def opened(script):
    transport = ScriptedTransport([('f0', ['f0 00'])] + script)
    dev = UsbTusbAdmhDevice(transport=transport)
    dev.open()
    return dev, transport


def test_settings_match_capture():
    dev, transport = opened([
        ('10', ['10 f0']),
        ('20 0f', ['20']),
        ('90 01 00', ['90']),
        ('b0 00 00', ['b0 01 00']),
        ('70 01 c7 08', ['70']),
        ('70 10 00 00', ['70']),
        ('80 12 34 05 67', ['80']),
        ('a0', ['a0']),
        ('40', ['40']),
    ])
    assert dev.dio_read() == 0xF0
    dev.dio_write(0xF)
    dev.set_input_type(1, 0)
    assert dev.get_input_type() == (1, 0)
    dev.select_clock(0, 199, 8)
    dev.select_clock(4, 0, 0)
    dev.set_trigger_level(0x1234, 0x0567)
    dev.set_transfer_limit(1000)  # host side only: no USB traffic
    dev.trigger()
    dev.stop()
    assert transport.script == []


def test_open_picks_the_unit_by_id_switch():
    transport = ScriptedTransport([('f0', ['f0 03']), ('10', ['10 00'])])
    dev = UsbTusbAdmhDevice(device_id=3, transport=transport)
    dev.open()
    assert dev.dio_read() == 0
    dev.close()
    assert transport.closed


def test_open_drops_replies_left_by_an_earlier_process():
    transport = ScriptedTransport([('f0', ['f0 00']), ('10', ['10 00'])],
                                  stale=['10 00', '50 01 00 00 00 00 00 00'])
    dev = UsbTusbAdmhDevice(transport=transport)
    dev.open()
    assert dev.dio_read() == 0


def test_open_rejects_another_id_switch():
    dev = UsbTusbAdmhDevice(device_id=3, transport=ScriptedTransport([('f0', ['f0 00'])]))
    with pytest.raises(AdmhError) as e:
        dev.open()
    assert e.value.code == 6


def test_calls_before_open_fail():
    dev = UsbTusbAdmhDevice(transport=ScriptedTransport([]))
    with pytest.raises(AdmhError) as e:
        dev.status()
    assert e.value.code == 7


@pytest.mark.parametrize('state, expected', [
    ('00', c.STATUS_STOPPED),
    ('01', c.STATUS_WAITING_TRIGGER),
    ('03', c.STATUS_SAMPLING),
    ('02', c.STATUS_STOPPED),  # stopped after a trigger
])
def test_status(state, expected):
    dev, _ = opened([('50', [f'50 {state} 00 00 00 00 00 00'])])
    assert dev.status() == (expected, 0)


def test_overflow_bits():
    dev, _ = opened([('50', ['50 0f 0f 9c b4 10 00 04']),
                     ('50', ['50 07 00 00 00 00 00 00'])])
    assert dev.status() == (c.STATUS_SAMPLING, c.OVERFLOW_CH1 | c.OVERFLOW_CH2)
    assert dev.status() == (c.STATUS_SAMPLING, c.OVERFLOW_CH1)


def test_unknown_status_bits_are_an_error():
    dev, _ = opened([('50', ['50 13 00 00 00 00 00 00'])])
    with pytest.raises(AdmhError):
        dev.status()


def test_length_reports_device_fifo():
    dev, _ = opened([('50', ['50 03 00 00 13 00 98 c2'])])
    assert dev.length() == (0x13, 0x98C2, 0, 3)


def test_read_spans_several_in_transfers():
    samples = np.arange(32768, 32768 + 0x3E, dtype=np.uint16)
    payload = samples.astype('>u2').tobytes()
    dev, _ = opened([
        ('50', ['50 03 00 00 3e 00 00 3a']),
        ('60 00 00 3e 00', [payload[:64].hex(' '), payload[64:].hex(' ')]),
    ])
    np.testing.assert_array_equal(dev.read(0, 1000), samples)


def test_read_is_split_into_chunks():
    dev, _ = opened([
        ('50', ['50 03 00 03 e8 00 00 00']),
        ('60 00 02 00 00', ['00 01' * 512]),
        ('60 00 00 2c 00', ['00 02' * 44]),
    ])
    counts = dev.read(0, 556)
    assert len(counts) == 556 and counts[0] == 1 and counts[-1] == 2


def test_read_never_asks_for_more_than_the_fifo_holds():
    dev, _ = opened([('50', ['50 03 00 00 00 00 00 02']),
                     ('60 00 00 02 01', ['7f fe 7f ff'])])
    assert list(dev.read(1, 10)) == [0x7FFE, 0x7FFF]


def test_wrong_reply_is_a_communication_error():
    dev, _ = opened([('a0', ['50'])])
    with pytest.raises(AdmhError) as e:
        dev.trigger()
    assert e.value.code == 9


@pytest.mark.parametrize('args, expected', [
    ((1, 0, 3, 0, 0), '30 00 00 00 00 00 00 03 00'),
    ((74565, 0, 3, 0, 0), '30 00 00 00 00 00 00 03 00'),  # CycLen unused when continuous
    ((1, 424090, 3, 0, 0), '30 00 00 00 06 78 9a 03 00'),
    ((1, 1048576, 3, 0, 0), '30 00 00 00 10 00 00 03 00'),
    ((1, 0, 1, 0, 0), '30 00 00 00 00 00 00 01 00'),
    ((1000, 0, 3, 1, 0), '30 00 03 e8 00 00 00 03 01'),
    ((1, 0, 3, 0, 1), '30 00 00 00 00 00 00 03 00'),  # Ch1Only stays on the host
])
def test_start_matches_capture(args, expected):
    dev, transport = opened([(expected, ['30'])])
    dev.start(*args)
    assert transport.script == []


def test_external_clock():
    dev, _ = opened([('70 20 18 00', ['70'])])
    dev.select_clock(c.CLOCK_SOURCE_EXTERNAL, 24, 0)
    with pytest.raises(AdmhError):
        dev.select_clock(c.CLOCK_SOURCE_EXTERNAL, 25, 0)


def test_ch1_only_discards_ch2():
    dev, transport = opened([
        ('30 00 00 00 00 00 00 03 00', ['30']),
        ('50', ['50 03 00 00 02 00 00 03']),
        ('60 00 00 03 01', ['00 01 00 02 00 03']),  # drained so the ch2 FIFO cannot overflow
        ('50', ['50 0b 00 00 00 00 00 00']),
    ])
    dev.start(1, 0, c.TRIGGER_SOFTWARE, c.MODE_CONTINUOUS, 1)
    assert dev.length()[:2] == (2, 0)
    assert len(dev.read(1, 10)) == 0
    assert dev.status() == (c.STATUS_SAMPLING, 0)  # ch2 overflow ignored
    assert transport.script == []
