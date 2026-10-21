# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import wx

from controls import CardBase
from controls import draw_row_face
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


def get_ceiling(value):
    # a round top for a rate axis: 1, 2 or 5 times a power of ten, in KB, MB or GB
    value = max(float(value or 0), 1024.0)
    unit = 1024.0
    while value > unit * 500:
        unit *= 1024
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500):
        if value <= unit * step:
            return unit * step
    return value


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


GRAPH_HEIGHT = 112
GRAPH_TOP = 30
GRAPH_BOTTOM = 10
LEGEND_GAP = 14
LEGEND_SWATCH = 12


class GraphCard(ReadoutCard):
    # load over time, newest on the right; an area and an optional line

    def __init__(self, parent, theme, label, capacity):
        super().__init__(parent, theme, label)
        self.SetMinSize(wx.Size(-1, GRAPH_HEIGHT))
        self.capacity = capacity
        self.series = []
        self.span = ''
        self.scale = ''

    def set_series(self, series, span, scale=''):
        # series: [(name, values, 'area' or 'line')], values 0..1 or None for a gap;
        # scale names the top line when the values are not percentages
        self.series = series
        self.span = span
        self.scale = scale
        self.Refresh()

    def get_colour(self, kind):
        theme = self.theme
        return theme['accent'] if kind == 'area' else mix(theme['accent'], theme['text'], 0.55)

    def draw(self, gc, width, height):
        theme = self.theme
        draw_row_face(gc, theme, width, height, self.first, self.last)
        font = get_font(9)
        gc.SetFont(font, wx.Colour(theme['text']))
        gc.DrawText(self.label, self.PADDING, 9)

        right = width - self.PADDING
        gc.SetFont(get_font(8), wx.Colour(theme['dim']))
        span_width = get_text_width(get_font(8), self.span)
        gc.DrawText(self.span, right - span_width, 10)
        x = right - span_width - LEGEND_GAP
        for name, _, kind in reversed(self.series):
            text_width = get_text_width(get_font(8), name)
            x -= text_width
            gc.DrawText(name, x, 10)
            x -= 5 + LEGEND_SWATCH
            if kind == 'area':
                fill_rect(gc, self.get_colour(kind), x, 13, LEGEND_SWATCH, 7, 1)
            else:
                fill_rect(gc, self.get_colour(kind), x, 16, LEGEND_SWATCH, 2)
            x -= LEGEND_GAP

        left, top = self.PADDING, GRAPH_TOP
        plot_width, plot_height = right - left, height - GRAPH_TOP - GRAPH_BOTTOM
        for level in (0.0, 0.5, 1.0):
            fill_rect(gc, theme['rim'], left, top + plot_height * (1 - level), plot_width, 1)
        if self.scale:
            gc.SetFont(get_font(7.5), wx.Colour(theme['dim']))
            gc.DrawText(self.scale, left + 2, top + 2)
        step = plot_width / float(max(1, self.capacity - 1))
        for _, values, kind in self.series:
            self.draw_values(gc, values, kind, left, top, plot_width, plot_height, step)

    def draw_values(self, gc, values, kind, left, top, plot_width, plot_height, step):
        start = left + plot_width - step * (len(values) - 1)
        runs, run = [], []
        for index, value in enumerate(values):
            if value is None:
                if run:
                    runs.append(run)
                run = []
                continue
            run.append((start + step * index,
                        top + plot_height * (1 - max(0.0, min(1.0, value)))))
        if run:
            runs.append(run)
        colour = wx.Colour(self.get_colour(kind))
        for run in runs:
            path = gc.CreatePath()
            path.MoveToPoint(*run[0])
            for point in run[1:]:
                path.AddLineToPoint(*point)
            if kind == 'area':
                area = gc.CreatePath()
                area.MoveToPoint(run[0][0], top + plot_height)
                for point in run:
                    area.AddLineToPoint(*point)
                area.AddLineToPoint(run[-1][0], top + plot_height)
                area.CloseSubpath()
                gc.SetPen(wx.TRANSPARENT_PEN)
                gc.SetBrush(wx.Brush(wx.Colour(colour.Red(), colour.Green(), colour.Blue(), 70)))
                gc.FillPath(area)
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(colour).Width(1.5)))
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            gc.StrokePath(path)
