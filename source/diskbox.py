# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os
import threading
import wx

import disks
import smart
import winuac

from controls import ActionCard
from controls import Panel
from controls import ScrollArea
from meters import VALUE_FONT
from meters import BUSY_DELAY
from meters import ReadoutCard
from meters import ValueCard
from meters import format_bytes
from utilities import call_painted
from utilities import get_font
from utilities import get_text_width

READ_NOTE = 'Asks Windows for the disk list; a sleeping drive may wake'
SLEEP_NOTE = 'Asleep, so it is not read · reading spins it up'


def format_count(value):
    return f'{value or 0:,}'


class DiskCard(ReadoutCard):

    def __init__(self, parent, theme, disk):
        name = disk['name'] or f'Disk {disk["number"]}'
        description = (f'Disk {disk["number"]} · {disk["media"]} · {disk["bus"]} · '
                       f'{format_bytes(disk["size"])}')
        super().__init__(parent, theme, name, description)
        self.health = disk['health']

    def draw_control(self, gc, width, height):
        right = width - self.PADDING
        text = self.health or 'Pooled'
        font = get_font(VALUE_FONT, bold=True)
        ink = self.theme['warn'] if self.health not in ('Healthy', None) else self.theme['text']
        gc.SetFont(font, wx.Colour(ink))
        text_width = get_text_width(font, text)
        gc.DrawText(text, right - text_width, (height - gc.GetTextExtent(text)[1]) / 2)
        return right - text_width


class DiskBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None, on_disks=None, on_quit=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.on_disks = on_disks
        self.on_quit = on_quit
        self.reading = False
        self.found = []
        self.healths = {}
        self.refresh = ActionCard(self.content, theme, 'Disk list', READ_NOTE, 'Read again',
                                  self.read)
        self.refresh.set_captions('Reading')
        self.build()
        self.read()

    def read(self, wake=None):
        if self.reading:
            return
        self.reading = True
        wx.CallLater(BUSY_DELAY, self.show_busy)

        def work():
            try:
                found = disks.list_disks()
            except Exception:
                found = None
            healths = {}
            for disk in found or []:
                if disk['media'] == 'Virtual':
                    continue
                try:
                    if disk['number'] == wake:
                        health = smart.read_ata(disk['number']) or {'kind': 'locked'}
                    else:
                        health = smart.read_health(disk['number'], disk['media'])
                except Exception:
                    health = None
                healths[disk['number']] = health
            call_painted(self, self.set_disks, found, healths)
        threading.Thread(target=work, daemon=True).start()

    def show_busy(self):
        if self and self.reading:
            self.refresh.set_caption('Reading')

    def set_disks(self, found, healths):
        if not self:
            return
        self.reading = False
        self.refresh.set_caption('Read again')
        if found is None:
            self.refresh.set_description('Windows did not answer · ' + READ_NOTE)
            return
        self.refresh.set_description(READ_NOTE)
        self.found, self.healths = found, healths
        self.build()
        if self.on_disks:
            self.on_disks(found)

    def get_rows(self, disk, health):
        board, theme = self.content, self.theme
        rows = [DiskCard(board, theme, disk)]
        kind = (health or {}).get('kind')

        def value(label, text, description='', warn=False):
            rows.append(ValueCard(board, theme, label, description, text, warn))

        if kind == 'sleeping':
            rows.append(ActionCard(board, theme, 'Power state', SLEEP_NOTE, 'Read anyway',
                                   lambda: self.read(disk['number'])))
        elif kind == 'locked':
            rows.append(ActionCard(board, theme, 'SMART', 'Needs administrator rights',
                                   'Run as administrator', self.elevate))
        elif kind == 'nvme':
            value('Temperature', f'{health["temperature"]} °C',
                  f'Above the warning level for {format_count(health["warning_minutes"])} min, '
                  f'critical for {format_count(health["critical_minutes"])} min')
            value('Life used', f'{health["used"]}%',
                  f'Spare {health["spare"]}%, warns below {health["spare_threshold"]}%',
                  health['used'] >= 90)
            value('Power-on time', f'{format_count(health["hours"])} h',
                  f'{format_count(health["hours"] // 24)} days · '
                  f'{format_count(health["power_cycles"])} power cycles')
            value('Written', format_bytes(health['written']),
                  f'Read {format_bytes(health["read"])}')
            value('Unsafe shutdowns', format_count(health['unsafe_shutdowns']))
            value('Media errors', format_count(health['media_errors']),
                  f'Error log entries {format_count(health["error_entries"])}',
                  health['media_errors'] > 0)
            if health['warning']:
                value('Critical warning', f'0x{health["warning"]:02X}',
                      'The drive reports a problem', True)
        elif kind == 'ata':
            if health.get('temperature') is not None:
                value('Temperature', f'{health["temperature"]} °C')
            if health.get('hours') is not None:
                value('Power-on time', f'{format_count(health["hours"])} h',
                      f'{format_count(health["hours"] // 24)} days · '
                      f'{format_count(health["power_cycles"])} power cycles')
            for item in health['attributes']:
                if item['id'] in (9, 12, 190, 194):
                    continue
                value(item['name'], format_count(item['raw']),
                      f'ID {item["id"]} · value {item["current"]}, worst {item["worst"]}',
                      item['warning'])
        return rows

    def elevate(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.pyw')
        if winuac.relaunch_as_admin(script, os.getpid()) and self.on_quit:
            self.on_quit()

    def build(self):
        for child in list(self.content.GetChildren()):
            if child is not self.refresh:
                child.Destroy()
        # the read card is kept across rebuilds, so free it from the old panel first
        holder = self.refresh.GetContainingSizer()
        if holder is not None:
            holder.Detach(self.refresh)
        board, theme = self.content, self.theme
        panels = []
        for disk in self.found:
            if disk['media'] == 'Virtual':
                continue
            rows = self.get_rows(disk, self.healths.get(disk['number']))
            panels.append(Panel(board, theme, f'disks.{disk["number"]}',
                                f'Disk {disk["number"]}', rows, self.folds, self.on_fold,
                                subtitle=disk['media']))
        pooled = [DiskCard(board, theme, disk) for disk in self.found
                  if disk['media'] == 'Virtual']
        if pooled:
            panels.append(Panel(board, theme, 'disks.spaces', 'Storage Spaces', pooled,
                                self.folds, self.on_fold))
        panels.append(Panel(board, theme, 'disks.read', 'Read', (self.refresh,), self.folds,
                            self.on_fold))
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
