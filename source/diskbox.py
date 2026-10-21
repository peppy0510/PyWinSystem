# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import threading
import wx

import disks

from controls import ActionCard
from controls import Panel
from controls import ScrollArea
from meters import ReadoutCard
from meters import format_bytes
from utilities import call_painted
from utilities import get_font
from utilities import get_text_width

READ_NOTE = 'Asks Windows for the disk list; a sleeping drive may wake'


class DiskCard(ReadoutCard):

    def __init__(self, parent, theme, disk):
        name = disk['name'] or 'Disk %d' % disk['number']
        description = 'Disk %d · %s · %s · %s' % (disk['number'], disk['media'], disk['bus'],
                                                  format_bytes(disk['size']))
        super().__init__(parent, theme, name, description)
        self.health = disk['health']

    def draw_control(self, gc, width, height):
        right = width - self.PADDING
        text = self.health or 'Pooled'
        font = get_font(9.5, bold=True)
        ink = self.theme['warn'] if self.health not in ('Healthy', None) else self.theme['text']
        gc.SetFont(font, wx.Colour(ink))
        text_width = get_text_width(font, text)
        gc.DrawText(text, right - text_width, (height - gc.GetTextExtent(text)[1]) / 2)
        return right - text_width


class DiskBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None, on_disks=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.on_disks = on_disks
        self.reading = False
        self.refresh = ActionCard(self.content, theme, 'Disk list', READ_NOTE, 'Read again',
                                  self.read)
        self.refresh.set_captions('Reading')
        self.build([])
        self.read()

    def read(self):
        if self.reading:
            return
        self.reading = True
        self.refresh.set_caption('Reading')

        def work():
            try:
                found = disks.list_disks()
            except Exception:
                found = None
            call_painted(self, self.set_disks, found)
        threading.Thread(target=work, daemon=True).start()

    def set_disks(self, found):
        if not self:
            return
        self.reading = False
        self.refresh.set_caption('Read again')
        if found is None:
            self.refresh.set_description('Windows did not answer · ' + READ_NOTE)
            return
        self.refresh.set_description(READ_NOTE)
        self.build(found)
        if self.on_disks:
            self.on_disks(found)

    def build(self, found):
        for child in list(self.content.GetChildren()):
            if child is not self.refresh:
                child.Destroy()
        # the read card is kept across rebuilds, so free it from the old panel first
        holder = self.refresh.GetContainingSizer()
        if holder is not None:
            holder.Detach(self.refresh)
        board, theme = self.content, self.theme
        panels = []
        physical = [DiskCard(board, theme, disk) for disk in found if disk['media'] != 'Virtual']
        pooled = [DiskCard(board, theme, disk) for disk in found if disk['media'] == 'Virtual']
        if physical:
            panels.append(Panel(board, theme, 'disks.physical', 'Physical disks', physical,
                                self.folds, self.on_fold,
                                subtitle='Health as Windows reports it, not SMART yet'))
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
