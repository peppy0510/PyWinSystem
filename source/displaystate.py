# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import ctypes.wintypes as wintypes
import threading
import uuid


WM_POWERBROADCAST = 0x0218
PBT_POWERSETTINGCHANGE = 0x8013
GUID_CONSOLE_DISPLAY_STATE = uuid.UUID('6fe69556-704a-47a0-8f24-c28d936fda47')
STATES = {0: 'off', 1: 'on', 2: 'dimmed'}


class GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]


class DisplayState(threading.Thread):
    # Windows tells a window when the displays go off, dim or come back

    def __init__(self):
        super().__init__(name='display-state', daemon=True)
        # Windows answers the registration with the current state right away
        self.state = None

    def run(self):
        import win32api
        import win32con
        import win32gui
        wndclass = win32gui.WNDCLASS()
        wndclass.lpszClassName = 'PyWinSystemDisplayState'
        wndclass.lpfnWndProc = {WM_POWERBROADCAST: self.on_power}
        wndclass.hInstance = win32api.GetModuleHandle(None)
        try:
            atom = win32gui.RegisterClass(wndclass)
            hwnd = win32gui.CreateWindow(atom, 'PyWinSystemDisplayState', 0, 0, 0, 0, 0,
                                         win32con.HWND_MESSAGE, 0, wndclass.hInstance, None)
            guid = GUID((ctypes.c_ubyte * 16)(*GUID_CONSOLE_DISPLAY_STATE.bytes_le))
            ctypes.windll.user32.RegisterPowerSettingNotification(
                wintypes.HANDLE(hwnd), ctypes.byref(guid), 0)
        except Exception:
            return
        win32gui.PumpMessages()

    def on_power(self, hwnd, message, wparam, lparam):
        if wparam == PBT_POWERSETTINGCHANGE and lparam:
            # POWERBROADCAST_SETTING: GUID (16), data length (4), then the DWORD state
            setting = ctypes.string_at(lparam, 24)
            if setting[:16] == GUID_CONSOLE_DISPLAY_STATE.bytes_le:
                self.state = STATES.get(int.from_bytes(setting[20:24], 'little'), self.state)
        return True
