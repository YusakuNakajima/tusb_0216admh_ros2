import struct

from tusb_0216admh import usb_capture


def usbpcap_frame(endpoint, transfer, info, data, device=5, stage=None):
    header_len = 27 if stage is None else 28
    header = struct.pack('<HQIHBHHBBI', header_len, 0x1234, 0, 0x09, info, 1, device,
                         endpoint, transfer, len(data))
    if stage is not None:
        header += bytes([stage])
    return header + data


def write_classic_pcap(path, linktype, frames):
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype))
        for t_s, frame in frames:
            f.write(struct.pack('<IIII', int(t_s), round((t_s % 1) * 1e6),
                                len(frame), len(frame)))
            f.write(frame)


def pcapng_block(block_type, body):
    body += b'\0' * (-len(body) % 4)
    total = len(body) + 12
    return struct.pack('<II', block_type, total) + body + struct.pack('<I', total)


def write_pcapng(path, linktype, frames):
    with open(path, 'wb') as f:
        f.write(pcapng_block(0x0A0D0D0A, struct.pack('<IHHq', 0x1A2B3C4D, 1, 0, -1)))
        # if_tsresol = 9 -> nanoseconds
        options = struct.pack('<HHB3x', 9, 1, 9) + struct.pack('<HH', 0, 0)
        f.write(pcapng_block(1, struct.pack('<HHI', linktype, 0, 65535) + options))
        for t_s, frame in frames:
            ts = round(t_s * 1e9)
            f.write(pcapng_block(6, struct.pack('<IIIII', 0, ts >> 32, ts & 0xFFFFFFFF,
                                                len(frame), len(frame)) + frame))


def test_usbpcap_bulk_and_control(tmp_path):
    path = tmp_path / 'c.pcap'
    setup = bytes([0x40, 0x01, 0x34, 0x12, 0x00, 0x00, 0x00, 0x00])  # vendor OUT
    write_classic_pcap(path, usb_capture.LINKTYPE_USBPCAP, [
        (1000.5, usbpcap_frame(0x02, 3, 0, b'\x01\x02\x03')),   # bulk OUT submit
        (1000.6, usbpcap_frame(0x81, 3, 0, b'')),               # bulk IN submit
        (1000.7, usbpcap_frame(0x81, 3, 1, b'\xaa\xbb')),       # bulk IN complete
        (1000.8, usbpcap_frame(0x00, 2, 0, setup, stage=0)),    # control setup
    ])
    packets = usb_capture.read_capture(path)
    assert len(packets) == 4
    out, in_submit, in_done, ctrl = packets
    assert out.endpoint == 0x02 and not out.is_in and out.data == b'\x01\x02\x03'
    assert out.transfer_type == 'bulk' and out.carries_payload
    assert out.time_s == 1000.5
    assert not in_submit.carries_payload
    assert in_done.from_device and in_done.data == b'\xaa\xbb' and in_done.carries_payload
    assert ctrl.setup == setup and ctrl.data == b''
    assert 'vendor OUT' in usb_capture.describe_setup(ctrl.setup)
    assert 'wValue=0x1234' in usb_capture.describe_setup(ctrl.setup)


def usbmon_frame(event, xfer, epnum, data, devnum=7, mmapped=True):
    header = struct.pack('<QcBBBHbbqiiII8s', 0xBEEF, event, xfer, epnum, devnum, 1,
                         ord('-'), 0, 2000, 250000, 0, len(data), len(data), b'\0' * 8)
    if mmapped:
        header += b'\0' * 16
    return header + data


def test_usbmon_pcapng(tmp_path):
    path = tmp_path / 'c.pcapng'
    write_pcapng(path, usb_capture.LINKTYPE_USB_LINUX_MMAPPED, [
        (2000.25, usbmon_frame(b'S', 3, 0x02, b'\x10\x20')),
        (2000.26, usbmon_frame(b'C', 3, 0x81, b'\x30' * 64)),
    ])
    packets = usb_capture.read_capture(path)
    assert [p.endpoint for p in packets] == [0x02, 0x81]
    assert packets[0].data == b'\x10\x20' and packets[0].carries_payload
    assert packets[1].from_device and len(packets[1].data) == 64
    assert packets[1].device == 7 and packets[1].transfer_type == 'bulk'
    assert packets[0].time_s == 2000.25  # usbmon carries its own timestamp
