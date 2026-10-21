# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import ctypes
import platform
import winreg

import psutil


CPU_KEY = r'HARDWARE\DESCRIPTION\System\CentralProcessor\0'
SECURE_BOOT_KEY = r'SYSTEM\CurrentControlSet\Control\SecureBoot\State'
FIRMWARE_TYPES = {1: 'Legacy BIOS', 2: 'UEFI'}
MEMORY_TYPES = {20: 'DDR', 21: 'DDR2', 24: 'DDR3', 26: 'DDR4', 34: 'DDR5', 35: 'LPDDR5'}


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
                               'PartNumber, DeviceLocator, SMBIOSMemoryType '
                               'FROM Win32_PhysicalMemory'):
        modules.append({
            'slot': (item.DeviceLocator or '').strip(),
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
                'date': '%s-%s-%s' % (released[:4], released[4:6], released[6:8])
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
            detail['pcie'] = 'PCIe %d.0 x%d' % (
                pynvml.nvmlDeviceGetMaxPcieLinkGeneration(handle),
                pynvml.nvmlDeviceGetMaxPcieLinkWidth(handle))
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
            'firmware': read_firmware()}
