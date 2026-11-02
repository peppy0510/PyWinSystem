# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import datetime
import os
import subprocess

from wslsettings import LOG_PATH


CREATE_NO_WINDOW = 0x08000000
LOG_LIMIT = 1024 * 1024


def decode(data):
    # wsl.exe writes UTF-16 unless WSL_UTF8 is set, netsh writes the console code page
    if data[1:2] == b'\x00':
        return data.decode('utf-16-le', 'replace')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('mbcs', 'replace')


def run(command, timeout=60):
    '''(exit code, output); a command that cannot start or overruns returns code -1.'''
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return -1, str(error)
    return result.returncode, decode(result.stdout or b'').replace('\r\n', '\n')


def powershell(script, timeout=120):
    return run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-Command', script], timeout)


def quote(value):
    return "'{}'".format(str(value).replace("'", "''"))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def log(message):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_LIMIT:
            with open(LOG_PATH, 'rb') as file:
                file.seek(-LOG_LIMIT // 2, os.SEEK_END)
                tail = file.read()
            with open(LOG_PATH, 'wb') as file:
                file.write(tail[tail.find(b'\n') + 1:])
        with open(LOG_PATH, 'a', encoding='utf-8') as file:
            file.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n')
    except OSError:
        pass


def read_last_log():
    try:
        with open(LOG_PATH, 'rb') as file:
            lines = file.read().decode('utf-8', 'replace').strip().split('\n')
    except OSError:
        return ''
    return lines[-1].strip() if lines else ''
