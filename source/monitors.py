# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import winreg

import displayconfig

from ctypes import wintypes


# read only: what each attached display reports in its EDID and where it is plugged in.
# PyWinMonitor holds the same reading together with the controls that change a display
ENUM_KEY = r'SYSTEM\CurrentControlSet\Enum\DISPLAY'
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001
DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
ENUM_CURRENT_SETTINGS = -1

EDID_HEADER = b'\x00\xff\xff\xff\xff\xff\xff\x00'
DESCRIPTOR_OFFSETS = (54, 72, 90, 108)
DESCRIPTOR_NAME = 0xFC
DESCRIPTOR_SERIAL = 0xFF
# the EDID week that marks a model year rather than a date of manufacture
MODEL_YEAR_WEEK = 255

# a few common EDID vendor codes; anything else shows as the bare code
MANUFACTURERS = {'ACR': 'Acer', 'AOC': 'AOC', 'AUS': 'ASUS', 'BNQ': 'BenQ', 'DEL': 'Dell',
                 'GSM': 'LG', 'HWP': 'HP', 'LEN': 'Lenovo', 'MSI': 'MSI', 'PHL': 'Philips',
                 'SAM': 'Samsung', 'SNY': 'Sony', 'VSC': 'ViewSonic', 'GBT': 'Gigabyte',
                 'HPN': 'HP', 'IVM': 'iiyama', 'NEC': 'NEC', 'EIZ': 'EIZO', 'APP': 'Apple'}


class PointL(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


# DEVMODEW; the printer and display fields share a 16 byte union, so the display shape alone
# keeps the later offsets right
class DeviceMode(ctypes.Structure):
    _fields_ = [('dmDeviceName', wintypes.WCHAR * 32), ('dmSpecVersion', wintypes.WORD),
                ('dmDriverVersion', wintypes.WORD), ('dmSize', wintypes.WORD),
                ('dmDriverExtra', wintypes.WORD), ('dmFields', wintypes.DWORD),
                ('dmPosition', PointL), ('dmDisplayOrientation', wintypes.DWORD),
                ('dmDisplayFixedOutput', wintypes.DWORD), ('dmColor', ctypes.c_short),
                ('dmDuplex', ctypes.c_short), ('dmYResolution', ctypes.c_short),
                ('dmTTOption', ctypes.c_short), ('dmCollate', ctypes.c_short),
                ('dmFormName', wintypes.WCHAR * 32), ('dmLogPixels', wintypes.WORD),
                ('dmBitsPerPel', wintypes.DWORD), ('dmPelsWidth', wintypes.DWORD),
                ('dmPelsHeight', wintypes.DWORD), ('dmDisplayFlags', wintypes.DWORD),
                ('dmDisplayFrequency', wintypes.DWORD), ('dmICMMethod', wintypes.DWORD),
                ('dmICMIntent', wintypes.DWORD), ('dmMediaType', wintypes.DWORD),
                ('dmDitherType', wintypes.DWORD), ('dmReserved1', wintypes.DWORD),
                ('dmReserved2', wintypes.DWORD), ('dmPanningWidth', wintypes.DWORD),
                ('dmPanningHeight', wintypes.DWORD)]


class DisplayDevice(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('DeviceName', wintypes.WCHAR * 32),
                ('DeviceString', wintypes.WCHAR * 128), ('StateFlags', wintypes.DWORD),
                ('DeviceID', wintypes.WCHAR * 128), ('DeviceKey', wintypes.WCHAR * 128)]


def get_display_device(name, index, flags=0):
    device = DisplayDevice()
    device.cb = ctypes.sizeof(DisplayDevice)
    if not ctypes.windll.user32.EnumDisplayDevicesW(name, index, ctypes.byref(device), flags):
        return None
    return device


def get_display_mode(device_name):
    mode = DeviceMode()
    mode.dmSize = ctypes.sizeof(DeviceMode)
    if not ctypes.windll.user32.EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS,
                                                     ctypes.byref(mode)):
        return {}
    return {'width': mode.dmPelsWidth, 'height': mode.dmPelsHeight,
            'left': mode.dmPosition.x, 'top': mode.dmPosition.y,
            'frequency': mode.dmDisplayFrequency}


# '\\?\DISPLAY#AOC4008#5&74d60c1&3&UID270597#{guid}' -> ('AOC4008', '5&74d60c1&3&UID270597'),
# the two levels of the registry key that holds the EDID
def get_instance_key(interface_name):
    parts = interface_name.split('#')
    if len(parts) < 3 or not parts[0].endswith('DISPLAY'):
        return None
    return parts[1], parts[2]


def read_edid(hardware_id, instance):
    path = '\\'.join((ENUM_KEY, hardware_id, instance, 'Device Parameters'))
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, 'EDID')[0]
    except OSError:
        return None


def get_descriptor_text(data, tag):
    for offset in DESCRIPTOR_OFFSETS:
        block = data[offset:offset + 18]
        if len(block) < 18 or block[0] or block[1] or block[2] or block[4]:
            continue
        if block[3] == tag:
            return block[5:18].split(b'\x0a')[0].decode('cp437', 'replace').strip()
    return ''


def get_manufacturer(data):
    value = (data[8] << 8) | data[9]
    return ''.join(chr(ord('A') + ((value >> shift) & 0x1F) - 1) for shift in (10, 5, 0))


def parse_edid(data):
    if not data or len(data) < 128 or bytes(data[:8]) != EDID_HEADER:
        return {}
    return {'manufacturer': get_manufacturer(data), 'product': (data[11] << 8) | data[10],
            'name': get_descriptor_text(data, DESCRIPTOR_NAME),
            'serial': get_descriptor_text(data, DESCRIPTOR_SERIAL),
            'serial_number': int.from_bytes(bytes(data[12:16]), 'little'),
            'year': 1990 + data[17], 'week': data[16],
            'width_cm': data[21], 'height_cm': data[22]}


def get_monitor_info(device_name):
    monitor = get_display_device(device_name, 0, EDD_GET_DEVICE_INTERFACE_NAME)
    key = monitor and get_instance_key(monitor.DeviceID)
    return parse_edid(read_edid(*key)) if key else {}


def assign_labels(monitors):
    # the same model twice gets numbered, left to right, as PyWinMonitor does
    counts = {}
    for monitor in monitors:
        counts[monitor['label']] = counts.get(monitor['label'], 0) + 1
    seen = {}
    for monitor in monitors:
        if counts[monitor['label']] > 1:
            seen[monitor['label']] = seen.get(monitor['label'], 0) + 1
            monitor['label'] = f'{monitor["label"]} ({seen[monitor["label"]]})'


# every display on the desktop, left to right; registry and display config only, a few ms
def read_monitors():
    connections = displayconfig.read_connections()
    monitors = []
    index = 0
    while True:
        adapter = get_display_device(None, index)
        index += 1
        if adapter is None:
            break
        if not adapter.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            continue
        monitor = get_monitor_info(adapter.DeviceName)
        monitor.update(get_display_mode(adapter.DeviceName))
        monitor.update(connections.get(adapter.DeviceName, {}))
        monitor['device'] = adapter.DeviceName
        monitor['adapter'] = adapter.DeviceString
        monitor['primary'] = bool(adapter.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE)
        monitor['label'] = monitor.get('name') or monitor.get('manufacturer') or 'Display'
        monitors.append(monitor)
    monitors.sort(key=lambda monitor: (monitor.get('left', 0), monitor.get('top', 0)))
    assign_labels(monitors)
    return monitors


def get_diagonal(monitor):
    width, height = monitor.get('width_cm', 0), monitor.get('height_cm', 0)
    return round((width ** 2 + height ** 2) ** 0.5 / 2.54) if width and height else 0


def get_port_name(output, connector):
    short = {'DisplayPort': 'DP', 'USB-C DisplayPort': 'USB-C'}.get(output, output)
    # a display chained over MST has no socket number of its own
    return f'{short} chain' if connector is None else f'{short} {connector + 1}'


def describe(monitor):
    parts = []
    if monitor.get('width'):
        parts.append(f'{monitor["width"]} × {monitor["height"]}')
    if monitor.get('frequency'):
        parts.append(f'{monitor["frequency"]} Hz')
    if get_diagonal(monitor):
        parts.append(f'{get_diagonal(monitor)}″')
    code = monitor.get('manufacturer')
    if code:
        name = MANUFACTURERS.get(code, code)
        parts.append(name if name == code else f'{name} ({code})')
    if monitor.get('product') is not None:
        parts.append(f'0x{monitor["product"]:04X}')
    serial = monitor.get('serial') or (str(monitor['serial_number'])
                                       if monitor.get('serial_number') else '')
    if serial:
        parts.append(f'serial {serial}')
    if monitor.get('year'):
        week = monitor.get('week') or 0
        if week == MODEL_YEAR_WEEK:
            parts.append(f'model year {monitor["year"]}')
        elif 0 < week <= 54:
            parts.append(f'made {monitor["year"]} week {week}')
        else:
            parts.append(f'made {monitor["year"]}')
    return ' · '.join(parts)
