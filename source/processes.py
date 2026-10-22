# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import datetime
import os
import re
import shlex
import subprocess
import winreg

from ctypes import wintypes

import psutil


SYSTEM_PROCESS_INFORMATION = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
# FILETIME counts 100 ns steps from 1601
EPOCH_OFFSET = 116444736000000000
TICKS = 10 ** 7
IDLE_PID = 0
SYSTEM_PROCESS_ID_INFORMATION = 88
SC_MANAGER_ENUMERATE_SERVICE = 0x0004
SC_ENUM_PROCESS_INFO = 0
SERVICE_WIN32 = 0x00000030
SERVICE_ACTIVE = 0x00000001
ERROR_MORE_DATA = 234
PROCESS_COMMAND_LINE_INFORMATION = 60
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STATUS_BUFFER_OVERFLOW = 0x80000005
STATUS_BUFFER_TOO_SMALL = 0xC0000023
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


class ServiceStatus(ctypes.Structure):
    _fields_ = [('name', wintypes.LPWSTR), ('display', wintypes.LPWSTR),
                ('type', wintypes.DWORD), ('state', wintypes.DWORD),
                ('controls', wintypes.DWORD), ('exit_code', wintypes.DWORD),
                ('service_exit_code', wintypes.DWORD), ('check_point', wintypes.DWORD),
                ('wait_hint', wintypes.DWORD), ('pid', wintypes.DWORD),
                ('flags', wintypes.DWORD)]


query = ctypes.windll.ntdll.NtQuerySystemInformation
query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
query.restype = wintypes.ULONG

user32 = ctypes.windll.user32
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
kernel32 = ctypes.windll.kernel32
kernel32.QueryDosDeviceW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
inquire = ctypes.windll.ntdll.NtQueryInformationProcess
inquire.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
                    ctypes.POINTER(wintypes.ULONG)]
inquire.restype = wintypes.ULONG
advapi32 = ctypes.windll.advapi32
advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
advapi32.OpenSCManagerW.restype = wintypes.HANDLE
advapi32.EnumServicesStatusExW.argtypes = [
    wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR]
advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
shell32 = ctypes.windll.shell32
shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
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


def read_command_line(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.ULONG(0)
        buffer = ctypes.create_string_buffer(4096)
        for _ in range(3):
            status = inquire(handle, PROCESS_COMMAND_LINE_INFORMATION, buffer, len(buffer),
                             ctypes.byref(size))
            if status == 0:
                text = UnicodeString.from_buffer(buffer)
                return ctypes.wstring_at(text.buffer, text.length // 2) if text.buffer else ''
            if status not in (STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_OVERFLOW,
                              STATUS_BUFFER_TOO_SMALL) or size.value <= len(buffer):
                return None
            buffer = ctypes.create_string_buffer(size.value)
        return None
    finally:
        kernel32.CloseHandle(handle)


def split_command_line(text):
    if not text:
        return []
    count = ctypes.c_int(0)
    found = shell32.CommandLineToArgvW(text, ctypes.byref(count))
    if not found:
        return text.split()
    try:
        return [found[index] for index in range(count.value)]
    finally:
        kernel32.LocalFree(found)


GENERIC_FILES = {'main', 'server', 'index', 'app', 'cli', '__main__', 'run', 'start', 'service'}
PLAIN_FOLDERS = {'src', 'source', 'lib', 'bin', 'dist', 'build', 'out', 'scripts', '.venv', 'venv',
                 'site-packages', 'node_modules'}
SHELLS = {'sh', 'bash', 'zsh', 'dash'}
HASHED = re.compile(r'^[0-9a-fA-F]{16,}$')


def get_stem(path):
    return os.path.splitext(re.split(r'[\\/]', path)[-1])[0].lower()


def name_script(path):
    parts = [part for part in re.split(r'[\\/]+', path) if part]
    if not parts:
        return ''
    if get_stem(parts[-1]) in GENERIC_FILES:
        for folder in reversed(parts[:-1]):
            if folder.lower() not in PLAIN_FOLDERS and not HASHED.match(folder):
                return folder + '/' + parts[-1]
    return parts[-1]


def get_operand(args, valued=()):
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
        elif arg in valued:
            skip = True
        elif not arg.startswith('-'):
            return index
    return None


def after(args, flags):
    for index, arg in enumerate(args[:-1]):
        if arg.lower() in flags:
            return args[index + 1]
    return None


def summarize_python(args):
    module = after(args, ('-m',))
    if module:
        return module
    if '-c' in args:
        return 'inline code'
    index = get_operand(args, ('-X', '-W', '-Q'))
    return name_script(args[index]) if index is not None else ''


def summarize_wsl(args):
    for index, arg in enumerate(args):
        if arg in ('--', '-e', '--exec'):
            return summarize_args(args[index + 1:])
    return after(args, ('-d', '--distribution')) or ''


def summarize_shell(args):
    command = after(args, ('-c',))
    if command is None:
        return ''
    try:
        return summarize_args(shlex.split(command))
    except ValueError:
        return command


def read_com_name(args):
    found = re.search(r'\{[0-9A-Fa-f-]{36}\}', ' '.join(args))
    if not found:
        return ''
    for key in ('AppID\\' + found.group(0), 'CLSID\\' + found.group(0)):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key) as opened:
                name = winreg.QueryValueEx(opened, '')[0]
                if name:
                    return name
        except OSError:
            continue
    return 'COM ' + found.group(0)[1:9]


def summarize_args(args):
    if not args:
        return ''
    stem, rest = get_stem(args[0]), args[1:]
    if stem.startswith('python') or stem in ('py', 'pyw'):
        return summarize_python(rest)
    if stem in ('node', 'bun', 'deno'):
        index = get_operand(rest, ('-r', '--require', '--import', '--loader'))
        return name_script(rest[index]) if index is not None else ''
    if stem == 'wsl':
        return summarize_wsl(rest)
    if stem in SHELLS:
        return summarize_shell(rest) or stem
    if stem == 'svchost':
        return after(rest, ('-s',)) or after(rest, ('-k',)) or ''
    if stem == 'dllhost':
        return read_com_name(rest)
    if stem == 'rundll32':
        return name_script(rest[0].split(',')[0]) if rest else ''
    if stem == 'cmd':
        for index, arg in enumerate(rest):
            if arg.lower() in ('/c', '/k'):
                tail = rest[index + 1:]
                return summarize_args(tail) or name_script(tail[0]) if tail else ''
        return ''
    if stem in ('powershell', 'pwsh'):
        script = after(rest, ('-file', '-f'))
        if script:
            return name_script(script)
        command = after(rest, ('-command', '-c'))
        return command[:60] if command else ''
    if stem in ('java', 'javaw'):
        jar = after(rest, ('-jar',))
        if jar:
            return name_script(jar)
        index = get_operand(rest, ('-cp', '-classpath', '--class-path'))
        return rest[index] if index is not None else ''
    return name_script(args[0])


SUMMARIZED = {'python', 'pythonw', 'py', 'pyw', 'node', 'bun', 'deno', 'wsl', 'svchost',
              'dllhost', 'rundll32', 'cmd', 'powershell', 'pwsh', 'java', 'javaw', 'sh', 'bash'}


def needs_summary(name):
    stem = get_stem(name)
    return stem in SUMMARIZED or stem.startswith('python')


def read_services():
    # the service manager names the PID of every running service without administrator rights,
    # which svchost's own command line does not
    services = {}
    manager = advapi32.OpenSCManagerW(None, None, SC_MANAGER_ENUMERATE_SERVICE)
    if not manager:
        return services
    try:
        needed, count, resume = wintypes.DWORD(0), wintypes.DWORD(0), wintypes.DWORD(0)
        buffer = ctypes.create_string_buffer(256 * 1024)
        while True:
            done = advapi32.EnumServicesStatusExW(
                manager, SC_ENUM_PROCESS_INFO, SERVICE_WIN32, SERVICE_ACTIVE, buffer,
                len(buffer), ctypes.byref(needed), ctypes.byref(count), ctypes.byref(resume),
                None)
            more = not done and ctypes.GetLastError() == ERROR_MORE_DATA
            if not done and not more:
                return services
            entries = ctypes.cast(buffer, ctypes.POINTER(ServiceStatus))
            for index in range(count.value):
                entry = entries[index]
                if entry.pid:
                    services.setdefault(entry.pid, []).append((entry.name, entry.display))
            if not more:
                return services
            if needed.value > len(buffer):
                buffer = ctypes.create_string_buffer(needed.value)
    finally:
        advapi32.CloseServiceHandle(manager)
