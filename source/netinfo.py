# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import socket
import urllib.request

import psutil


TRACE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'


def get_addresses():
    addresses = {}
    for name, items in psutil.net_if_addrs().items():
        entry = {'mac': None, 'ipv4': [], 'ipv6': []}
        for item in items:
            if item.family == psutil.AF_LINK:
                entry['mac'] = item.address.replace('-', ':').upper()
            elif item.family == socket.AF_INET:
                entry['ipv4'].append(item.address)
            elif item.family == socket.AF_INET6:
                entry['ipv6'].append(item.address.split('%')[0])
        wide = [address for address in entry['ipv6'] if not address.lower().startswith('fe80')]
        entry['ipv6'] = wide or entry['ipv6']
        addresses[name] = entry
    return addresses


def describe(entry):
    if not entry:
        return ''
    parts = []
    if entry['mac']:
        parts.append(entry['mac'])
    parts += entry['ipv4'][:1]
    parts += entry['ipv6'][:1]
    return ' · '.join(parts)


def parse_trace(text):
    for line in (text or '').splitlines():
        key, _, value = line.partition('=')
        if key.strip() == 'ip':
            return value.strip() or None
    return None


# asks an outside server, so it runs on a button press and never on a timer
def lookup_public_ip():
    request = urllib.request.Request(TRACE_URL, headers={'User-Agent': 'PyWinSystem'})
    with urllib.request.urlopen(request, timeout=5) as response:
        return parse_trace(response.read().decode('utf-8', 'replace'))
