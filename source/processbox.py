# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import bisect
import os
import time
import wx

import psutil

import processes
import winuac

from controls import ScrollBar
from controls import draw_button
from controls import get_button_width
from icons import draw_glyph
from meters import VALUE_FONT
from meters import format_bytes
from utilities import BAND_INSET
from utilities import BUTTON_GAP
from utilities import BUTTON_HEIGHT
from utilities import HEADER_BAND
from utilities import PANEL_MARGIN
from utilities import PANEL_PAD
from utilities import PANEL_RADIUS
from utilities import Canvas
from utilities import apply_clip_siblings
from utilities import draw_chevron
from utilities import fill_rect
from utilities import get_font
from utilities import get_ink
from utilities import get_text_top
from utilities import get_text_width


ROW_HEIGHT = 30
COLUMN_HEIGHT = 26
FIELD_HEIGHT = 26
FIELD_INSET = 8
FILTER_PAD = 10
FILTER_GAP = 6
CLEAR_SIZE = 22
CLEAR_GLYPH = 8
CHEVRON = 10
CHEVRON_X = BAND_INSET + 6 + CHEVRON / 2
NAME_LEFT = BAND_INSET + 6 + CHEVRON + 6
PID_GAP = 6
CPU_WIDTH = 52
MEMORY_WIDTH = 76
COLUMN_GAP = 12
LABEL_WIDTH = 96
LINE_HEIGHT = 18
DETAIL_TOP = 2
DETAIL_GAP = 8
DETAIL_BOTTOM = 12
MAX_COMMAND_LINES = 12
MARK_SIZE = 7
NAME_FONT = 9
NOTE_FONT = 8
SCROLL_LINE = 3 * ROW_HEIGHT
COPIED_MS = 1500
# the first read after a page switch and the sampler's next beat can land a few ms apart
MIN_ELAPSED = 0.3
TICKS = 10 ** 7

DENIED = 'Needs administrator rights'
MISSING = 'Not available'
CAPTIONS = {'open': 'Open location', 'path': 'Copy path', 'command': 'Copy command line',
            'admin': 'Run as administrator'}
COPIED = 'Copied'
HINT = 'Name, PID or path'
KINDS = (('all', 'All'), ('apps', 'Apps'), ('background', 'Background'),
         ('windows', 'Windows'))
USAGES = (('any', 'Any use'), ('cpu', 'CPU ≥ 1%'), ('memory', 'Memory ≥ 100 MB'),
          ('large', 'Memory ≥ 1 GB'))
USAGE_TESTS = {'any': lambda row: True,
               'cpu': lambda row: (row['cpu'] or 0) >= 1,
               'memory': lambda row: row['memory'] >= 100 << 20,
               'large': lambda row: row['memory'] >= 1 << 30}
SORTS = ('name', 'cpu', 'memory')


def format_cpu(value):
    return '' if value is None else '%.1f%%' % value


def describe(value):
    if value is False:
        return DENIED
    return value or MISSING


def draw_sort_mark(gc, cx, cy, descending, colour):
    gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(wx.Colour(colour)).Width(1.5)
                           .Cap(wx.CAP_ROUND).Join(wx.JOIN_ROUND)))
    gc.SetBrush(wx.TRANSPARENT_BRUSH)
    half, rise = MARK_SIZE / 2.0, MARK_SIZE / 4.0
    tip = rise if descending else -rise
    path = gc.CreatePath()
    path.MoveToPoint(cx - half, cy - tip)
    path.AddLineToPoint(cx, cy + tip)
    path.AddLineToPoint(cx + half, cy - tip)
    gc.StrokePath(path)


class ProcessList(Canvas):

    def __init__(self, parent, theme, state, on_scroll, on_change=None, on_quit=None):
        super().__init__(parent, theme)
        self.on_scroll = on_scroll
        self.on_change = on_change
        self.on_quit = on_quit
        self.table = processes.ProcessTable()
        self.paths = processes.ImagePaths()
        self.images = {}
        self.cpus = psutil.cpu_count() or 1
        self.admin = winuac.is_admin()
        self.rows = []
        self.by_pid = {}
        self.times = {}
        self.sampled = None
        self.sort = state.get('sort') if state.get('sort') in SORTS else 'cpu'
        self.descending = bool(state.get('descending', self.sort != 'name'))
        self.kind = state.get('kind') if state.get('kind') in dict(KINDS) else 'all'
        self.usage = state.get('usage') if state.get('usage') in dict(USAGES) else 'any'
        self.filter = ''
        self.expanded = set()
        self.details = {}
        self.copied = None
        self.offset = 0
        self.items = []
        self.tops = []
        self.extent = 0
        self.hovered = None
        self.pressed = None
        self.wraps = {}
        self.measure = None
        self.chips = []
        self.field = wx.TextCtrl(self, style=wx.BORDER_NONE)
        self.field.SetHint(HINT)
        self.field.SetFont(get_font(NAME_FONT))
        self.field.Bind(wx.EVT_TEXT, self.on_text)
        self.field.Bind(wx.EVT_KEY_DOWN, self.on_field_key)
        self.field.Bind(wx.EVT_MOUSEWHEEL, self.on_wheel)
        self.layout_header(self.GetClientSize()[0])
        self.Bind(wx.EVT_LEFT_DOWN, self.on_down)
        self.Bind(wx.EVT_LEFT_DCLICK, self.on_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_up)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.on_leave)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.on_lost)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_wheel)
        self.Bind(wx.EVT_CHAR, self.on_char)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def read_now(self):
        self.times, self.sampled = {}, None
        self.set_rows(self.table.read(), time.monotonic())

    def set_rows(self, rows, now):
        if self.sampled is not None and now - self.sampled < MIN_ELAPSED:
            return
        elapsed = now - self.sampled if self.sampled is not None else 0
        times = {}
        for row in rows:
            key = row['key'] = processes.get_key(row)
            previous = self.times.get(key)
            row['cpu'] = None
            if previous is not None and elapsed > 0:
                share = (row['time'] - previous) * 100.0 / (elapsed * TICKS * self.cpus)
                row['cpu'] = max(0.0, min(100.0, share))
            times[key] = row['time']
            row['path'] = self.images[key] if key in self.images else self.paths.read(row['pid'])
        self.times, self.sampled = times, now
        self.images = {row['key']: row['path'] for row in rows}
        self.rows = rows
        self.by_pid = {row['pid']: row for row in rows}
        windowed = processes.get_window_pids()
        for row in rows:
            row['kind'] = self.get_kind(row, windowed)
        self.expanded &= set(times)
        self.details = {key: value for key, value in self.details.items() if key in times}
        self.relayout()

    def get_kind(self, row, windowed):
        # a browser's helpers share its name and descend from the process that owns the window
        current = row
        for _ in range(16):
            if current['pid'] in windowed:
                return 'apps'
            parent = self.by_pid.get(current['ppid'])
            if (parent is None or parent['name'] != row['name']
                    or parent['created'] > current['created']):
                break
            current = parent
        return 'windows' if processes.is_windows_path(row['path']) else 'background'

    def matches(self, row, needle):
        return (needle in row['name'].lower() or str(row['pid']).startswith(needle)
                or needle in (row['path'] or '').lower())

    def get_shown(self):
        needle = self.filter.lower()
        test = USAGE_TESTS[self.usage]
        shown = [row for row in self.rows if (self.kind == 'all' or row['kind'] == self.kind)
                 and test(row) and (not needle or self.matches(row, needle))]
        if self.sort == 'name':
            shown.sort(key=lambda row: (row['name'].lower(), row['pid']), reverse=self.descending)
        elif self.sort == 'cpu':
            shown.sort(key=lambda row: (-1 if row['cpu'] is None else row['cpu'], row['memory']),
                       reverse=self.descending)
        else:
            shown.sort(key=lambda row: row['memory'], reverse=self.descending)
        return shown

    def relayout(self):
        width = self.GetClientSize()[0]
        items, top = [], 0
        for row in self.get_shown():
            detail = self.get_detail(row, width) if row['key'] in self.expanded else None
            height = ROW_HEIGHT + (detail['height'] if detail else 0)
            items.append((top, height, row, detail))
            top += height
        self.items, self.extent = items, top
        self.tops = [item[0] for item in items]
        self.scroll_to(self.offset)
        self.Refresh()

    def get_measure(self):
        if self.measure is None:
            self.measure_dc = wx.MemoryDC(wx.Bitmap(1, 1))
            self.measure = wx.GraphicsContext.Create(self.measure_dc)
            self.measure.SetFont(get_font(VALUE_FONT), wx.BLACK)
        return self.measure

    def wrap(self, text, limit, most=1):
        key = (text, limit, most)
        if key in self.wraps:
            return self.wraps[key]
        gc = self.get_measure()
        fits = lambda part: gc.GetTextExtent(part)[0] <= limit
        lines, rest = [], text
        while rest and len(lines) < most:
            if fits(rest):
                lines.append(rest)
                rest = ''
                break
            low, high = 1, len(rest)
            while low < high:
                middle = (low + high + 1) // 2
                if fits(rest[:middle]):
                    low = middle
                else:
                    high = middle - 1
            # break after a space or a path separator when one sits in the back half
            cut = max(rest.rfind(mark, 0, low) for mark in (' ', '\\', '/'))
            if cut >= low // 2:
                low = cut + 1
            lines.append(rest[:low].rstrip())
            rest = rest[low:].lstrip(' ')
        if rest and lines:
            last = lines[-1]
            while last and not fits(last + '…'):
                last = last[:-1]
            lines[-1] = last + '…'
        if len(self.wraps) > 2000:
            self.wraps.clear()
        self.wraps[key] = lines or ['']
        return self.wraps[key]

    def get_parent_text(self, row):
        parent = self.by_pid.get(row['ppid'])
        if parent is not None and parent['created'] <= row['created']:
            return '%s · PID %d' % (parent['name'], parent['pid'])
        return 'PID %d · exited' % row['ppid'] if row['ppid'] else MISSING

    def get_detail(self, row, width):
        details = self.details.get(row['key']) or {}
        command = details.get('cmdline')
        command = processes.join_cmdline(command) if command else command
        started = processes.get_start_time(row['created'])
        fields = [('Path', describe(details.get('exe')), 3),
                  ('Command line', describe(command), MAX_COMMAND_LINES),
                  ('Folder', describe(details.get('cwd')), 3),
                  ('User', describe(details.get('user')), 1),
                  ('Parent', self.get_parent_text(row), 1),
                  ('Started', started.strftime('%Y-%m-%d %H:%M:%S') if started else MISSING, 1),
                  ('Threads', '%d threads · %d handles · session %d' % (
                      row['threads'], row['handles'], row['session']), 1),
                  ('Memory', 'Private %s · working set %s · commit %s' % (
                      format_bytes(row['memory']), format_bytes(row['working_set']),
                      format_bytes(row['commit'])), 2),
                  ('I/O', 'Read %s · written %s' % (format_bytes(row['read']),
                                                    format_bytes(row['written'])), 1)]
        limit = max(40, width - PANEL_PAD - NAME_LEFT - LABEL_WIDTH)
        lines = [(label, self.wrap(text, limit, most)) for label, text, most in fields]
        top = DETAIL_TOP + sum(len(texts) for _, texts in lines) * LINE_HEIGHT + DETAIL_GAP

        names = []
        if isinstance(details.get('exe'), str):
            names += ['open', 'path']
        if command:
            names.append('command')
        if not self.admin and False in (details.get('exe'), details.get('cmdline'),
                                        details.get('cwd')):
            names.append('admin')
        buttons, left = [], NAME_LEFT
        for name in names:
            button_width = get_button_width(CAPTIONS[name])
            if name in ('path', 'command'):
                button_width = max(button_width, get_button_width(COPIED))
            if left > NAME_LEFT and left + button_width > width - PANEL_PAD:
                left, top = NAME_LEFT, top + BUTTON_HEIGHT + BUTTON_GAP
            buttons.append((name, wx.Rect(left, top, button_width, BUTTON_HEIGHT)))
            left += button_width + BUTTON_GAP
        if buttons:
            top += BUTTON_HEIGHT
        return {'lines': lines, 'buttons': buttons, 'height': top + DETAIL_BOTTOM,
                'details': details}

    def layout_header(self, width):
        top = HEADER_BAND + 1 + FILTER_PAD
        self.field_rect = wx.Rect(PANEL_PAD, top, max(0, width - PANEL_PAD * 2), FIELD_HEIGHT)
        self.clear_rect = wx.Rect(self.field_rect.x + self.field_rect.width - CLEAR_SIZE - 2,
                                  top + (FIELD_HEIGHT - CLEAR_SIZE) // 2, CLEAR_SIZE, CLEAR_SIZE)
        y = top + FIELD_HEIGHT + FILTER_GAP
        chips = []
        for group, options in (('kind', KINDS), ('usage', USAGES)):
            left = PANEL_PAD
            for value, caption in options:
                chip_width = get_button_width(caption)
                if left > PANEL_PAD and left + chip_width > width - PANEL_PAD:
                    left, y = PANEL_PAD, y + BUTTON_HEIGHT + BUTTON_GAP
                chips.append((group, value, caption, wx.Rect(left, y, chip_width, BUTTON_HEIGHT)))
                left += chip_width + BUTTON_GAP
            y += BUTTON_HEIGHT + FILTER_GAP
        self.chips = chips
        self.column_top = y - FILTER_GAP + FILTER_PAD + 1
        self.list_top = self.column_top + COLUMN_HEIGHT + 1
        text_height = self.field.GetBestSize().height
        self.field.SetSize(self.field_rect.x + FIELD_INSET,
                           self.field_rect.y + (FIELD_HEIGHT - text_height) // 2,
                           max(0, self.field_rect.width - FIELD_INSET - CLEAR_SIZE - 4),
                           text_height)

    def get_state(self):
        return {'sort': self.sort, 'descending': self.descending, 'kind': self.kind,
                'usage': self.usage}

    def is_filtered(self):
        return bool(self.filter) or self.kind != 'all' or self.usage != 'any'

    def get_columns(self, width):
        memory_right = width - PANEL_PAD
        cpu_right = memory_right - MEMORY_WIDTH - COLUMN_GAP
        return cpu_right - CPU_WIDTH, cpu_right, memory_right

    def get_view_height(self):
        return max(0, self.GetClientSize()[1] - self.list_top)

    def get_limit(self):
        return max(0, self.extent - self.get_view_height())

    def scroll_to(self, offset):
        self.offset = min(self.get_limit(), max(0, int(offset)))
        if self.on_scroll:
            self.on_scroll()

    def hit_test(self, position):
        x, y = position
        width = self.GetClientSize()[0]
        if y < HEADER_BAND or x < 0 or x >= width:
            return None
        if y < self.column_top:
            if self.filter and self.clear_rect.Contains(x, y):
                return ('clear', None)
            for group, value, _, rect in self.chips:
                if rect.Contains(x, y):
                    return ('chip', group, value)
            return None
        if y < self.list_top:
            cpu_left, cpu_right, _ = self.get_columns(width)
            if x < cpu_left - COLUMN_GAP / 2:
                return ('sort', 'name')
            return ('sort', 'cpu' if x < cpu_right + COLUMN_GAP / 2 else 'memory')
        spot = y - self.list_top + self.offset
        index = bisect.bisect_right(self.tops, spot) - 1
        if index < 0:
            return None
        top, height, row, detail = self.items[index]
        if spot >= top + height:
            return None
        inside = spot - top - ROW_HEIGHT
        if inside < 0:
            return ('row', row['key'])
        for name, rect in detail['buttons']:
            if rect.Contains(x, inside):
                return ('button', row['key'], name)
        return None

    def on_motion(self, event):
        target = self.hit_test(event.GetPosition())
        if target != self.hovered:
            self.hovered = target
            self.SetCursor(wx.Cursor(wx.CURSOR_HAND if target else wx.CURSOR_ARROW))
            self.Refresh()

    def on_leave(self, event):
        if self.hovered is not None and not self.HasCapture():
            self.hovered = None
            self.Refresh()

    def on_down(self, event):
        self.SetFocus()
        self.pressed = self.hit_test(event.GetPosition())
        if self.pressed is not None and not self.HasCapture():
            self.CaptureMouse()
        self.Refresh()

    def on_up(self, event):
        if self.HasCapture():
            self.ReleaseMouse()
        pressed, self.pressed = self.pressed, None
        if pressed is not None and pressed == self.hit_test(event.GetPosition()):
            self.act(pressed)
        self.Refresh()

    def on_lost(self, event):
        self.pressed = None
        self.Refresh()

    def on_wheel(self, event):
        lines = event.GetWheelRotation() / float(event.GetWheelDelta())
        self.scroll_by(-int(round(lines * SCROLL_LINE)))

    def scroll_by(self, delta):
        before = self.offset
        self.scroll_to(self.offset + delta)
        if self.offset != before:
            self.GetParent().bar.show()
            self.update_hover()
            self.Refresh()

    def update_hover(self):
        position = self.ScreenToClient(wx.GetMousePosition())
        self.hovered = self.hit_test(position) if self.GetClientRect().Contains(position) else None

    def on_char(self, event):
        code = event.GetKeyCode()
        page = self.get_view_height() - ROW_HEIGHT
        steps = {wx.WXK_UP: -ROW_HEIGHT, wx.WXK_DOWN: ROW_HEIGHT, wx.WXK_PAGEUP: -page,
                 wx.WXK_PAGEDOWN: page, wx.WXK_HOME: -self.extent, wx.WXK_END: self.extent}
        if code in steps:
            self.scroll_by(steps[code])
        elif code == wx.WXK_ESCAPE and self.field.GetValue():
            self.field.SetValue('')
        elif code == wx.WXK_BACK:
            self.type_text(self.field.GetValue()[:-1])
        elif (event.GetUnicodeKey() >= 32 and not event.ControlDown()
              and not event.AltDown()):
            self.type_text(self.field.GetValue() + chr(event.GetUnicodeKey()))
        else:
            event.Skip()

    def type_text(self, text):
        self.field.SetFocus()
        self.field.SetValue(text)
        self.field.SetInsertionPointEnd()

    def on_field_key(self, event):
        code = event.GetKeyCode()
        page = self.get_view_height() - ROW_HEIGHT
        steps = {wx.WXK_UP: -ROW_HEIGHT, wx.WXK_DOWN: ROW_HEIGHT, wx.WXK_PAGEUP: -page,
                 wx.WXK_PAGEDOWN: page}
        if code in steps:
            self.scroll_by(steps[code])
        elif code == wx.WXK_ESCAPE and self.field.GetValue():
            self.field.SetValue('')
        else:
            event.Skip()

    def on_text(self, event):
        text = self.field.GetValue().strip()
        if text != self.filter:
            self.filter = text
            self.offset = 0
            self.relayout()
        event.Skip()

    def act(self, target):
        kind, key = target[0], target[1]
        if kind == 'clear':
            self.field.SetValue('')
            self.field.SetFocus()
        elif kind == 'chip':
            if getattr(self, key) != target[2]:
                setattr(self, key, target[2])
                self.offset = 0
                self.relayout()
                self.notify()
        elif kind == 'sort':
            if self.sort == key:
                self.descending = not self.descending
            else:
                self.sort, self.descending = key, key != 'name'
            self.relayout()
            self.notify()
        elif kind == 'row':
            if key in self.expanded:
                self.expanded.discard(key)
            else:
                self.expanded.add(key)
                self.details[key] = processes.read_details(key[0])
            self.relayout()
        elif kind == 'button':
            self.press(key, target[2])

    def press(self, key, name):
        details = self.details.get(key) or {}
        if name == 'open':
            processes.open_location(details.get('exe'))
        elif name == 'admin':
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'main.pyw')
            if winuac.relaunch_as_admin(script, os.getpid()) and self.on_quit:
                self.on_quit()
        else:
            text = details.get('exe') if name == 'path' else processes.join_cmdline(
                details.get('cmdline'))
            if text and wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                # the text stays on the clipboard after the app quits
                wx.TheClipboard.Flush()
                wx.TheClipboard.Close()
                copied = self.copied = (key, name)
                wx.CallLater(COPIED_MS, self.clear_copied, copied)
                self.Refresh()

    def notify(self):
        if self.on_change:
            self.on_change()

    def clear_copied(self, copied):
        if self and self.copied == copied:
            self.copied = None
            self.Refresh()

    def on_size(self, event):
        self.layout_header(self.GetClientSize()[0])
        self.relayout()
        event.Skip()

    def set_theme(self, theme):
        super().set_theme(theme)
        self.field.SetBackgroundColour(wx.Colour(theme['control']))
        self.field.SetForegroundColour(wx.Colour(theme['text']))
        self.field.Refresh()

    def get_subtitle(self):
        total = len(self.rows)
        if not self.is_filtered():
            return '%d running' % total
        return '%d of %d' % (len(self.items), total)

    def draw(self, gc, width, height):
        theme = self.theme
        start = max(0, bisect.bisect_right(self.tops, self.offset) - 1)
        for index in range(start, len(self.items)):
            top, row_height, row, detail = self.items[index]
            y = self.list_top + top - self.offset
            if y >= height:
                break
            self.draw_item(gc, width, y, row_height, row, detail, index == 0,
                           index == len(self.items) - 1)
        if not self.items:
            fill_rect(gc, theme['face'], 0, self.list_top, width, ROW_HEIGHT, PANEL_RADIUS)
            fill_rect(gc, theme['face'], 0, self.list_top, width, PANEL_RADIUS)
            font = get_font(NAME_FONT)
            gc.SetFont(font, wx.Colour(theme['dim']))
            gc.DrawText('No process matches' if self.rows else 'Reading', NAME_LEFT,
                        get_text_top(font, self.list_top, ROW_HEIGHT))
        self.draw_header(gc, width)

    def draw_item(self, gc, width, y, row_height, row, detail, first, last):
        theme = self.theme
        fill = theme['face']
        if last:
            fill_rect(gc, fill, 0, y, width, row_height, PANEL_RADIUS)
            fill_rect(gc, fill, 0, y, width, PANEL_RADIUS)
        else:
            fill_rect(gc, fill, 0, y, width, row_height)
        key = row['key']
        target = ('row', key)
        if self.pressed == target:
            fill_rect(gc, theme['control_down'], BAND_INSET, y + 2, width - BAND_INSET * 2,
                      ROW_HEIGHT - 4, PANEL_RADIUS)
        elif self.hovered == target:
            fill_rect(gc, theme['control_hover'], BAND_INSET, y + 2, width - BAND_INSET * 2,
                      ROW_HEIGHT - 4, PANEL_RADIUS)
        if not first:
            fill_rect(gc, theme['rim'], PANEL_PAD, y, max(0, width - PANEL_PAD * 2), 1)

        open_ = detail is not None
        draw_chevron(gc, 'down' if open_ else 'right', CHEVRON_X, y + ROW_HEIGHT / 2, CHEVRON,
                     theme['text'] if self.hovered == target or open_ else theme['dim'])
        cpu_left, cpu_right, memory_right = self.get_columns(width)
        value_font = get_font(VALUE_FONT, bold=True)
        gc.SetFont(value_font, wx.Colour(theme['text']))
        for text, right in ((format_cpu(row['cpu']), cpu_right),
                            (format_bytes(row['memory']), memory_right)):
            if text:
                gc.DrawText(text, right - get_text_width(value_font, text),
                            get_text_top(value_font, y, ROW_HEIGHT))

        name_font, note_font = get_font(NAME_FONT), get_font(NOTE_FONT)
        pid = 'PID %d' % row['pid']
        room = cpu_left - COLUMN_GAP - NAME_LEFT
        name_top = get_text_top(name_font, y, ROW_HEIGHT)
        gc.SetFont(name_font, wx.Colour(theme['text']))
        name = self.fit_text(gc, row['name'], max(0, room - get_text_width(note_font, pid)
                                                  - PID_GAP))
        gc.DrawText(name, NAME_LEFT, name_top)
        pid_left = NAME_LEFT + get_text_width(name_font, name) + PID_GAP
        if pid_left + get_text_width(note_font, pid) <= NAME_LEFT + room:
            gc.SetFont(note_font, wx.Colour(theme['dim']))
            baseline = name_top + get_ink(name_font)[1]
            gc.DrawText(pid, pid_left, baseline - get_ink(note_font)[1])

        if open_:
            self.draw_detail(gc, width, y + ROW_HEIGHT, key, detail)

    def draw_detail(self, gc, width, top, key, detail):
        theme = self.theme
        label_font, text_font = get_font(NOTE_FONT), get_font(VALUE_FONT)
        line_top = top + DETAIL_TOP
        for label, texts in detail['lines']:
            gc.SetFont(label_font, wx.Colour(theme['dim']))
            gc.DrawText(label, NAME_LEFT, get_text_top(label_font, line_top, LINE_HEIGHT))
            denied = texts[0] in (DENIED, MISSING)
            gc.SetFont(text_font, wx.Colour(theme['dim' if denied else 'text']))
            for text in texts:
                gc.DrawText(text, NAME_LEFT + LABEL_WIDTH,
                            get_text_top(text_font, line_top, LINE_HEIGHT))
                line_top += LINE_HEIGHT
        for name, rect in detail['buttons']:
            target = ('button', key, name)
            if self.pressed == target:
                state = 'down'
            elif self.hovered == target:
                state = 'hover'
            else:
                state = 'plain'
            caption = COPIED if self.copied == (key, name) else CAPTIONS[name]
            draw_button(gc, theme, wx.Rect(rect.x, top + rect.y, rect.width, rect.height),
                        caption, state)

    def draw_header(self, gc, width):
        theme = self.theme
        fill_rect(gc, theme['bg'], 0, 0, width, self.list_top)
        fill_rect(gc, theme['band'], 0, 0, width, HEADER_BAND, PANEL_RADIUS)
        fill_rect(gc, theme['band'], 0, HEADER_BAND - PANEL_RADIUS, width, PANEL_RADIUS)
        fill_rect(gc, theme['rim'], 0, HEADER_BAND, width, 1)
        fill_rect(gc, theme['accent'], 0, 6, 2, HEADER_BAND - 12, 1)

        font = get_font(9, True)
        title = 'PROCESSES'
        title_top = get_text_top(font, 0, HEADER_BAND)
        gc.SetFont(font, wx.Colour(theme['text']))
        gc.DrawText(title, NAME_LEFT, title_top)
        sub_font = get_font(NOTE_FONT)
        sub_left = NAME_LEFT + get_text_width(font, title) + 16
        gc.SetFont(sub_font, wx.Colour(theme['dim']))
        baseline = title_top + get_ink(font)[1]
        gc.DrawText(self.fit_text(gc, self.get_subtitle(), max(0, width - sub_left - PANEL_PAD)),
                    sub_left, baseline - get_ink(sub_font)[1])

        column_top = self.column_top
        fill_rect(gc, theme['face'], 0, HEADER_BAND + 1, width, column_top + COLUMN_HEIGHT
                  - HEADER_BAND - 1)
        self.draw_filters(gc, width)
        fill_rect(gc, theme['rim'], PANEL_PAD, column_top - 1, max(0, width - PANEL_PAD * 2), 1)
        fill_rect(gc, theme['rim'], PANEL_PAD, column_top + COLUMN_HEIGHT,
                  max(0, width - PANEL_PAD * 2), 1)
        cpu_left, cpu_right, memory_right = self.get_columns(width)
        for name, caption, edge, align in (('name', 'Name', NAME_LEFT, 'left'),
                                           ('cpu', 'CPU', cpu_right, 'right'),
                                           ('memory', 'Memory', memory_right, 'right')):
            active = self.sort == name
            lit = active or self.hovered == ('sort', name)
            label_font = get_font(NOTE_FONT, bold=active)
            text_width = get_text_width(label_font, caption)
            left = edge if align == 'left' else edge - text_width
            middle = column_top + COLUMN_HEIGHT / 2
            gc.SetFont(label_font, wx.Colour(theme['text' if lit else 'dim']))
            gc.DrawText(caption, left, get_text_top(label_font, column_top, COLUMN_HEIGHT))
            if active:
                mark = left + text_width + 4 + MARK_SIZE / 2 if align == 'left' \
                    else left - 4 - MARK_SIZE / 2
                draw_sort_mark(gc, mark, middle, self.descending, theme['accent'])


    def draw_filters(self, gc, width):
        theme = self.theme
        rect = self.field_rect
        fill_rect(gc, theme['control'], rect.x, rect.y, rect.width, rect.height, PANEL_RADIUS)
        if self.filter:
            lit = self.hovered == ('clear', None)
            if lit:
                fill_rect(gc, theme['control_hover'], self.clear_rect.x, self.clear_rect.y,
                          self.clear_rect.width, self.clear_rect.height, PANEL_RADIUS)
            draw_glyph(gc, 'close', self.clear_rect.x + CLEAR_SIZE / 2,
                       self.clear_rect.y + CLEAR_SIZE / 2, CLEAR_GLYPH,
                       theme['text' if lit else 'dim'], 1.5)
        for group, value, caption, chip in self.chips:
            target = ('chip', group, value)
            if getattr(self, group) == value:
                state = 'lit'
            elif self.pressed == target:
                state = 'down'
            elif self.hovered == target:
                state = 'hover'
            else:
                state = 'plain'
            draw_button(gc, theme, chip, caption, state)


class ProcessBox(wx.Panel):

    def __init__(self, parent, theme, state=None, on_change=None, on_quit=None):
        super().__init__(parent)
        self.theme = theme
        self.active = False
        self.list = ProcessList(self, theme, state or {}, self.update_bar, on_change, on_quit)
        self.bar = ScrollBar(self, theme)
        apply_clip_siblings(self.list)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_MOUSEWHEEL, self.list.on_wheel)
        self.apply_theme(theme)

    def set_active(self, active):
        self.active = active
        if active:
            self.list.read_now()
            self.list.field.SetFocus()

    def set_rows(self, rows, now):
        if self.active:
            self.list.set_rows(rows, now)

    def get_state(self):
        return self.list.get_state()

    def update_bar(self):
        width, height = self.GetClientSize()
        bar_width = ScrollBar.WIDTH + ScrollBar.INSET * 2
        top = PANEL_MARGIN + self.list.list_top
        self.bar.SetSize(width - bar_width, top, bar_width, max(0, height - PANEL_MARGIN - top))
        view = self.list.get_view_height()
        extent, limit = self.list.extent, self.list.get_limit()
        self.bar.set_span(view / float(extent) if extent else 1.0,
                          self.list.offset / float(limit) if limit else 0.0)

    def on_size(self, event):
        width, height = self.GetClientSize()
        self.list.SetSize(PANEL_MARGIN, PANEL_MARGIN, max(0, width - PANEL_MARGIN * 2),
                          max(0, height - PANEL_MARGIN * 2))
        self.bar.Raise()
        self.update_bar()
        event.Skip()

    def apply_theme(self, theme):
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme['bg']))
        self.list.set_theme(theme)
        self.bar.set_theme(theme)
        self.Refresh()

    def tick(self):
        pass
