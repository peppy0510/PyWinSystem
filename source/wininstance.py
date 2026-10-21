# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes


MUTEX_NAME = 'Local\\PyWinSystem'
ERROR_ALREADY_EXISTS = 183

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

# the mutex lives as long as this handle
handle = None


def has_running_instance():
    # psutil cannot read the command line of an elevated instance
    global handle
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return False
    return ctypes.get_last_error() == ERROR_ALREADY_EXISTS


def show_running_window(title):
    # the running copy may sit hidden in the tray; bring it back instead of doing nothing
    import win32con
    import win32gui
    hwnd = win32gui.FindWindow('wxWindowNR', title)
    if not hwnd:
        return
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE if win32gui.IsIconic(hwnd)
                        else win32con.SW_SHOW)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
