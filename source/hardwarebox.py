# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import threading

import hardware

from controls import Panel
from controls import ScrollArea
from meters import ValueCard
from meters import format_bytes
from utilities import call_painted


def join(*parts):
    return ' · '.join(str(part) for part in parts if part)


def format_speed(bits):
    if not bits:
        return ''
    for unit, size in (('Gbps', 10 ** 9), ('Mbps', 10 ** 6), ('Kbps', 10 ** 3)):
        if bits >= size:
            return (f'{round(bits / float(size), 1):g} {unit}')
    return f'{int(bits)} bps'


def describe_module(module):
    speed = f'{int(module["configured"])} MT/s' if module.get('configured') else ''
    return join(module['maker'], module['part'], module['type'], speed)


class HardwareBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.apply_theme(theme)

        def work():
            try:
                found = hardware.read_hardware()
            except Exception:
                found = None
            call_painted(self, self.build, found)
        threading.Thread(target=work, daemon=True).start()

    def add_panel(self, key, title, body, subtitle=''):
        return Panel(self.content, self.theme, 'hardware.' + key, title, body, self.folds,
                     self.on_fold, subtitle=subtitle)

    def build(self, found):
        if not self or not found:
            return
        board, theme = self.content, self.theme
        panels = []
        cpu = found['cpu']
        clock = f'{cpu["mhz"] / 1000.0:.1f} GHz base' if cpu.get('mhz') else ''
        body = [ValueCard(board, theme, cpu['name'] or 'Processor',
                          join(f'{cpu["cores"]} cores', f'{cpu["threads"]} threads', clock))]
        if found.get('board'):
            body.append(ValueCard(board, theme, found['board'], 'Mainboard'))
        bios, firmware = found.get('bios'), found.get('firmware') or {}
        if bios:
            secure = firmware.get('secure_boot')
            if secure is not None:
                secure = f'Secure Boot {"on" if secure else "off"}'
            body.append(ValueCard(board, theme, f'BIOS {bios["version"]}', join(
                bios['maker'], bios['date'], firmware.get('type'), secure)))
        panels.append(self.add_panel('cpu', 'Processor', body))

        modules = found['memory']
        body = [ValueCard(board, theme, module['slot'] or 'Module', describe_module(module),
                          format_bytes(module['size'])) for module in modules]
        panels.append(self.add_panel('memory', 'Memory', body, join(
            format_bytes(found['total']), f'{len(modules)} modules' if modules else '')))

        body = []
        for gpu in found['gpus']:
            body.append(ValueCard(board, theme, gpu['name'] or 'Display adapter',
                                  join(gpu.get('pcie'), 'driver ' + gpu['driver']
                                       if gpu.get('driver') else ''),
                                  format_bytes(gpu['vram']) if gpu.get('vram') else ''))
        panels.append(self.add_panel('gpu', 'Graphics', body))

        body = []
        for nic in found.get('nics', []):
            if nic['virtual']:
                state = 'virtual'
            else:
                state = 'connected' if nic['connected'] else 'not connected'
            body.append(ValueCard(board, theme, nic['device'] or nic['name'],
                                  join(nic['name'], state, nic['driver']),
                                  format_speed(nic['speed']) if nic['connected'] else ''))
        if body:
            panels.append(self.add_panel('network', 'Network adapters', body))

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

    def tick(self):
        pass
