# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import ctypes.wintypes as wintypes
import socket
import urllib.request

import psutil


TRACE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'
GAA_FLAG_SKIP_ANYCAST = 0x2
GAA_FLAG_SKIP_MULTICAST = 0x4
GAA_FLAG_INCLUDE_GATEWAYS = 0x80
ERROR_BUFFER_OVERFLOW = 111
AF_INET6 = 23
# Windows fills these in for adapters that have no DNS server of their own
PLACEHOLDER_DNS = ('fec0:0:0:ffff::1', 'fec0:0:0:ffff::2', 'fec0:0:0:ffff::3')


class SocketAddress(ctypes.Structure):
    _fields_ = [('sockaddr', ctypes.c_void_p), ('length', ctypes.c_int)]


# the unicast, DNS server and gateway lists share this head
class AddressItem(ctypes.Structure):
    pass


AddressItem._fields_ = [('alignment', ctypes.c_ulonglong), ('next', ctypes.POINTER(AddressItem)),
                        ('address', SocketAddress), ('prefix_origin', ctypes.c_int),
                        ('suffix_origin', ctypes.c_int), ('dad_state', ctypes.c_int),
                        ('valid_lifetime', wintypes.ULONG),
                        ('preferred_lifetime', wintypes.ULONG),
                        ('lease_lifetime', wintypes.ULONG), ('prefix_length', ctypes.c_ubyte)]


# IP_ADAPTER_ADDRESSES_LH up to FirstGatewayAddress; it is only read through a pointer
class Adapter(ctypes.Structure):
    pass


Adapter._fields_ = [('alignment', ctypes.c_ulonglong), ('next', ctypes.POINTER(Adapter)),
                    ('adapter_name', ctypes.c_char_p),
                    ('unicast', ctypes.POINTER(AddressItem)),
                    ('anycast', ctypes.c_void_p), ('multicast', ctypes.c_void_p),
                    ('dns', ctypes.POINTER(AddressItem)), ('dns_suffix', ctypes.c_wchar_p),
                    ('description', ctypes.c_wchar_p), ('friendly_name', ctypes.c_wchar_p),
                    ('physical_address', ctypes.c_ubyte * 8),
                    ('physical_length', wintypes.ULONG), ('flags', wintypes.ULONG),
                    ('mtu', wintypes.ULONG), ('if_type', wintypes.DWORD),
                    ('oper_status', ctypes.c_int), ('ipv6_index', wintypes.DWORD),
                    ('zone_indices', wintypes.ULONG * 16), ('prefix', ctypes.c_void_p),
                    ('transmit_speed', ctypes.c_ulonglong),
                    ('receive_speed', ctypes.c_ulonglong), ('wins', ctypes.c_void_p),
                    ('gateway', ctypes.POINTER(AddressItem))]


def read_sockaddr(address):
    if not address.sockaddr:
        return None
    raw = ctypes.string_at(address.sockaddr, address.length)
    family = int.from_bytes(raw[:2], 'little')
    if family == socket.AF_INET:
        return socket.inet_ntop(socket.AF_INET, raw[4:8])
    if family == AF_INET6:
        return socket.inet_ntop(socket.AF_INET6, raw[8:24])
    return None


def walk(item):
    while item:
        yield item.contents
        item = item.contents.next


def split_family(addresses):
    return ([address for address in addresses if ':' not in address],
            [address for address in addresses if ':' in address])


def get_routes():
    size = wintypes.ULONG(16 * 1024)
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = ctypes.windll.iphlpapi.GetAdaptersAddresses(
            0, GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_INCLUDE_GATEWAYS,
            None, buffer, ctypes.byref(size))
        if result != ERROR_BUFFER_OVERFLOW:
            break
    if result:
        return {}
    routes = {}
    for adapter in walk(ctypes.cast(buffer, ctypes.POINTER(Adapter))):
        prefixes = {}
        for item in walk(adapter.unicast):
            address = read_sockaddr(item.address)
            if address:
                prefixes[address] = item.prefix_length
        gateways = [read_sockaddr(item.address) for item in walk(adapter.gateway)]
        servers = [read_sockaddr(item.address) for item in walk(adapter.dns)]
        routes[adapter.friendly_name] = {
            'prefixes': prefixes,
            'gateways': split_family([address for address in gateways if address]),
            'dns': split_family([address for address in servers
                                 if address and address not in PLACEHOLDER_DNS]),
        }
    return routes


def get_addresses():
    try:
        routes = get_routes()
    except OSError:
        routes = {}
    addresses = {}
    for name, items in psutil.net_if_addrs().items():
        route = routes.get(name) or {}
        entry = {'mac': None, 'ipv4': [], 'ipv6': [], 'prefixes': route.get('prefixes', {}),
                 'gateways': route.get('gateways', ([], [])), 'dns': route.get('dns', ([], []))}
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
    return (entry or {}).get('mac') or ''


def get_private(entry):
    if not entry or not entry['ipv4']:
        return '', ''
    address = entry['ipv4'][0]
    prefix = entry['prefixes'].get(address)
    value = f'{address}/{prefix}' if prefix is not None else address
    return value, ' · '.join(entry['ipv4'][1:] + entry['ipv6'][:1])


def get_pair(lists):
    # IPv4 first; IPv6 only when the adapter has no IPv4 entry
    ipv4, ipv6 = lists
    found = ipv4 or ipv6
    return (found[0], ' · '.join(found[1:] + (ipv6 if ipv4 else [])[:1])) if found else ('', '')


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
