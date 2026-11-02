# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

Processor details without administrator rights: the core kinds and caches Windows reports
per logical processor, the identity and microcode the registry keeps, the instruction sets
Windows reports, and the clock the performance counters see.

The rated turbo clock is not read: CPUID leaf 16h answers zero once Hyper-V runs underneath
Windows, as it does with WSL 2, so only the clock seen while the app runs is shown.
'''


import ctypes
import struct
import winreg

from ctypes import wintypes


CPU_KEY = r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'

RELATION_CORE = 0
RELATION_CACHE = 2
RELATION_PACKAGE = 3
RELATION_ALL = 0xFFFF
CACHE_TYPES = {0: 'unified', 1: 'instruction', 2: 'data', 3: 'trace'}

# IsProcessorFeaturePresent; Windows answers for what it can use, not only what the chip has
FEATURES = (('SSE4.1', 37), ('SSE4.2', 38), ('AVX', 39), ('AVX2', 40), ('AVX-512', 41))

PDH_FMT_DOUBLE = 0x00000200
PERFORMANCE = r'\Processor Information(_Total)\% Processor Performance'
FREQUENCY = r'\Processor Information(_Total)\Processor Frequency'

kernel32 = ctypes.windll.kernel32


def popcount(mask):
    return bin(mask).count('1')


def read_topology():
    '''{'kinds': [{'cores', 'threads', 'l1d', 'l1i', 'l2', 'l2_shared'}] fastest kind first,
    'l3': bytes, 'packages': count} from GetLogicalProcessorInformationEx; each cache is put
    with the kind of core its processors belong to.'''
    size = wintypes.DWORD(0)
    kernel32.GetLogicalProcessorInformationEx(RELATION_ALL, None, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not kernel32.GetLogicalProcessorInformationEx(RELATION_ALL, buffer, ctypes.byref(size)):
        return None
    data = buffer.raw
    cores, caches, packages = [], [], 0
    offset = 0
    while offset + 8 <= len(data):
        relation, length = struct.unpack_from('<II', data, offset)
        body = offset + 8
        if relation == RELATION_CORE:
            # Flags, EfficiencyClass, 20 reserved, GroupCount, then GROUP_AFFINITY entries
            mask = struct.unpack_from('<Q', data, body + 24)[0]
            cores.append((data[body + 1], mask))
        elif relation == RELATION_CACHE:
            # Level, Associativity, LineSize, CacheSize, Type, 18 reserved, GroupCount, mask
            level, _, _, cache_size, kind = struct.unpack_from('<BBHII', data, body)
            mask = struct.unpack_from('<Q', data, body + 32)[0]
            caches.append((level, CACHE_TYPES.get(kind, 'unified'), cache_size, mask))
        elif relation == RELATION_PACKAGE:
            packages += 1
        offset += length

    kinds = {}
    for efficiency, mask in cores:
        kind = kinds.setdefault(efficiency, {'cores': 0, 'threads': 0, 'mask': 0})
        kind['cores'] += 1
        kind['threads'] += popcount(mask)
        kind['mask'] |= mask
    l3 = 0
    for level, cache_type, cache_size, mask in caches:
        if level >= 3:
            l3 += cache_size
            continue
        owners = [kind for kind in kinds.values() if kind['mask'] & mask]
        if len(owners) != 1:
            continue
        kind = owners[0]
        if level == 1:
            kind['l1d' if cache_type == 'data' else 'l1i'] = cache_size
        else:
            kind['l2'] = cache_size
            # how many cores of this kind sit behind one L2
            kind['l2_shared'] = sum(1 for efficiency, core in cores if core & mask)
    # a higher efficiency class is the faster core, as on Intel P-cores
    return {'kinds': [kinds[key] for key in sorted(kinds, reverse=True)], 'l3': l3,
            'packages': packages}


def read_identity():
    identity = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CPU_KEY) as key:
            identity['vendor'] = winreg.QueryValueEx(key, 'VendorIdentifier')[0]
            identity['model'] = ' '.join(winreg.QueryValueEx(key, 'Identifier')[0].split())
            revision = winreg.QueryValueEx(key, 'Update Revision')[0]
            if isinstance(revision, bytes) and revision:
                # 4 bytes on newer Windows (33 01 00 00 is 0x133), 8 on older with the
                # revision in the upper half
                value = int.from_bytes(revision, 'little')
                identity['microcode'] = value >> 32 if len(revision) == 8 else value
    except OSError:
        pass
    return identity


def read_features():
    return [name for name, code in FEATURES if kernel32.IsProcessorFeaturePresent(code)]


def format_size(size):
    if size >= 1024 * 1024:
        return f'{size / (1024 * 1024):g} MB'
    return f'{size // 1024} KB'


def describe_kind(kind):
    '''L1 48 KB data + 32 KB code, L2 2 MB each'''
    parts = []
    if kind.get('l1d') and kind.get('l1i'):
        parts.append(f'L1 {format_size(kind["l1d"])} data + {format_size(kind["l1i"])} code')
    if kind.get('l2'):
        shared = kind.get('l2_shared', 1)
        parts.append(f'L2 {format_size(kind["l2"])} ' +
                     ('each' if shared <= 1 else f'per {shared} cores'))
    return ', '.join(parts)


def read_details():
    details = read_topology() or {'kinds': [], 'l3': 0, 'packages': 1}
    details.update({'identity': read_identity(), 'features': read_features()})
    return details


def describe_kinds(kinds, threads):
    '''8 P-cores · 8 E-cores · 24 threads on a hybrid chip, 16 cores · 32 threads otherwise.'''
    if len(kinds) == 2:
        fast, slow = kinds
        return [f'{fast["cores"]} P-cores', f'{slow["cores"]} E-cores', f'{threads} threads']
    count = sum(kind['cores'] for kind in kinds)
    return [f'{count} cores', f'{threads} threads'] if count else []


class ClockMeter:
    '''The clock the cores run at now, from the performance counters: the base frequency
    times the processor performance, which passes 100% under turbo. Keeps the lowest and
    highest seen since the app started.'''

    def __init__(self):
        self.pdh = ctypes.windll.pdh
        self.query = ctypes.c_void_p()
        self.counters = []
        self.low = self.high = None
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(self.query)):
            self.query = None
            return
        for path in (PERFORMANCE, FREQUENCY):
            counter = ctypes.c_void_p()
            if self.pdh.PdhAddEnglishCounterW(self.query, path, None, ctypes.byref(counter)):
                self.counters = []
                return
            self.counters.append(counter)
        # the first collection only primes the rate counters
        self.pdh.PdhCollectQueryData(self.query)

    def read_counter(self, counter):
        value = (ctypes.c_double * 2)()
        # PDH_FMT_COUNTERVALUE: a DWORD status, padding, then the double
        if self.pdh.PdhGetFormattedCounterValue(counter, PDH_FMT_DOUBLE, None, value):
            return None
        return value[1]

    def sample(self):
        if not self.query or not self.counters or self.pdh.PdhCollectQueryData(self.query):
            return None
        performance, frequency = (self.read_counter(counter) for counter in self.counters)
        if not performance or not frequency:
            return None
        mhz = frequency * performance / 100.0
        self.low = mhz if self.low is None else min(self.low, mhz)
        self.high = mhz if self.high is None else max(self.high, mhz)
        return {'now': mhz, 'low': self.low, 'high': self.high, 'base': frequency}
