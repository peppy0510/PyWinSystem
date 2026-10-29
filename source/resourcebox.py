# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import collections
import functools
import os
import platform
import socket
import threading
import time
import wx

import energy
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
from meters import get_rate_scale
from meters import get_watt_ceiling
from utilities import call_painted


HISTORY = 300
HDD_ASLEEP = 0.8
MONITOR_OFF = 0.3
# a row graph is only about 100 px wide, so it shows the last minute
ROW_HISTORY = 60


def format_uptime(seconds):
    days, seconds = divmod(int(seconds), 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return (f'{days} {"day" if days == 1 else "days"} '
            f'{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}')


def get_power_text(gpu):
    parts = [f'{gpu["power"]:.0f} W of {gpu["power_limit"] or 0:.0f} W']
    if gpu.get('fan') is not None:
        parts.append(f'fan {int(gpu["fan"])}%')
    if gpu.get('core_clock') and gpu.get('memory_clock'):
        parts.append(f'{int(gpu["core_clock"])} / {int(gpu["memory_clock"])} MHz')
    return ' · '.join(parts)


def format_percent(value):
    return '—' if value is None else f'{round(value * 100)}%'


def get_ratio(used, total):
    return used / float(total) if total else None


class ResourceBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.layout_key = None
        self.cards = {}
        self.headers = []
        self.summaries = {}
        self.disk_names = {}
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=HISTORY))
        self.interval = 1.0
        self.energy = energy.EnergyLog()
        self.display = None
        self.electricity = {}
        self.tariffs = energy.load_tariffs()
        self.tariff_time = self.get_tariff_time()
        self.sampled = None
        self.public_ip = None
        self.looking_up = False
        self.apply_theme(theme)

    def set_disk_names(self, disks):
        self.disk_names = {f'PhysicalDrive{disk["number"]}': disk for disk in disks}
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
        panel = Panel(self.content, self.theme, 'resources.' + key, title, body, self.folds,
                      self.on_fold, subtitle=subtitle)
        panel.header.summary = functools.partial(self.draw_summary, key)
        self.headers.append(panel.header)
        return panel

    def draw_summary(self, key, gc, width, height):
        card = self.cards.get(self.summaries.get(key))
        return card.draw_summary(gc, width, height) if card else None

    def build(self, data):
        for child in list(self.content.GetChildren()):
            child.Destroy()
        board, theme = self.content, self.theme
        cards = self.cards = {}
        self.headers = []
        # a folded panel shows its graph in the header (System, the host name); with several
        # GPUs, the first one's
        self.summaries = {'system': 'host', 'sensors': 'graph.power', 'electricity': 'graph.wall',
                          'cpu': 'graph.cpu', 'memory': 'graph.memory', 'disk': 'graph.disk',
                          'network': 'graph.network'}
        if data['gpus']:
            self.summaries['gpu'] = f'graph.gpu{int(data["gpus"][0]["index"])}'
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
                                  f'Windows {release} · build {version}', socket.gethostname())
        cards['uptime'] = ValueCard(board, theme, 'Uptime')
        panels.append(self.add_panel('system', 'System', [cards['host'], cards['uptime']]))
        panels.append(self.add_panel('sensors', 'Temperature and power',
                                     self.build_sensors(data)))
        if 'sensor.total' in cards:
            keys = (('cost.case', 'Inside the case'), ('cost.monitors', 'Monitors'),
                    ('cost.wall', 'Wall power'), ('cost.rate', 'At this rate'),
                    ('cost.today', 'Today'), ('cost.month', 'This month'))
            for key, label in keys:
                cards[key] = ValueCard(board, theme, label)
            panels.append(self.add_panel('electricity', 'Electricity',
                                         [cards[key] for key, _ in keys]
                                         + [graph('graph.wall', 'Wall power over time')],
                                         'Drives, monitors and the rest are estimates'))

        body = [meter('cpu', 'CPU', f'{len(data["cpu"]["cores"])} logical processors'),
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
            body.append(meter(f'gpu{gpu["index"]}', f'GPU {gpu["index"]}', gpu['name']))
            body.append(meter(f'vram{gpu["index"]}', f'VRAM {gpu["index"]}'))
            if gpu.get('power') is not None:
                body.append(meter(f'power{gpu["index"]}', f'Power {gpu["index"]}'))
            body.append(graph(f'graph.gpu{gpu["index"]}', f'GPU {gpu["index"]} over time'))
        if body:
            panels.append(self.add_panel('gpu', 'GPU', body,
                                         'WSL share is not reported per process'))

        body = []
        for name in data['disks']:
            disk = self.disk_names.get(name)
            label = disk['name'] if disk else name
            description = name.replace('PhysicalDrive', 'Disk ')
            if disk:
                description += f' · {disk["media"]} · {disk["bus"]}'
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
            value(f'sensor.gpu{gpu["index"]}', f'GPU {gpu["index"]}')
        for number in sorted(sensors['nvme']):
            disk = self.disk_names.get(f'PhysicalDrive{int(number)}') or {}
            value(f'sensor.disk{int(number)}', disk.get('name') or f'Disk {int(number)}',
                  f'Disk {int(number)} · NVMe')
        monitor = sensors['monitor']
        if monitor is None:
            value('sensor.monitor', 'CPU and mainboard temperatures',
                  'Windows has no reading without a sensor driver · '
                  'shown here while LibreHardwareMonitor runs')
        else:
            for index, item in enumerate(monitor):
                value(f'sensor.lhm{index}', item['name'], item['hardware'])
        if sensors['cpu_power'] or any(gpu.get('power') for gpu in data['gpus']):
            value('sensor.total', 'CPU and GPUs', 'Power drawn by the parts that report it')
            cards['graph.power'] = GraphCard(board, theme, 'Power over time', HISTORY)
            body.append(cards['graph.power'])
        return body

    def set_sensors(self, data):
        cards, sensors = self.cards, data['sensors']
        cpu = sensors['cpu_power']
        if 'sensor.cpu' in cards:
            parts = [f'{label} {cpu[key]:.1f} W' for key, label in (
                ('cores', 'Cores'), ('graphics', 'Graphics'), ('dram', 'Memory')) if key in cpu]
            cards['sensor.cpu'].set_value(f'{cpu.get("package", 0):.1f} W',
                                          ' · '.join(parts) or 'Intel RAPL energy counter')
        gpu_watts = 0.0
        for gpu in data['gpus']:
            key = f'sensor.gpu{gpu["index"]}'
            parts = [gpu['name']]
            if gpu.get('power') is not None:
                parts.append(f'{gpu["power"]:.0f} W')
                gpu_watts += gpu['power']
            if key in cards:
                cards[key].set_value('' if gpu.get('temp') is None else f'{gpu["temp"]} °C',
                                     ' · '.join(parts))
        for number, temperature in sensors['nvme'].items():
            if f'sensor.disk{int(number)}' in cards:
                cards[f'sensor.disk{int(number)}'].set_value(f'{int(temperature)} °C')
        for index, item in enumerate(sensors['monitor'] or []):
            if f'sensor.lhm{index}' in cards:
                unit = '%.0f °C' if item['type'] == 'Temperature' else '%.0f rpm'
                cards[f'sensor.lhm{index}'].set_value(unit % item['value'])
        if 'sensor.total' in cards:
            cpu_watts = cpu.get('package', 0.0)
            cards['sensor.total'].set_value(f'{cpu_watts + gpu_watts:.0f} W')
            history = self.history
            history['power.cpu'].append(cpu_watts)
            history['power.gpu'].append(gpu_watts)
            values = list(history['power.cpu']) + list(history['power.gpu'])
            ceiling = get_watt_ceiling(max(values + [0]))

            def watts(value):
                return f'{value * ceiling:.0f} W'
            cards['graph.power'].set_series([
                ('CPU', [value / ceiling for value in history['power.cpu']], 'area',
                 f'{cpu_watts:.0f} W', watts),
                ('GPUs', [value / ceiling for value in history['power.gpu']], 'line',
                 f'{gpu_watts:.0f} W', watts)],
                self.get_span(), f'{int(ceiling)} W', self.interval)

    def set_electricity(self, values):
        self.electricity = values

    def get_tariff_time(self):
        try:
            return os.path.getmtime(energy.TARIFF_PATH)
        except OSError:
            return None

    def get_tariff(self):
        # a saved edit to tariffs.json applies without a restart
        changed = self.get_tariff_time()
        if changed != self.tariff_time:
            self.tariff_time = changed
            self.tariffs = energy.load_tariffs()
        plan = self.electricity.get('plan', 'kr_home')
        return self.tariffs.get(plan) or self.tariffs['kr_home']

    def get_drive_watts(self, data):
        sensors = data['sensors']
        watts = 0.0
        for number, states in (sensors.get('nvme_power') or {}).items():
            if not states:
                continue
            # busy reads as the top state; idle as the lowest, where Windows parks an idle
            # drive on its own (APST)
            busy = any(data['disks'].get(f'PhysicalDrive{int(number)}') or (0, 0))
            watts += max(power for power, _ in states) if busy else min(
                power for power, _ in states)
        for number, spinning in (sensors.get('spinning') or {}).items():
            watts += float(self.electricity.get('hdd_watts', 6)) if spinning else HDD_ASLEEP
        return watts

    def get_monitor_watts(self):
        count = wx.Display.GetCount()
        state = self.display.state if self.display else 'on'
        each = float(self.electricity.get('monitor_watts', 25))
        if state == 'off':
            return count * MONITOR_OFF, f'{int(count)} off'
        if state is None:
            return count * each, f'{int(count)}, on state unknown, {each:.0f} W each'
        return count * each, f'{int(count)} {state}, {each:.0f} W each'

    def set_cost(self, data):
        cards = self.cards
        now = time.monotonic()
        seconds = 0 if self.sampled is None else min(now - self.sampled, 60)
        self.sampled = now
        if 'cost.wall' not in cards:
            return
        cpu = data['sensors']['cpu_power'].get('package', 0.0)
        gpus = sum(gpu.get('power') or 0.0 for gpu in data['gpus'])
        drives = self.get_drive_watts(data)
        other = float(self.electricity.get('other_watts', 30))
        efficiency = max(1.0, float(self.electricity.get('psu_efficiency', 90)))
        case = cpu + gpus + drives + other
        monitors, monitor_note = self.get_monitor_watts()
        # monitors draw from the wall themselves, not through the power supply
        wall = case * 100.0 / efficiency + monitors
        self.energy.add(wall, seconds)
        cards['cost.case'].set_value(f'{case:.0f} W', f'CPU {cpu:.0f} · GPUs {gpus:.0f} · '
                                     f'drives {drives:.0f} · rest {other:.0f} W')
        cards['cost.monitors'].set_value(f'{monitors:.0f} W', monitor_note)

        tariff, month = self.get_tariff(), time.localtime().tm_mon
        household = float(self.electricity.get('household_kwh', 250))
        currency = tariff.get('currency', 'KRW')

        def money(value):
            return energy.format_money(value, currency)

        monthly = wall / 1000.0 * 24 * energy.DAYS_PER_MONTH
        month_cost = energy.get_share(monthly, household, tariff, month)
        cards['cost.wall'].set_value(f'{wall:.0f} W', f'The case at {efficiency:.0f}% efficiency, '
                                     'plus the monitors')
        history = self.history['power.wall']
        history.append(wall)
        ceiling = get_watt_ceiling(max(history))

        def watts(value):
            return f'{value * ceiling:.0f} W'
        cards['graph.wall'].set_series([
            ('Wall', [value / ceiling for value in history], 'area', f'{wall:.0f} W', watts)],
            self.get_span(), f'{int(ceiling)} W', self.interval)
        cards['cost.rate'].set_value(money(month_cost / (24 * energy.DAYS_PER_MONTH)) + ' / h',
                                     f'Day {money(month_cost / energy.DAYS_PER_MONTH)} · month '
                                     f'{money(month_cost)} · {tariff.get("name", "")}')
        used_month, used_today = self.energy.get_month(), self.energy.get_today()
        spent = energy.get_share(used_month, household, tariff, month)
        price = spent / used_month if used_month else 0.0
        cards['cost.today'].set_value(money(used_today * price),
                                      f'{used_today:.2f} kWh counted while this app ran')
        digits = 2 if used_month < 10 else 1
        cards['cost.month'].set_value(money(spent),
                                      f'{used_month:.{digits}f} kWh counted while this app ran')

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
        boot = time.strftime('%Y-%m-%d %H:%M', time.localtime(data['boot']))
        cards['uptime'].set_value(format_uptime(seconds), f'Since {boot}')

        cpu = data['cpu']
        cards['cpu'].set_value(cpu['total'] / 100.0,
                               share=wsl and wsl.get('host_cpu', 0) / 100.0)
        cards['cores'].set_values(cpu['cores'])

        memory = data['memory']
        cards['memory'].set_value(
            get_ratio(memory['used'], memory['total']),
            f'{format_bytes(memory["used"])} of {format_bytes(memory["total"])}',
            share=wsl and get_ratio(wsl.get('host_memory', 0), memory['total']))
        swap = data['swap']
        cards['swap'].set_value(get_ratio(swap['used'], swap['total']),
                                f'{format_bytes(swap["used"])} of {format_bytes(swap["total"])}')

        for gpu in data['gpus']:
            index = gpu['index']
            temp = f'{gpu["temp"]}°C' if gpu.get('temp') is not None else ''
            cards[f'gpu{index}'].set_value(gpu['util'] / 100.0, ' · '.join(
                part for part in (gpu['name'], temp) if part))
            cards[f'vram{index}'].set_value(
                get_ratio(gpu['used'], gpu['total']),
                f'{format_bytes(gpu["used"])} of {format_bytes(gpu["total"])}')
            if f'power{index}' in cards:
                cards[f'power{index}'].set_value(get_ratio(gpu['power'], gpu['power_limit']),
                                                 get_power_text(gpu))

        for name, pair in data['disks'].items():
            cards['disk:' + name].set_rates(pair, interval=self.interval)
        addresses = data.get('addresses') or {}
        for name, pair in data['networks'].items():
            cards['net:' + name].set_rates(pair, netinfo.describe(addresses.get(name)),
                                           self.interval)

        if wsl:
            self.set_wsl(wsl, cpu)
        self.set_history(data)
        self.set_sensors(data)
        self.set_cost(data)
        for header in self.headers:
            if header.folded:
                header.Refresh()

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
        return f'{round(seconds / 60)} min' if seconds >= 120 else f'{int(seconds)} s'

    def set_history(self, data):
        history, wsl = self.history, data['wsl']
        memory = data['memory']
        history['cpu'].append(data['cpu']['total'] / 100.0)
        history['cpu.wsl'].append(wsl.get('host_cpu', 0) / 100.0 if wsl else None)
        history['memory'].append(get_ratio(memory['used'], memory['total']))
        history['memory.wsl'].append(get_ratio(wsl.get('host_memory', 0), memory['total'])
                                     if wsl else None)
        for gpu in data['gpus']:
            history[f'gpu{gpu["index"]}'].append(gpu['util'] / 100.0)
            history[f'vram{gpu["index"]}'].append(get_ratio(gpu['used'], gpu['total']))

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
            scale = get_rate_scale(max(incoming + outgoing + [0]))
            ceiling = scale[0]

            def rate(value, ceiling=ceiling, scale=scale):
                return format_rate(value * ceiling, scale)
            cards['graph.' + key].set_series([
                (names[0], [value / ceiling for value in incoming], 'area',
                 format_rate(incoming[-1], scale), rate),
                (names[1], [value / ceiling for value in outgoing], 'line',
                 format_rate(outgoing[-1], scale), rate)],
                span, format_rate(ceiling, scale), self.interval)
        for key, name in (('cpu', 'CPU'), ('memory', 'Memory')):
            series = [(name, list(history[key]), 'area', format_percent(history[key][-1]))]
            if any(value is not None for value in history[key + '.wsl']):
                series.append(('WSL', list(history[key + '.wsl']), 'line',
                               format_percent(history[key + '.wsl'][-1])))
            cards['graph.' + key].set_series(series, span, interval=self.interval)
        for gpu in data['gpus']:
            index = gpu['index']
            cards[f'graph.gpu{index}'].set_series([
                ('GPU', list(history[f'gpu{index}']), 'area',
                 format_percent(history[f'gpu{index}'][-1])),
                ('VRAM', list(history[f'vram{index}']), 'line',
                 format_percent(history[f'vram{index}'][-1]))], span, interval=self.interval)

    def set_wsl(self, wsl, cpu):
        cards, config = self.cards, wsl['config']
        processors = config.get('processors') or len(cpu['cores'])
        cards['wsl.cpu'].set_value(
            None if wsl.get('cpu') is None else wsl['cpu'] / 100.0,
            f'{int(processors)} of {len(cpu["cores"])} processors · {wsl.get("host_cpu", 0):.1f}% '
            'of the whole PC')
        inside = wsl.get('memory')
        limit = config.get('memory') or (inside or {}).get('total')
        if inside:
            windows = format_bytes(wsl.get('host_memory'))
            cards['wsl.memory'].set_value(
                get_ratio(inside['used'], limit),
                f'{format_bytes(inside["used"])} of {format_bytes(limit)} limit · '
                f'{windows} on Windows')
        else:
            cards['wsl.memory'].set_value(None, f'{format_bytes(wsl.get("host_memory"))} '
                                          'on Windows')
        cards['wsl.disk'].set_rates(wsl.get('disk'), interval=self.interval)
        cards['wsl.network'].set_rates(wsl.get('network'), interval=self.interval)

    def tick(self):
        pass
