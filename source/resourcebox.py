# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


from controls import Panel
from controls import ScrollArea
from meters import CoreCard
from meters import MeterCard
from meters import RateCard
from meters import format_bytes
from meters import format_rate


def get_ratio(used, total):
    return used / float(total) if total else None


def get_io_text(pair, first='R', second='W'):
    if not pair:
        return '—'
    return '%s %s   %s %s' % (first, format_rate(pair[0]), second, format_rate(pair[1]))


class ResourceBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.layout_key = None
        self.cards = {}
        self.disk_names = {}
        self.apply_theme(theme)

    def set_disk_names(self, disks):
        self.disk_names = {'PhysicalDrive%d' % disk['number']: disk for disk in disks}
        self.layout_key = None

    def get_layout_key(self, data):
        return (len(data['gpus']), tuple(data['disks']), tuple(data['networks']),
                data['wsl'] is not None, tuple(sorted(self.disk_names)))

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

        def rate(key, label, description=''):
            cards[key] = RateCard(board, theme, label, description)
            return cards[key]

        body = [meter('cpu', 'CPU', '%d logical processors' % len(data['cpu']['cores']))]
        cards['cores'] = CoreCard(board, theme, 'Per processor')
        body.append(cards['cores'])
        if wsl:
            body.append(meter('wsl.cpu', 'WSL'))
        panels.append(self.add_panel('cpu', 'CPU', body))

        body = [meter('memory', 'Memory'), meter('swap', 'Page file')]
        if wsl:
            body.append(meter('wsl.memory', 'WSL'))
        panels.append(self.add_panel('memory', 'Memory', body))

        body = []
        for gpu in data['gpus']:
            body.append(meter('gpu%d' % gpu['index'], 'GPU %d' % gpu['index'], gpu['name']))
            body.append(meter('vram%d' % gpu['index'], 'VRAM %d' % gpu['index']))
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
        panels.append(self.add_panel('disk', 'Disk I/O', body))

        body = [rate('net:' + name, name) for name in data['networks']]
        if wsl:
            mirrored = wsl['config'].get('networking') == 'mirrored'
            body.append(rate('wsl.network', 'WSL', 'Part of the adapters above'
                             if mirrored else 'Through the WSL virtual adapter'))
        panels.append(self.add_panel('network', 'Network', body))

        self.set_panels(panels)
        self.bind_children()
        self.apply_theme(theme)
        self.relayout_panels()

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

        for name, pair in data['disks'].items():
            cards['disk:' + name].set_rates(get_io_text(pair))
        for name, pair in data['networks'].items():
            cards['net:' + name].set_rates(get_io_text(pair, '↓', '↑'))

        if wsl:
            self.set_wsl(wsl, cpu)

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
        cards['wsl.disk'].set_rates(get_io_text(wsl.get('disk')))
        cards['wsl.network'].set_rates(get_io_text(wsl.get('network'), '↓', '↑'))

    def tick(self):
        pass
