# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import ctypes.wintypes as wintypes
import struct


INVALID_HANDLE = wintypes.HANDLE(-1).value
GENERIC_READ_WRITE = 0xC0000000
SHARE_READ_WRITE = 3
OPEN_EXISTING = 3

IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
STORAGE_PROTOCOL_PROPERTY = 50
NVME_PROTOCOL = 3
NVME_LOG_PAGE = 2
NVME_HEALTH_LOG = 2
NVME_LOG_SIZE = 512
NVME_IDENTIFY = 1
NVME_IDENTIFY_CONTROLLER = 1
NVME_IDENTIFY_SIZE = 4096
PROTOCOL_DATA_OFFSET = 40

SMART_RCV_DRIVE_DATA = 0x7C088
SMART_READ_ATTRIBUTES = 0xD0
SMART_COMMAND = 0xB0
SMART_BUFFER = 512

ATA_ATTRIBUTES = {
    1: 'Read error rate', 4: 'Start/stop count', 5: 'Reallocated sectors',
    7: 'Seek error rate', 9: 'Power-on hours', 10: 'Spin retry count', 12: 'Power cycles',
    187: 'Reported uncorrectable', 188: 'Command timeout', 190: 'Airflow temperature',
    192: 'Power-off retracts', 193: 'Load cycles', 194: 'Temperature',
    197: 'Pending sectors', 198: 'Offline uncorrectable', 199: 'CRC errors',
}
# a raw value above zero on these means the surface or the link is failing
ATA_WARNINGS = (5, 187, 197, 198)

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
kernel32.GetDevicePowerState.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def open_disk(number, access=0):
    handle = kernel32.CreateFileW(rf'\\.\PhysicalDrive{int(number)}', access, SHARE_READ_WRITE,
                                  None, OPEN_EXISTING, 0, None)
    return None if handle == INVALID_HANDLE else handle


def control(handle, code, buffer):
    returned = wintypes.DWORD()
    return bool(kernel32.DeviceIoControl(handle, code, buffer, len(buffer), buffer, len(buffer),
                                         ctypes.byref(returned), None))


def is_spinning(number):
    # asks the power manager, which answers without spinning the drive up
    handle = open_disk(number)
    if handle is None:
        return None
    try:
        state = wintypes.BOOL()
        if not kernel32.GetDevicePowerState(handle, ctypes.byref(state)):
            return None
        return bool(state.value)
    finally:
        kernel32.CloseHandle(handle)


def read_uint(data, start, size):
    return int.from_bytes(data[start:start + size], 'little')


def read_nvme(number):
    handle = open_disk(number)
    if handle is None:
        return None
    try:
        query = struct.pack('<II', STORAGE_PROTOCOL_PROPERTY, 0)
        protocol = struct.pack('<IIIIII', NVME_PROTOCOL, NVME_LOG_PAGE, NVME_HEALTH_LOG, 0,
                               PROTOCOL_DATA_OFFSET, NVME_LOG_SIZE)
        buffer = ctypes.create_string_buffer(query + protocol + bytes(8 + NVME_LOG_SIZE + 64))
        if not control(handle, IOCTL_STORAGE_QUERY_PROPERTY, buffer):
            return None
    finally:
        kernel32.CloseHandle(handle)
    start = 8 + PROTOCOL_DATA_OFFSET
    data = buffer.raw[start:start + NVME_LOG_SIZE]
    unit = 512 * 1000
    return {
        'kind': 'nvme',
        'warning': data[0],
        'temperature': read_uint(data, 1, 2) - 273,
        'spare': data[3], 'spare_threshold': data[4], 'used': data[5],
        'read': read_uint(data, 32, 16) * unit, 'written': read_uint(data, 48, 16) * unit,
        'power_cycles': read_uint(data, 112, 16), 'hours': read_uint(data, 128, 16),
        'unsafe_shutdowns': read_uint(data, 144, 16), 'media_errors': read_uint(data, 160, 16),
        'error_entries': read_uint(data, 176, 16),
        'warning_minutes': read_uint(data, 192, 4), 'critical_minutes': read_uint(data, 196, 4),
    }


def read_nvme_power(number):
    handle = open_disk(number)
    if handle is None:
        return None
    try:
        query = struct.pack('<II', STORAGE_PROTOCOL_PROPERTY, 0)
        protocol = struct.pack('<IIIIII', NVME_PROTOCOL, NVME_IDENTIFY, NVME_IDENTIFY_CONTROLLER,
                               0, PROTOCOL_DATA_OFFSET, NVME_IDENTIFY_SIZE)
        buffer = ctypes.create_string_buffer(query + protocol + bytes(8 + NVME_IDENTIFY_SIZE + 64))
        if not control(handle, IOCTL_STORAGE_QUERY_PROPERTY, buffer):
            return None
    finally:
        kernel32.CloseHandle(handle)
    start = 8 + PROTOCOL_DATA_OFFSET
    data = buffer.raw[start:start + NVME_IDENTIFY_SIZE]
    states = []
    for index in range(data[263] + 1):
        offset = 2048 + index * 32
        flags = data[offset + 3]
        scale = 0.0001 if flags & 1 else 0.01
        states.append((read_uint(data, offset, 2) * scale, not flags & 2))
    return states


def read_ata(number):
    # SMART over the classic IOCTL needs a read-write handle, so administrator rights
    handle = open_disk(number, GENERIC_READ_WRITE)
    if handle is None:
        return None
    try:
        # SENDCMDINPARAMS: buffer size, IDEREGS, drive number, 3 + 16 reserved bytes
        registers = struct.pack('<8B', SMART_READ_ATTRIBUTES, 1, 1, 0x4F, 0xC2,
                                0xA0 | ((number & 1) << 4), SMART_COMMAND, 0)
        command = (struct.pack('<I', SMART_BUFFER) + registers + struct.pack('<B', number)
                   + bytes(19))
        buffer = ctypes.create_string_buffer(command + bytes(16 + SMART_BUFFER))
        if not control(handle, SMART_RCV_DRIVE_DATA, buffer):
            return None
    finally:
        kernel32.CloseHandle(handle)
    # SENDCMDOUTPARAMS: size (4) + DRIVERSTATUS (12), then the 512-byte SMART page
    data = buffer.raw[16:16 + SMART_BUFFER]
    attributes = []
    for index in range(30):
        offset = 2 + index * 12
        code = data[offset]
        if not code:
            continue
        raw = read_uint(data, offset + 5, 6)
        if code in (190, 194):
            raw &= 0xFF
        attributes.append({'id': code, 'name': ATA_ATTRIBUTES.get(code, f'Attribute {code}'),
                           'current': data[offset + 3], 'worst': data[offset + 4], 'raw': raw,
                           'warning': code in ATA_WARNINGS and raw > 0})
    found = {item['id']: item['raw'] for item in attributes}
    return {'kind': 'ata', 'attributes': attributes, 'hours': found.get(9),
            'temperature': found.get(194, found.get(190)), 'power_cycles': found.get(12)}


def read_health(number, media):
    if media == 'HDD':
        spinning = is_spinning(number)
        if spinning is False:
            return {'kind': 'sleeping'}
        health = read_ata(number)
        return health or {'kind': 'locked'}
    return read_nvme(number) or read_ata(number) or {'kind': 'locked'}
