# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

One-off move from wsl-service, the command line tool this WSL page grew out of. Nothing else
in the app imports this module; it runs only from --wsl migrate.
'''


import json
import os
import re

import wslmanager
import wslnet
import wslsettings

from wslshell import log
from wslshell import powershell
from wslshell import quote
from wslshell import run


TASKS = ('WSLService', 'WSL-Resume', 'WSL-Boot')
RULES = ('+WSLTCP', '+WSLUDP')
SHORTCUT = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu',
                        'Programs', 'WSL Restart.lnk')
SCRIPT = re.compile(r'"?([^"]*?)[\\/]source[\\/]wslservice\.py"?', re.IGNORECASE)

FIND = '''
$t = Get-ScheduledTask -TaskName 'WSLService' -ErrorAction SilentlyContinue
if ($t) { $t.Actions | ForEach-Object { $_.Arguments } }
'''

REMOVE_HYPERV = '''
if (Get-Command Remove-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {{
    Remove-NetFirewallHyperVRule -Name {names} -ErrorAction SilentlyContinue
}}
'''


def find_folder(given=None):
    '''The wsl-service folder: the one given, or the one its boot task runs from.'''
    if given:
        return given if os.path.exists(os.path.join(given, 'source', 'settings.json')) else None
    code, output = powershell(FIND)
    for line in output.split('\n'):
        found = SCRIPT.search(line.strip())
        if found and os.path.exists(os.path.join(found.group(1), 'source', 'settings.json')):
            return found.group(1)
    return None


def read_commented_json(path):
    with open(path, 'rb') as file:
        lines = file.read().decode('utf-8').split('\n')
    return json.loads('\n'.join(v for v in lines if not v.strip().startswith('//')))


def read_old_settings(folder):
    settings = read_commented_json(os.path.join(folder, 'source', 'settings.json'))
    own = os.path.join(folder, 'settings.json')
    if os.path.exists(own):
        # a key there replaces the default as a whole, as wsl-service 0.3 does
        settings.update(read_commented_json(own))
    return settings


def convert(old):
    '''(our settings, notes) from the wsl-service keys.'''
    notes = []
    ports = sorted(set(old.get('PROXY_FORWARDING_TCP_PORTS', [])))
    udp = sorted(set(old.get('PROXY_FORWARDING_UDP_PORTS', []) +
                     old.get('SOURCE_INSERTED_PROXY_FORWARDING_UDP_PORTS', [])))
    extra = set(old.get('FIREWALL_ALLOWED_PORTS', [])) | set(udp)
    settings = dict(wslsettings.DEFAULTS)
    settings.update({
        'distribution': old.get('DISTRIBUTION', ''),
        'ports': ports,
        'firewall_ports': sorted(extra - set(ports)),
        'external_address': old.get('EXTERNAL_ADDRESS', ''),
        'binding_address': old.get('BINDING_ADDRESS', settings['binding_address']),
        'vethernet_address': old.get('VETHERNET_ADDRESS', settings['vethernet_address']),
        'startup_commands': old.get('INITD_EXECUTES', []),
        'resume_action': old.get('RESUME_ACTION', 'restart'),
        'resume_probe_host': old.get('RESUME_PROBE_HOST', ''),
        'resume_probe_ports': old.get('RESUME_PROBE_PORTS', []),
        'keepalive': bool(old.get('KEEPALIVE', False)),
    })
    found = wslmanager.get_distributions()
    names = [name for name, version, default in found]
    if settings['distribution'] not in names:
        notes.append(f'{settings["distribution"]} is not installed, the default distribution '
                     'is used instead')
        settings['distribution'] = ''
    # wsl-service had to name it; the default one is better followed than pinned
    elif any(name == settings['distribution'] and default for name, version, default in found):
        settings['distribution'] = ''
    if udp and wslmanager.get_mode() == 'nat':
        notes.append(f'UDP {", ".join(map(str, udp))} stay opened on the firewall, but are not '
                     'relayed into WSL any more')
    if old.get('INITD_SERVICES'):
        notes.append('INITD_SERVICES is left behind; wsl-service no longer applied it either')
    mode = str(old.get('NETWORK_MODE', 'portproxy')).lower()
    if (mode == 'mirrored') != (wslmanager.get_mode() == 'mirrored'):
        notes.append(f'wsl-service was set to {mode}; the mode now follows .wslconfig '
                     f'({wslmanager.get_mode()})')
    return settings, notes


def get_leftovers():
    '''What wsl-service registered that is still on this machine.'''
    code, output = powershell(
        f"foreach ($n in {', '.join(quote(v) for v in TASKS)}) {{ "
        "if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) { $n } }")
    tasks = [v.strip() for v in output.split('\n') if v.strip() in TASKS]
    names = ', '.join(quote(v) for v in RULES)
    code, output = powershell(
        f'(Get-NetFirewallRule -DisplayName {names} -ErrorAction SilentlyContinue).DisplayName; '
        'if (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue) { '
        f'(Get-NetFirewallHyperVRule -Name {names} -ErrorAction SilentlyContinue).Name }}')
    rules = sorted({v.strip() for v in output.split('\n') if v.strip() in RULES})
    return {'tasks': tasks, 'rules': rules, 'shortcut': os.path.exists(SHORTCUT)}


def migrate(given=None, preview=False):
    '''(lines to show, succeeded). Needs elevation unless previewing.'''
    lines = []
    folder = find_folder(given)
    if folder is None:
        return ['wsl-service was not found; give its folder after --wsl migrate'], False
    lines.append(f'wsl-service in {folder}')
    settings, notes = convert(read_old_settings(folder))
    changed = {k: v for k, v in settings.items() if v != wslsettings.DEFAULTS[k]}
    lines.append(f'Settings for {wslsettings.PATH}: {json.dumps(changed)}')
    if os.path.exists(wslsettings.PATH):
        lines.append(f'{wslsettings.PATH} exists and is kept as wsl.json.bak')
    lines += [f'Note: {note}' for note in notes]
    lines += [f'Then: {step}' for step in wslmanager.apply(settings, preview=True)]
    leftovers = get_leftovers()
    if leftovers['tasks']:
        lines.append(f'Remove the wsl-service tasks {", ".join(leftovers["tasks"])}')
    if leftovers['rules']:
        lines.append(f'Remove the wsl-service firewall rules {", ".join(leftovers["rules"])}')
    if leftovers['shortcut']:
        lines.append(f'Remove the shortcut {SHORTCUT}')
    lines.append(f'The folder {folder} stays; delete it yourself when this works')
    if preview:
        return lines, True

    if os.path.exists(wslsettings.PATH):
        os.replace(wslsettings.PATH, wslsettings.PATH + '.bak')
    wslsettings.save(settings)
    # ours open before theirs close, so the ports never go dark in between
    wslmanager.apply(settings)
    for name in leftovers['tasks']:
        run(['schtasks', '/Delete', '/TN', name, '/F'])
    for name in leftovers['rules']:
        run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={name}'])
    if leftovers['rules']:
        powershell(REMOVE_HYPERV.format(names=', '.join(quote(v) for v in RULES)))
    old_ports = {(a, p) for a, p, c, cp in wslnet.get_portproxy()
                 if p in settings['ports']} - {tuple(v) for v in
                                               wslsettings.load_state().get('portproxy', [])}
    wslnet.delete_portproxy(sorted(old_ports))
    if leftovers['shortcut']:
        os.remove(SHORTCUT)
    log(f'migrated from wsl-service in {folder}')
    left = get_leftovers()
    if left['tasks'] or left['rules'] or left['shortcut']:
        lines.append(f'Still there: {left}')
        return lines, False
    lines.append('Done; the WSL page shows the result')
    return lines, True
