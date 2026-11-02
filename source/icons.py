# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import math
import wx


def get_pen(gc, colour, width):
    return gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(colour)).Width(width)
                        .Cap(wx.CAP_ROUND).Join(wx.JOIN_ROUND))


def draw_glyph(gc, name, cx, cy, size, colour, width=None):
    handler = HANDLERS.get(name)
    if handler is None:
        return
    width = width or max(1.0, size * 0.085)
    gc.SetPen(get_pen(gc, colour, width))
    gc.SetBrush(wx.TRANSPARENT_BRUSH)
    handler(gc, cx, cy, size, wx.Colour(colour), width)


def draw_disk(gc, cx, cy, size, colour, width):
    half_width, half_height = size * 0.42, size * 0.30
    gc.DrawRoundedRectangle(cx - half_width, cy - half_height, half_width * 2,
                            half_height * 2, size * 0.08)
    gc.StrokeLine(cx - half_width, cy + size * 0.06, cx + half_width, cy + size * 0.06)
    gc.SetPen(wx.TRANSPARENT_PEN)
    gc.SetBrush(wx.Brush(colour))
    dot = size * 0.11
    gc.DrawEllipse(cx + size * 0.20 - dot / 2, cy + size * 0.18 - dot / 2, dot, dot)


def draw_chip(gc, cx, cy, size, colour, width):
    half = size * 0.26
    gc.DrawRoundedRectangle(cx - half, cy - half, half * 2, half * 2, size * 0.05)
    for offset in (-size * 0.12, size * 0.12):
        gc.StrokeLine(cx + offset, cy - half, cx + offset, cy - size * 0.44)
        gc.StrokeLine(cx + offset, cy + half, cx + offset, cy + size * 0.44)
        gc.StrokeLine(cx - half, cy + offset, cx - size * 0.44, cy + offset)
        gc.StrokeLine(cx + half, cy + offset, cx + size * 0.44, cy + offset)


def draw_chart(gc, cx, cy, size, colour, width):
    base = cy + size * 0.38
    gc.StrokeLine(cx - size * 0.42, base, cx + size * 0.42, base)

    bar = size * 0.17
    gc.SetPen(wx.TRANSPARENT_PEN)
    gc.SetBrush(wx.Brush(colour))
    for offset, height in ((-size * 0.28, 0.30), (0.0, 0.54), (size * 0.28, 0.42)):
        top = base - size * height
        gc.DrawRectangle(cx + offset - bar / 2, top, bar, base - top - width / 2)


def draw_settings(gc, cx, cy, size, colour, width):
    outer, inner, hub = size * 0.48, size * 0.33, size * 0.15
    steps = 16

    path = gc.CreatePath()
    for step in range(steps):
        angle = math.radians(step * 360.0 / steps)
        radius = outer if step % 2 == 0 else inner
        x, y = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        if step:
            path.AddLineToPoint(x, y)
        else:
            path.MoveToPoint(x, y)
    path.CloseSubpath()
    gc.StrokePath(path)
    gc.DrawEllipse(cx - hub, cy - hub, hub * 2, hub * 2)


def draw_menu(gc, cx, cy, size, colour, width):
    half = size * 0.42
    for offset in (-size * 0.30, 0.0, size * 0.30):
        gc.StrokeLine(cx - half, cy + offset, cx + half, cy + offset)


def draw_list(gc, cx, cy, size, colour, width):
    for offset in (-size * 0.30, 0.0, size * 0.30):
        gc.StrokeLine(cx - size * 0.16, cy + offset, cx + size * 0.42, cy + offset)
    gc.SetPen(wx.TRANSPARENT_PEN)
    gc.SetBrush(wx.Brush(colour))
    dot = size * 0.13
    for offset in (-size * 0.30, 0.0, size * 0.30):
        gc.DrawEllipse(cx - size * 0.40 - dot / 2, cy + offset - dot / 2, dot, dot)


# a screen on its stand; without the stand it reads as a plain box at this size
def draw_monitor(gc, cx, cy, size, colour, width):
    half = size * 0.44
    top = cy - size * 0.38
    bottom = cy + size * 0.16
    gc.DrawRoundedRectangle(cx - half, top, half * 2, bottom - top, size * 0.08)
    gc.StrokeLine(cx, bottom, cx, cy + size * 0.34)
    gc.StrokeLine(cx - size * 0.22, cy + size * 0.36, cx + size * 0.22, cy + size * 0.36)


# a console window with a prompt, for WSL
def draw_terminal(gc, cx, cy, size, colour, width):
    half_width, half_height = size * 0.44, size * 0.34
    gc.DrawRoundedRectangle(cx - half_width, cy - half_height, half_width * 2,
                            half_height * 2, size * 0.08)
    path = gc.CreatePath()
    path.MoveToPoint(cx - size * 0.24, cy - size * 0.12)
    path.AddLineToPoint(cx - size * 0.08, cy + size * 0.02)
    path.AddLineToPoint(cx - size * 0.24, cy + size * 0.16)
    gc.StrokePath(path)
    gc.StrokeLine(cx + size * 0.02, cy + size * 0.16, cx + size * 0.24, cy + size * 0.16)


def draw_minimize(gc, cx, cy, size, colour, width):
    gc.StrokeLine(cx - size * 0.40, cy, cx + size * 0.40, cy)


def draw_maximize(gc, cx, cy, size, colour, width):
    span = size * 0.72
    gc.DrawRectangle(cx - span / 2, cy - span / 2, span, span)


def draw_restore(gc, cx, cy, size, colour, width):
    gc.DrawRectangle(cx - size * 0.38, cy - size * 0.22, size * 0.60, size * 0.60)
    path = gc.CreatePath()
    path.MoveToPoint(cx - size * 0.22, cy - size * 0.22)
    path.AddLineToPoint(cx - size * 0.22, cy - size * 0.38)
    path.AddLineToPoint(cx + size * 0.38, cy - size * 0.38)
    path.AddLineToPoint(cx + size * 0.38, cy + size * 0.22)
    path.AddLineToPoint(cx + size * 0.22, cy + size * 0.22)
    gc.StrokePath(path)


def draw_close(gc, cx, cy, size, colour, width):
    arm = size * 0.36
    gc.StrokeLine(cx - arm, cy - arm, cx + arm, cy + arm)
    gc.StrokeLine(cx - arm, cy + arm, cx + arm, cy - arm)


def draw_person(gc, cx, cy, size, colour, width):
    gc.DrawEllipse(cx - size * 0.19, cy - size * 0.44, size * 0.38, size * 0.38)
    path = gc.CreatePath()
    path.AddArc(cx, cy + size * 0.46, size * 0.36, math.radians(180), math.radians(360), True)
    gc.StrokePath(path)


HANDLERS = {
    'disk': draw_disk,
    'chip': draw_chip,
    'chart': draw_chart,
    'settings': draw_settings,
    'menu': draw_menu,
    'list': draw_list,
    'terminal': draw_terminal,
    'monitor': draw_monitor,
    'minimize': draw_minimize,
    'maximize': draw_maximize,
    'restore': draw_restore,
    'close': draw_close,
    'person': draw_person,
}
