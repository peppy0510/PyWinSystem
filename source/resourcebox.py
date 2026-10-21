# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import collections
import platform
import socket
import threading
import time
import wx

import netinfo

from controls import ActionCard
from controls import Panel
from controls import ScrollArea
from meters import CoreCard
from meters import GraphCard
from meters import MeterCard
from meters import BUSY_DELAY
from meters import RateCard
from meters import ValueCard
from meters import format_bytes
from meters import format_rate
from meters import get_ceiling
from meters import get_watt_ceiling
from utilities import call_painted


HISTORY = 300
# a row graph is only about 100 px wide, so it shows the last minute
ROW_HISTORY = 60


def format_uptime(seconds):
    days, seconds = divmod(int(seconds), 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return '%d %s %02d:%02d:%02d' % (days, 'day' if days == 1 else 'days', hours, minutes,
                                     seconds)


def get_power_text(gpu):
    parts = ['%.0f W of %.0f W' % (gpu['power'], gpu['power_limit'] or 0)]
    if gpu.get('fan') is not None:
        parts.append('fan %d%%' % gpu['fan'])
    if gpu.get('core_clock') and gpu.get('memory_clock'):
        parts.append('%d / %d MHz' % (gpu['core_clock'], gpu['memory_clock']))
    return ' · '.join(parts)


def get_ratio(used, total):
    return used / float(total) if total else None


class ResourceBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.layout_key = None
        self.cards = {}
        self.disk_names = {}
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=HISTORY))
        self.interval = 1.0
        self.public_ip = None
        self.looking_up = False
        self.apply_theme(theme)

    def set_disk_names(self, disks):
        self.disk_names = {'PhysicalDrive%d' % disk['number']: disk for disk in disks}
        self.layout_key = None

    def get_layout_key(self, data):
        sensors = data['sensors']
        monitor = sensors['monitor']
        return (len(data['gpus']), tuple(data['disks']), tuple(data['networks']),
                data['wsl'] is not None, tuple(sorted(self.disk_names)),
                tuple(sorted(sensors['nvme'])), tuple(sorted(sensors['cpu_power'])),
                None if monitor is None else tuple((item['hardware'], item['name'])
                                                   for item in monitor))

    def add_panel(self, key, title, body, subtitle=''):
        return Panel(self.content, self.theme, 'resources.' + key, title, body, self.folds,
                     self.on_fold, subtitle=subtitle)

    def build(self, data):
        for child in list(self.content.GetChildren()):
            child.Destroy()
        board, theme = self.content, self.theme
        cards = self.cards = {}
        wsl = data['wsl']
        panels = []

        def meter(key, label, description=''):
            cards[key] = MeterCard(board, theme, label, description)
            return cards[key]

        def graph(key, label):
            cards[key] = GraphCard(board, theme, label, HISTORY)
            return cards[key]

        def rate(key, label, description='', names=('R', 'W')):
            cards[key] = RateCard(board, theme, label, description, names, ROW_HISTORY)
            return cards[key]

        release, version = platform.release(), platform.version()
        cards['host'] = ValueCard(board, theme, 'Hostname',
                                  'Windows %s · build %s' % (release, version), socket.gethostname())
        cards['uptime'] = ValueCard(board, theme, 'Uptime')
        panels.append(self.add_panel('system', 'System', [cards['host'], cards['uptime']]))
        panels.append(self.add_panel('sensors', 'Temperature and power',
                                     self.build_sensors(data)))

        body = [meter('cpu', 'CPU', '%d logical processors' % len(data['cpu']['cores'])),
                graph('graph.cpu', 'CPU over time')]
        cards['cores'] = CoreCard(board, theme, 'Per processor')
        body.append(cards['cores'])
        if wsl:
            body.append(meter('wsl.cpu', 'WSL'))
        panels.append(self.add_panel('cpu', 'CPU', body))

        body = [meter('memory', 'Memory'), graph('graph.memory', 'Memory over time'),
                meter('swap', 'Page file')]
        if wsl:
            body.append(meter('wsl.memory', 'WSL'))
        panels.append(self.add_panel('memory', 'Memory', body))

        body = []
        for gpu in data['gpus']:
            body.append(meter('gpu%d' % gpu['index'], 'GPU %d' % gpu['index'], gpu['name']))
            body.append(meter('vram%d' % gpu['index'], 'VRAM %d' % gpu['index']))
            if gpu.get('power') is not None:
                body.append(meter('power%d' % gpu['index'], 'Power %d' % gpu['index']))
            body.append(graph('graph.gpu%d' % gpu['index'], 'GPU %d over time' % gpu['index']))
        if body:
            panels.append(self.add_panel('gpu', 'GPU', body,
                                         'WSL share is not reported per process'))

        body = []
        for name in data['disks']:
            disk = self.disk_names.get(name)
            label = disk['name'] if disk else name
            description = name.replace('PhysicalDrive', 'Disk ')
            if disk:
                description += ' · %s · %s' % (disk['media'], disk['bus'])
            body.append(rate('disk:' + name, label, description))
        if wsl:
            body.append(rate('wsl.disk', 'WSL', 'Virtual disks inside WSL'))
        body.append(graph('graph.disk', 'Physical disks over time'))
        panels.append(self.add_panel('disk', 'Disk I/O', body))

        body = [rate('net:' + name, name, names=('Down', 'Up')) for name in data['networks']]
        cards['public'] = ActionCard(board, theme, 'Public IP', self.get_public_text(), 'Look up',
                                     self.look_up)
        cards['public'].set_captions('Looking up')
        body.append(cards['public'])
        if wsl:
            mirrored = wsl['config'].get('networking') == 'mirrored'
            body.append(rate('wsl.network', 'WSL', 'Part of the adapters above'
                             if mirrored else 'Through the WSL virtual adapter',
                             ('Down', 'Up')))
        body.append(graph('graph.network', 'All adapters over time'))
        panels.append(self.add_panel('network', 'Network', body))

        self.set_panels(panels)
        self.bind_children()
        self.apply_theme(theme)
        self.relayout_panels()

    def build_sensors(self, data):
        board, theme, cards = self.content, self.theme, self.cards
        sensors = data['sensors']
        body = []

        def value(key, label, description=''):
            cards[key] = ValueCard(board, theme, label, description)
            body.append(cards[key])

        if sensors['cpu_power']:
            value('sensor.cpu', 'CPU power', 'Intel RAPL energy counter')
        for gpu in data['gpus']:
            value('sensor.gpu%d' % gpu['index'], 'GPU %d' % gpu['index'])
        for number in sorted(sensors['nvme']):
            disk = self.disk_names.get('PhysicalDrive%d' % number) or {}
            value('sensor.disk%d' % number, disk.get('name') or 'Disk %d' % number,
                  'Disk %d · NVMe' % number)
        monitor = sensors['monitor']
        if monitor is None:
            value('sensor.monitor', 'CPU and mainboard temperatures',
                  'Windows has no reading without a sensor driver · '
                  'shown here while LibreHardwareMonitor runs')
        else:
            for index, item in enumerate(monitor):
                value('sensor.lhm%d' % index, item['name'], item['hardware'])
        if sensors['cpu_power'] or any(gpu.get('power') for gpu in data['gpus']):
            value('sensor.total', 'CPU and GPUs', 'Power drawn by the parts that report it')
            cards['graph.power'] = GraphCard(board, theme, 'Power over time', HISTORY)
            body.append(cards['graph.power'])
        return body

    def set_sensors(self, data):
        cards, sensors = self.cards, data['sensors']
        cpu = sensors['cpu_power']
        if 'sensor.cpu' in cards:
            parts = ['%s %.1f W' % (label, cpu[key]) for key, label in (
                ('cores', 'Cores'), ('graphics', 'Graphics'), ('dram', 'Memory')) if key in cpu]
            cards['sensor.cpu'].set_value('%.1f W' % cpu.get('package', 0),
                                          ' · '.join(parts) or 'Intel RAPL energy counter')
        gpu_watts = 0.0
        for gpu in data['gpus']:
            key = 'sensor.gpu%d' % gpu['index']
            parts = [gpu['name']]
            if gpu.get('power') is not None:
                parts.append('%.0f W' % gpu['power'])
                gpu_watts += gpu['power']
            if key in cards:
                cards[key].set_value('' if gpu.get('temp') is None else '%d °C' % gpu['temp'],
                                     ' · '.join(parts))
        for number, temperature in sensors['nvme'].items():
            if 'sensor.disk%d' % number in cards:
                cards['sensor.disk%d' % number].set_value('%d °C' % temperature)
        for index, item in enumerate(sensors['monitor'] or []):
            if 'sensor.lhm%d' % index in cards:
                unit = '%.0f °C' if item['type'] == 'Temperature' else '%.0f rpm'
                cards['sensor.lhm%d' % index].set_value(unit % item['value'])
        if 'sensor.total' in cards:
            cpu_watts = cpu.get('package', 0.0)
            cards['sensor.total'].set_value('%.0f W' % (cpu_watts + gpu_watts))
            history = self.history
            history['power.cpu'].append(cpu_watts)
            history['power.gpu'].append(gpu_watts)
            values = list(history['power.cpu']) + list(history['power.gpu'])
            ceiling = get_watt_ceiling(max(values + [0]))
            cards['graph.power'].set_series([
                ('CPU', [value / ceiling for value in history['power.cpu']], 'area'),
                ('GPUs', [value / ceiling for value in history['power.gpu']], 'line')],
                self.get_span(), '%d W' % ceiling)

    def on_fold(self):
        self.relayout_panels()
        if self.on_folds:
            self.on_folds()

    def apply_theme(self, theme):
        self.set_theme(theme)
        for child in self.content.GetChildren():
            if hasattr(child, 'set_theme'):
                child.set_theme(theme)
        self.Refresh()

    def set_data(self, data):
        if not self:
            return
        key = self.get_layout_key(data)
        if key != self.layout_key:
            self.layout_key = key
            self.build(data)
        cards, wsl = self.cards, data['wsl']

        seconds = time.time() - data['boot']
        cards['uptime'].set_value(format_uptime(seconds), 'Since %s' % time.strftime(
            '%Y-%m-%d %H:%M', time.localtime(data['boot'])))

        cpu = data['cpu']
        cards['cpu'].set_value(cpu['total'] / 100.0,
                               share=wsl and wsl.get('host_cpu', 0) / 100.0)
        cards['cores'].set_values(cpu['cores'])

        memory = data['memory']
        cards['memory'].set_value(get_ratio(memory['used'], memory['total']), '%s of %s' % (
            format_bytes(memory['used']), format_bytes(memory['total'])),
            share=wsl and get_ratio(wsl.get('host_memory', 0), memory['total']))
        swap = data['swap']
        cards['swap'].set_value(get_ratio(swap['used'], swap['total']), '%s of %s' % (
            format_bytes(swap['used']), format_bytes(swap['total'])))

        for gpu in data['gpus']:
            index = gpu['index']
            temp = '%d°C' % gpu['temp'] if gpu.get('temp') is not None else ''
            cards['gpu%d' % index].set_value(gpu['util'] / 100.0, ' · '.join(
                part for part in (gpu['name'], temp) if part))
            cards['vram%d' % index].set_value(get_ratio(gpu['used'], gpu['total']), '%s of %s' % (
                format_bytes(gpu['used']), format_bytes(gpu['total'])))
            if 'power%d' % index in cards:
                cards['power%d' % index].set_value(get_ratio(gpu['power'], gpu['power_limit']),
                                                   get_power_text(gpu))

        for name, pair in data['disks'].items():
            cards['disk:' + name].set_rates(pair)
        addresses = data.get('addresses') or {}
        for name, pair in data['networks'].items():
            cards['net:' + name].set_rates(pair,
                                           netinfo.describe(addresses.get(name)))

        if wsl:
            self.set_wsl(wsl, cpu)
        self.set_history(data)
        self.set_sensors(data)

    def get_public_text(self):
        if self.public_ip:
            return self.public_ip
        return 'Asks cloudflare.com once each time you press it'

    def look_up(self):
        if self.looking_up:
            return
        self.looking_up = True
        wx.CallLater(BUSY_DELAY, self.show_busy)

        def work():
            try:
                address = netinfo.lookup_public_ip()
            except Exception:
                address = None
            call_painted(self, self.set_public_ip, address)
        threading.Thread(target=work, daemon=True).start()

    def show_busy(self):
        card = self.cards.get('public') if self else None
        if card and self.looking_up:
            card.set_caption('Looking up')

    def set_public_ip(self, address):
        if not self:
            return
        self.looking_up = False
        card = self.cards.get('public')
        if address:
            self.public_ip = address
        if card:
            card.set_caption('Look up')
            card.set_description(self.get_public_text() if address else 'No answer · try again')

    def set_interval(self, interval):
        self.interval = float(interval)

    def get_span(self):
        seconds = HISTORY * self.interval
        return '%d min' % round(seconds / 60) if seconds >= 120 else '%d s' % seconds

    def set_history(self, data):
        history, wsl = self.history, data['wsl']
        memory = data['memory']
        history['cpu'].append(data['cpu']['total'] / 100.0)
        history['cpu.wsl'].append(wsl.get('host_cpu', 0) / 100.0 if wsl else None)
        history['memory'].append(get_ratio(memory['used'], memory['total']))
        history['memory.wsl'].append(get_ratio(wsl.get('host_memory', 0), memory['total'])
                                     if wsl else None)
        for gpu in data['gpus']:
            history['gpu%d' % gpu['index']].append(gpu['util'] / 100.0)
            history['vram%d' % gpu['index']].append(get_ratio(gpu['used'], gpu['total']))

        # Storage Spaces drives repeat the I/O of the disks under them
        physical = [name for name in data['disks']
                    if self.disk_names.get(name, {}).get('media') != 'Virtual']
        for key, pairs in (('disk', [data['disks'][name] for name in physical]),
                           ('network', list(data['networks'].values()))):
            history[key + '.in'].append(sum(pair[0] for pair in pairs))
            history[key + '.out'].append(sum(pair[1] for pair in pairs))

        span, cards = self.get_span(), self.cards
        for key, names in (('disk', ('Read', 'Write')), ('network', ('Down', 'Up'))):
            incoming, outgoing = list(history[key + '.in']), list(history[key + '.out'])
            ceiling = get_ceiling(max(incoming + outgoing + [0]))
            cards['graph.' + key].set_series([
                (names[0], [value / ceiling for value in incoming], 'area'),
                (names[1], [value / ceiling for value in outgoing], 'line')],
                span, format_rate(ceiling))
        for key, name in (('cpu', 'CPU'), ('memory', 'Memory')):
            series = [(name, list(history[key]), 'area')]
            if any(value is not None for value in history[key + '.wsl']):
                series.append(('WSL', list(history[key + '.wsl']), 'line'))
            cards['graph.' + key].set_series(series, span)
        for gpu in data['gpus']:
            index = gpu['index']
            cards['graph.gpu%d' % index].set_series([
                ('GPU', list(history['gpu%d' % index]), 'area'),
                ('VRAM', list(history['vram%d' % index]), 'line')], span)

    def set_wsl(self, wsl, cpu):
        cards, config = self.cards, wsl['config']
        processors = config.get('processors') or len(cpu['cores'])
        cards['wsl.cpu'].set_value(
            None if wsl.get('cpu') is None else wsl['cpu'] / 100.0,
            '%d of %d processors · %.1f%% of the whole PC' % (
                processors, len(cpu['cores']), wsl.get('host_cpu', 0)))
        inside = wsl.get('memory')
        limit = config.get('memory') or (inside or {}).get('total')
        if inside:
            cards['wsl.memory'].set_value(get_ratio(inside['used'], limit), '%s of %s limit · '
                                          '%s on Windows' % (
                                              format_bytes(inside['used']), format_bytes(limit),
                                              format_bytes(wsl.get('host_memory'))))
        else:
            cards['wsl.memory'].set_value(None, '%s on Windows' % format_bytes(
                wsl.get('host_memory')))
        cards['wsl.disk'].set_rates(wsl.get('disk'))
        cards['wsl.network'].set_rates(wsl.get('network'))

    def tick(self):
        pass
