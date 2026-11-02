# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

The GPU output lookup table. It replaces the values just before they leave for the screen,
so every monitor follows it; the only way left for a panel that does not open DDC/CI.

It cannot touch the backlight: the picture looks darker without being less bright, and
lowering it crushes the dark tones. A monitor that has the hardware control uses that first.

Windows puts the ramp back when the display mode changes or the session unlocks; applying it
again is up to the app.
'''


import ctypes
import math

from ctypes import wintypes


# all three channels are 1 at this temperature, which is the untouched state
NEUTRAL_KELVIN = 6500
MIN_KELVIN = 2000
MAX_KELVIN = 10000

# untouched channel factors; above 1 does nothing, white is already at the top
NEUTRAL_CHANNELS = (1.0, 1.0, 1.0)

RAMP_TYPE = (wintypes.WORD * 256) * 3

gdi32 = ctypes.windll.gdi32

gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]


def open_device(device):
    '''Takes the GDI name as is, such as `\\\\.\\DISPLAY1`. Each screen has its own DC, so
    one monitor can be dimmed alone.'''
    return gdi32.CreateDCW('DISPLAY', device, None, None)


def close_device(handle):
    if handle:
        gdi32.DeleteDC(handle)


def get_kelvin_rgb(kelvin):
    '''Black body approximation: the three channel strengths from a temperature alone.'''
    value = max(1000, min(40000, kelvin)) / 100.0

    if value <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(value) - 161.1195681661
    else:
        red = 329.698727446 * pow(value - 60, -0.1332047592)
        green = 288.1221695283 * pow(value - 60, -0.0755148492)

    if value >= 66:
        blue = 255.0
    elif value <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(value - 10) - 305.0447927307

    return tuple(max(0.0, min(255.0, channel)) / 255.0
                 for channel in (red, green, blue))


NEUTRAL_RGB = get_kelvin_rgb(NEUTRAL_KELVIN)


def get_temperature_scale(kelvin):
    '''Divided by the neutral temperature, so 6500 K is exactly (1, 1, 1); the
    approximation falls short of 255 even there and would tint the default.

    Above 1 is cut: white is already at the top, and more only crushes the bright tones.'''
    return tuple(min(1.0, mine / neutral)
                 for mine, neutral in zip(get_kelvin_rgb(kelvin), NEUTRAL_RGB))


def build_ramp(brightness=1.0, contrast=1.0, kelvin=NEUTRAL_KELVIN,
               channels=NEUTRAL_CHANNELS):
    '''Contrast spreads or narrows the tones around the middle, then brightness scales the
    whole; the other order blows out white when contrast rises on a dimmed screen.

    Temperature and RGB are both channel factors and multiply: the temperature sets the
    direction and RGB trims one channel on top, as a monitor OSD does.'''
    scale = get_temperature_scale(kelvin)
    scale = [tone * max(0.0, min(1.0, gain)) for tone, gain in zip(scale, channels)]
    ramp = RAMP_TYPE()

    for index in range(256):
        value = (index / 255.0 - 0.5) * contrast + 0.5
        value = max(0.0, min(1.0, value * brightness))
        for channel in range(3):
            ramp[channel][index] = int(round(value * scale[channel] * 65535))

    return ramp


def apply_ramp(handle, ramp):
    if not handle:
        return False
    return bool(gdi32.SetDeviceGammaRamp(handle, ctypes.byref(ramp)))


def apply(handle, brightness=1.0, contrast=1.0, kelvin=NEUTRAL_KELVIN,
          channels=NEUTRAL_CHANNELS):
    return apply_ramp(handle, build_ramp(brightness, contrast, kelvin, channels))


def reset(handle):
    return apply(handle)


def read_ramp(handle):
    ramp = RAMP_TYPE()
    if not handle or not gdi32.GetDeviceGammaRamp(handle, ctypes.byref(ramp)):
        return None
    return ramp
