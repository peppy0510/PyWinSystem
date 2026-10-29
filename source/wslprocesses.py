# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import datetime
import os
import subprocess
import threading
import time

import psutil


HOST = 'vmmemwsl'
CREATE_NO_WINDOW = 0x08000000
RESCAN = 10.0
RETRY = 5.0
LIST_TIMEOUT = 10
# a helper outlives the page by at most this long when nothing asks for its rows
IDLE_LIMIT = 6.0

# one line, as wsl.exe passes arguments through Windows quoting; /proc/*/stat works on any
# distro, ps only adds the user and the arguments and falls back to the busybox form
SCRIPT = ('tck=$(getconf CLK_TCK 2>/dev/null) || tck=100; '
          'page=$(getconf PAGESIZE 2>/dev/null) || page=4096; '
          'if ps -eo pid= >/dev/null 2>&1; then list() { ps -eo pid=,user=,args= -ww; }; '
          'else list() { ps -o pid,user,args; }; fi; '
          'while :; do read up idle < /proc/uptime; echo "@begin $tck $page $up"; '
          'cat /proc/[0-9]*/stat 2>/dev/null; echo @args; list 2>/dev/null; echo @end; '
          'sleep "$1"; done')

STATES = {'R': 'Running', 'S': 'Sleeping', 'D': 'Waiting on disk', 'Z': 'Zombie',
          'T': 'Stopped', 't': 'Stopped by a tracer', 'I': 'Idle', 'X': 'Dead'}


def list_running():
    # older WSL writes UTF-16 here, newer UTF-8
    result = subprocess.run(['wsl.exe', '--list', '--running', '--quiet'], capture_output=True,
                            timeout=LIST_TIMEOUT, creationflags=CREATE_NO_WINDOW,
                            env=dict(os.environ, WSL_UTF8='1'))
    if result.returncode != 0:
        return []
    raw = result.stdout
    text = raw.decode('utf-16-le', 'replace') if b'\x00' in raw else raw.decode('utf-8', 'replace')
    return [line.strip().lstrip('﻿') for line in text.splitlines() if line.strip()]


def parse_stat(line):
    # the name sits in parentheses and may hold spaces or parentheses itself
    left, right = line.index('('), line.rindex(')')
    fields = line[right + 2:].split()
    return {'pid': int(line[:left]), 'name': line[left + 1:right], 'state': fields[0],
            'ppid': int(fields[1]), 'ticks': int(fields[11]) + int(fields[12]),
            'threads': int(fields[17]), 'start': int(fields[19]), 'rss': int(fields[21])}


def parse_arguments(lines):
    found = {}
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit():
            found[int(parts[0])] = (parts[1], parts[2] if len(parts) > 2 else '')
    return found


class Helper(threading.Thread):

    def __init__(self, owner, distro, interval):
        super().__init__(name='wsl-' + distro, daemon=True)
        self.owner = owner
        self.distro = distro
        self.previous = {}
        self.previous_uptime = None
        self.process = subprocess.Popen(
            ['wsl.exe', '-d', distro, '-u', 'root', '-e', 'sh', '-c', SCRIPT, 'sh',
             str(interval)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW)

    def run(self):
        header, stats, arguments, section = None, [], [], None
        try:
            for raw in self.process.stdout:
                line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                if line.startswith('@begin '):
                    header, stats, arguments = line, [], []
                    section = stats
                elif line == '@args' and header:
                    section = arguments
                elif line == '@end' and header:
                    self.publish(header, stats, arguments)
                    header = None
                elif header and section is not None:
                    section.append(line)
                if not self.owner.is_wanted():
                    break
        except (OSError, ValueError):
            pass
        finally:
            self.stop()
            self.owner.on_helper_end(self)

    def stop(self):
        if self.process.poll() is None:
            try:
                self.process.kill()
            except OSError:
                pass

    def publish(self, header, stats, arguments):
        try:
            _, tick, page, uptime = header.split()
            tick, page, uptime = int(tick) or 100, int(page) or 4096, float(uptime)
        except ValueError:
            return
        names = parse_arguments(arguments)
        now = datetime.datetime.now()
        elapsed = uptime - self.previous_uptime if self.previous_uptime is not None else 0
        cpus = psutil.cpu_count() or 1
        rows, ticks = [], {}
        for line in stats:
            try:
                stat = parse_stat(line)
            except (ValueError, IndexError):
                continue
            key = ('wsl', self.distro, stat['pid'], stat['start'])
            ticks[key] = stat['ticks']
            previous = self.previous.get(key)
            cpu = None
            if previous is not None and elapsed > 0:
                share = (stat['ticks'] - previous) / float(tick) / elapsed / cpus * 100.0
                cpu = max(0.0, min(100.0, share))
            user, command = names.get(stat['pid'], ('', ''))
            started = now - datetime.timedelta(seconds=max(0.0, uptime - stat['start'] / tick))
            rows.append({'key': key, 'wsl': self.distro, 'pid': stat['pid'],
                         'ppid': stat['ppid'], 'name': stat['name'], 'created': stat['start'],
                         'cpu': cpu, 'memory': stat['rss'] * page, 'threads': stat['threads'],
                         'state': STATES.get(stat['state'], stat['state']), 'user': user,
                         'command': command or f'[{stat["name"]}]', 'started': started,
                         'path': None})
        self.previous, self.previous_uptime = ticks, uptime
        self.owner.on_rows(self, rows)


class WslProcesses:
    # one helper per running distro while the Processes page is open; nothing touches
    # wsl.exe while vmmemWSL is absent, since asking a stopped WSL starts it

    def __init__(self):
        self.lock = threading.Lock()
        self.helpers = {}
        self.rows = {}
        self.failed = {}
        self.interval = 1
        self.scanned = 0.0
        self.scanning = False
        self.missing = False
        self.touched = 0.0

    def is_wanted(self):
        return time.monotonic() - self.touched < max(IDLE_LIMIT, self.interval * 3)

    def update(self, host_running):
        self.touched = time.monotonic()
        if not host_running:
            self.stop()
            return
        if self.missing or self.scanning:
            return
        if self.helpers and time.monotonic() - self.scanned < RESCAN:
            return
        self.scanning = True
        threading.Thread(target=self.scan, name='wsl-scan', daemon=True).start()

    def scan(self):
        try:
            running = list_running()
        except FileNotFoundError:
            self.missing = True
            running = []
        except (OSError, subprocess.SubprocessError):
            running = None
        try:
            if running is not None and self.is_wanted():
                self.adjust(running)
        finally:
            self.scanned = time.monotonic()
            self.scanning = False

    def adjust(self, running):
        now = time.monotonic()
        with self.lock:
            for distro in [name for name in self.helpers if name not in running]:
                self.helpers.pop(distro).stop()
                self.rows.pop(distro, None)
            for distro in running:
                if distro in self.helpers or now - self.failed.get(distro, -RETRY) < RETRY:
                    continue
                try:
                    helper = Helper(self, distro, self.interval)
                except OSError:
                    self.failed[distro] = now
                    continue
                self.helpers[distro] = helper
                helper.start()

    def on_rows(self, helper, rows):
        with self.lock:
            if self.helpers.get(helper.distro) is helper:
                self.rows[helper.distro] = rows

    def on_helper_end(self, helper):
        with self.lock:
            if self.helpers.get(helper.distro) is helper:
                del self.helpers[helper.distro]
                self.rows.pop(helper.distro, None)
                # a distro that stopped is not started again; the next scan decides
                self.failed[helper.distro] = time.monotonic()
                self.scanned = 0.0

    def get_rows(self):
        with self.lock:
            return [row for distro in sorted(self.rows) for row in self.rows[distro]]

    def get_distros(self):
        with self.lock:
            return sorted(self.rows)

    def set_interval(self, interval):
        interval = max(1, int(interval))
        if interval != self.interval:
            self.interval = interval
            self.stop()

    def stop(self):
        with self.lock:
            helpers, self.helpers, self.rows = list(self.helpers.values()), {}, {}
        for helper in helpers:
            helper.stop()
