# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import threading
import wx

import hardware
import monitors

from controls import CardBase
from controls import Panel
from controls import ScrollArea
from controls import get_pen
from hovertip import show_hover_tip
from meters import ValueCard
from meters import format_bytes
from utilities import call_painted
from utilities import draw_text_in
from utilities import get_font


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

    def __init__(self, parent, theme, ports, owners):
        super().__init__(parent, theme, 'Sockets',
                         'Filled in use, outlined free; driver order, not the bracket')
        self.ports = ports
        self.owners = owners
        self.port_rects = []
        self.SetMinSize(wx.Size(-1, self.HEIGHT))

    def get_owner(self, port):
        return self.owners.get((port['card'], port['output'], port['connector']))

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
                show_hover_tip(self, self.theme, [
                    (monitors.get_port_name(port['output'], port['connector']), 'dim'),
                    (text, 'text')], point)
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
            if port['used']:
                fill, edge, ink = theme['accent'], theme['accent'], theme['text']
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
            draw_text_in(gc, monitors.get_port_name(port['output'], port['connector']), rect,
                         get_font(8, port['used']), ink, back=theme['face'])
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
            # two cards of one model take their socket lists in turn
            same = card_ports.get(gpu['name']) or []
            if same:
                body.append(SocketRow(board, theme, same.pop(0), owners))
        panels.append(self.add_panel('gpu', 'Graphics', body))

        body = []
        for monitor in displays:
            port = ''
            if monitor.get('output'):
                port = monitors.get_port_name(monitor['output'], monitor['connector'])
            body.append(ValueCard(board, theme, monitor['label'],
                                  join(monitor.get('adapter'), monitors.describe(monitor)), port))
        if body:
            panels.append(self.add_panel('displays', 'Displays', body))

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
