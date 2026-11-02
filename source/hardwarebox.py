# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import threading
import wx

import benchmarks
import cpuinfo
import hardware
import monitors

from controls import CardBase
from controls import Panel
from controls import ScrollArea
from controls import draw_button
from controls import get_button_width
from controls import get_pen
from hovertip import show_hover_tip
from meters import ValueCard
from meters import format_bytes
from utilities import BUTTON_GAP
from utilities import BUTTON_HEIGHT
from utilities import call_painted
from utilities import draw_text_in
from utilities import get_font


CHANNEL_NAMES = {1: 'Single channel', 2: 'Dual channel', 3: 'Triple channel',
                 4: 'Quad channel', 6: 'Hexa channel', 8: 'Octa channel'}

# socket outlines in a 30 x 10 box; the shape tells DisplayPort from HDMI at a glance
PORT_WIDTH = 30
PORT_HEIGHT = 10
PORT_GAP = 12


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


def get_port_outline(output, x, y):
    w, h, cut = PORT_WIDTH, PORT_HEIGHT, 3
    if output == 'DisplayPort':
        # one corner clipped, as on the plug
        return [(x, y), (x + w, y), (x + w, y + h - cut), (x + w - cut, y + h), (x, y + h)]
    if output == 'HDMI':
        return [(x, y), (x + w, y), (x + w, y + h - cut), (x + w - cut, y + h),
                (x + cut, y + h), (x, y + h - cut)]
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


class SocketRow(CardBase):
    '''The display sockets of one graphics card in driver order; a used one is filled and
    names its display in a tip.'''

    HEIGHT = 60

    def __init__(self, parent, theme, ports, owners, chained=()):
        description = 'Filled in use, outlined free; driver order, not the bracket'
        # the socket a chain hangs from cannot be told, so each chained display gets a socket
        # of its own after the real ones
        if chained:
            description = f'MST: chained from one of the sockets · {description}'
        super().__init__(parent, theme, 'Sockets', description)
        self.ports = list(ports) + [
            {'card': monitor.get('card'), 'output': 'DisplayPort', 'connector': None,
             'used': True, 'monitor': monitor, 'name': f'MST {index + 1}'}
            for index, monitor in enumerate(chained)]
        self.owners = owners
        self.port_rects = []
        self.SetMinSize(wx.Size(-1, self.HEIGHT))

    def get_owner(self, port):
        return port.get('monitor') or self.owners.get(
            (port['card'], port['output'], port['connector']))

    @staticmethod
    def get_name(port):
        return port.get('name') or monitors.get_port_name(port['output'], port['connector'])

    def update_label_tip(self, point=None):
        point = point or wx.GetMousePosition()
        position = self.ScreenToClient(point)
        for rect, port in self.port_rects:
            if rect.Contains(position):
                owner = self.get_owner(port)
                if owner:
                    text = f'{owner["label"]}  {monitors.describe(owner)}'
                else:
                    text = 'In use' if port['used'] else 'Free'
                show_hover_tip(self, self.theme, [(self.get_name(port), 'dim'), (text, 'text')],
                               point)
                return
        super().update_label_tip(point)

    def draw_control(self, gc, width, height):
        theme = self.theme
        count = len(self.ports)
        left = width - self.PADDING - count * PORT_WIDTH - (count - 1) * PORT_GAP
        top = (height - PORT_HEIGHT) / 2 - 5
        self.port_rects = []
        for index, port in enumerate(self.ports):
            x = left + index * (PORT_WIDTH + PORT_GAP)
            # quiet like the rest of the page: a plugged socket is filled grey, not lit
            if port['used']:
                fill, edge, ink = theme['control'], theme['dim'], theme['dim']
            else:
                fill, edge, ink = None, theme['edge'], theme['faint']
            path = gc.CreatePath()
            points = get_port_outline(port['output'], x + 0.5, top + 0.5)
            path.MoveToPoint(*points[0])
            for point in points[1:]:
                path.AddLineToPoint(*point)
            path.CloseSubpath()
            if fill:
                gc.SetBrush(wx.Brush(wx.Colour(fill)))
                gc.FillPath(path)
            gc.SetPen(get_pen(gc, edge))
            gc.StrokePath(path)
            rect = wx.Rect(int(x - PORT_GAP / 2), int(top + PORT_HEIGHT + 4),
                           PORT_WIDTH + PORT_GAP, 14)
            draw_text_in(gc, self.get_name(port), rect, get_font(8), ink, back=theme['face'])
            self.port_rects.append((wx.Rect(int(x - PORT_GAP / 2), int(top - 4),
                                            PORT_WIDTH + PORT_GAP, PORT_HEIGHT + 22), port))
        return left - PORT_GAP / 2


def get_card_ports(found):
    # sockets per graphics card name, in the order the cards are listed; the display config
    # names a card only through the displays on it, so a card with none has no sockets here
    cards = {}
    for monitor in found.get('monitors', []):
        if monitor.get('ports'):
            cards.setdefault(monitor['adapter'], {})[monitor['card']] = monitor['ports']
    return {name: list(ports.values()) for name, ports in cards.items()}


class LinkCard(CardBase):
    '''A row with a button per page to open in the browser.'''

    def __init__(self, parent, theme, label, description, links):
        super().__init__(parent, theme, label, description)
        self.links = links
        self.rects = []

    def hits(self, position):
        return any(rect.Contains(position) for rect, _ in self.rects)

    def activate(self):
        for rect, url in self.rects:
            if rect.Contains(self.up_position):
                benchmarks.open_page(url)
                return

    def on_track(self, event):
        super().on_track(event)
        # the light follows the button under the pointer, not the row
        self.Refresh()

    def draw_control(self, gc, width, height):
        right = width - self.PADDING
        mouse = self.ScreenToClient(wx.GetMousePosition())
        rects = []
        for caption, url in reversed(self.links):
            button = get_button_width(caption)
            rect = wx.Rect(right - button, (height - BUTTON_HEIGHT) // 2, button, BUTTON_HEIGHT)
            over = self.hovered and rect.Contains(mouse)
            draw_button(gc, self.theme, rect, caption,
                        'down' if over and self.pressed else 'hover' if over else 'plain')
            rects.insert(0, (rect, url))
            right = rect.x - BUTTON_GAP
        self.rects = rects
        return right


class HardwareBox(ScrollArea):

    clock_card = None
    base_mhz = None

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

    def get_cpu_rows(self, details, cpu):
        board, theme = self.content, self.theme
        rows = []
        kinds = details.get('kinds', [])
        names = ('P-cores', 'E-cores') if len(kinds) == 2 else ('Cores',)
        for name, kind in zip(names, kinds):
            rows.append(ValueCard(board, theme, name, cpuinfo.describe_kind(kind),
                                  f'{kind["cores"]} · {kind["threads"]} threads'))
        if details.get('l3'):
            rows.append(ValueCard(board, theme, 'L3 cache', 'Shared by every core',
                                  cpuinfo.format_size(details['l3'])))

        self.base_mhz = cpu.get('mhz')
        base = f'base {self.base_mhz / 1000.0:.1f} GHz' if self.base_mhz else ''
        self.clock_card = ValueCard(board, theme, 'Clock', join('Reading', base), '…')
        rows.append(self.clock_card)

        identity = details.get('identity') or {}
        if identity.get('model'):
            microcode = identity.get('microcode')
            rows.append(ValueCard(board, theme, 'Model', identity['model'],
                                  f'microcode 0x{microcode:X}' if microcode else ''))
        if details.get('features'):
            rows.append(ValueCard(board, theme, 'Instructions',
                                  ' · '.join(details['features']), ''))
        if cpu.get('name'):
            rows.append(LinkCard(board, theme, 'Benchmarks',
                                 'Look this processor up in the browser',
                                 benchmarks.get_cpu_links(cpu['name'])))
        return rows

    def set_clock(self, clock):
        # the rated turbo cannot be read under Hyper-V, so the range is what was seen
        if not self or not self.clock_card or not clock:
            return
        self.clock_card.set_value(
            f'{clock["now"] / 1000.0:.2f} GHz',
            join(f'{clock["low"] / 1000.0:.2f}–{clock["high"] / 1000.0:.2f} GHz since the app '
                 'started', f'base {clock["base"] / 1000.0:.1f} GHz'))

    def add_panel(self, key, title, body, subtitle=''):
        return Panel(self.content, self.theme, 'hardware.' + key, title, body, self.folds,
                     self.on_fold, subtitle=subtitle)

    def build(self, found):
        if not self or not found:
            return
        board, theme = self.content, self.theme
        panels = []
        cpu = found['cpu']
        details = found.get('cpu_details') or {}
        clock = f'{cpu["mhz"] / 1000.0:.1f} GHz base' if cpu.get('mhz') else ''
        counts = cpuinfo.describe_kinds(details.get('kinds', []), cpu['threads']) or [
            f'{cpu["cores"]} cores', f'{cpu["threads"]} threads']
        body = [ValueCard(board, theme, cpu['name'] or 'Processor', join(*counts, clock))]
        body += self.get_cpu_rows(details, cpu)
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
        body = []
        channels = hardware.read_channels(modules)
        if channels:
            name = CHANNEL_NAMES.get(channels['count'], f'{channels["count"]}-channel')
            speed = f'{channels["speed"]} MT/s'
            if channels['rated'] and channels['rated'] != channels['speed']:
                speed += f' of {channels["rated"]} rated'
            body.append(ValueCard(board, theme, name, join(
                f'{channels["modules"]} modules in {channels["count"]} channels', speed,
                'peak = MT/s × 8 bytes × channels'),
                f'{channels["bandwidth"] / 10 ** 9:.1f} GB/s'))
        controllers = {channel[0] for channel in map(hardware.get_channel, modules) if channel}
        for module in modules:
            label = module['slot'] or 'Module'
            channel = hardware.get_channel(module)
            if channel:
                owner = f'P{channel[0]} ' if len(controllers) > 1 else ''
                label = f'{owner}Channel {channel[1]} · {label}'
            body.append(ValueCard(board, theme, label, describe_module(module),
                                  format_bytes(module['size'])))
        panels.append(self.add_panel('memory', 'Memory', body, join(
            format_bytes(found['total']), f'{len(modules)} modules' if modules else '')))

        displays = found.get('monitors', [])
        owners = {(monitor.get('card'), monitor.get('output'), monitor.get('connector')): monitor
                  for monitor in displays}
        card_ports = get_card_ports(found)
        body = []
        for gpu in found['gpus']:
            body.append(ValueCard(board, theme, gpu['name'] or 'Display adapter',
                                  join(gpu.get('pcie'), 'driver ' + gpu['driver']
                                       if gpu.get('driver') else ''),
                                  format_bytes(gpu['vram']) if gpu.get('vram') else ''))
            # a virtual adapter has no memory of its own and no benchmark either
            if gpu.get('vram') and gpu.get('name'):
                body.append(LinkCard(board, theme, 'Benchmarks',
                                     'Look this card up in the browser',
                                     benchmarks.get_gpu_links(gpu['name'])))
            # two cards of one model take their socket lists in turn
            same = card_ports.get(gpu['name']) or []
            if same:
                ports = same.pop(0)
                chained = [monitor for monitor in displays if monitor.get('chained')
                           and ports and monitor.get('card') == ports[0]['card']]
                body.append(SocketRow(board, theme, ports, owners, chained))
        panels.append(self.add_panel('gpu', 'Graphics', body))
        # each display, with its controls, is on the Monitors page

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
