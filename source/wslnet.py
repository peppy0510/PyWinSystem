# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import re

from wslshell import powershell
from wslshell import quote
from wslshell import run


RULE = 'PyWinSystem WSL'
GROUP = 'PyWinSystem'
PROTOCOLS = ('TCP', 'UDP')
# the id WSL registers its virtual machine with on the Hyper-V firewall
HYPERV_VM_CREATOR_ID = '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'

ADDRESS = re.compile(r'^\d+(?:\.\d+){3}$')

# the cmdlets name every rule they cannot find, so missing ones are asked for quietly
QUERY = '''
foreach ($p in 'TCP', 'UDP') {{
    $r = Get-NetFirewallRule -Name ({rule} + ' ' + $p) -ErrorAction SilentlyContinue
    if ($r) {{ 'windows|' + (($r | Get-NetFirewallPortFilter).LocalPort -join ',') }}
    if (Get-Command Get-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {{
        $h = Get-NetFirewallHyperVRule -Name ({rule} + ' ' + $p) -ErrorAction SilentlyContinue
        if ($h) {{ 'hyperv|' + ($h.LocalPorts -join ',') }}
    }}
}}
'''

REMOVE = '''
foreach ($p in 'TCP', 'UDP') {{
    Remove-NetFirewallRule -Name ({rule} + ' ' + $p) -ErrorAction SilentlyContinue
    if (Get-Command Remove-NetFirewallHyperVRule -ErrorAction SilentlyContinue) {{
        Remove-NetFirewallHyperVRule -Name ({rule} + ' ' + $p) -ErrorAction SilentlyContinue
    }}
}}
'''

ADD_WINDOWS = '''
foreach ($p in 'TCP', 'UDP') {{
    New-NetFirewallRule -Name ({rule} + ' ' + $p) -DisplayName ({rule} + ' ' + $p) -Group {group} `
        -Direction Inbound -Protocol $p -LocalPort {ports} -Action Allow | Out-Null
}}
'''

ADD_HYPERV = '''
foreach ($p in 'TCP', 'UDP') {{
    New-NetFirewallHyperVRule -Name ({rule} + ' ' + $p) -DisplayName ({rule} + ' ' + $p) `
        -VMCreatorId {creator} -Direction Inbound -Protocol $p -LocalPorts {ports} `
        -Action Allow | Out-Null
}}
'''


def parse_ports(text):
    return [int(v) for v in text.split(',') if v.strip().isdigit()]


def get_opened():
    '''{'windows': ports, 'hyperv': ports} opened by our rules.'''
    code, output = powershell(QUERY.format(rule=quote(RULE)))
    opened = {'windows': set(), 'hyperv': set()}
    for line in output.split('\n'):
        kind, _, ports = line.strip().partition('|')
        if kind in opened:
            opened[kind].update(parse_ports(ports))
    return {k: sorted(v) for k, v in opened.items()}


def set_rules(ports, hyperv):
    '''Replaces our rules; an empty list only removes them. Needs elevation.'''
    script = REMOVE.format(rule=quote(RULE))
    if ports:
        listed = ','.join(str(v) for v in sorted(set(ports)))
        script += ADD_WINDOWS.format(rule=quote(RULE), group=quote(GROUP), ports=listed)
        if hyperv:
            script += ADD_HYPERV.format(rule=quote(RULE), creator=quote(HYPERV_VM_CREATOR_ID),
                                        ports=listed)
    return powershell(script)[0] == 0


def remove_rules():
    return powershell(REMOVE.format(rule=quote(RULE)))[0] == 0


def get_portproxy():
    '''[(listen address, listen port, connect address, connect port)] of every v4tov4 entry.'''
    code, output = run(['netsh', 'interface', 'portproxy', 'show', 'v4tov4'])
    entries = []
    for line in output.split('\n'):
        parts = line.split()
        if (len(parts) == 4 and ADDRESS.match(parts[0]) and parts[1].isdigit()
                and parts[3].isdigit()):
            entries.append((parts[0], int(parts[1]), parts[2], int(parts[3])))
    return entries


def delete_portproxy(entries):
    for listen_address, listen_port in entries:
        run(['netsh', 'interface', 'portproxy', 'delete', 'v4tov4',
             f'listenport={listen_port}', f'listenaddress={listen_address}'])


def add_portproxy(listen_address, connect_address, ports):
    added = []
    for port in sorted(set(ports)):
        code, _ = run(['netsh', 'interface', 'portproxy', 'add', 'v4tov4',
                       f'listenport={port}', f'listenaddress={listen_address}',
                       f'connectport={port}', f'connectaddress={connect_address}'])
        if code == 0:
            added.append([listen_address, port])
    return added
