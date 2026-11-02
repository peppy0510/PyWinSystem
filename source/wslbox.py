# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import math
import os
import re
import subprocess
import threading
import time

import psutil
import wx

import wslcli
import wslconfig
import wslmanager
import wslsettings
import wsltasks

from controls import ActionCard
from controls import ChoiceCard
from controls import Panel
from controls import ScrollArea
from controls import SettingCard
from controls import SliderCard
from controls import get_button_width
from meters import BUSY_DELAY
from meters import ValueCard
from utilities import call_painted
from wslcards import HOST_KEYS
from wslcards import PORT_KEYS
from wslcards import TextCard
from wslshell import is_admin
from wslshell import log


# a status read takes seconds, so the page asks again only now and then
REFRESH_MS = 30000
CONFIRM_MS = 3000
PROBLEM_MS = 6000
# a slider drag writes .wslconfig once it settles, not on every step
CONFIG_DELAY_MS = 700

READ_NOTE = 'Reads WSL, the tasks and the firewall; never starts WSL'
RESTART_NOTE = 'Shuts every distribution down, also ones another tool keeps running'
RESTART_CONFIG_NOTE = 'Restart to use the changed .wslconfig or wsl.conf'
REMOVE_NOTE = 'Takes our firewall rules, forwarding and tasks away; the settings stay'

TASK_LABELS = ((wsltasks.BOOT, 'Boot task', 'Starts WSL, publishes the ports, runs the commands'),
               (wsltasks.RESUME, 'Resume task', 'Recovers WSL after sleep'),
               (wsltasks.KEEPALIVE, 'Keepalive task', 'Holds the distribution without a logon'))

ACTIONS = {
    'restart': ('Restart', 'Restarting', wslmanager.restart),
    'apply': ('Apply', 'Applying', wslmanager.apply),
    'uninstall': ('Remove', 'Removing', wslmanager.uninstall),
}

SWITCH = (('', 'Default'), ('true', 'On'), ('false', 'Off'))

# key: (section, label, description, kind, options); a value equal to WSL's own default is
# removed from the file rather than written
CONFIG_CARDS = (
    ('networkingMode', 'wsl2', 'Networking', 'Mirrored shares the host network',
     (('nat', 'NAT'), ('mirrored', 'Mirrored'))),
    ('memory', 'wsl2', 'Memory', 'GB for the VM; the default is half the RAM', 'memory'),
    ('processors', 'wsl2', 'Processors', 'Logical processors; the default is all', 'processors'),
    ('swap', 'wsl2', 'Swap', 'GB, 0 turns it off; the default is a quarter of the RAM', 'swap'),
    ('dnsTunneling', 'wsl2', 'DNS tunneling', 'Answers DNS through Windows', SWITCH),
    ('vmIdleTimeout', 'wsl2', 'Idle shutdown', 'Never keeps an idle VM running',
     (('', 'Default'), ('-1', 'Never'))),
    ('hostAddressLoopback', 'experimental', 'Host address loopback',
     'Mirrored: Windows reaches WSL by the LAN address', SWITCH),
    ('autoMemoryReclaim', 'experimental', 'Memory reclaim', 'Returns cached memory',
     (('', 'Default'), ('disabled', 'Off'), ('gradual', 'Gradual'),
      ('dropcache', 'Drop cache'))),
)

USER_KEYS = HOST_KEYS.lower()

# /etc/wsl.conf of the distribution: (section, key, label, description, kind)
WSL_CONF_CARDS = (
    ('boot', 'systemd', 'systemd', 'Starts systemd as the first process', SWITCH),
    ('interop', 'enabled', 'Windows programs', 'Runs .exe files from Linux', SWITCH),
    ('interop', 'appendWindowsPath', 'Windows PATH', 'Adds the Windows PATH to $PATH', SWITCH),
    ('automount', 'enabled', 'Mount drives', 'Mounts the Windows drives under /mnt', SWITCH),
    ('network', 'generateHosts', 'Generate hosts', 'Rewrites /etc/hosts at start', SWITCH),
    ('network', 'generateResolvConf', 'Generate resolv.conf',
     'Rewrites /etc/resolv.conf at start', SWITCH),
    ('network', 'hostname', 'Host name', 'Empty keeps the Windows name', HOST_KEYS),
    ('user', 'default', 'Default user', 'Empty keeps the user made at install', USER_KEYS),
)


def join(ports):
    return ', '.join(str(v) for v in ports) if ports else 'none'


def parse_ports(text):
    return sorted({int(v) for v in re.findall(r'\d+', text)})


def parse_gigabytes(text):
    found = re.match(r'^\s*(\d+(?:\.\d+)?)\s*([KMGT]?B)?\s*$', text or '', re.IGNORECASE)
    if not found:
        return None
    scale = {'KB': 1 / 1024 ** 2, 'MB': 1 / 1024, 'GB': 1, 'TB': 1024}
    return float(found.group(1)) * scale.get((found.group(2) or 'GB').upper(), 1)


class WslBox(ScrollArea):

    def __init__(self, parent, theme, folds=None, on_fold=None):
        super().__init__(parent, theme)
        self.folds = folds if folds is not None else set()
        self.on_folds = on_fold
        self.status = None
        self.waiting = None
        self.reading = False
        self.read_again = False
        self.active = False
        self.busy = None
        self.confirming = False
        self.read_at = 0
        self.config_backed_up = False
        self.config_changed = False
        self.pending_config = {}
        self.wsl_conf_written_at = 0

        ram = psutil.virtual_memory().total / 1024 ** 3
        self.defaults = {'memory': max(1, round(ram / 2)), 'processors': os.cpu_count() or 1,
                         'swap': max(1, math.ceil(ram / 4))}
        self.bounds = {'memory': (1, max(2, round(ram)), 1, 0),
                       'processors': (1, os.cpu_count() or 1, 1, 0),
                       'swap': (0, max(2, round(ram)), 1, 0)}

        board = self.content
        self.read_card = ActionCard(board, theme, 'Status', READ_NOTE, 'Read again', self.read)
        self.read_card.set_captions('Reading')
        self.cards = {}
        for action, (caption, working, function) in ACTIONS.items():
            card = ActionCard(board, theme, '', '', caption, lambda a=action: self.run(a))
            card.set_captions(working, 'Confirm')
            self.cards[action] = card
        self.cards['restart'].label = 'Restart WSL'
        self.cards['restart'].description = RESTART_NOTE
        self.cards['apply'].label = 'Apply settings'
        self.cards['uninstall'].label = 'Remove from Windows'
        self.cards['uninstall'].description = REMOVE_NOTE
        self.cards['uninstall'].set_tone('warn')
        self.log_card = ActionCard(board, theme, 'Log', '', 'Open', self.open_log)
        self.settings_cards = self.make_settings_cards()
        self.config_cards = self.make_config_cards()
        self.wsl_conf_cards = self.make_wsl_conf_cards()
        self.kept = ([self.read_card, self.log_card] + list(self.cards.values()) +
                     list(self.settings_cards.values()) + list(self.config_cards.values()) +
                     list(self.wsl_conf_cards.values()))

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.config_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.write_config, self.config_timer)
        self.build()

    def make_settings_cards(self):
        board, theme = self.content, self.theme

        def text(key, label, description, keys, placeholder='none'):
            return TextCard(board, theme, label, description,
                            lambda value: self.store(key, value), keys, placeholder)
        return {
            'distribution': ChoiceCard(board, theme, 'Distribution', 'Default follows wsl.exe',
                                       (('', 'Default'),), self.on_distribution),
            'ports': text('ports', 'Ports', 'Opened, and forwarded in NAT mode', PORT_KEYS),
            'firewall_ports': text('firewall_ports', 'Firewall only',
                                   'Opened without forwarding, for a proxy on Windows',
                                   PORT_KEYS),
            'listening': ActionCard(board, theme, 'Listening, not published', '', 'Add all',
                                    self.add_listening),
            'keepalive': SettingCard(board, theme, 'Keepalive',
                                     'Keeps the distribution running without a logon',
                                     lambda: self.store('keepalive', None)),
            'resume_action': ChoiceCard(board, theme, 'After sleep',
                                        'Heal repairs only the part that broke',
                                        (('restart', 'Restart'), ('heal', 'Heal'),
                                         ('none', 'None')),
                                        lambda: self.store('resume_action', None)),
            'resume_probe_ports': text('resume_probe_ports', 'Probe ports',
                                       'Connected from Windows after sleep',
                                       PORT_KEYS),
            'resume_probe_host': text('resume_probe_host', 'Probe host',
                                      'Looked up inside WSL after sleep', HOST_KEYS),
            'more': ActionCard(board, theme, 'More settings',
                               'Startup commands and NAT addresses live in wsl.json', 'Open',
                               self.open_settings),
        }

    def make_config_cards(self):
        board, theme = self.content, self.theme
        cards = {}
        for key, section, label, description, kind in CONFIG_CARDS:
            def changed(key=key, section=section):
                self.queue_config(key, section)
            if isinstance(kind, str):
                cards[key] = SliderCard(board, theme, label, description, self.bounds[kind],
                                        changed, default=self.defaults[kind])
            else:
                cards[key] = ChoiceCard(board, theme, label, description, kind, changed)
        cards['open'] = ActionCard(board, theme, '.wslconfig', wslconfig.get_path(), 'Open',
                                   self.open_config)
        return cards

    def make_wsl_conf_cards(self):
        board, theme = self.content, self.theme
        cards = {}
        for section, key, label, description, kind in WSL_CONF_CARDS:
            if isinstance(kind, str):
                cards[f'{section}.{key}'] = TextCard(
                    board, theme, label, description,
                    lambda value, s=section, k=key: self.write_wsl_conf({(s, k): value or None}),
                    kind, 'default')
            else:
                card = ChoiceCard(board, theme, label, description, kind)
                card.on_change = lambda c=card, s=section, k=key: self.write_wsl_conf(
                    {(s, k): c.GetValue() or None})
                cards[f'{section}.{key}'] = card
        return cards

    def write_wsl_conf(self, changes):
        distribution = (self.status or {}).get('distribution')
        if not distribution:
            return

        def work():
            problem = wslmanager.write_wsl_conf(distribution, changes)
            call_painted(self, self.finish_wsl_conf, changes, problem)
        threading.Thread(target=work, daemon=True).start()

    def finish_wsl_conf(self, changes, problem):
        if not self:
            return
        if problem is None:
            self.wsl_conf_written_at = time.monotonic()
            self.config_changed = True
        else:
            # nothing was written, so the next read puts the old value back in the card
            for section, key in changes:
                card = self.wsl_conf_cards[f'{section}.{key}']
                note = card.description
                card.description = f'Not saved: {problem}'
                card.Refresh()
                wx.CallLater(PROBLEM_MS, self.restore_note, card, note)
                if isinstance(card, TextCard):
                    card.text = None
        self.read()

    def restore_note(self, card, note):
        if card:
            card.description = note
            card.Refresh()

    def is_editing(self):
        for card in list(self.settings_cards.values()) + list(self.wsl_conf_cards.values()):
            if isinstance(card, TextCard) and card.is_editing():
                return True
        for card in self.config_cards.values():
            if isinstance(card, SliderCard) and (card.dragging or card.entry is not None):
                return True
        return False

    def set_active(self, active):
        self.active = active
        if active:
            self.timer.Start(REFRESH_MS)
            if time.monotonic() - self.read_at > 2:
                self.read()
        else:
            self.timer.Stop()

    def on_timer(self, event):
        if self.active and self.IsShownOnScreen() and not self.is_editing():
            self.read()

    def read(self):
        # a change made while a read runs is read once more when that one lands
        if self.reading:
            self.read_again = True
            return
        self.reading = True
        self.read_again = False
        wx.CallLater(BUSY_DELAY, self.show_reading)
        started = time.monotonic()

        def work():
            try:
                status = wslmanager.get_status()
            except Exception as error:
                status = {'problems': [f'Could not read the status: {error}'], 'failed': True}
            status['read_started'] = started
            call_painted(self, self.set_status, status)
        threading.Thread(target=work, daemon=True).start()

    def show_reading(self):
        if self and self.reading:
            self.read_card.set_caption('Reading')

    def set_status(self, status):
        if not self:
            return
        self.reading = False
        self.read_at = time.monotonic()
        self.read_card.set_caption('Read again')
        self.status = status
        if self.read_again:
            self.read()
        # a rebuild would take the field away under the typing
        if self.is_editing():
            wx.CallLater(1000, self.retry_build)
            return
        self.build()

    def retry_build(self):
        if not self:
            return
        if self.is_editing():
            wx.CallLater(1000, self.retry_build)
            return
        self.build()

    def store(self, key, value):
        settings = wslsettings.load()[0]
        card = self.settings_cards[key]
        if key in ('ports', 'firewall_ports', 'resume_probe_ports'):
            value = parse_ports(value)
            card.SetValue(', '.join(map(str, value)))
        elif key in ('keepalive', 'resume_action'):
            value = card.GetValue()
        settings[key] = value
        wslsettings.save(settings)
        self.read()

    def on_distribution(self):
        self.store('distribution', self.settings_cards['distribution'].GetValue())

    def add_listening(self):
        status = self.status or {}
        listening = (status.get('listening') or {}).get('tcp') or []
        settings = wslsettings.load()[0]
        missing = [v for v in listening if v not in settings['ports']]
        if missing:
            self.store('ports', ', '.join(map(str, settings['ports'] + missing)))

    def queue_config(self, key, section):
        card = self.config_cards[key]
        value = card.GetValue()
        if isinstance(card, SliderCard):
            if value == self.defaults[key]:
                value = None
            elif key in ('memory', 'swap'):
                value = f'{value}GB'
        elif key == 'networkingMode' and value == 'nat':
            value = None
        self.pending_config[(section, key)] = value or None
        self.config_timer.StartOnce(CONFIG_DELAY_MS)

    def write_config(self, event=None, read=True):
        if not self.pending_config:
            return
        changes, self.pending_config = self.pending_config, {}
        try:
            # the file as it was before this run of the app stays in .wslconfig.bak
            wslconfig.write(changes, backup=not self.config_backed_up)
            self.config_backed_up = True
            self.config_changed = True
            log(f'.wslconfig {changes}')
        except OSError as error:
            self.config_cards['open'].set_description(f'Could not write: {error}')
        if read:
            self.read()

    def run(self, action):
        if self.busy or self.reading:
            return
        caption, working, function = ACTIONS[action]
        card = self.cards[action]
        if action == 'uninstall' and not self.confirming:
            self.confirming = True
            card.set_caption('Confirm')
            wx.CallLater(CONFIRM_MS, self.end_confirm)
            return
        self.end_confirm()
        self.busy = action
        card.set_caption(working)
        settings = wslsettings.load()[0]
        elevate = wslmanager.needs_admin(action, settings) and not is_admin()

        def work():
            try:
                if elevate:
                    done = wslcli.relaunch_as_admin([action], wait=True)
                else:
                    function()
                    done = True
            except Exception as error:
                log(f'{action} failed: {error}')
                done = False
            call_painted(self, self.finish, action, done)
        threading.Thread(target=work, daemon=True).start()

    def end_confirm(self):
        if self and self.confirming:
            self.confirming = False
            self.cards['uninstall'].set_caption(ACTIONS['uninstall'][0])

    def finish(self, action, done):
        if not self:
            return
        self.busy = None
        self.cards[action].set_caption(ACTIONS[action][0])
        if action == 'restart' and done:
            self.config_changed = False
        if not done:
            self.cards[action].set_description('Not done, the administrator prompt was refused')
        self.read()

    # the tray asks for these by name, greyed while something runs
    def restart(self):
        self.run('restart')

    def apply(self):
        self.run('apply')

    def is_busy(self):
        return bool(self.busy)

    def open_file(self, path, card):
        if not os.path.exists(path):
            card.set_description('Nothing there yet')
            return
        # .json and .wslconfig often have no program attached, so ask for Notepad by name
        subprocess.Popen(['notepad.exe', path])

    def open_log(self):
        self.open_file(wslsettings.LOG_PATH, self.log_card)

    def open_settings(self):
        if not os.path.exists(wslsettings.PATH):
            wslsettings.save(wslsettings.load()[0])
        self.open_file(wslsettings.PATH, self.settings_cards['more'])

    def open_config(self):
        self.open_file(wslconfig.get_path(), self.config_cards['open'])

    def update_settings_cards(self, status):
        settings = wslsettings.load()[0]
        cards = self.settings_cards
        names = [d['name'] for d in status.get('distributions', [])]
        default = next((d['name'] for d in status.get('distributions', []) if d['default']), '')
        # the default one shows once, as following the default; the others pin a name
        options = (('', f'{default} · default' if default else 'Default'),) + tuple(
            (name, name) for name in names if name != default)
        choice = cards['distribution']
        if options != choice.options:
            choice.options = options
            choice.segment = max(get_button_width(name) for _, name in options)
            choice.relayout()
        pinned = settings['distribution']
        choice.SetValue('' if pinned == default else pinned)
        for key in ('ports', 'firewall_ports', 'resume_probe_ports'):
            cards[key].SetValue(', '.join(map(str, settings[key])))
        cards['resume_probe_host'].SetValue(settings['resume_probe_host'])
        cards['keepalive'].SetValue(settings['keepalive'])
        cards['resume_action'].SetValue(settings['resume_action'])
        listening = (status.get('listening') or {}).get('tcp')
        if listening is None:
            cards['listening'].set_description('Read only while the distribution runs')
        else:
            cards['listening'].set_description(
                join([v for v in listening if v not in settings['ports']]))

    def update_config_cards(self):
        # the file, not the status: a status read may have started before the last write
        config = wslconfig.read()
        for key, section, label, description, kind in CONFIG_CARDS:
            card = self.config_cards[key]
            value = config.get(section, {}).get(key, '')
            if isinstance(card, SliderCard):
                if key == 'processors':
                    number = int(value) if value.strip().isdigit() else None
                else:
                    number = parse_gigabytes(value)
                card.SetValue(self.defaults[key] if number is None else number)
            elif key == 'networkingMode':
                card.SetValue('mirrored' if value.lower() == 'mirrored' else 'nat')
            else:
                known = [option for option, name in kind]
                card.SetValue(value.lower() if value.lower() in known else '')

    def update_wsl_conf_cards(self, status):
        # a read that began before the last write still holds the old file
        if status.get('read_started', 0) < self.wsl_conf_written_at:
            return
        conf = status.get('wsl_conf') or {}
        for section, key, label, description, kind in WSL_CONF_CARDS:
            card = self.wsl_conf_cards[f'{section}.{key}']
            value = conf.get(section, {}).get(key, '')
            if isinstance(card, TextCard):
                card.SetValue(value)
            else:
                known = [option for option, name in kind]
                card.SetValue(value.lower() if value.lower() in known else '')

    def get_state_rows(self, status):
        board, theme = self.content, self.theme
        rows = []
        if status.get('failed'):
            return [self.cards['restart']]
        names = {d['name']: d for d in status['distributions']}
        found = names.get(status['distribution'])
        if found:
            detail = f'Version {found["version"]}' + (' · default' if found['default'] else '')
            state = 'Running' if status['running'] else 'Stopped'
        else:
            detail, state = 'Not installed', '—'
        rows.append(ValueCard(board, theme, status['distribution'] or 'No distribution',
                              detail, state, not found))
        mode = 'Mirrored' if status['mode'] == 'mirrored' else 'NAT'
        rows.append(ValueCard(board, theme, 'Networking', 'networkingMode in .wslconfig', mode))
        if status['keepalive']:
            held = {'task': 'Keepalive task', 'process': 'A wsl.exe process'}.get(
                status['held_by'], 'Nothing')
            rows.append(ValueCard(board, theme, 'Held by', 'Keepalive keeps WSL running', held,
                                  status['running'] and status['held_by'] is None))
        restart = self.cards['restart']
        restart.set_description(RESTART_CONFIG_NOTE if self.config_changed else RESTART_NOTE)
        restart.set_tone('warn' if self.config_changed else 'plain')
        rows.append(restart)
        return rows

    def get_service_rows(self, status):
        board, theme = self.content, self.theme
        rows = []
        tasks = status.get('tasks', {})
        unapplied = [p for p in status.get('problems', []) if 'press Apply' in p]
        for name, label, note in TASK_LABELS:
            state = tasks.get(name, '—')
            if name == wsltasks.KEEPALIVE and not status.get('keepalive') and state == 'Missing':
                continue
            # nothing configured needs no task, so a missing one only warns when Apply would add it
            rows.append(ValueCard(board, theme, label, note,
                                  'Not registered' if state == 'Missing' else state,
                                  state == 'Missing' and bool(unapplied)))
        self.cards['apply'].set_description(unapplied[0].replace(', press Apply', '')
                                            if unapplied else 'The settings are in effect')
        self.cards['apply'].set_tone('warn' if unapplied else 'plain')
        self.log_card.set_description(status.get('last_log') or 'Nothing logged yet')
        rows += [self.cards['apply'], self.cards['uninstall'], self.log_card]
        return rows

    def get_port_rows(self, status):
        board, theme = self.content, self.theme
        if status.get('failed'):
            return []
        opened = status['opened']
        rows = [ValueCard(board, theme, 'Published', join(status['published']),
                          str(len(status['published'])))]
        where = 'Windows and Hyper-V firewalls' if status['mode'] == 'mirrored' \
            else 'Windows firewall'
        rows.append(ValueCard(board, theme, 'Opened', f'{join(opened["windows"])} · {where}',
                              str(len(opened['windows']))))
        if status['mode'] == 'nat':
            forwarded = status.get('forwarded', [])
            rows.append(ValueCard(board, theme, 'Forwarded',
                                  ', '.join(f'{a}:{p} → {c}' for a, p, c, _ in forwarded)
                                  or 'none', str(len(forwarded))))
        listening = status.get('listening')
        if listening is None:
            rows.append(ValueCard(board, theme, 'Listening in WSL',
                                  'Read only while the distribution runs', '—'))
        else:
            rows.append(ValueCard(board, theme, 'Listening in WSL',
                                  f'TCP {join(listening["tcp"])} · UDP {join(listening["udp"])}',
                                  str(len(listening['tcp']) + len(listening['udp']))))
            idle = status.get('idle_ports', [])
            rows.append(ValueCard(board, theme, 'Published, nothing listening', join(idle),
                                  str(len(idle))))
        return rows

    def get_problem_rows(self, status):
        board, theme = self.content, self.theme
        problems = status.get('problems', [])
        if not problems:
            return [ValueCard(board, theme, 'Nothing to fix', '', '')]
        return [ValueCard(board, theme, problem, '', '', True) for problem in problems]

    def build(self):
        for child in list(self.content.GetChildren()):
            if child not in self.kept:
                child.Destroy()
        # the kept cards outlive a rebuild, so free them from the old panels first
        for card in self.kept:
            holder = card.GetContainingSizer()
            if holder is not None:
                holder.Detach(card)
        for card in (list(self.settings_cards.values()) + list(self.config_cards.values()) +
                     list(self.wsl_conf_cards.values())):
            card.Hide()
        board, theme = self.content, self.theme
        panels = []
        status = self.status
        if status is None:
            panels.append(Panel(board, theme, 'wsl.read', 'WSL', (self.read_card,),
                                self.folds, self.on_fold))
        else:
            mode = status.get('mode', '')
            panels.append(Panel(board, theme, 'wsl.state', 'WSL', self.get_state_rows(status),
                                self.folds, self.on_fold,
                                subtitle='Mirrored' if mode == 'mirrored' else mode.upper()))
            panels.append(Panel(board, theme, 'wsl.service', 'Service',
                                self.get_service_rows(status), self.folds, self.on_fold))
            port_rows = self.get_port_rows(status)
            if port_rows:
                panels.append(Panel(board, theme, 'wsl.ports', 'Ports', port_rows, self.folds,
                                    self.on_fold))
            if not status.get('failed'):
                self.update_settings_cards(status)
                self.update_config_cards()
                rows = list(self.settings_cards.values())
                # with one distribution there is nothing to choose
                if len(self.settings_cards['distribution'].options) < 2:
                    rows.remove(self.settings_cards['distribution'])
                panels.append(Panel(board, theme, 'wsl.settings', 'Settings', rows, self.folds,
                                    self.on_fold, subtitle='press Apply after a change'))
                panels.append(Panel(board, theme, 'wsl.config', '.wslconfig',
                                    list(self.config_cards.values()), self.folds, self.on_fold,
                                    subtitle='used after Restart WSL'))
                if status.get('wsl_conf') is not None:
                    self.update_wsl_conf_cards(status)
                    rows = list(self.wsl_conf_cards.values())
                else:
                    rows = [ValueCard(board, theme, 'Read while the distribution runs',
                                      'Starting WSL just to read it is left to you', '')]
                panels.append(Panel(board, theme, 'wsl.conf', '/etc/wsl.conf', rows,
                                    self.folds, self.on_fold,
                                    subtitle=f'in {status.get("distribution", "")}'))
            problems = status.get('problems', [])
            panels.append(Panel(board, theme, 'wsl.problems', 'Problems',
                                self.get_problem_rows(status), self.folds, self.on_fold,
                                subtitle=str(len(problems)) if problems else ''))
            panels.append(Panel(board, theme, 'wsl.read', 'Read', (self.read_card,),
                                self.folds, self.on_fold))
        self.set_panels(panels)
        self.bind_children()
        self.apply_theme(theme)
        self.relayout_panels()

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

    def close(self):
        self.timer.Stop()
        self.config_timer.Stop()
        # a slider let go just before closing still gets written
        self.write_config(read=False)

    def tick(self):
        pass
