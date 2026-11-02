# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

DDC/CI: reads and writes the monitor's own OSD over the I2C line in the video cable. It
reaches what the buttons reach, so the backlight and the input really change.

Not every monitor answers. A panel with a sloppy EDID never opens the channel, and all four
entry points fail with 0xC0262582 (I2C transmit failure). Which codes work comes from the
capabilities string only: an unsupported code still reads back a plausible value.

ctypes defaults to int for returns and arguments and would cut 64-bit handles, so every
argtypes is set.
'''


import ctypes

from ctypes import wintypes


ERROR_I2C_TRANSMIT = 0xC0262582

BRIGHTNESS = 0x10
CONTRAST = 0x12
RED_GAIN = 0x16
GREEN_GAIN = 0x18
BLUE_GAIN = 0x1A
INPUT_SOURCE = 0x60
VOLUME = 0x62
POWER_MODE = 0xD6

# short, as the monitor's own OSD and the port labels on its back write them
INPUT_NAMES = {
    0x01: 'VGA1', 0x02: 'VGA2', 0x03: 'DVI1', 0x04: 'DVI2',
    0x05: 'Composite1', 0x06: 'Composite2', 0x07: 'S-Video1', 0x08: 'S-Video2',
    0x09: 'Tuner1', 0x0A: 'Tuner2', 0x0B: 'Tuner3',
    0x0C: 'Component1', 0x0D: 'Component2', 0x0E: 'Component3',
    0x0F: 'DP1', 0x10: 'DP2', 0x11: 'HDMI1', 0x12: 'HDMI2',
}


class PhysicalMonitor(ctypes.Structure):
    '''handle is not a HANDLE (c_void_p): dxva2 numbers the monitors from 0, c_void_p reads
    0 as None, and the first monitor would lose its handle. It stays an integer.'''

    _fields_ = [('handle', ctypes.c_size_t),
                ('description', wintypes.WCHAR * 128)]


class MonitorInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD),
                ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD),
                ('szDevice', wintypes.WCHAR * 32)]


MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

user32 = ctypes.windll.user32
dxva2 = ctypes.windll.dxva2

user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC, ctypes.c_void_p, MONITOR_ENUM_PROC, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]

dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
    wintypes.HMONITOR, ctypes.POINTER(wintypes.DWORD)]
dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
    wintypes.HMONITOR, wintypes.DWORD, ctypes.POINTER(PhysicalMonitor)]
dxva2.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(PhysicalMonitor)]
dxva2.GetCapabilitiesStringLength.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
dxva2.CapabilitiesRequestAndCapabilitiesReply.argtypes = [
    wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD]
# wintypes.BYTE is a signed c_byte and would wrap a code such as 0xD6 to a negative
dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes = [
    wintypes.HANDLE, ctypes.c_ubyte, ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
dxva2.SetVCPFeature.argtypes = [wintypes.HANDLE, ctypes.c_ubyte, wintypes.DWORD]


def enumerate_handles():
    '''One physical monitor handle per screen, keyed by the GDI name the gamma side uses.'''
    found = {}

    def callback(monitor, hdc, rect, data):
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return True

        count = wintypes.DWORD()
        if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(
                monitor, ctypes.byref(count)) or not count.value:
            return True

        monitors = (PhysicalMonitor * count.value)()
        if dxva2.GetPhysicalMonitorsFromHMONITOR(monitor, count.value, monitors):
            found[info.szDevice] = monitors
        return True

    user32.EnumDisplayMonitors(None, None, MONITOR_ENUM_PROC(callback), 0)
    return found


def destroy_handles(monitors):
    try:
        dxva2.DestroyPhysicalMonitors(len(monitors), monitors)
    except OSError:
        pass


def get_capabilities(handle):
    length = wintypes.DWORD()
    if not dxva2.GetCapabilitiesStringLength(handle, ctypes.byref(length)):
        return None
    if length.value < 2:
        return None

    buffer = ctypes.create_string_buffer(length.value)
    if not dxva2.CapabilitiesRequestAndCapabilitiesReply(handle, buffer, length.value):
        return None
    return buffer.value.decode('ascii', 'replace')


def get_vcp(handle, code):
    current, maximum = wintypes.DWORD(), wintypes.DWORD()
    if not dxva2.GetVCPFeatureAndVCPFeatureReply(
            handle, code, None, ctypes.byref(current), ctypes.byref(maximum)):
        return None
    return (current.value, maximum.value)


def set_vcp(handle, code, value):
    return bool(dxva2.SetVCPFeature(handle, code, int(value)))


def get_section(text, name):
    '''Inside `name(...)`; it nests, so the first `)` is not the end.'''
    start = text.find(name + '(')
    if start < 0:
        return ''

    index = start + len(name)
    depth = 0
    while index < len(text):
        if text[index] == '(':
            depth += 1
        elif text[index] == ')':
            depth -= 1
            if not depth:
                return text[start + len(name) + 1:index]
        index += 1
    return ''


def parse_values(body):
    '''Only a flat list such as `60(0F 11)`. A nested one such as `E1(04(00 01) ...)` means
    something else per code and is not read; None stands for a continuous value.'''
    if body is None or '(' in body:
        return None

    values = []
    for token in body.split():
        try:
            values.append(int(token, 16))
        except ValueError:
            return None
    return values or None


def parse_vcp(body):
    codes = {}
    index = 0

    while index < len(body):
        if body[index].isspace():
            index += 1
            continue

        token = body[index:index + 2]
        index += 2
        while index < len(body) and body[index].isspace():
            index += 1

        values = None
        if index < len(body) and body[index] == '(':
            start = index
            depth = 0
            while index < len(body):
                if body[index] == '(':
                    depth += 1
                elif body[index] == ')':
                    depth -= 1
                    if not depth:
                        index += 1
                        break
                index += 1
            values = body[start + 1:index - 1]

        try:
            codes[int(token, 16)] = parse_values(values)
        except ValueError:
            continue

    return codes


def parse_capabilities(text):
    if not text:
        return {}
    return {
        'model': get_section(text, 'model'),
        'type': get_section(text, 'type'),
        'mccs': get_section(text, 'mccs_ver'),
        'vcp': parse_vcp(get_section(text, 'vcp')),
    }


def get_input_name(value):
    return INPUT_NAMES.get(value, f'Input {value:02X}')
