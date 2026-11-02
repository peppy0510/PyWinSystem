# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import threading

import wx

import gamma
import monitors
import monitortask

from controls import Panel
from controls import ScrollArea
from displays import DisplayManager
from meters import ValueCard
from monitorbox import MonitorBox
from utilities import call_painted


# a slider drag saves and updates the restore task once it settles
SAVE_DELAY_MS = 600


class MonitorsPage(wx.Panel):
    '''Holds the Monitors page. DDC/CI answers slowly, about 4 seconds a monitor the first
    time, so the monitors are read when the page first opens, not when the app starts.'''

    def __init__(self, parent, theme, settings, folds, on_change, on_fold=None):
        super().__init__(parent)
        self.theme = theme
        self.folds = folds
        self.on_change = on_change
        self.on_fold = on_fold
        self.stored = settings.get('monitors') or {}
        self.capabilities = settings.get('capabilities') or {}
        self.manager = None
        self.box = None
        self.loading = False
        self.saver = None

        self.waiting = ScrollArea(self, theme)
        card = ValueCard(self.waiting.content, theme, 'Reading the monitors…',
                         'DDC/CI answers slowly the first time', '')
        self.waiting.set_panels([Panel(self.waiting.content, theme, 'monitors.reading',
                                       'Monitors', (card,), set(), None)])
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.waiting, 1, wx.EXPAND)
        self.SetSizer(self.sizer)
        self.apply_theme(theme)

    def set_active(self, active):
        if active and self.manager is None and not self.loading:
            self.load()

    def load(self):
        self.loading = True

        def work():
            manager = DisplayManager()
            try:
                manager.refresh(self.capabilities)
            except Exception:
                manager.release()
            call_painted(self, self.show, manager)
        threading.Thread(target=work, daemon=True).start()

    def show(self, manager):
        if not self:
            manager.close()
            return
        self.loading = False
        self.manager = manager
        manager.load(self.stored)
        manager.apply_software()
        self.box = MonitorBox(self, self.theme, manager.displays, self.folds, self.changed,
                              self.on_fold)
        self.sizer.Replace(self.waiting, self.box)
        self.waiting.Destroy()
        self.waiting = None
        self.Layout()
        self.capabilities = manager.store_capabilities()

    def changed(self):
        if self.saver is not None and self.saver.IsRunning():
            self.saver.Stop()
        self.saver = wx.CallLater(SAVE_DELAY_MS, self.save)

    def save(self):
        if self.manager is None:
            return
        self.stored = self.manager.store()
        self.capabilities = self.manager.store_capabilities() or self.capabilities
        self.on_change()
        stored = dict(self.stored)
        threading.Thread(target=monitortask.sync, args=(stored,), daemon=True).start()

    def get_state(self):
        return {'monitors': self.stored, 'capabilities': self.capabilities}

    def reset_all(self):
        if self.manager is not None:
            self.manager.reset_software()
            self.box.on_reset()
        else:
            # not read yet: every screen goes back to untouched all the same
            for info in monitors.read_monitors():
                handle = gamma.open_device(info['device'])
                gamma.reset(handle)
                gamma.close_device(handle)
        self.stored = {}
        self.on_change()
        threading.Thread(target=monitortask.sync, args=({},), daemon=True).start()

    def apply_theme(self, theme):
        self.theme = theme
        self.SetBackgroundColour(wx.Colour(theme['bg']))
        for page in (self.waiting, self.box):
            if page is not None:
                page.apply_theme(theme) if page is self.box else page.set_theme(theme)
        if self.waiting is not None:
            for child in self.waiting.content.GetChildren():
                if hasattr(child, 'set_theme'):
                    child.set_theme(theme)
        self.Refresh()

    def close(self):
        if self.saver is not None and self.saver.IsRunning():
            self.saver.Stop()
            self.save()
        if self.manager is not None:
            self.manager.close()

    def tick(self):
        pass
