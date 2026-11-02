# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import math
import string

import wx

from controls import ActionCard
from controls import CardBase
from controls import ChipGrid
from controls import NumberEntry
from controls import PanelHeader
from controls import draw_button
from controls import draw_row_face
from hovertip import hide_hover_tip
from hovertip import show_hover_tip
from utilities import BUTTON_HEIGHT
from utilities import HEADER_BAND
from utilities import PANEL_MARGIN
from utilities import PANEL_PAD
from utilities import draw_text_in
from utilities import fill_rect
from utilities import get_font
from utilities import get_ink
from utilities import get_text_top


PORT_KEYS = string.digits + ', '
HOST_KEYS = string.ascii_letters + string.digits + '.-_'
TEXT_LIMIT = 400


class BusyCard(ActionCard):
    '''An action card that turns a ring beside its button while the action runs, so a
    restart that takes half a minute does not look stuck.'''

    RING = 14
    GAP = 12
    busy = False
    angle = 0

    def set_busy(self, busy):
        if busy != self.busy:
            self.busy = busy
            self.Refresh()

    def spin(self):
        self.angle = (self.angle + 30) % 360
        self.Refresh()

    def draw_control(self, gc, width, height):
        left = super().draw_control(gc, width, height)
        if not self.busy:
            return left
        radius = self.RING / 2 - 1
        cx, cy = left - self.GAP - self.RING / 2, height / 2
        gc.SetPen(wx.Pen(wx.Colour(self.theme['edge']), 2))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.DrawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
        path = gc.CreatePath()
        start = math.radians(self.angle)
        path.AddArc(cx, cy, radius, start, start + math.radians(100), True)
        gc.SetPen(wx.Pen(wx.Colour(self.theme['accent']), 2))
        gc.StrokePath(path)
        return left - self.GAP - self.RING


class TextCard(NumberEntry, CardBase):
    '''A one-line field the card draws itself, like the slider's number; Enter or a press
    elsewhere commits, Escape keeps the old text.'''

    FIELD_WIDTH = 210
    FIELD_PAD = 8
    FONT_SIZE = 9

    def __init__(self, parent, theme, label, description, on_commit, keys, placeholder=''):
        super().__init__(parent, theme, label, description)
        self.text = ''
        self.keys = keys
        self.on_commit = on_commit
        self.placeholder = placeholder
        self.bind_entry()

    def GetValue(self):
        return self.text

    def SetValue(self, text):
        if self.entry is None and text != self.text:
            self.text = text
            self.Refresh()

    def is_editing(self):
        return self.entry is not None

    def get_control_rect(self, width, height):
        field = min(self.FIELD_WIDTH, max(80, width // 2 - self.PADDING))
        return wx.Rect(width - self.PADDING - field, (height - BUTTON_HEIGHT) // 2, field,
                       BUTTON_HEIGHT)

    def activate(self):
        if self.entry is None:
            self.start_entry(self.text)
            self.select_entry(0, len(self.text))

    def replace_selection(self, text):
        entry = self.entry
        low, high = self.get_selection()
        typed = ''.join(char for char in text if char in self.keys)
        merged = entry['text'][:low] + typed + entry['text'][high:]
        if len(merged) <= TEXT_LIMIT:
            entry['text'] = merged
            low += len(typed)
        self.select_entry(low, low)

    def on_entry_char(self, event):
        key = event.GetUnicodeKey()
        if (self.entry is None or event.ControlDown() or event.AltDown()
                or not key or chr(key) not in self.keys):
            event.Skip()
            return
        self.replace_selection(chr(key))

    def end_entry(self, apply):
        entry, self.entry = self.entry, None
        if entry is None:
            return
        self.entry_timer.Stop()
        if apply and entry['text'] != self.text:
            self.text = entry['text']
            self.on_commit(self.text)
        self.Refresh()

    def draw_control(self, gc, width, height):
        theme = self.theme
        rect = self.get_control_rect(width, height)
        editing = self.entry is not None
        fill_rect(gc, theme['control_hover'] if editing or self.hovered else theme['control'],
                  rect.x, rect.y, rect.width, rect.height, 3)
        if editing:
            fill_rect(gc, theme['accent'], rect.x, rect.bottom, rect.width, 1)
        font = get_font(self.FONT_SIZE)
        inner = wx.Rect(rect.x + self.FIELD_PAD, rect.y, rect.width - self.FIELD_PAD * 2,
                        rect.height)
        top = get_text_top(font, inner.y, inner.height)
        gc.Clip(inner.x - 1, inner.y, inner.width + 2, inner.height)
        if not editing:
            if self.text:
                gc.SetFont(font, wx.Colour(theme['text']))
                gc.DrawText(self.fit_text(gc, self.text, inner.width), inner.x, top)
            elif self.placeholder:
                gc.SetFont(font, wx.Colour(theme['faint']))
                gc.DrawText(self.placeholder, inner.x, top)
        else:
            text = self.entry['text']
            gc.SetFont(font, wx.Colour(theme['text']))
            offsets = gc.GetPartialTextExtents(text) if text else []
            caret = offsets[self.entry['caret'] - 1] if self.entry['caret'] else 0
            # a long line slides left so the caret stays in the field
            origin = inner.x - max(0, caret - inner.width + 2)
            ink_top, ink_bottom = get_ink(font)

            def draw_text():
                gc.SetFont(font, wx.Colour(theme['text']))
                gc.DrawText(text, origin, top)
            self.draw_entry(gc, draw_text, origin, offsets, top + ink_top - 2,
                            top + ink_bottom + 3)
        gc.ResetClip()
        return rect.x


class PortGrid(ChipGrid):
    '''Every port in one wrapping grid, lit where it is open to the network; many ports stay
    readable at a glance, and a tip tells what each one is and does.'''

    def __init__(self, parent, theme, on_toggle):
        super().__init__(parent, theme, [])
        self.on_toggle = on_toggle
        self.ports = []

    def set_ports(self, ports):
        '''ports: dicts of port, label, on, warn and note, in the order to show.'''
        self.ports = list(ports)
        self.set_options([port['label'] for port in self.ports])

    def relayout(self):
        # not yet sized, the grid takes the width of the page, so it opens at its full
        # height instead of growing a moment later
        if self.GetClientSize()[0] <= 0:
            width = self.GetParent().GetClientSize()[0] - PANEL_MARGIN * 2
            if width > 0:
                self.SetMinSize(wx.Size(-1, self.get_height(width)))
            return
        super().relayout()

    def choose(self):
        index = self.hit_test(self.up_position)
        if index < 0 or index != self.down_index:
            return
        port = self.ports[index]
        port['on'] = not port['on']
        self.Refresh()
        self.on_toggle(port['port'], port['on'])

    def on_track(self, event):
        super().on_track(event)
        if 0 <= self.marked < len(self.ports):
            port = self.ports[self.marked]
            show_hover_tip(self, self.theme, [(port['label'], 'dim'), (port['note'], 'text')],
                           self.ClientToScreen(event.GetPosition()))
        else:
            hide_hover_tip(self)

    def on_leave(self, event):
        super().on_leave(event)
        hide_hover_tip(self)

    def draw(self, gc, width, height):
        draw_row_face(gc, self.theme, width, height, self.first, self.last)
        for index, port in enumerate(self.ports):
            if port['on']:
                state = 'lit'
            elif self.pressed and index == self.down_index and index == self.marked:
                state = 'down'
            elif index == self.marked:
                state = 'hover'
            else:
                state = 'plain'
            draw_button(gc, self.theme, self.get_chip_rect(index, width), port['label'], state,
                        'warn' if port['warn'] else None)


class HelpHeader(PanelHeader):
    '''A panel header with a ? at its right end that tells in a tip what the panel is for.'''

    MARK = 14

    # Panel hands its toggle over as on_toggle, while a press calls on_click
    on_toggle = None

    def __init__(self, parent, theme, title, subtitle, help_text):
        super().__init__(parent, theme, title, subtitle, self.toggle)
        self.help_text = help_text

    def toggle(self):
        if self.on_toggle:
            self.on_toggle()

    def get_mark_rect(self):
        width = self.GetClientSize()[0]
        return wx.Rect(width - PANEL_PAD - self.MARK, (HEADER_BAND - self.MARK) // 2,
                       self.MARK, self.MARK)

    def update_tip(self, point=None):
        point = point or wx.GetMousePosition()
        mark = self.get_mark_rect().Inflate(4, 4)
        if mark.Contains(self.ScreenToClient(point)):
            show_hover_tip(self, self.theme, [(self.title.title(), 'dim'),
                                              (self.help_text, 'text')], point)
            return
        super().update_tip(point)

    def draw(self, gc, width, height):
        super().draw(gc, width, height)
        rect = self.get_mark_rect()
        gc.SetPen(wx.Pen(wx.Colour(self.theme['dim']), 1))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.DrawEllipse(rect.x + 0.5, rect.y + 0.5, rect.width - 1, rect.height - 1)
        draw_text_in(gc, '?', rect, get_font(8, True), self.theme['dim'],
                     back=self.theme['band'])
