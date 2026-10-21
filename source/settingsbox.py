# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


from controls import ChoiceCard
from controls import Panel
from controls import ScrollArea
from controls import SettingCard

THEMES = (('auto', 'Auto'), ('light', 'Light'), ('dark', 'Dark'))
INTERVALS = ((1, '1 s'), (2, '2 s'), (5, '5 s'))


class SettingsBox(ScrollArea):

    def __init__(self, parent, theme, settings, on_change, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        board = self.content

        self.ontop = SettingCard(board, theme, 'Always on top', 'Keep the window above others',
                                 on_change)
        self.theme_choice = ChoiceCard(board, theme, 'Theme', 'Auto follows Windows',
                                       THEMES, on_change)
        self.interval = ChoiceCard(board, theme, 'Refresh', 'How often the numbers update',
                                   INTERVALS, on_change)

        self.ontop.SetValue(settings.get('on_top', False))
        self.theme_choice.SetValue(settings.get('theme', 'dark'))
        self.interval.SetValue(settings.get('interval', 1))

        self.set_panels([
            Panel(board, theme, 'settings.window', 'Window', (self.ontop,), self.folds,
                  self.on_fold),
            Panel(board, theme, 'settings.appearance', 'Appearance', (self.theme_choice,),
                  self.folds, self.on_fold),
            Panel(board, theme, 'settings.sampling', 'Sampling', (self.interval,), self.folds,
                  self.on_fold),
        ])
        self.bind_children()
        self.apply_theme(theme)

    def get_values(self):
        return {'on_top': self.ontop.GetValue(), 'theme': self.theme_choice.GetValue(),
                'interval': self.interval.GetValue()}

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
