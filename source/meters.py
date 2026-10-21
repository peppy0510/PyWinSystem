# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import collections
import wx

from controls import CardBase
from controls import draw_row_face
from utilities import fill_rect
from utilities import get_font
from utilities import get_text_width
from utilities import mix

BAR_WIDTH = 150
BAR_HEIGHT = 6
VALUE_FONT = 8.5
VALUE_WIDTH = 34
VALUE_GAP = 10
HIGH = 0.9

CORE_GAP = 4
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
    value = max(float(value or 0), 1024.0)
    unit = 1024.0
    while value > unit * 500:
        unit *= 1024
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500):
        if value <= unit * step:
            return unit * step
    return value


def get_series_colour(theme, kind):
    return theme['accent'] if kind == 'area' else mix(theme['accent'], theme['text'], 0.55)


def draw_series(gc, theme, values, kind, rect, capacity, pen=1.5):
    left, top, width, height = rect
    step = width / float(max(1, capacity - 1))
    start = left + width - step * (len(values) - 1)
    runs, run = [], []
    for index, value in enumerate(values):
        if value is None:
            if run:
                runs.append(run)
            run = []
            continue
        run.append((start + step * index, top + height * (1 - max(0.0, min(1.0, value)))))
    if run:
        runs.append(run)
    colour = wx.Colour(get_series_colour(theme, kind))
    for run in runs:
        path = gc.CreatePath()
        path.MoveToPoint(*run[0])
        for point in run[1:]:
            path.AddLineToPoint(*point)
        if kind == 'area':
            area = gc.CreatePath()
            area.MoveToPoint(run[0][0], top + height)
            for point in run:
                area.AddLineToPoint(*point)
            area.AddLineToPoint(run[-1][0], top + height)
            area.CloseSubpath()
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.SetBrush(wx.Brush(wx.Colour(colour.Red(), colour.Green(), colour.Blue(), 70)))
            gc.FillPath(area)
        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(colour).Width(pen)))
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        gc.StrokePath(path)


class ReadoutCard(CardBase):

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


class ValueCard(ReadoutCard):

    def __init__(self, parent, theme, label, description='', value=''):
        super().__init__(parent, theme, label, description)
        self.value = value

    def draw_control(self, gc, width, height):
        right = width - self.PADDING
        if not self.value:
            return right
        font = get_font(VALUE_FONT, bold=True)
        text_width = get_text_width(font, self.value)
        gc.SetFont(font, wx.Colour(self.theme['text']))
        gc.DrawText(self.value, right - text_width, (height - gc.GetTextExtent(self.value)[1]) / 2)
        return right - text_width


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
        font = get_font(VALUE_FONT, bold=True)
        text = '—' if value is None else '%d%%' % round(value * 100)
        gc.SetFont(font, wx.Colour(ink))
        gc.DrawText(text, right - get_text_width(font, text),
                    (height - gc.GetTextExtent(text)[1]) / 2)

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
    # two rates in fixed columns, so changing digits never move the label's room

    NAME_GAP = 5
    PAIR_GAP = 16
    WIDEST = '999.9 MB/s'
    SPARK_WIDTH = 96
    SPARK_HEIGHT = 26
    SPARK_GAP = 14
    LABEL_ROOM = 110

    def __init__(self, parent, theme, label, description='', names=('R', 'W'), capacity=300):
        super().__init__(parent, theme, label, description)
        self.names = names
        self.pair = None
        self.capacity = capacity
        self.history = (collections.deque(maxlen=capacity), collections.deque(maxlen=capacity))

    def set_rates(self, pair, description=None):
        self.set_text(description=description)
        self.pair = pair
        for values, value in zip(self.history, pair or (None, None)):
            values.append(value)
        self.Refresh()

    def draw_spark(self, gc, right, height):
        left = right - self.SPARK_WIDTH
        if left - self.PADDING < self.LABEL_ROOM:
            return right
        top = (height - self.SPARK_HEIGHT) / 2
        fill_rect(gc, self.theme['rim'], left, top + self.SPARK_HEIGHT, self.SPARK_WIDTH, 1)
        peaks = [value for values in self.history for value in values if value]
        ceiling = get_ceiling(max(peaks)) if peaks else 1.0
        for values, kind in zip(self.history, ('area', 'line')):
            draw_series(gc, self.theme, [None if value is None else value / ceiling
                                         for value in values], kind,
                        (left, top, self.SPARK_WIDTH, self.SPARK_HEIGHT), self.capacity, 1.2)
        return left

    def draw_control(self, gc, width, height):
        theme = self.theme
        value_font, name_font = get_font(VALUE_FONT, bold=True), get_font(VALUE_FONT)
        column = get_text_width(value_font, self.WIDEST)
        values = ('—', '—') if self.pair is None else tuple(format_rate(value)
                                                            for value in self.pair)
        x = width - self.PADDING
        for index in (1, 0):
            text = values[index]
            gc.SetFont(value_font, wx.Colour(theme['text']))
            gc.DrawText(text, x - get_text_width(value_font, text),
                        (height - gc.GetTextExtent(text)[1]) / 2)
            x -= column + self.NAME_GAP
            name = self.names[index]
            gc.SetFont(name_font, wx.Colour(theme['dim']))
            x -= get_text_width(name_font, name)
            gc.DrawText(name, x, (height - gc.GetTextExtent(name)[1]) / 2)
            if index:
                x -= self.PAIR_GAP
        return self.draw_spark(gc, x - self.SPARK_GAP, height)


class CoreCard(ReadoutCard):

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
        # the same thickness and round ends as the horizontal meter bars
        column, radius = BAR_HEIGHT, BAR_HEIGHT / 2
        gap = max(1, min(CORE_GAP, (right - self.PADDING - 140) // count - column))
        left = right - count * (column + gap) + gap
        top = (height - CORE_HEIGHT) / 2
        for index, value in enumerate(self.values):
            x = left + index * (column + gap)
            fill_rect(gc, theme['track'], x, top, column, CORE_HEIGHT, radius)
            if value > 0:
                level = max(column, CORE_HEIGHT * min(100, value) / 100.0)
                colour = theme['warn'] if value >= HIGH * 100 else theme['accent']
                fill_rect(gc, colour, x, top + CORE_HEIGHT - level, column, level, radius)
        return left


GRAPH_HEIGHT = 112
GRAPH_TOP = 30
GRAPH_BOTTOM = 10
LEGEND_GAP = 14
LEGEND_SWATCH = 12


class GraphCard(ReadoutCard):

    def __init__(self, parent, theme, label, capacity):
        super().__init__(parent, theme, label)
        self.SetMinSize(wx.Size(-1, GRAPH_HEIGHT))
        self.capacity = capacity
        self.series = []
        self.span = ''
        self.scale = ''

    def set_series(self, series, span, scale=''):
        # series: [(name, values 0..1 or None, 'area' or 'line')]
        self.series = series
        self.span = span
        self.scale = scale
        self.Refresh()

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
                fill_rect(gc, get_series_colour(theme, kind), x, 13, LEGEND_SWATCH, 7, 1)
            else:
                fill_rect(gc, get_series_colour(theme, kind), x, 16, LEGEND_SWATCH, 2)
            x -= LEGEND_GAP

        left, top = self.PADDING, GRAPH_TOP
        plot_width, plot_height = right - left, height - GRAPH_TOP - GRAPH_BOTTOM
        for level in (0.0, 0.5, 1.0):
            fill_rect(gc, theme['rim'], left, top + plot_height * (1 - level), plot_width, 1)
        if self.scale:
            gc.SetFont(get_font(7.5), wx.Colour(theme['dim']))
            gc.DrawText(self.scale, left + 2, top + 2)
        for _, values, kind in self.series:
            draw_series(gc, theme, values, kind, (left, top, plot_width, plot_height),
                        self.capacity)
