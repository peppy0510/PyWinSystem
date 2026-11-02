# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import json
import os
import subprocess
import sys
import traceback

import wslmanager

from ctypes import wintypes
from wslshell import is_admin
from wslshell import log


ACTIONS = ('status', 'check', 'apply', 'uninstall', 'boot', 'resume', 'restart', 'migrate')
SEE_MASK_NOCLOSEPROCESS = 0x00000040
INFINITE = 0xFFFFFFFF
MB_ICONINFORMATION = 0x40
MB_ICONWARNING = 0x30

USAGE = f'''usage: main.pyw --wsl ACTION [FOLDER] [--preview] [--json]

  ACTION     {", ".join(ACTIONS)}
  FOLDER     where wsl-service lives, for migrate when its task cannot tell
  --preview  print what apply, uninstall or migrate would change, and change nothing
  --json     print status or check as json'''


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('fMask', ctypes.c_ulong),
                ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int),
                ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE),
                ('hProcess', wintypes.HANDLE)]


def relaunch_as_admin(arguments, wait=False):
    '''Runs --wsl with these arguments elevated and without a window; False when UAC is refused.'''
    if getattr(sys, 'frozen', False):
        parameters = subprocess.list2cmdline(['--wsl'] + arguments)
        folder = os.path.dirname(sys.executable)
    else:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.pyw')
        parameters = subprocess.list2cmdline([script, '--wsl'] + arguments)
        folder = os.path.dirname(script)
    info = ShellExecuteInfo(cbSize=ctypes.sizeof(ShellExecuteInfo),
                            fMask=SEE_MASK_NOCLOSEPROCESS, lpVerb='runas',
                            lpFile=sys.executable, lpParameters=parameters,
                            lpDirectory=folder, nShow=0)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False
    if info.hProcess:
        if wait:
            ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, INFINITE)
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True


def show(data, as_json):
    if as_json:
        print(json.dumps(data, indent=2))
        return
    for key, value in data.items():
        if key == 'problems':
            continue
        print(f' * {key}')
        print(f'   {value}')
    problems = data.get('problems') or []
    print(' * problems')
    for problem in problems or ['none']:
        print(f'   {problem}')


def report(lines, succeeded):
    # the installed app and an elevated run have nothing on screen to print to, so they
    # answer in a box; a terminal or a pipe gets the lines
    if sys.stdout is not None and not is_console_hidden():
        for line in lines:
            print(f' * {line}')
        return
    ctypes.windll.user32.MessageBoxW(None, '\n\n'.join(lines), 'PyWinSystem WSL',
                                     MB_ICONINFORMATION if succeeded else MB_ICONWARNING)


def is_console_hidden():
    window = ctypes.windll.kernel32.GetConsoleWindow()
    return bool(window) and not ctypes.windll.user32.IsWindowVisible(window)


def run_logged(argv):
    '''main, with what a task without a window or console would otherwise lose in wsl.log.'''
    arguments = argv[argv.index('--wsl') + 1:]
    quiet = bool(arguments) and arguments[0] in ('status', 'check')
    if not quiet:
        log(f'--wsl {" ".join(arguments)} · {"elevated" if is_admin() else "not elevated"} · '
            f'{sys.executable}')
    try:
        return main(argv)
    except BaseException as error:
        if isinstance(error, SystemExit):
            raise
        log(f'--wsl {" ".join(arguments)} failed\n{traceback.format_exc()}')
        return 1


def main(argv):
    arguments = argv[argv.index('--wsl') + 1:]
    action = arguments[0] if arguments else ''
    preview = '--preview' in arguments
    as_json = '--json' in arguments
    if action not in ACTIONS:
        print(USAGE)
        return 2

    if action == 'migrate':
        if not preview and not is_admin():
            return 0 if relaunch_as_admin(arguments) else 1
        given = next((v for v in arguments[1:] if not v.startswith('--')), None)
        import wslmigrate
        lines, succeeded = wslmigrate.migrate(given, preview)
        report(lines, succeeded)
        return 0 if succeeded else 1

    if action == 'status':
        status = wslmanager.get_status()
        show(status, as_json)
        return 1 if status['problems'] else 0

    if action == 'check':
        problems = wslmanager.check()
        show({'problems': problems}, as_json)
        return 1 if problems else 0

    if not preview and wslmanager.needs_admin(action) and not is_admin():
        return 0 if relaunch_as_admin(arguments) else 1

    if action == 'apply':
        steps = wslmanager.apply(preview=preview)
    elif action == 'uninstall':
        steps = wslmanager.uninstall(preview=preview)
    elif preview:
        print(f'--preview applies to apply and uninstall, not {action}')
        return 2
    else:
        steps = []
        {'boot': wslmanager.boot, 'resume': wslmanager.resume,
         'restart': wslmanager.restart}[action]()
    for step in steps:
        print(f' * {step}')
    return 0
