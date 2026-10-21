# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os
import threading
import time
import winreg
import wx

from diskbox import DiskBox
from resourcebox import ResourceBox
from sampler import Sampler
from settingsbox import SettingsBox
from sidemenu import SideMenu
from titlebar import TitleBar
from utilities import APP_NAME
from utilities import THEMES
from utilities import apply_clip_siblings
from utilities import apply_no_caption
from utilities import apply_titlebar_theme
from utilities import call_painted
from utilities import get_asset_path
from utilities import get_frame_margins
from utilities import load_settings
from utilities import save_settings


DEFAULT_SIZE = (460, 720)

MENU_ITEMS = (('Resources', 'chart'), ('Disks', 'disk'), None, ('Settings', 'settings'))

FRAME_STYLE = wx.DEFAULT_FRAME_STYLE & ~wx.CAPTION

MIN_VISIBLE_WIDTH = 120
MIN_VISIBLE_HEIGHT = 32


def is_windows_dark():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        winreg.CloseKey(key)
        return value == 0
    except OSError:
        return True


class SamplerThread(threading.Thread):
    # WM_TIMER starves while the mouse keeps moving; a thread keeps the beat

    def __init__(self, frame):
        super().__init__(name='sampler', daemon=True)
        self.frame = frame
        self.sampler = Sampler()
        self.interval = 1.0
        self.running = True
        self.visible = True

    def run(self):
        target = time.perf_counter()
        while self.running:
            target += self.interval
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                target = time.perf_counter()
            # nobody looks at a hidden window, so skip the work
            if not self.running or not self.visible:
                continue
            try:
                data = self.sampler.sample()
                call_painted(self.frame, self.frame.on_sample, data)
            except Exception:
                continue


class MainFrame(wx.Frame):

    stored_rect = None
    started = False
    restore_bounds = None

    def __init__(self):
        settings = load_settings()
        super().__init__(None, title=APP_NAME, size=wx.Size(*DEFAULT_SIZE),
                         style=FRAME_STYLE)
        apply_no_caption(self)

        self.theme_name = self.resolve_theme(settings.get('theme', 'dark'))
        theme = THEMES[self.theme_name]
        self.set_icon()

        self.folds = set(settings.get('folded_panels', []))

        self.book = wx.Simplebook(self)
        self.resourcebox = ResourceBox(self.book, theme, self.folds, self.store_settings)
        self.diskbox = DiskBox(self.book, theme, self.folds, self.store_settings,
                               self.resourcebox.set_disk_names)
        self.settingsbox = SettingsBox(self.book, theme, settings, self.on_settings,
                                       self.folds, self.store_settings)
        for page in (self.resourcebox, self.diskbox, self.settingsbox):
            self.book.AddPage(page, '')

        self.titlebar = TitleBar(self, theme, self.on_menu, self.toggle_maximize)
        self.sidemenu = SideMenu(self, theme, MENU_ITEMS, self.on_select)
        apply_clip_siblings(self.book)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.titlebar, 0, wx.EXPAND)
        sizer.Add(self.book, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.sampler = SamplerThread(self)
        self.apply_theme()
        self.on_settings()

        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_MAXIMIZE, self.on_maximize)
        self.Bind(wx.EVT_ICONIZE, self.on_iconize)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.sampler.start()
        self.restore_rect(settings)
        self.started = True

    def is_rect_visible(self, rect):
        for index in range(wx.Display.GetCount()):
            shared = wx.Display(index).GetClientArea().Intersect(rect)
            if shared.width >= MIN_VISIBLE_WIDTH and shared.height >= MIN_VISIBLE_HEIGHT:
                return True
        return False

    def centre_on_primary(self):
        primary = wx.Display(wx.Display.GetFromPoint(wx.Point(0, 0))).GetClientArea()
        width, height = self.GetSize()
        self.SetPosition(wx.Point(primary.x + (primary.width - width) // 2,
                                  primary.y + (primary.height - height) // 2))

    def restore_rect(self, settings):
        stored = settings.get('rect')
        if stored and len(stored) == 4:
            rect = wx.Rect(*stored)
            if self.is_rect_visible(rect):
                self.SetRect(rect)
                self.stored_rect = list(stored)
                return
            self.SetSize(rect.GetSize())

        self.centre_on_primary()
        self.stored_rect = list(self.GetRect())

    def set_icon(self):
        path = get_asset_path('icon', 'icon.ico')
        if os.path.exists(path):
            self.SetIcon(wx.Icon(path, wx.BITMAP_TYPE_ICO))

    def apply_theme(self):
        theme = THEMES[self.theme_name]
        self.SetBackgroundColour(wx.Colour(theme['bg']))
        self.book.SetBackgroundColour(wx.Colour(theme['bg']))
        self.titlebar.set_theme(theme)
        self.sidemenu.set_theme(theme)
        for page in (self.resourcebox, self.diskbox, self.settingsbox):
            page.apply_theme(theme)
        apply_titlebar_theme(self, theme)
        self.Refresh()

    def on_menu(self):
        self.sidemenu.toggle()

    def on_select(self, index):
        self.book.SetSelection(index)

    def toggle_maximize(self):
        # Windows maximizes a captionless frame past the work area and over the taskbar
        if self.restore_bounds is not None:
            bounds, self.restore_bounds = self.restore_bounds, None
            self.SetRect(wx.Rect(*bounds))
        else:
            self.restore_bounds = list(self.GetRect())
            index = max(0, wx.Display.GetFromWindow(self))
            work = wx.Display(index).GetClientArea()
            left, top, right, bottom = get_frame_margins(self)
            self.SetRect(wx.Rect(work.x - left, work.y - top,
                                 work.width + left + right,
                                 work.height + top + bottom))
        self.titlebar.set_maximized(self.restore_bounds is not None)

    def on_maximize(self, event):
        if not self.IsMaximized():
            return
        self.Maximize(False)
        if self.restore_bounds is None:
            self.toggle_maximize()

    def on_iconize(self, event):
        self.sampler.visible = not event.IsIconized()
        event.Skip()

    def on_char(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and self.sidemenu.is_open():
            self.sidemenu.close()
            return
        event.Skip()

    @staticmethod
    def resolve_theme(choice):
        if choice == 'auto':
            return 'dark' if is_windows_dark() else 'light'
        return choice if choice in THEMES else 'dark'

    def on_settings(self):
        values = self.settingsbox.get_values()
        style = self.GetWindowStyle()
        if values['on_top']:
            self.SetWindowStyle(style | wx.STAY_ON_TOP)
        else:
            self.SetWindowStyle(style & ~wx.STAY_ON_TOP)

        theme_name = self.resolve_theme(values['theme'])
        if theme_name != self.theme_name:
            self.theme_name = theme_name
            self.apply_theme()
        self.sampler.interval = float(values['interval'])
        self.store_settings()

    def on_sample(self, data):
        if self:
            self.resourcebox.set_data(data)

    def on_size(self, event):
        self.sidemenu.place(TitleBar.HEIGHT)
        event.Skip()

    def store_settings(self):
        if not self.started:
            return
        settings = self.settingsbox.get_values()
        settings.update({
            'rect': self.stored_rect,
            'folded_panels': sorted(self.folds),
        })
        save_settings(settings)

    def on_close(self, event):
        self.sampler.running = False
        # the drawer's capture and slide timer crash a closing frame (0xc0000374)
        self.sidemenu.close()
        self.sidemenu.timer.Stop()
        if self.restore_bounds is not None:
            self.stored_rect = list(self.restore_bounds)
        elif self.IsIconized() is False and self.IsMaximized() is False:
            self.stored_rect = list(self.GetRect())
        self.store_settings()
        event.Skip()


def launch_mainapp():
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    apply_titlebar_theme(frame, THEMES[frame.theme_name])
    app.MainLoop()
