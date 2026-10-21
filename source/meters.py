# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import collections
import re
import wx

from controls import CardBase
from controls import draw_row_face
from utilities import fill_rect
from utilities import get_font
from utilities import get_text_width
from utilities import mix

SLOT_WIDTH = 200
SLOT_GAP = 14
VALUE_COLUMN = 104
MIN_LABEL = 100
# a quick answer would flip a busy caption on and off in a blink, so it waits this long
BUSY_DELAY = 400
BAR_HEIGHT = 6
VALUE_FONT = 8.5
# a rate can switch from B/s to KB/s, so rate units sit left-aligned in a column of their own;
# a fixed unit stays put under plain right alignment
UNITS = ('B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s')
UNIT_PATTERN = '|'.join(re.escape(unit) for unit in sorted(UNITS, key=len, reverse=True))
MEASURE = re.compile(r'^([\d.,]+)\s*(%s)$' % UNIT_PATTERN)
UNIT_GAP = 3
HIGH = 0.9

CORE_HEIGHT = 22


def format_bytes(value):
    value = float(value or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return ('%.0f %s' if unit in ('B', 'KB') else '%.1f %s') % (value, unit)
        value /= 1024


def get_rate_scale(peak):
    # a row keeps the unit of its graph's top, so readings change unit only when the graph
    # rescales; KB/s is the smallest
    peak = max(float(peak or 0), 1024.0)
    unit, name = 1024.0, 'KB/s'
    for bigger in ('MB/s', 'GB/s', 'TB/s'):
        if peak <= unit * 500:
            break
        unit, name = unit * 1024, bigger
    ceiling = next((unit * step for step in (1, 2, 5, 10, 20, 50, 100, 200, 500)
                    if peak <= unit * step), peak)
    return ceiling, unit, name


def format_rate(value, scale):
    ceiling, unit, name = scale
    digits = 1 if ceiling / unit <= 10 else 0
    return '%.*f %s' % (digits, (value or 0) / unit, name)


def get_unit_width():
    font = get_font(VALUE_FONT, bold=True)
    return max(get_text_width(font, unit) for unit in UNITS)


def get_watt_ceiling(value):
    for step in (25, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000):
        if (value or 0) <= step:
            return step
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

    def get_grid(self, width):
        right = width - self.PADDING
        value_left = right - VALUE_COLUMN
        slot_right = value_left - SLOT_GAP
        slot_left = max(self.PADDING + MIN_LABEL, slot_right - SLOT_WIDTH)
        return slot_left, slot_right, value_left, right

    def draw_value(self, gc, text, right, middle, ink='text', bold=True):
        font = get_font(VALUE_FONT, bold=bold)
        gc.SetFont(font, wx.Colour(self.theme[ink]))
        top = middle - gc.GetTextExtent(text or '0')[1] / 2
        found = MEASURE.match(text)
        if not found:
            gc.DrawText(text, right - get_text_width(font, text), top)
            return get_text_width(font, text)
        number, unit = found.groups()
        unit_left = right - get_unit_width()
        gc.DrawText(unit, unit_left, top)
        number_right = unit_left - UNIT_GAP
        gc.DrawText(number, number_right - get_text_width(font, number), top)
        return right - number_right + get_text_width(font, number)


class ValueCard(ReadoutCard):

    def __init__(self, parent, theme, label, description='', value='', warn=False):
        super().__init__(parent, theme, label, description)
        self.value = value
        self.warn = warn

    def set_value(self, value, description=None):
        changed = self.set_text(description=description)
        if value != self.value:
            self.value = value
            changed = True
        if changed:
            self.Refresh()

    def draw_control(self, gc, width, height):
        right = width - self.PADDING
        if not self.value:
            return right
        drawn = self.draw_value(gc, self.value, right, height / 2, 'warn' if self.warn else 'text')
        # no picture here, so a long label may run into the empty slot
        return right - drawn


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
        left, slot_right, _, right = self.get_grid(width)
        value = None if self.value is None else max(0.0, min(1.0, self.value))
        high = value is not None and value >= HIGH
        self.draw_value(gc, '—' if value is None else '%d%%' % round(value * 100), right,
                        height / 2, 'warn' if high else 'text')
        bar_width = slot_right - left
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

    SPARK_HEIGHT = 26
    LINE_GAP = 8

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

    def draw_control(self, gc, width, height):
        theme = self.theme
        left, slot_right, value_left, right = self.get_grid(width)
        peaks = [value for values in self.history for value in values if value]
        scale = get_rate_scale(max(peaks) if peaks else 0)
        values = ('—', '—') if self.pair is None else tuple(format_rate(value, scale)
                                                            for value in self.pair)
        for index, middle in enumerate((height / 2 - self.LINE_GAP,
                                        height / 2 + self.LINE_GAP)):
            name_font = get_font(VALUE_FONT)
            gc.SetFont(name_font, wx.Colour(theme['dim']))
            gc.DrawText(self.names[index], value_left,
                        middle - gc.GetTextExtent(self.names[index])[1] / 2)
            self.draw_value(gc, values[index], right, middle)

        top = (height - self.SPARK_HEIGHT) / 2
        spark_width = slot_right - left
        fill_rect(gc, theme['rim'], left, top + self.SPARK_HEIGHT, spark_width, 1)
        ceiling = scale[0]
        for values, kind in zip(self.history, ('area', 'line')):
            draw_series(gc, theme, [None if value is None else value / ceiling
                                    for value in values], kind,
                        (left, top, spark_width, self.SPARK_HEIGHT), self.capacity, 1.2)
        return left


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
        left, slot_right, _, right = self.get_grid(width)
        if not count:
            return left
        # the same thickness and round ends as the horizontal meter bars, spread over the slot
        column, radius = BAR_HEIGHT, BAR_HEIGHT / 2
        step = (slot_right - left - column) / float(max(1, count - 1))
        top = (height - CORE_HEIGHT) / 2
        for index, value in enumerate(self.values):
            x = left + index * step
            fill_rect(gc, theme['track'], x, top, column, CORE_HEIGHT, radius)
            if value > 0:
                level = max(column, CORE_HEIGHT * min(100, value) / 100.0)
                colour = theme['warn'] if value >= HIGH * 100 else theme['accent']
                fill_rect(gc, colour, x, top + CORE_HEIGHT - level, column, level, radius)
        return left


GRAPH_HEIGHT = 100
GRAPH_PAD = 12
LEGEND_SWATCH = 10
LEGEND_LINE = 18


class GraphCard(ReadoutCard):

    def __init__(self, parent, theme, label, capacity):
        super().__init__(parent, theme, label)
        self.SetMinSize(wx.Size(-1, GRAPH_HEIGHT))
        self.capacity = capacity
        self.series = []
        self.span = ''
        self.scale = ''

    def set_series(self, series, span, scale=''):
        # series: [(name, values 0..1 or None, 'area' or 'line', latest value as text)]
        self.series = series
        self.span = span
        self.scale = scale
        self.Refresh()

    def draw(self, gc, width, height):
        theme = self.theme
        draw_row_face(gc, theme, width, height, self.first, self.last)
        left, slot_right, value_left, right = self.get_grid(width)
        self.draw_label(gc, height, left - self.PADDING - self.LABEL_GAP)

        middle = height / 2 - (len(self.series) - 1) * LEGEND_LINE / 2
        note = get_font(VALUE_FONT)
        for index, (name, _, kind, text) in enumerate(self.series):
            y = middle + index * LEGEND_LINE
            colour = get_series_colour(theme, kind)
            if kind == 'area':
                fill_rect(gc, colour, value_left, y - 3, LEGEND_SWATCH, 7, 1)
            else:
                fill_rect(gc, colour, value_left, y - 1, LEGEND_SWATCH, 2)
            gc.SetFont(note, wx.Colour(theme['dim']))
            gc.DrawText(name, value_left + LEGEND_SWATCH + 5, y - gc.GetTextExtent(name)[1] / 2)
            self.draw_value(gc, text, right, y)

        top = GRAPH_PAD
        plot_width, plot_height = slot_right - left, height - GRAPH_PAD * 2
        for level in (0.0, 0.5, 1.0):
            fill_rect(gc, theme['rim'], left, top + plot_height * (1 - level), plot_width, 1)
        gc.SetFont(get_font(7.5), wx.Colour(theme['dim']))
        if self.scale:
            gc.DrawText(self.scale, left + 2, top + 2)
        span_width = get_text_width(get_font(7.5), self.span)
        gc.DrawText(self.span, slot_right - span_width - 2, top + 2)
        for _, values, kind, _ in self.series:
            draw_series(gc, theme, values, kind, (left, top, plot_width, plot_height),
                        self.capacity)
