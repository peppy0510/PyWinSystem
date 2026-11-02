# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes

from ctypes import wintypes


QDC_ALL_PATHS = 0x00000001
QDC_ONLY_ACTIVE_PATHS = 0x00000002
PATH_ACTIVE = 0x00000001
GET_SOURCE_NAME = 1
GET_TARGET_NAME = 2
MODE_INFO_SIZE = 64

OUTPUTS = {0: 'VGA', 1: 'S-Video', 2: 'Composite', 3: 'Component', 4: 'DVI', 5: 'HDMI',
           6: 'LVDS', 8: 'D-Jpn', 9: 'SDI', 10: 'DisplayPort', 11: 'Embedded DisplayPort',
           12: 'UDI', 13: 'Embedded UDI', 14: 'SDTV dongle', 15: 'Miracast',
           16: 'Indirect wired', 17: 'Indirect virtual', 18: 'USB-C DisplayPort',
           -0x80000000: 'Internal'}


class Luid(ctypes.Structure):
    _fields_ = [('low', wintypes.DWORD), ('high', wintypes.LONG)]


class PathSource(ctypes.Structure):
    _fields_ = [('adapter', Luid), ('id', ctypes.c_uint32), ('mode', ctypes.c_uint32),
                ('flags', ctypes.c_uint32)]


class PathTarget(ctypes.Structure):
    _fields_ = [('adapter', Luid), ('id', ctypes.c_uint32), ('mode', ctypes.c_uint32),
                ('output', ctypes.c_int32), ('rotation', ctypes.c_int32),
                ('scaling', ctypes.c_int32), ('refresh_numerator', ctypes.c_uint32),
                ('refresh_denominator', ctypes.c_uint32), ('scan_line', ctypes.c_int32),
                ('available', ctypes.c_int32), ('flags', ctypes.c_uint32)]


class Path(ctypes.Structure):
    _fields_ = [('source', PathSource), ('target', PathTarget), ('flags', ctypes.c_uint32)]


class InfoHeader(ctypes.Structure):
    _fields_ = [('type', ctypes.c_int32), ('size', ctypes.c_uint32), ('adapter', Luid),
                ('id', ctypes.c_uint32)]


class SourceName(ctypes.Structure):
    _fields_ = [('header', InfoHeader), ('device', wintypes.WCHAR * 32)]


class TargetName(ctypes.Structure):
    _fields_ = [('header', InfoHeader), ('flags', ctypes.c_uint32), ('output', ctypes.c_int32),
                ('manufacturer', ctypes.c_uint16), ('product', ctypes.c_uint16),
                ('connector', ctypes.c_uint32), ('name', wintypes.WCHAR * 64),
                ('path', wintypes.WCHAR * 128)]


def get_info(info, kind, path_part):
    info.header.type = kind
    info.header.size = ctypes.sizeof(info)
    info.header.adapter = path_part.adapter
    info.header.id = path_part.id
    return ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(info)) == 0


# NVIDIA lists DVI heads that have no socket on the card, so an unused DVI is left out
PHANTOM_OUTPUTS = ('DVI',)
PORT_ORDER = ('DisplayPort', 'USB-C DisplayPort', 'HDMI', 'DVI')


def query_paths(flags):
    user32 = ctypes.windll.user32
    path_count, mode_count = ctypes.c_uint32(), ctypes.c_uint32()
    if user32.GetDisplayConfigBufferSizes(flags, ctypes.byref(path_count),
                                          ctypes.byref(mode_count)):
        return []
    paths = (Path * path_count.value)()
    modes = (ctypes.c_byte * (MODE_INFO_SIZE * mode_count.value))()
    if user32.QueryDisplayConfig(flags, ctypes.byref(path_count), paths,
                                 ctypes.byref(mode_count), modes, None):
        return []
    return paths[:path_count.value]


def get_port_key(port):
    order = PORT_ORDER.index(port['output']) if port['output'] in PORT_ORDER else len(PORT_ORDER)
    return order, port['output'], port['connector']


# {'\\\\.\\DISPLAY1': {'card': luid, 'output': 'DisplayPort', 'connector': 0,
# 'ports': [...]}} for the active displays; ports lists every socket of that graphics
# card with whether a display uses it. No administrator rights, about 1 ms for two cards.
# connector counts the ports of one kind on one card as the driver numbers them, not
# their order on the bracket. A display behind a DisplayPort MST hub, in a dock or in a
# monitor that can daisy-chain, gets the socket of the hub with 'hub': True, or
# 'connector': None and 'chained': True when that socket cannot be told
def read_connections():
    targets = {}
    for path in query_paths(QDC_ALL_PATHS):
        key = (path.target.adapter.low, path.target.adapter.high, path.target.id)
        target = targets.get(key)
        if target is None:
            name = TargetName()
            if not get_info(name, GET_TARGET_NAME, path.target):
                continue
            target = targets[key] = {'card': key[:2],
                                     'output': OUTPUTS.get(name.output, 'Other'),
                                     'connector': name.connector, 'used': False}
        if path.flags & PATH_ACTIVE:
            target['used'] = True

    # the sockets of a card share one block of target ids; MST adds targets outside it, and
    # NVIDIA puts the DisplayPort socket of the hub in the next digit (RTX 4070 Ti: sockets
    # 0x1100-0x1106, two monitors with hubs on DP 1 and DP 3 as 0x1205 and 0x1225)
    blocks = {}
    for low, high, number in targets:
        blocks[(low, high)] = min(blocks.get((low, high), number >> 8), number >> 8)
    sockets = {(low, high, target['connector']): target
               for (low, high, number), target in targets.items()
               if number >> 8 == blocks[(low, high)] and target['output'] == 'DisplayPort'}
    for (low, high, number), target in targets.items():
        if number >> 8 == blocks[(low, high)]:
            continue
        socket = sockets.get((low, high, (number >> 4) & 0xF))
        if target['output'] == 'DisplayPort' and socket is not None:
            target['connector'] = socket['connector']
            target['hub'] = True
            socket['used'] = socket['used'] or target['used']
        else:
            target['connector'] = None
            target['chained'] = True

    ports = {}
    for (low, high, _), target in targets.items():
        if target.get('chained') or target.get('hub'):
            continue
        if target['output'] in PHANTOM_OUTPUTS and not target['used']:
            continue
        ports.setdefault((low, high), []).append(target)
    for items in ports.values():
        items.sort(key=get_port_key)

    connections = {}
    for path in query_paths(QDC_ONLY_ACTIVE_PATHS):
        source = SourceName()
        if not get_info(source, GET_SOURCE_NAME, path.source):
            continue
        adapter = (path.target.adapter.low, path.target.adapter.high)
        target = targets.get((*adapter, path.target.id))
        if target is None:
            continue
        connections[source.device] = {'card': adapter, 'output': target['output'],
                                      'connector': target['connector'],
                                      'chained': bool(target.get('chained')),
                                      'hub': bool(target.get('hub')),
                                      'ports': [dict(port) for port in ports.get(adapter, [])]}
    return connections
