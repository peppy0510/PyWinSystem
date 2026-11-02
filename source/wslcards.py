# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import string

import wx

from controls import CardBase
from controls import NumberEntry
from utilities import BUTTON_HEIGHT
from utilities import fill_rect
from utilities import get_font
from utilities import get_ink
from utilities import get_text_top


PORT_KEYS = string.digits + ', '
HOST_KEYS = string.ascii_letters + string.digits + '.-_'
TEXT_LIMIT = 400


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
