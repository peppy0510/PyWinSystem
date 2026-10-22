# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import datetime
import os
import subprocess

from ctypes import wintypes

import psutil


SYSTEM_PROCESS_INFORMATION = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
# FILETIME counts 100 ns steps from 1601
EPOCH_OFFSET = 116444736000000000
TICKS = 10 ** 7
IDLE_PID = 0
SYSTEM_PROCESS_ID_INFORMATION = 88
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
DWMWA_CLOAKED = 14
SYSTEM_ROOT = os.path.normcase(os.environ.get('SystemRoot', r'C:\Windows')) + os.sep


class UnicodeString(ctypes.Structure):
    _fields_ = [('length', wintypes.USHORT), ('maximum', wintypes.USHORT),
                ('buffer', ctypes.c_void_p)]


class ProcessInformation(ctypes.Structure):
    _fields_ = [('next', wintypes.ULONG), ('threads', wintypes.ULONG),
                ('private_working_set', ctypes.c_longlong), ('hard_faults', wintypes.ULONG),
                ('threads_peak', wintypes.ULONG), ('cycles', ctypes.c_ulonglong),
                ('created', ctypes.c_longlong), ('user', ctypes.c_longlong),
                ('kernel', ctypes.c_longlong), ('name', UnicodeString),
                ('priority', wintypes.LONG), ('pid', ctypes.c_size_t),
                ('ppid', ctypes.c_size_t), ('handles', wintypes.ULONG),
                ('session', wintypes.ULONG), ('key', ctypes.c_size_t),
                ('peak_virtual', ctypes.c_size_t), ('virtual', ctypes.c_size_t),
                ('page_faults', wintypes.ULONG), ('peak_working_set', ctypes.c_size_t),
                ('working_set', ctypes.c_size_t), ('peak_paged_pool', ctypes.c_size_t),
                ('paged_pool', ctypes.c_size_t), ('peak_nonpaged_pool', ctypes.c_size_t),
                ('nonpaged_pool', ctypes.c_size_t), ('pagefile', ctypes.c_size_t),
                ('peak_pagefile', ctypes.c_size_t), ('private', ctypes.c_size_t),
                ('read_operations', ctypes.c_longlong), ('write_operations', ctypes.c_longlong),
                ('other_operations', ctypes.c_longlong), ('read_bytes', ctypes.c_longlong),
                ('write_bytes', ctypes.c_longlong), ('other_bytes', ctypes.c_longlong)]


query = ctypes.windll.ntdll.NtQuerySystemInformation
query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
query.restype = wintypes.ULONG

user32 = ctypes.windll.user32
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
kernel32 = ctypes.windll.kernel32
kernel32.QueryDosDeviceW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
WindowVisitor = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class ProcessTable:
    # one system call returns every process; psutil asks per process and takes ~0.9 s for 500

    def __init__(self):
        self.buffer = ctypes.create_string_buffer(1 << 20)

    def fill(self):
        needed = wintypes.ULONG(0)
        for _ in range(8):
            status = query(SYSTEM_PROCESS_INFORMATION, self.buffer, len(self.buffer),
                           ctypes.byref(needed))
            if status != STATUS_INFO_LENGTH_MISMATCH:
                return status == 0
            # processes may start between the two calls
            self.buffer = ctypes.create_string_buffer(needed.value + (1 << 16))
        return False

    def read(self):
        if not self.fill():
            return []
        found, offset = [], 0
        while True:
            entry = ProcessInformation.from_buffer(self.buffer, offset)
            if entry.pid != IDLE_PID:
                name = ctypes.wstring_at(entry.name.buffer, entry.name.length // 2) \
                    if entry.name.buffer else ''
                found.append({
                    'pid': entry.pid, 'ppid': entry.ppid, 'name': name or 'System',
                    'created': entry.created, 'time': entry.user + entry.kernel,
                    'memory': entry.private_working_set, 'working_set': entry.working_set,
                    'commit': entry.private, 'threads': entry.threads,
                    'handles': entry.handles, 'session': entry.session,
                    'read': entry.read_bytes, 'written': entry.write_bytes,
                })
            if not entry.next:
                return found
            offset += entry.next


class ProcessIdInformation(ctypes.Structure):
    _fields_ = [('pid', ctypes.c_size_t), ('name', UnicodeString)]


class ImagePaths:
    # asks by PID without opening the process, so protected and elevated ones answer too

    def __init__(self):
        self.devices = {}

    def load_devices(self):
        self.devices = {}
        buffer = ctypes.create_unicode_buffer(1024)
        for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            if kernel32.QueryDosDeviceW(letter + ':', buffer, len(buffer)):
                self.devices[buffer.value + '\\'] = letter + ':\\'

    def to_dos(self, path):
        for attempt in range(2):
            for device, drive in self.devices.items():
                if path.startswith(device):
                    return drive + path[len(device):]
            if attempt == 0:
                self.load_devices()
        return path

    def read(self, pid):
        size = 512
        for _ in range(3):
            buffer = ctypes.create_string_buffer(size)
            info = ProcessIdInformation(pid, UnicodeString(0, size, ctypes.addressof(buffer)))
            status = query(SYSTEM_PROCESS_ID_INFORMATION, ctypes.byref(info),
                           ctypes.sizeof(info), None)
            if status == STATUS_INFO_LENGTH_MISMATCH:
                size = info.name.maximum
                continue
            if status != 0 or not info.name.length:
                return None
            return self.to_dos(ctypes.wstring_at(buffer, info.name.length // 2))
        return None


def is_cloaked(handle):
    # suspended store apps keep a visible but cloaked window
    value = wintypes.DWORD(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(handle, DWMWA_CLOAKED, ctypes.byref(value),
                                                   ctypes.sizeof(value))
    except OSError:
        return False
    return bool(value.value)


def get_window_pids():
    pids = set()

    def visit(handle, _):
        if (user32.IsWindowVisible(handle) and not user32.GetWindow(handle, GW_OWNER)
                and user32.GetWindowTextLengthW(handle)
                and not user32.GetWindowLongW(handle, GWL_EXSTYLE) & WS_EX_TOOLWINDOW
                and not is_cloaked(handle)):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            pids.add(pid.value)
        return True
    user32.EnumWindows(WindowVisitor(visit), 0)
    return pids


def is_windows_path(path):
    return not path or os.path.normcase(path).startswith(SYSTEM_ROOT)


def get_key(process):
    return process['pid'], process['created']


def get_start_time(created):
    if created <= EPOCH_OFFSET:
        return None
    return datetime.datetime.fromtimestamp((created - EPOCH_OFFSET) / float(TICKS))


def read_details(pid):
    # each of these may be refused on its own for an elevated or protected process
    details = {}
    try:
        process = psutil.Process(pid)
    except psutil.Error:
        return None
    for key, read in (('exe', process.exe), ('cmdline', process.cmdline),
                      ('user', process.username), ('cwd', process.cwd)):
        try:
            details[key] = read()
        except psutil.AccessDenied:
            details[key] = False
        except (psutil.Error, OSError):
            details[key] = None
    return details


def join_cmdline(parts):
    return subprocess.list2cmdline(parts) if parts else ''


def open_location(path):
    if path and os.path.exists(path):
        subprocess.Popen(['explorer.exe', '/select,', os.path.normpath(path)])
