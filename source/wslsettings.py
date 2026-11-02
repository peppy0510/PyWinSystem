# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import json
import os


# the boot tasks read this too, so it may not import wx through utilities
FOLDER = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'PyWinSystem')
PATH = os.path.join(FOLDER, 'wsl.json')
STATE_PATH = os.path.join(FOLDER, 'wsl-state.json')
LOG_PATH = os.path.join(FOLDER, 'wsl.log')

RESUME_ACTIONS = ('restart', 'heal', 'none')

# nothing is published until a port is added
DEFAULTS = {
    # empty follows the default distribution of wsl.exe
    'distribution': '',
    # forwarded in NAT mode, opened in both modes
    'ports': [],
    # opened without forwarding, such as a reverse proxy on Windows
    'firewall_ports': [],
    # empty picks the address of the adapter that holds the default route
    'external_address': '',
    # a static address inside WSL in NAT mode, outside the LAN subnet
    'binding_address': '192.168.100.1',
    'vethernet_address': '192.168.100.2',
    'startup_commands': [],
    'resume_action': 'restart',
    'resume_probe_host': '',
    'resume_probe_ports': [],
    'keepalive': False,
}


def read_file(path):
    try:
        with open(path, encoding='utf-8') as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load():
    '''(settings, problems): a stored value of the wrong type falls back to its default.'''
    stored = read_file(PATH)
    settings = dict(DEFAULTS)
    problems = []
    for key, value in stored.items():
        if key not in DEFAULTS:
            problems.append(f'{key} in {PATH} is not a setting')
        elif type(value) is not type(DEFAULTS[key]):
            problems.append(f'{key} in {PATH} must be {type(DEFAULTS[key]).__name__}')
        else:
            settings[key] = value
    return settings, problems


def save(settings):
    changed = {k: v for k, v in settings.items() if k in DEFAULTS and v != DEFAULTS[k]}
    os.makedirs(FOLDER, exist_ok=True)
    with open(PATH, 'w', encoding='utf-8') as file:
        json.dump(changed, file, ensure_ascii=False, indent=2)


def load_state():
    return read_file(STATE_PATH)


def save_state(state):
    os.makedirs(FOLDER, exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as file:
        json.dump(state, file, indent=2)
