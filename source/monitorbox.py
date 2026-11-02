# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

Every screen on one page, one folding panel each. Inside, what the monitor does itself and
what only the graphics card does sit under their own headings: both have a "brightness" of a
different nature, and mixed up nobody could tell which one moved.

The monitor side shows only what its capabilities allow. A control for a missing feature
would be the worst kind: the slider moves and the screen stays the same.
'''


import ddcci
import gamma
import patterns
import wx

from controls import ActionCard
from controls import CardBase
from controls import ChoiceCard
from controls import Panel
from controls import ScrollArea
from controls import SliderCard
from controls import draw_row_face
from controls import get_pen
from hovertip import show_hover_tip
from utilities import draw_text_in
from utilities import get_font
from utilities import get_text_width


SOFTWARE_BRIGHTNESS = (25, 100)
SOFTWARE_CONTRAST = (50, 150)
SOFTWARE_CHANNEL = (50, 100)
KELVIN_STEP = 100

# on the graphics card side 100% is the untouched state
NEUTRAL_PERCENT = 100

HARDWARE_SLIDERS = ((ddcci.BRIGHTNESS, 'Brightness', 'Backlight inside the monitor'),
                    (ddcci.CONTRAST, 'Contrast', 'Set by the monitor itself'),
                    (ddcci.VOLUME, 'Volume', 'Speakers or headphone jack on the monitor'),
                    (ddcci.RED_GAIN, 'Red gain', 'The monitor\'s own colour balance'),
                    (ddcci.GREEN_GAIN, 'Green gain', 'The monitor\'s own colour balance'),
                    (ddcci.BLUE_GAIN, 'Blue gain', 'The monitor\'s own colour balance'))

SOFTWARE_CHANNELS = (('red', 'Red'), ('green', 'Green'), ('blue', 'Blue'))


class UnitSlider(SliderCard):
    '''Shows the value with its unit; the edit field gets the number alone, a unit there would
    only be more to delete.

    The value column has one width, fitted to the longest value of any unit; measured per row
    the % and K tracks would start at different x.'''

    WIDEST = '10000 K'

    def __init__(self, parent, theme, label, description, bounds, unit='', on_change=None,
                 default=None):
        super().__init__(parent, theme, label, description, (*bounds, 0), on_change, default)
        self.unit = unit
        self.value_width = get_text_width(get_font(self.VALUE_SIZE), self.WIDEST)

    def format(self, value):
        return f'{int(round(value))}{self.unit}'

    def edit(self):
        if self.entry is None:
            self.start_entry(str(int(round(self.value))))


class GroupRow(CardBase):
    '''A heading row inside a panel; pressing it does nothing.'''

    HEIGHT = 30

    def __init__(self, parent, theme, label):
        super().__init__(parent, theme, label, '')
        self.SetMinSize(wx.Size(-1, self.HEIGHT))

    def draw(self, gc, width, height):
        theme = self.theme
        draw_row_face(gc, theme, width, height, self.first, self.last)
        rect = wx.Rect(self.PADDING, 0, max(0, width - self.PADDING * 2), height)
        draw_text_in(gc, self.label.upper(), rect, get_font(8, True), theme['dim'],
                     align='left', back=theme['face'])


class NoticeRow(CardBase):
    '''A read-only row with its value or its reason at the right.'''

    def __init__(self, parent, theme, label, description, value, tone='warn'):
        super().__init__(parent, theme, label, description)
        self.value = value
        self.tone = tone

    def draw_control(self, gc, width, height):
        theme = self.theme
        font = get_font(9)
        text_width = get_text_width(font, self.value)
        rect = wx.Rect(width - self.PADDING - text_width, 0, text_width, height)
        draw_text_in(gc, self.value, rect, font, theme[self.tone], align='right',
                     back=theme['face'])
        return rect.x


# socket outlines, drawn in a 30 x 10 box; the shape tells DisplayPort from HDMI at a glance
PORT_WIDTH = 30
PORT_HEIGHT = 10
PORT_GAP = 12
PORT_SHORT = {'DisplayPort': 'DP', 'USB-C DisplayPort': 'USB-C', 'HDMI': 'HDMI', 'DVI': 'DVI'}


def get_port_outline(output, x, y):
    w, h, cut = PORT_WIDTH, PORT_HEIGHT, 3
    if output == 'DisplayPort':
        # one corner clipped, as on the plug
        return [(x, y), (x + w, y), (x + w, y + h - cut), (x + w - cut, y + h), (x, y + h)]
    if output == 'HDMI':
        return [(x, y), (x + w, y), (x + w, y + h - cut), (x + w - cut, y + h),
                (x + cut, y + h), (x, y + h - cut)]
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


class PortRow(CardBase):
    '''The sockets of one graphics card in driver order, this display's lit and marked.'''

    HEIGHT = 64
    LABEL_TOP = 6

    def __init__(self, parent, theme, ports, current, owners=None):
        super().__init__(parent, theme, 'Sockets',
                         'Filled in use, outlined free; driver order, not the bracket')
        self.ports = ports
        self.current = current
        self.owners = owners or {}
        self.port_rects = []
        self.SetMinSize(wx.Size(-1, self.HEIGHT))

    def get_port_name(self, port):
        return f'{PORT_SHORT.get(port["output"], port["output"])} {port["connector"] + 1}'

    # the display in the socket under the pointer; otherwise the cut-short label tip
    def update_label_tip(self, point=None):
        point = point or wx.GetMousePosition()
        position = self.ScreenToClient(point)
        for rect, port in self.port_rects:
            if not rect.Contains(position):
                continue
            owner = self.owners.get((port.get('card'), port['output'], port['connector']))
            if (port['output'], port['connector']) == self.current:
                text = f'{owner} (this one)' if owner else 'This display'
            elif owner:
                text = owner
            else:
                text = 'In use' if port['used'] else 'Free'
            show_hover_tip(self, self.theme, [(self.get_port_name(port), 'dim'),
                                              (text, 'text')], point)
            return
        super().update_label_tip(point)

    def draw_control(self, gc, width, height):
        theme = self.theme
        count = len(self.ports)
        if not count:
            return width - self.PADDING
        left = width - self.PADDING - count * PORT_WIDTH - (count - 1) * PORT_GAP
        top = (height - PORT_HEIGHT) / 2 - 5
        self.port_rects = []
        for index, port in enumerate(self.ports):
            x = left + index * (PORT_WIDTH + PORT_GAP)
            mine = (port['output'], port['connector']) == self.current
            if mine:
                fill, edge, ink = theme['accent'], theme['accent'], theme['text']
            elif port['used']:
                fill, edge, ink = theme['control'], theme['dim'], theme['dim']
            else:
                fill, edge, ink = None, theme['edge'], theme['faint']
            path = gc.CreatePath()
            points = get_port_outline(port['output'], x + 0.5, top + 0.5)
            path.MoveToPoint(*points[0])
            for point in points[1:]:
                path.AddLineToPoint(*point)
            path.CloseSubpath()
            if fill:
                gc.SetBrush(wx.Brush(wx.Colour(fill)))
                gc.FillPath(path)
            gc.SetPen(get_pen(gc, edge))
            gc.StrokePath(path)
            name = self.get_port_name(port)
            self.port_rects.append((wx.Rect(int(x - PORT_GAP / 2), int(top - 9),
                                            PORT_WIDTH + PORT_GAP, PORT_HEIGHT + 27), port))
            rect = wx.Rect(int(x - PORT_GAP / 2), int(top + PORT_HEIGHT + 4),
                           PORT_WIDTH + PORT_GAP, 14)
            draw_text_in(gc, name, rect, get_font(8, mine), ink, back=theme['face'])
            if mine:
                # a mark above as well, so the colour is not the only sign
                mark = gc.CreatePath()
                middle = x + PORT_WIDTH / 2
                mark.MoveToPoint(middle - 4, top - 8)
                mark.AddLineToPoint(middle + 4, top - 8)
                mark.AddLineToPoint(middle, top - 3)
                mark.CloseSubpath()
                gc.SetBrush(wx.Brush(wx.Colour(theme['accent'])))
                gc.FillPath(mark)
        return left - PORT_GAP / 2


def get_hardware_unit(limit):
    '''MCCS lets each code set its own maximum. Brightness is usually 100 and reads as a
    percentage, but RGB gain goes to 255, and a % on anything but 100 would lie.'''
    return '%' if limit == 100 else ''


class MonitorSection:
    '''The panel of one screen, tying its cards to that screen.'''

    def __init__(self, board, theme, display, folds, on_fold, on_change, owners=None):
        self.display = display
        self.on_change = on_change
        self.owners = owners or {}
        self.board = board
        self.patterns = None
        rows = (self.build_hardware(board, theme) + self.build_software(board, theme)
                + self.build_calibration(board, theme) + self.build_connection(board, theme))
        self.panel = Panel(board, theme, f'monitor.{display.key}', display.label, rows,
                           folds, on_fold, display.get_summary())

    def build_hardware(self, board, theme):
        '''What the monitor does itself; one that does not answer only says so.'''
        display = self.display
        rows = [GroupRow(board, theme, 'Monitor · DDC/CI')]
        if not display.has_hardware():
            rows.append(NoticeRow(board, theme, 'Monitor controls',
                                  'This monitor does not answer DDC/CI', 'Not available'))
            return rows

        for code, label, description in HARDWARE_SLIDERS:
            if not display.supports(code):
                continue
            # the callback is set once the card exists; the slider holds its own value, so
            # the card alone gives the code and the value
            limit = display.get_limit(code)
            card = UnitSlider(board, theme, label, description, (0, limit, 1),
                              get_hardware_unit(limit), default=display.get_default(code))
            card.SetValue(display.get_hardware(code))
            card.on_change = self.get_hardware_handler(code, card)
            rows.append(card)

        code = ddcci.INPUT_SOURCE
        if display.supports(code) and display.choices.get(code):
            options = [(value, ddcci.get_input_name(value))
                       for value in display.choices[code]]
            self.input = ChoiceCard(board, theme, 'Input source',
                                    'Switch the port the monitor shows', options,
                                    self.on_input)
            self.input.SetValue(display.get_hardware(code))
            rows.append(self.input)
        return rows

    def build_software(self, board, theme):
        '''Replaces what the graphics card sends. Every monitor follows it, but the backlight
        stays, so the lower it goes the more the dark tones crush.'''
        display = self.display
        self.scaled = {}
        rows = [GroupRow(board, theme, 'Graphics card · gamma')]

        for name, label, description, bounds in (
                ('brightness', 'Brightness', 'Dims the signal; shadows crush below 100%',
                 SOFTWARE_BRIGHTNESS),
                ('contrast', 'Contrast', '100% leaves the signal untouched',
                 SOFTWARE_CONTRAST)):
            card = UnitSlider(board, theme, label, description, (*bounds, 1), '%',
                              default=NEUTRAL_PERCENT)
            card.SetValue(round(display.get_software(name) * 100))
            card.on_change = self.get_software_handler(name, card)
            self.scaled[name] = card
            rows.append(card)

        self.kelvin = UnitSlider(board, theme, 'Colour temperature',
                                 f'{gamma.NEUTRAL_KELVIN} K leaves it untouched',
                                 (gamma.MIN_KELVIN, gamma.MAX_KELVIN, KELVIN_STEP), ' K',
                                 self.on_kelvin, gamma.NEUTRAL_KELVIN)
        self.kelvin.SetValue(display.get_software('kelvin'))
        rows.append(self.kelvin)

        for name, label in SOFTWARE_CHANNELS:
            card = UnitSlider(board, theme, label, 'Trims one channel after the temperature',
                              (*SOFTWARE_CHANNEL, 1), '%', default=NEUTRAL_PERCENT)
            card.SetValue(round(display.get_software(name) * 100))
            card.on_change = self.get_software_handler(name, card)
            self.scaled[name] = card
            rows.append(card)

        rows.append(ActionCard(board, theme, 'Reset',
                               'Put the graphics card back to untouched', 'Reset',
                               self.on_reset))
        return rows

    def build_connection(self, board, theme):
        # read only: what the panel says about itself, which card drives it and through
        # which port
        display = self.display
        rows = [GroupRow(board, theme, 'Details')]
        for label, description, value in display.get_identity():
            rows.append(NoticeRow(board, theme, label, description, value, 'text'))
        number = display.device.rpartition('DISPLAY')[2]
        rows.append(NoticeRow(board, theme, 'Graphics card', f'Windows display {number}',
                              display.info.get('adapter') or 'Unknown', 'text'))
        rows.append(NoticeRow(board, theme, 'Port', 'Numbered as the driver counts them',
                              display.get_port() or 'Unknown', 'text'))
        ports = display.info.get('ports')
        if ports:
            rows.append(PortRow(board, theme, ports,
                                (display.info.get('output'), display.info.get('connector')),
                                self.owners))
        return rows

    def get_hardware_handler(self, code, card):
        def handler():
            self.display.set_hardware(code, card.GetValue())
        return handler

    def get_software_handler(self, name, card):
        '''Shown in percent, passed on as a factor; 100% is untouched.'''
        def handler():
            self.display.set_software(name, card.GetValue() / 100.0)
            self.on_change()
        return handler

    def on_kelvin(self):
        self.display.set_software('kelvin', self.kelvin.GetValue())
        self.on_change()

    def on_input(self):
        self.display.set_hardware(ddcci.INPUT_SOURCE, self.input.GetValue())

    def build_calibration(self, board, theme):
        # full-screen patterns on this display, to judge the sliders above against
        return [GroupRow(board, theme, 'Calibration'),
                ActionCard(board, theme, 'Test patterns',
                           'Black and white level, gamma, ramps, bars, sharpness, solid fills',
                           'Open', self.on_patterns)]

    def on_patterns(self):
        if self.patterns:
            self.patterns.Raise()
            return
        self.patterns = patterns.PatternWindow(self.board.GetTopLevelParent(),
                                               self.display.device, self.display.label)
        self.patterns.Bind(wx.EVT_WINDOW_DESTROY, self.on_patterns_closed)
        self.patterns.Show()
        self.patterns.SetFocus()

    def on_patterns_closed(self, event):
        if event.GetEventObject() is self.patterns:
            self.patterns = None
        event.Skip()

    def on_reset(self):
        self.display.reset_software()
        self.show_software()
        self.on_change()

    def show_software(self):
        for name, card in self.scaled.items():
            card.SetValue(round(self.display.get_software(name) * 100))
        self.kelvin.SetValue(self.display.get_software('kelvin'))


class MonitorBox(ScrollArea):

    def __init__(self, parent, theme, displays, folds, on_change, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds
        self.on_folds = on_fold
        # which display sits in each socket, for the socket tips
        owners = {(display.info.get('card'), display.info.get('output'),
                   display.info.get('connector')): display.label for display in displays}
        self.sections = [MonitorSection(self.content, theme, display, folds, self.on_fold,
                                        on_change, owners)
                         for display in displays]
        self.set_panels([section.panel for section in self.sections])
        self.bind_children()
        self.apply_theme(theme)

    def on_reset(self):
        '''Called after every screen is already reset; only sets the cards again.'''
        for section in self.sections:
            section.show_software()

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
