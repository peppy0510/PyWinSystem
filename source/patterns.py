# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import wx

from utilities import get_font


# full-screen test patterns for one display, drawn pixel for pixel through a plain DC (a
# graphics context would smooth the 1 px lines) and cached as one bitmap per pattern
CAPTION_MS = 2500
CAPTION_PAD = 12
LABEL = 8

GAMMAS = (1.8, 2.0, 2.2, 2.4, 2.6)
BLACK_STEPS = range(1, 21)
WHITE_STEPS = range(235, 255)
BARS_75 = ((191, 191, 191), (191, 191, 0), (0, 191, 191), (0, 191, 0), (191, 0, 191),
           (191, 0, 0), (0, 0, 191))
BARS_100 = ((255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255),
            (255, 0, 0), (0, 0, 255))


def fill(dc, colour, x, y, width, height):
    dc.SetPen(wx.TRANSPARENT_PEN)
    dc.SetBrush(wx.Brush(wx.Colour(*colour)))
    dc.DrawRectangle(int(x), int(y), int(width), int(height))


def label(dc, text, x, y, colour, centre=True):
    dc.SetFont(get_font(LABEL + 2))
    dc.SetTextForeground(wx.Colour(*colour))
    width = dc.GetTextExtent(text)[0]
    dc.DrawText(text, int(x - width / 2 if centre else x), int(y))


def draw_steps(dc, width, height, ground, steps, ink):
    # one square per level on the ground level; every square that stands apart is a level
    # the panel resolves
    fill(dc, (ground,) * 3, 0, 0, width, height)
    count = len(steps)
    size = min(width // (count + 2), height // 4)
    left = (width - size * count) // 2
    top = (height - size) // 2
    for index, value in enumerate(steps):
        fill(dc, (value,) * 3, left + index * size, top, size, size)
        label(dc, str(value), left + index * size + size / 2, top + size + 10, ink)
    return left, top + size + 40


def draw_black(dc, width, height):
    left, top = draw_steps(dc, width, height, 0, BLACK_STEPS, (90, 90, 90))
    label(dc, 'Black level: raise brightness or black level until the lowest squares just '
          'part from the background', width / 2, top, (90, 90, 90))


def draw_white(dc, width, height):
    left, top = draw_steps(dc, width, height, 255, WHITE_STEPS, (150, 150, 150))
    label(dc, 'White level: lower contrast until the highest squares part from the background',
          width / 2, top, (150, 150, 150))


def get_striped(width, height):
    # alternate black and white rows average to half the light, whatever the gamma
    row_black, row_white = bytes(width * 3), b'\xff' * (width * 3)
    data = b''.join(row_white if y % 2 else row_black for y in range(height))
    return wx.Image(width, height, data).ConvertToBitmap()


def draw_gamma(dc, width, height):
    fill(dc, (128, 128, 128), 0, 0, width, height)
    size = min(width // (len(GAMMAS) * 2 + 1), height // 3)
    left = (width - size * (len(GAMMAS) * 2 - 1)) // 2
    top = (height - size) // 2
    stripes = get_striped(size, size)
    for index, gamma in enumerate(GAMMAS):
        x = left + index * size * 2
        dc.DrawBitmap(stripes, x, top)
        inner = size // 2
        value = round(255 * 0.5 ** (1 / gamma))
        fill(dc, (value,) * 3, x + (size - inner) // 2, top + (size - inner) // 2, inner, inner)
        label(dc, f'{gamma:.1f}', x + size / 2, top + size + 10, (230, 230, 230))
    label(dc, 'Gamma: step back; the square that melts into its stripes is the gamma '
          'the panel shows', width / 2, top + size + 50, (230, 230, 230))


def get_ramp(width, height, channel):
    row = bytearray(width * 3)
    for x in range(width):
        value = x * 255 // max(1, width - 1)
        for index in range(3):
            if channel is None or channel == index:
                row[x * 3 + index] = value
    return wx.Image(width, 1, bytes(row)).Rescale(width, height).ConvertToBitmap()


def draw_ramps(dc, width, height):
    fill(dc, (0, 0, 0), 0, 0, width, height)
    band = height // 4
    for index, channel in enumerate((None, 0, 1, 2)):
        dc.DrawBitmap(get_ramp(width, band, channel), 0, index * band)
    label(dc, 'Ramps: a smooth run from black to full; steps or tinted bands are lost levels',
          CAPTION_PAD * 2, height - band // 2, (200, 200, 200), centre=False)


def draw_bars(dc, width, height):
    count = len(BARS_75)
    for row, (bars, top, part) in enumerate(((BARS_75, 0, 2 / 3), (BARS_100, 2 / 3, 1 / 3))):
        for index, colour in enumerate(bars):
            x = width * index // count
            fill(dc, colour, x, height * top, width * (index + 1) // count - x + 1,
                 height * part + 1)
    label(dc, 'Colour bars at 75% and 100%', CAPTION_PAD * 2, height * 2 / 3 - 40,
          (20, 20, 20), centre=False)


def get_lines(width, height, vertical):
    if vertical:
        row = b'\x00\x00\x00\xff\xff\xff' * (width // 2) + b'\x00\x00\x00' * (width % 2)
        data = row * height
    else:
        data = b''.join((b'\xff' if y % 2 else b'\x00') * (width * 3) for y in range(height))
    return wx.Image(width, height, data).ConvertToBitmap()


def draw_sharpness(dc, width, height):
    fill(dc, (128, 128, 128), 0, 0, width, height)
    size = min(width // 4, height // 2)
    top = (height - size) // 2
    gap = (width - size * 2) // 3
    dc.DrawBitmap(get_lines(size, size, True), gap, top)
    dc.DrawBitmap(get_lines(size, size, False), gap * 2 + size, top)
    label(dc, 'Sharpness: 1 px lines should read as even grey stripes, without moiré or '
          'ghosting', width / 2, top + size + 20, (20, 20, 20))


def solid(colour):
    def draw(dc, width, height):
        fill(dc, colour, 0, 0, width, height)
    return draw


PATTERNS = (('Black level', draw_black), ('White level', draw_white), ('Gamma', draw_gamma),
            ('Ramps', draw_ramps), ('Colour bars', draw_bars), ('Sharpness', draw_sharpness),
            ('White', solid((255, 255, 255))), ('Grey 50%', solid((128, 128, 128))),
            ('Black', solid((0, 0, 0))), ('Red', solid((255, 0, 0))),
            ('Green', solid((0, 255, 0))), ('Blue', solid((0, 0, 255))))


def render(index, width, height):
    bitmap = wx.Bitmap(width, height)
    dc = wx.MemoryDC(bitmap)
    PATTERNS[index][1](dc, width, height)
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def find_display(device):
    for index in range(wx.Display.GetCount()):
        if wx.Display(index).GetName() == device:
            return wx.Display(index).GetGeometry()
    return None


class PatternWindow(wx.Frame):
    '''Covers one display. Right, Space or a click: next; Left or a right click: back;
    Esc: close. A caption names the pattern for a moment and on each mouse move.'''

    def __init__(self, parent, device, title):
        rect = find_display(device) or wx.Display(0).GetGeometry()
        super().__init__(parent, title=f'{title} test patterns', pos=rect.GetPosition(),
                         size=rect.GetSize(),
                         style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE)
        self.title = title
        self.index = 0
        self.bitmaps = {}
        self.caption = True
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)
        self.Bind(wx.EVT_LEFT_DOWN, lambda event: self.step(1))
        self.Bind(wx.EVT_RIGHT_DOWN, lambda event: self.step(-1))
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.show_caption()

    def get_bitmap(self):
        width, height = self.GetClientSize()
        key = (self.index, width, height)
        if key not in self.bitmaps:
            self.bitmaps[key] = render(self.index, width, height)
        return self.bitmaps[key]

    def step(self, delta):
        self.index = (self.index + delta) % len(PATTERNS)
        self.show_caption()

    def show_caption(self):
        self.caption = True
        self.SetCursor(wx.Cursor(wx.CURSOR_ARROW))
        self.timer.StartOnce(CAPTION_MS)
        self.Refresh()

    def on_timer(self, event):
        self.caption = False
        # a pointer over a solid field would read as a stuck pixel
        self.SetCursor(wx.Cursor(wx.CURSOR_BLANK))
        self.Refresh()

    def on_motion(self, event):
        if not self.caption:
            self.show_caption()
        event.Skip()

    def on_key(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self.Close()
        elif code in (wx.WXK_RIGHT, wx.WXK_SPACE, wx.WXK_DOWN, wx.WXK_PAGEDOWN):
            self.step(1)
        elif code in (wx.WXK_LEFT, wx.WXK_UP, wx.WXK_PAGEUP, wx.WXK_BACK):
            self.step(-1)
        else:
            event.Skip()

    def on_paint(self, event):
        dc = wx.BufferedPaintDC(self)
        dc.DrawBitmap(self.get_bitmap(), 0, 0)
        if self.caption:
            self.draw_caption(dc)

    def draw_caption(self, dc):
        name = PATTERNS[self.index][0]
        lines = (f'{self.title} · {name} · {self.index + 1} of {len(PATTERNS)}',
                 '→ Space or click: next   ← or right click: back   Esc: close')
        dc.SetFont(get_font(LABEL + 2))
        sizes = [dc.GetTextExtent(line) for line in lines]
        box_width = max(size[0] for size in sizes) + CAPTION_PAD * 2
        box_height = sum(size[1] for size in sizes) + CAPTION_PAD * 2 + 4
        top = self.GetClientSize()[1] - box_height - CAPTION_PAD * 2
        dc.SetPen(wx.Pen(wx.Colour(90, 90, 90)))
        dc.SetBrush(wx.Brush(wx.Colour(24, 25, 28)))
        dc.DrawRectangle(CAPTION_PAD * 2, top, box_width, box_height)
        y = top + CAPTION_PAD
        for line, (_, line_height), colour in zip(lines, sizes, ((230, 233, 237), (139, 146, 155))):
            dc.SetTextForeground(wx.Colour(*colour))
            dc.DrawText(line, CAPTION_PAD * 3, y)
            y += line_height + 4

    def on_close(self, event):
        self.timer.Stop()
        event.Skip()
