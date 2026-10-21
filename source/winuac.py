# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import os
import sys


SHELL_EXECUTE_MIN = 32


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(script, after=None):
    # not pythonw, a run from a terminal would lose its console
    arguments = '' if hasattr(sys, 'frozen') else '"%s"' % script
    # the new copy waits for this one to let go of the single-instance mutex
    if after:
        arguments += ' --after %d' % after
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', sys.executable, arguments, os.path.dirname(script), 1)
    except Exception:
        return False
    return result > SHELL_EXECUTE_MIN
