# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os
import sys

from wininstance import has_running_instance
from wininstance import show_running_window


class stderr:
    def write(self, *args, **kwargs):
        pass


if not sys.stderr:
    sys.stderr = stderr()


def launch():
    from mainapp import launch_mainapp
    launch_mainapp()


def wait_for_previous():
    if '--after' not in sys.argv:
        return
    import psutil
    try:
        pid = int(sys.argv[sys.argv.index('--after') + 1])
        psutil.Process(pid).wait(10)
    except (ValueError, IndexError, psutil.Error):
        pass


def run_headless(code):
    # a task gives pythonw standard handles it cannot flush, and Python then exits with 120
    # after the work is done
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)


def main():
    # the tasks run without a window beside a running app, so before the instance guard
    if '--wsl' in sys.argv:
        from wslcli import run_logged
        run_headless(run_logged(sys.argv))
    if '--monitors' in sys.argv:
        from monitortask import main as run_monitors
        run_headless(run_monitors(sys.argv))
    wait_for_previous()
    if not has_running_instance():
        launch()
    else:
        show_running_window('PyWinSystem')


if __name__ == '__main__':
    main()
