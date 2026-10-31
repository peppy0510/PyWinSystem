# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import platform
import re
import winreg

import psutil

import monitors


CPU_KEY = r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'
SECURE_BOOT_KEY = r'SYSTEM\CurrentControlSet\Control\SecureBoot\State'
FIRMWARE_TYPES = {1: 'Legacy BIOS', 2: 'UEFI'}
MEMORY_TYPES = {20: 'DDR', 21: 'DDR2', 24: 'DDR3', 26: 'DDR4', 34: 'DDR5', 35: 'LPDDR5'}
WINDOWS_KEY = r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
# ProductName still says Windows 10 on Windows 11, so the build decides
WINDOWS_11_BUILD = 22000
EDITIONS = {'Core': 'Home', 'CoreN': 'Home N', 'CoreSingleLanguage': 'Home Single Language',
            'Professional': 'Pro', 'ProfessionalN': 'Pro N',
            'ProfessionalWorkstation': 'Pro for Workstations',
            'ProfessionalEducation': 'Pro Education', 'Enterprise': 'Enterprise',
            'EnterpriseS': 'Enterprise LTSC', 'Education': 'Education',
            'IoTEnterprise': 'IoT Enterprise', 'ServerStandard': 'Server Standard',
            'ServerDatacenter': 'Server Datacenter'}


def read_cpu():
    cpu = {'name': platform.processor(), 'mhz': None,
           'cores': psutil.cpu_count(logical=False), 'threads': psutil.cpu_count()}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CPU_KEY) as key:
            cpu['name'] = ' '.join(winreg.QueryValueEx(key, 'ProcessorNameString')[0].split())
            cpu['mhz'] = winreg.QueryValueEx(key, '~MHz')[0]
    except OSError:
        pass
    return cpu


# one registry key, well under a millisecond
def read_windows():
    values = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINDOWS_KEY) as key:
            for name in ('CurrentBuild', 'UBR', 'DisplayVersion', 'EditionID'):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    except OSError:
        return f'Windows {platform.release()}', f'build {platform.version()}'
    build = str(values.get('CurrentBuild') or platform.version().split('.')[-1])
    major = '11' if build.isdigit() and int(build) >= WINDOWS_11_BUILD else platform.release()
    edition = values.get('EditionID')
    name = ' '.join(part for part in (f'Windows {major}', EDITIONS.get(edition, edition))
                    if part)
    if 'UBR' in values:
        build += f'.{values["UBR"]}'
    return name, ' · '.join(part for part in (values.get('DisplayVersion'), f'build {build}')
                            if part)


def read_firmware():
    firmware = {'type': None, 'secure_boot': None}
    kind = ctypes.c_int()
    try:
        if ctypes.windll.kernel32.GetFirmwareType(ctypes.byref(kind)):
            firmware['type'] = FIRMWARE_TYPES.get(kind.value)
    except Exception:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SECURE_BOOT_KEY) as key:
            firmware['secure_boot'] = bool(winreg.QueryValueEx(key, 'UEFISecureBootEnabled')[0])
    except OSError:
        pass
    return firmware


def query(service, sql):
    return list(service.ExecQuery(sql))


def read_wmi():
    import win32com.client
    service = win32com.client.GetObject(r'winmgmts:\\.\root\cimv2')
    modules = []
    for item in query(service, 'SELECT Capacity, Speed, ConfiguredClockSpeed, Manufacturer, '
                               'PartNumber, DeviceLocator, BankLabel, SMBIOSMemoryType '
                               'FROM Win32_PhysicalMemory'):
        modules.append({
            'slot': (item.DeviceLocator or '').strip(),
            'bank': (item.BankLabel or '').strip(),
            'size': int(item.Capacity or 0),
            'speed': item.Speed,
            'configured': item.ConfiguredClockSpeed,
            'type': MEMORY_TYPES.get(item.SMBIOSMemoryType),
            'maker': (item.Manufacturer or '').strip(),
            'part': (item.PartNumber or '').strip(),
        })
    adapters = []
    for item in query(service, 'SELECT Name, DriverVersion, VideoProcessor '
                               'FROM Win32_VideoController'):
        adapters.append({'name': (item.Name or '').strip(),
                         'driver': (item.DriverVersion or '').strip()})
    boards = query(service, 'SELECT Manufacturer, Product FROM Win32_BaseBoard')
    board = None
    if boards:
        board = ' '.join(part.strip() for part in (boards[0].Manufacturer, boards[0].Product)
                         if part)
    bios = None
    for item in query(service, 'SELECT Manufacturer, SMBIOSBIOSVersion, ReleaseDate '
                               'FROM Win32_BIOS'):
        released = item.ReleaseDate or ''
        bios = {'maker': (item.Manufacturer or '').strip(),
                'version': (item.SMBIOSBIOSVersion or '').strip(),
                'date': f'{released[:4]}-{released[4:6]}-{released[6:8]}'
                if len(released) >= 8 else ''}
    service = win32com.client.GetObject(r'winmgmts:\\.\root\StandardCimv2')
    nics = []
    for item in query(service, 'SELECT Name, InterfaceDescription, Speed, DriverVersionString, '
                               'DriverProvider, MediaConnectState, Virtual FROM MSFT_NetAdapter'):
        nics.append({'name': (item.Name or '').strip(),
                     'device': (item.InterfaceDescription or '').strip(),
                     'speed': int(item.Speed or 0),
                     'driver': join_parts(item.DriverProvider, item.DriverVersionString),
                     'connected': item.MediaConnectState == 1,
                     'virtual': bool(item.Virtual)})
    nics.sort(key=lambda nic: (nic['virtual'], not nic['connected'], nic['name']))
    return modules, adapters, board, nics, bios


def join_parts(*parts):
    return ' '.join(str(part).strip() for part in parts if part)


# boards name the channel in the bank or the slot: 'P0 CHANNEL A', 'ChannelA-DIMM0',
# 'Controller1-ChannelA-DIMM0', 'DIMM_A1'; the controller or socket in front keeps two
# controllers' channel A apart
CHANNEL = re.compile(r'(?:CHANNEL\s*|DIMM[_ ]?)([A-H])(?![A-Z])', re.I)
CONTROLLER = re.compile(r'(?:P|CONTROLLER|NODE)\s*(\d+)', re.I)


def get_channel(module):
    for text in (module.get('bank'), module.get('slot')):
        found = CHANNEL.search(text or '')
        if found:
            owner = CONTROLLER.search(text) or CONTROLLER.search(module.get('bank') or '')
            return (owner.group(1) if owner else '0'), found.group(1).upper()
    return None


# channel count, the speed the modules run at, and the bandwidth that makes in theory:
# MT/s x 8 bytes x channels. None when the slot names do not say the channel
def read_channels(modules):
    channels = [get_channel(module) for module in modules if module.get('size')]
    if not channels or None in channels:
        return None
    speeds = [module.get('configured') or module.get('speed') or 0 for module in modules]
    rated = [module.get('speed') or 0 for module in modules]
    count = len(set(channels))
    speed = min(speed for speed in speeds if speed) if any(speeds) else 0
    return {'count': count, 'modules': len(channels), 'speed': speed,
            'rated': min(rate for rate in rated if rate) if any(rated) else 0,
            'bandwidth': speed * 10 ** 6 * 8 * count}


def read_nvidia():
    try:
        import pynvml
        pynvml.nvmlInit()
    except Exception:
        return None, {}
    driver = pynvml.nvmlSystemGetDriverVersion()
    details = {}
    for index in range(pynvml.nvmlDeviceGetCount()):
        handle = pynvml.nvmlDeviceGetHandleByIndex(index)
        name = pynvml.nvmlDeviceGetName(handle)
        detail = {'vram': pynvml.nvmlDeviceGetMemoryInfo(handle).total}
        try:
            detail['pcie'] = (f'PCIe {int(pynvml.nvmlDeviceGetMaxPcieLinkGeneration(handle))}.0 '
                              f'x{int(pynvml.nvmlDeviceGetMaxPcieLinkWidth(handle))}')
        except Exception:
            detail['pcie'] = None
        details[name] = detail
    return driver, details


def read_hardware():
    # COM objects must be gone before CoUninitialize, so they live in read_wmi only
    import pythoncom
    pythoncom.CoInitialize()
    try:
        modules, adapters, board, nics, bios = read_wmi()
    finally:
        pythoncom.CoUninitialize()
    driver, details = read_nvidia()
    for adapter in adapters:
        detail = details.get(adapter['name'])
        if detail:
            adapter.update(detail)
            adapter['driver'] = driver or adapter['driver']
    return {'cpu': read_cpu(), 'memory': modules, 'total': psutil.virtual_memory().total,
            'gpus': adapters, 'board': board, 'nics': nics, 'bios': bios,
            'firmware': read_firmware(), 'monitors': monitors.read_monitors()}
