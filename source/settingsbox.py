# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os

import energy

from controls import ActionCard
from controls import ChoiceCard
from controls import Panel
from controls import ScrollArea
from controls import SettingCard
from controls import SliderCard

THEMES = (('auto', 'Auto'), ('light', 'Light'), ('dark', 'Dark'))
INTERVALS = ((1, '1 s'), (2, '2 s'), (5, '5 s'))
PLANS = (('kr_home', 'KR home'), ('kr_flat', 'KR flat'), ('us', 'US'), ('jp', 'JP'))


class SettingsBox(ScrollArea):

    def __init__(self, parent, theme, settings, on_change, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        board = self.content

        self.ontop = SettingCard(board, theme, 'Always on top', 'Keep the window above others',
                                 on_change)
        self.tray = SettingCard(board, theme, 'Tray icon', 'Show an icon in the notification area',
                                on_change)
        self.close_to_tray = SettingCard(board, theme, 'Close to tray',
                                         'Closing hides the window instead of quitting', on_change)
        self.theme_choice = ChoiceCard(board, theme, 'Theme', 'Auto follows Windows',
                                       THEMES, on_change)
        self.interval = ChoiceCard(board, theme, 'Refresh', 'How often the numbers update',
                                   INTERVALS, on_change)

        self.plan = ChoiceCard(board, theme, 'Plan', 'Prices come from tariffs.json',
                               PLANS, on_change)
        self.household = SliderCard(board, theme, 'Rest of the home',
                                    'kWh a month without this PC, for stepped prices',
                                    (0, 2000, 10, 0), on_change, default=250)
        self.other = SliderCard(board, theme, 'Other parts',
                                'Watts the counters miss: board, memory, drives, fans',
                                (0, 400, 5, 0), on_change, default=40)
        self.efficiency = SliderCard(board, theme, 'Power supply efficiency',
                                     'Percent of wall power that reaches the parts',
                                     (50, 100, 1, 0), on_change, default=90)
        self.rates = ActionCard(board, theme, 'Rates', 'Edit the prices; changes apply at once',
                                'Open', self.open_rates)

        self.ontop.SetValue(settings.get('on_top', False))
        self.plan.SetValue(settings.get('plan', 'kr_home'))
        self.household.SetValue(settings.get('household_kwh', 250))
        self.other.SetValue(settings.get('other_watts', 40))
        self.efficiency.SetValue(settings.get('psu_efficiency', 90))
        self.tray.SetValue(settings.get('tray_icon', True))
        self.close_to_tray.SetValue(settings.get('close_to_tray', False))
        self.theme_choice.SetValue(settings.get('theme', 'dark'))
        self.interval.SetValue(settings.get('interval', 1))

        self.set_panels([
            Panel(board, theme, 'settings.window', 'Window',
                  (self.ontop, self.tray, self.close_to_tray), self.folds, self.on_fold),
            Panel(board, theme, 'settings.appearance', 'Appearance', (self.theme_choice,),
                  self.folds, self.on_fold),
            Panel(board, theme, 'settings.sampling', 'Sampling', (self.interval,), self.folds,
                  self.on_fold),
            Panel(board, theme, 'settings.electricity', 'Electricity',
                  (self.plan, self.household, self.other, self.efficiency, self.rates),
                  self.folds, self.on_fold),
        ])
        self.bind_children()
        self.apply_theme(theme)

    def get_values(self):
        return {'on_top': self.ontop.GetValue(), 'tray_icon': self.tray.GetValue(),
                'close_to_tray': self.close_to_tray.GetValue(),
                'theme': self.theme_choice.GetValue(), 'interval': self.interval.GetValue(),
                'plan': self.plan.GetValue(), 'household_kwh': self.household.GetValue(),
                'other_watts': self.other.GetValue(),
                'psu_efficiency': self.efficiency.GetValue()}

    def open_rates(self):
        energy.load_tariffs()
        try:
            os.startfile(energy.TARIFF_PATH)
        except OSError:
            pass

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

    def tick(self):
        pass
