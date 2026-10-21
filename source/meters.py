# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import wx

from controls import CardBase
from utilities import fill_rect
from utilities import get_font
from utilities import get_text_width
from utilities import mix

BAR_WIDTH = 150
BAR_HEIGHT = 6
VALUE_WIDTH = 46
VALUE_GAP = 10
HIGH = 0.9

CORE_GAP = 2
CORE_HEIGHT = 22


def format_bytes(value):
    value = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return ('%.0f %s' if unit in ('B', 'KB') else '%.1f %s') % (value, unit)
        value /= 1024


def format_rate(value):
    return format_bytes(value) + '/s'


class ReadoutCard(CardBase):
    # a row that only shows numbers; nothing to press

    def __init__(self, parent, theme, label, description=''):
        super().__init__(parent, theme, label, description)
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))

    def set_text(self, label=None, description=None):
        changed = False
        if label is not None and label != self.label:
            self.label = label
            changed = True
        if description is not None and description != self.description:
            self.description = description
            changed = True
        return changed

    def get_hit(self):
        return wx.Rect()


class MeterCard(ReadoutCard):

    value = None
    share = None

    def set_value(self, value, description=None, share=None):
        # share marks the part of the bar that belongs to WSL
        changed = self.set_text(description=description)
        if value != self.value or share != self.share:
            self.value, self.share = value, share
            changed = True
        if changed:
            self.Refresh()

    def draw_control(self, gc, width, height):
        theme = self.theme
        right = width - self.PADDING
        value = None if self.value is None else max(0.0, min(1.0, self.value))
        high = value is not None and value >= HIGH
        ink = theme['warn'] if high else theme['text']
        font = get_font(10, bold=True)
        text = '—' if value is None else '%d%%' % round(value * 100)
        gc.SetFont(font, wx.Colour(ink))
        gc.DrawText(text, right - get_text_width(font, text), (height - gc.GetTextExtent(text)[1]) / 2)

        bar_right = right - VALUE_WIDTH - VALUE_GAP
        bar_width = min(BAR_WIDTH, max(40, bar_right - self.PADDING - 120))
        left = bar_right - bar_width
        top = (height - BAR_HEIGHT) / 2
        fill_rect(gc, theme['track'], left, top, bar_width, BAR_HEIGHT, BAR_HEIGHT / 2)
        if value:
            fill_rect(gc, theme['warn'] if high else theme['accent'], left, top,
                      max(BAR_HEIGHT, bar_width * value), BAR_HEIGHT, BAR_HEIGHT / 2)
        if value and self.share:
            share = max(0.0, min(value, self.share))
            fill_rect(gc, mix(theme['accent'], theme['text'], 0.55), left, top,
                      max(BAR_HEIGHT, bar_width * share), BAR_HEIGHT, BAR_HEIGHT / 2)
        return left


class RateCard(ReadoutCard):

    text = ''

    def set_rates(self, text, description=None):
        changed = self.set_text(description=description)
        if text != self.text:
            self.text = text
            changed = True
        if changed:
            self.Refresh()

    def draw_control(self, gc, width, height):
        font = get_font(9.5, bold=True)
        right = width - self.PADDING
        text_width = get_text_width(font, self.text)
        gc.SetFont(font, wx.Colour(self.theme['text']))
        gc.DrawText(self.text, right - text_width, (height - gc.GetTextExtent(self.text)[1]) / 2)
        return right - text_width


class CoreCard(ReadoutCard):
    # one small column per logical processor

    def __init__(self, parent, theme, label, description=''):
        super().__init__(parent, theme, label, description)
        self.values = []

    def set_values(self, values):
        values = [round(value) for value in values]
        if values != self.values:
            self.values = values
            self.Refresh()

    def draw_control(self, gc, width, height):
        theme = self.theme
        count = len(self.values)
        right = width - self.PADDING
        if not count:
            return right
        column = max(3, min(8, (right - self.PADDING - 140) // count - CORE_GAP))
        left = right - count * (column + CORE_GAP) + CORE_GAP
        top = (height - CORE_HEIGHT) / 2
        for index, value in enumerate(self.values):
            x = left + index * (column + CORE_GAP)
            fill_rect(gc, theme['track'], x, top, column, CORE_HEIGHT, 1)
            level = CORE_HEIGHT * max(0, min(100, value)) / 100.0
            if level >= 1:
                colour = theme['warn'] if value >= HIGH * 100 else theme['accent']
                fill_rect(gc, colour, x, top + CORE_HEIGHT - level, column, level, 1)
        return left
