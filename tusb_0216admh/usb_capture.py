"""Reader for USB captures (pcap / pcapng), used to recover the protocol.

Supports the link types produced by
- USBPcap on Windows (Wireshark / USBPcapCMD): LINKTYPE_USBPCAP = 249
- usbmon on Linux (e.g. a Windows VM with USB passthrough):
  LINKTYPE_USB_LINUX = 189 and LINKTYPE_USB_LINUX_MMAPPED = 220
with only the standard library, so it runs anywhere.
"""

import dataclasses
import struct

LINKTYPE_USB_LINUX = 189
LINKTYPE_USBPCAP = 249
LINKTYPE_USB_LINUX_MMAPPED = 220

TRANSFER_TYPES = {0: 'iso', 1: 'interrupt', 2: 'control', 3: 'bulk'}

_PCAPNG_SHB = 0x0A0D0D0A
_PCAPNG_IDB = 0x00000001
_PCAPNG_SPB = 0x00000003
_PCAPNG_EPB = 0x00000006


@dataclasses.dataclass
class UsbPacket:
    """One URB submission or completion."""

    time_s: float  # capture timestamp, seconds since the epoch
    bus: int
    device: int
    endpoint: int  # with the direction bit, e.g. 0x81
    transfer_type: str
    from_device: bool  # True for a completion (device -> host side of the URB)
    status: int
    data: bytes
    setup: bytes = None  # 8-byte SETUP packet of a control transfer
    urb_id: int = 0

    @property
    def is_in(self):
        return bool(self.endpoint & 0x80)

    @property
    def carries_payload(self):
        """True for the packet that holds the transferred bytes."""
        if self.transfer_type == 'control' and self.setup is not None:
            return True
        return bool(self.data) and (self.from_device == self.is_in)


def _iter_pcap_records(f):
    """Yield (linktype, time_s, frame) from a pcap or pcapng file."""
    head = f.read(4)
    f.seek(0)
    if len(head) < 4:
        return
    magic_le = struct.unpack('<I', head)[0]
    if magic_le == _PCAPNG_SHB:
        yield from _iter_pcapng(f)
    else:
        yield from _iter_classic_pcap(f)


def _iter_classic_pcap(f):
    header = f.read(24)
    for endian in '<>':
        magic = struct.unpack(endian + 'I', header[:4])[0]
        if magic in (0xA1B2C3D4, 0xA1B23C4D):
            break
    else:
        raise ValueError('not a pcap/pcapng file')
    frac_scale = 1e-9 if magic == 0xA1B23C4D else 1e-6
    linktype = struct.unpack(endian + 'I', header[20:24])[0] & 0x0FFFFFFF
    while True:
        rec = f.read(16)
        if len(rec) < 16:
            return
        ts_sec, ts_frac, incl_len, _ = struct.unpack(endian + 'IIII', rec)
        yield linktype, ts_sec + ts_frac * frac_scale, f.read(incl_len)


def _iter_pcapng(f):
    endian = '<'
    interfaces = []  # (linktype, seconds per timestamp unit)
    while True:
        head = f.read(8)
        if len(head) < 8:
            return
        block_type = struct.unpack('<I', head[:4])[0]
        if block_type == _PCAPNG_SHB:
            bom = f.read(4)
            endian = '<' if struct.unpack('<I', bom)[0] == 0x1A2B3C4D else '>'
            block_len = struct.unpack(endian + 'I', head[4:])[0]
            f.read(block_len - 12)
            interfaces = []  # interface ids restart in each section
            continue
        block_len = struct.unpack(endian + 'I', head[4:])[0]
        body = f.read(block_len - 8)[:-4]  # drop the trailing length
        block_type = struct.unpack(endian + 'I', head[:4])[0]
        if block_type == _PCAPNG_IDB:
            linktype = struct.unpack(endian + 'H', body[:2])[0]
            interfaces.append((linktype, _pcapng_tsresol(body[8:], endian)))
        elif block_type == _PCAPNG_EPB:
            if_id, ts_high, ts_low, cap_len = struct.unpack(endian + 'IIII', body[:16])
            linktype, unit_s = interfaces[if_id]
            yield linktype, ((ts_high << 32) | ts_low) * unit_s, body[20:20 + cap_len]
        elif block_type == _PCAPNG_SPB and interfaces:
            # No timestamp in a simple packet block.
            orig_len = struct.unpack(endian + 'I', body[:4])[0]
            yield interfaces[0][0], 0.0, body[4:4 + orig_len]


def _pcapng_tsresol(options, endian):
    pos = 0
    while pos + 4 <= len(options):
        code, length = struct.unpack(endian + 'HH', options[pos:pos + 4])
        if code == 0:
            break
        if code == 9 and length >= 1:  # if_tsresol
            v = options[pos + 4]
            return 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
        pos += 4 + ((length + 3) & ~3)
    return 1e-6


# USBPCAP_BUFFER_PACKET_HEADER (packed, little endian), 27 bytes
_USBPCAP_HEADER = struct.Struct('<HQIHBHHBBI')


def _parse_usbpcap(time_s, frame):
    (header_len, irp_id, status, _function, info, bus, device, endpoint,
     transfer, data_len) = _USBPCAP_HEADER.unpack_from(frame)
    payload = frame[header_len:header_len + data_len]
    transfer_type = TRANSFER_TYPES.get(transfer, f'unknown{transfer}')
    setup = None
    if transfer_type == 'control' and header_len >= 28:
        stage = frame[27]  # 0 setup, 1 data, 2 status, 3 complete
        if stage == 0:
            setup, payload = payload[:8], payload[8:]
    return UsbPacket(time_s=time_s, bus=bus, device=device, endpoint=endpoint,
                     transfer_type=transfer_type, from_device=bool(info & 0x01),
                     status=status, data=bytes(payload), setup=setup, urb_id=irp_id)


# struct usbmon_packet (host byte order, assumed little endian), first 48 bytes
_USBMON_HEADER = struct.Struct('<QcBBBHbbqiiII8s')


def _parse_usbmon(linktype, frame):
    (urb_id, event, xfer, epnum, devnum, busnum, flag_setup, _flag_data,
     ts_sec, ts_usec, status, _length, len_cap, setup) = _USBMON_HEADER.unpack_from(frame)
    header_len = 64 if linktype == LINKTYPE_USB_LINUX_MMAPPED else 48
    is_submit = event == b'S'
    transfer_type = TRANSFER_TYPES.get(xfer, f'unknown{xfer}')
    return UsbPacket(
        time_s=ts_sec + ts_usec * 1e-6, bus=busnum, device=devnum, endpoint=epnum,
        transfer_type=transfer_type, from_device=not is_submit, status=status,
        data=bytes(frame[header_len:header_len + len_cap]),
        setup=setup if (transfer_type == 'control' and is_submit and flag_setup == 0)
        else None,
        urb_id=urb_id)


def read_capture(path):
    """Return every USB packet of a capture file as a list of UsbPacket."""
    packets = []
    with open(path, 'rb') as f:
        for linktype, time_s, frame in _iter_pcap_records(f):
            if linktype == LINKTYPE_USBPCAP:
                packets.append(_parse_usbpcap(time_s, frame))
            elif linktype in (LINKTYPE_USB_LINUX, LINKTYPE_USB_LINUX_MMAPPED):
                packets.append(_parse_usbmon(linktype, frame))
            else:
                raise ValueError(f'unsupported link type {linktype}')
    return packets


def describe_setup(setup):
    """Decode an 8-byte SETUP packet into a short string."""
    bm, req, value, index, length = struct.unpack('<BBHHH', setup)
    kind = ('standard', 'class', 'vendor', 'reserved')[(bm >> 5) & 0x3]
    direction = 'IN' if bm & 0x80 else 'OUT'
    return (f'{kind} {direction} bmRequestType=0x{bm:02x} bRequest=0x{req:02x} '
            f'wValue=0x{value:04x} wIndex=0x{index:04x} wLength={length}')
