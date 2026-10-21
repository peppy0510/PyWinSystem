# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


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


def main():
    wait_for_previous()
    if not has_running_instance():
        launch()
    else:
        show_running_window('PyWinSystem')


if __name__ == '__main__':
    main()
