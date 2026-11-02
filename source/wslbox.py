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
from monitorbox import GroupRow
from utilities import call_painted
from wslcards import BusyCard
from wslcards import HOST_KEYS
from wslcards import HelpHeader
from wslcards import PORT_KEYS
from wslcards import PortGrid
from wslcards import TextCard
from wslshell import is_admin
from wslshell import log
from wslshell import read_last_log


# a status read takes seconds, so the page asks again only now and then
REFRESH_MS = 30000
CONFIRM_MS = 3000
BUSY_SPIN_MS = 80
PROBLEM_MS = 6000
# the page opens with what the registry and the files tell at once; the rest shows these
PENDING = 'Reading…'
PENDING_VALUE = '…'
# a slider drag writes .wslconfig once it settles, not on every step
CONFIG_DELAY_MS = 700

READ_NOTE = 'Reads WSL and the firewall again; a stopped WSL is not started'
RESTART_NOTE = 'Stops every Linux distribution and starts this one again'
RESTART_CONFIG_NOTE = 'Restart to use the changed settings below'
REMOVE_NOTE = 'Closes the ports and stops the start at boot; your choices here are kept'
# kept folded until it is opened once, so a newcomer meets the everyday settings first
ADVANCED_SEEN = 'wsl.advanced.seen'

HELP_STATE = ('The Linux distribution this page looks after, whether it runs, and how WSL '
              'shares the network of this PC. Restart WSL stops it and starts it again.')
HELP_OPEN = ('Servers you run in WSL wait on ports. Light a port and press Apply, and other '
             'computers and phones on your network reach that server at the address of this PC.')
HELP_START = ('Starts WSL when Windows starts, even before anyone signs in, keeps it running, '
              'and brings it back after sleep. Press Apply after turning it on.')
HELP_ADVANCED = ('What happens after sleep, the state of the service, its log, and settings '
                 'most people never need. The files of WSL itself show below while this is open.')
HELP_CONFIG = ('.wslconfig in your user folder: memory, processors and networking of the WSL '
               'machine, shared by every distribution. Used after Restart WSL.')
HELP_CONF = ('/etc/wsl.conf inside the distribution: systemd, Windows programs and drives, '
             'host name and the default user. Used after Restart WSL.')

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
    ('memory', 'wsl2', 'Memory', 'GB of the {total} GB RAM; the default {default} is half',
     'memory'),
    ('processors', 'wsl2', 'Processors', 'Of the {total} logical processors; the default is all',
     'processors'),
    ('swap', 'wsl2', 'Swap', 'GB, 0 turns it off; the default {default} is a quarter of the RAM',
     'swap'),
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
        try:
            self.status = wslmanager.get_quick_status()
        except Exception:
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
            card = BusyCard(board, theme, '', '', caption, lambda a=action: self.run(a))
            card.set_captions(working, 'Confirm')
            self.cards[action] = card
        self.cards['restart'].label = 'Restart WSL'
        self.cards['restart'].description = RESTART_NOTE
        self.cards['apply'].label = 'Apply changes'
        self.cards['apply'].set_tone('warn')
        self.cards['uninstall'].label = 'Turn the service off'
        self.cards['uninstall'].description = REMOVE_NOTE
        self.cards['uninstall'].set_tone('warn')
        self.log_card = ActionCard(board, theme, 'Log', '', 'Open', self.open_log)
        self.port_grid = PortGrid(board, theme, self.toggle_port)
        if ADVANCED_SEEN not in self.folds:
            self.folds.update({'wsl.advanced', ADVANCED_SEEN})
        self.advanced_folded = self.is_advanced_folded()
        self.settings_cards = self.make_settings_cards()
        self.config_cards = self.make_config_cards()
        self.wsl_conf_cards = self.make_wsl_conf_cards()
        self.kept = ([self.read_card, self.log_card, self.port_grid] + list(self.cards.values()) +
                     list(self.settings_cards.values()) + list(self.config_cards.values()) +
                     list(self.wsl_conf_cards.values()))

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.config_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.write_config, self.config_timer)
        self.busy_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_busy_tick, self.busy_timer)
        self.build()

    def make_settings_cards(self):
        board, theme = self.content, self.theme

        def text(key, label, description, keys, placeholder='none'):
            return TextCard(board, theme, label, description,
                            lambda value: self.store(key, value), keys, placeholder)
        return {
            'add_port': text('add_port', 'Add a port',
                             'Open one that nothing in WSL listens on yet', PORT_KEYS,
                             'port number'),
            'keepalive': SettingCard(board, theme, 'Start with Windows',
                                     'Runs WSL from boot, also before sign-in, and brings it '
                                     'back after sleep',
                                     lambda: self.store('keepalive', None)),
            'resume_action': ChoiceCard(board, theme, 'After sleep',
                                        'Repair fixes only what broke; Restart drops '
                                        'open connections',
                                        (('restart', 'Restart'), ('heal', 'Repair'),
                                         ('none', 'Nothing')),
                                        lambda: self.store('resume_action', None)),
            'resume_probe_ports': text('resume_probe_ports', 'Check these ports',
                                       'Repair connects to them from Windows to see they work',
                                       PORT_KEYS),
            'resume_probe_host': text('resume_probe_host', 'Check this name',
                                      'Repair looks it up inside WSL to see DNS works',
                                      HOST_KEYS),
            'distribution': ChoiceCard(board, theme, 'Distribution',
                                       'The one the ports and the start at boot belong to',
                                       (('', 'Default'),), self.on_distribution),
            'firewall_ports': text('firewall_ports', 'Also open on Windows',
                                   'Ports of a server running on Windows itself, not in WSL',
                                   PORT_KEYS),
            'more': ActionCard(board, theme, 'More settings',
                               'Startup commands and NAT addresses, in wsl.json', 'Open',
                               self.open_settings),
        }

    def make_config_cards(self):
        board, theme = self.content, self.theme
        cards = {}
        for key, section, label, description, kind in CONFIG_CARDS:
            def changed(key=key, section=section):
                self.queue_config(key, section)
            if isinstance(kind, str):
                description = description.format(total=self.bounds[kind][1],
                                                 default=self.defaults[kind])
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
        if key == 'add_port':
            key, value = 'ports', sorted(set(settings['ports']) | set(parse_ports(value)))
            card.SetValue('')
        elif key in ('firewall_ports', 'resume_probe_ports'):
            value = parse_ports(value)
            card.SetValue(', '.join(map(str, value)))
        elif key in ('keepalive', 'resume_action'):
            value = card.GetValue()
        settings[key] = value
        wslsettings.save(settings)
        self.read()

    def toggle_port(self, port, on):
        settings = wslsettings.load()[0]
        ports = set(settings['ports'])
        if on:
            ports.add(port)
        else:
            ports.discard(port)
        settings['ports'] = sorted(ports)
        wslsettings.save(settings)
        self.read()

    def on_distribution(self):
        self.store('distribution', self.settings_cards['distribution'].GetValue())

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
        card.set_busy(True)
        self.busy_note = card.description
        self.busy_started = time.monotonic()
        # log lines from before the press are not this action's steps
        self.busy_stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        self.busy_timer.Start(BUSY_SPIN_MS)
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

    def on_busy_tick(self, event):
        # the step comes from the log, so an elevated run in its own process shows too
        card = self.cards.get(self.busy)
        if card is None:
            self.busy_timer.Stop()
            return
        card.spin()
        elapsed = int(time.monotonic() - self.busy_started)
        line = read_last_log()
        step = line[20:] if line[:19] >= self.busy_stamp else ''
        card.set_description(f'{elapsed} s · {step}' if step else f'{elapsed} s')

    def finish(self, action, done):
        if not self:
            return
        self.busy = None
        self.busy_timer.Stop()
        self.cards[action].set_busy(False)
        self.cards[action].set_description(self.busy_note)
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
        for key in ('firewall_ports', 'resume_probe_ports'):
            cards[key].SetValue(', '.join(map(str, settings[key])))
        cards['resume_probe_host'].SetValue(settings['resume_probe_host'])
        cards['keepalive'].SetValue(settings['keepalive'])
        cards['resume_action'].SetValue(settings['resume_action'])
        return settings

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
        partial = status.get('partial')
        if found:
            detail = f'Version {found["version"]}' + (' · default' if found['default'] else '')
            state = PENDING_VALUE if partial else ('Running' if status['running'] else 'Stopped')
        else:
            detail, state = 'Not installed', '—'
        rows.append(ValueCard(board, theme, status['distribution'] or 'No distribution',
                              detail, state, not found))
        if status['mode'] == 'mirrored':
            mode, note = 'Mirrored', 'WSL shares the network of this PC'
        else:
            mode, note = 'NAT', 'WSL sits behind this PC; ports are forwarded to it'
        rows.append(ValueCard(board, theme, 'Networking', note, mode))
        restart = self.cards['restart']
        # while it runs the card shows the time and the step instead
        if self.busy != 'restart':
            restart.set_description(RESTART_CONFIG_NOTE if self.config_changed else RESTART_NOTE)
        restart.set_tone('warn' if self.config_changed else 'plain')
        rows.append(restart)
        return rows

    def get_unapplied(self, status):
        return [p.replace(', press Apply', '') for p in status.get('problems') or []
                if 'press Apply' in p]

    def get_port_rows(self, status, settings):
        board, theme = self.content, self.theme
        partial = status.get('partial')
        listening = status.get('listening') or (status.get('last_listening') if partial
                                                else None) or {}
        heard = set(listening.get('tcp', [])) | set(listening.get('udp', []))
        names = listening.get('names', {})
        opened = set((status.get('opened') or {}).get('windows', []))
        chosen = set(settings['ports'])
        ports = []
        for port in sorted(chosen | heard):
            name = names.get(str(port))
            on = port in chosen
            warn = False
            # a port nothing listens on leaves the grid once it is off, so off means removed
            gone = port not in heard
            click = 'click to remove it' if gone else 'click to close it'
            if partial:
                note = PENDING
            elif on and port in opened:
                silent = gone and status.get('listening') is not None
                note = ('Open, but nothing in WSL answers on it now' if silent else
                        'Open · other devices can reach it') + f' · {click}'
            elif on:
                note = f'Turned on · Apply opens it · {click}'
            elif port in opened:
                note, warn = 'Turned off · open until Apply', True
            else:
                note = 'Only this PC can reach it · click to open it'
            ports.append({'port': port, 'label': f'{port} {name}' if name else str(port),
                          'on': on, 'warn': warn, 'note': note})
        rows = []
        if not chosen and not settings['firewall_ports'] and not settings['keepalive'] \
                and not partial:
            rows.append(ValueCard(board, theme, 'Get started',
                                  'Light the ports other devices should reach, then press Apply',
                                  ''))
        if ports:
            silent = [p['port'] for p in ports
                      if p['on'] and p['port'] not in heard and status.get('listening') is not None]
            summary = f'{len(chosen)} of {len(ports)} open'
            note = 'Lit ones are open to other devices; click one to turn it on or off'
            if silent and not partial:
                note = (f'Nothing answers on {", ".join(map(str, silent))} now; click one to '
                        'remove it')
            rows.append(ValueCard(board, theme, 'Ports', note, summary))
            # one grid for the page's life, so a refresh does not grow it again from nothing
            self.port_grid.set_ports(ports)
            rows.append(self.port_grid)
        elif partial:
            rows.append(ValueCard(board, theme, PENDING, '', ''))
        elif status.get('running'):
            rows.append(ValueCard(board, theme, 'Nothing in WSL listens for other devices',
                                  'Start a server in WSL, or add a port below', ''))
        else:
            rows.append(ValueCard(board, theme, 'WSL is not running',
                                  'Its servers show here once it runs', ''))
        rows.append(self.settings_cards['add_port'])
        return rows

    def get_advanced_rows(self, status, settings):
        board, theme = self.content, self.theme
        cards = self.settings_cards
        rows = [GroupRow(board, theme, 'After sleep'), cards['resume_action']]
        # the checks only matter to Repair
        if settings['resume_action'] == 'heal':
            rows += [cards['resume_probe_ports'], cards['resume_probe_host']]

        rows.append(GroupRow(board, theme, 'Service'))
        boot = (status.get('tasks') or {}).get(wsltasks.BOOT)
        if boot is None:
            started = PENDING_VALUE
        else:
            started = 'No' if boot == 'Missing' else 'Yes'
        rows.append(ValueCard(board, theme, 'Starts at boot',
                              'Opens the ports and runs the startup commands, set up by Apply',
                              started, boot == 'Missing' and bool(self.get_unapplied(status))))
        if settings['keepalive'] and not status.get('partial'):
            held = {'task': 'Yes', 'process': 'Yes, by another program'}.get(
                status['held_by'], 'No')
            rows.append(ValueCard(board, theme, 'Kept running now',
                                  'Start with Windows holds the distribution', held,
                                  bool(status['running']) and status['held_by'] is None))
        self.log_card.set_description(status.get('last_log') or 'Nothing logged yet')
        rows += [self.cards['uninstall'], self.log_card, self.read_card]

        rows.append(GroupRow(board, theme, 'More'))
        # with one distribution there is nothing to choose
        if len(cards['distribution'].options) > 1:
            rows.append(cards['distribution'])
        rows += [cards['firewall_ports'], cards['more']]
        return rows

    def get_problem_rows(self, status):
        board, theme = self.content, self.theme
        problems = [p for p in status.get('problems') or [] if 'press Apply' not in p]
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
            card.Hide()
        board, theme = self.content, self.theme
        panels = []
        status = self.status
        if status is None or status.get('failed'):
            rows = [ValueCard(board, theme, problem, '', '', True)
                    for problem in (status or {}).get('problems', [])]
            panels.append(Panel(board, theme, 'wsl.state', 'WSL', rows + [self.read_card],
                                self.folds, self.on_fold))
        else:
            settings = self.update_settings_cards(status)
            self.update_config_cards()
            panels.append(self.make_panel('wsl.state', 'WSL', self.get_state_rows(status),
                                          HELP_STATE))
            unapplied = self.get_unapplied(status)
            if unapplied:
                if self.busy != 'apply':
                    self.cards['apply'].set_description(' · '.join(unapplied))
                panels.append(Panel(board, theme, 'wsl.apply', 'Not applied yet',
                                    (self.cards['apply'],), self.folds, self.on_fold))
            problems = self.get_problem_rows(status)
            if problems:
                panels.append(Panel(board, theme, 'wsl.problems', 'Problems', problems,
                                    self.folds, self.on_fold, subtitle=str(len(problems))))
            panels.append(self.make_panel('wsl.open', 'Open to the network',
                                          self.get_port_rows(status, settings), HELP_OPEN))
            panels.append(self.make_panel('wsl.start', 'Start with Windows',
                                          [self.settings_cards['keepalive']], HELP_START))
            panels.append(self.make_panel('wsl.advanced', 'Advanced settings',
                                          self.get_advanced_rows(status, settings),
                                          HELP_ADVANCED))
            # the files of WSL itself show only while Advanced settings is open
            if not self.is_advanced_folded():
                panels.append(self.make_panel('wsl.config', 'WSL settings',
                                              list(self.config_cards.values()), HELP_CONFIG,
                                              '.wslconfig · used after Restart WSL'))
                if status.get('wsl_conf') is not None:
                    self.update_wsl_conf_cards(status)
                    rows = list(self.wsl_conf_cards.values())
                elif status.get('partial'):
                    rows = [ValueCard(board, theme, PENDING, '', '')]
                else:
                    rows = [ValueCard(board, theme, 'Shown while the distribution runs',
                                      'It is not started just to read this', '')]
                panels.append(self.make_panel('wsl.conf', 'Distribution settings', rows,
                                              HELP_CONF, '/etc/wsl.conf in '
                                              f'{status.get("distribution", "")}'))
        self.set_panels(panels)
        self.bind_children()
        self.apply_theme(theme)
        self.relayout_panels()

    def make_panel(self, key, title, rows, help_text, subtitle=''):
        header = HelpHeader(self.content, self.theme, title, subtitle, help_text)
        return Panel(self.content, self.theme, key, title, rows, self.folds, self.on_fold,
                     header=header)

    def is_advanced_folded(self):
        return 'wsl.advanced' in self.folds

    def on_fold(self):
        # opening or closing Advanced settings adds or takes away the panels below it
        if self.is_advanced_folded() != self.advanced_folded:
            self.advanced_folded = self.is_advanced_folded()
            wx.CallAfter(self.build)
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
        self.busy_timer.Stop()
        # a slider let go just before closing still gets written
        self.write_config(read=False)

    def tick(self):
        pass
