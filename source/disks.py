# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

description:
Physical disk list from the Windows storage stack. Read once at start and on
request only, never on a timer, so a spun-down drive is left alone.
'''


MEDIA_TYPES = {3: 'HDD', 4: 'SSD', 5: 'SCM'}
BUS_TYPES = {1: 'SCSI', 2: 'ATAPI', 3: 'ATA', 6: 'Fibre', 7: 'USB', 8: 'RAID', 10: 'SAS',
             11: 'SATA', 12: 'SD', 13: 'MMC', 15: 'File', 16: 'Spaces', 17: 'NVMe'}
HEALTH = {0: 'Healthy', 1: 'Warning', 2: 'Unhealthy', 5: 'Unknown'}


def query_disks():
    import win32com.client
    service = win32com.client.GetObject(r'winmgmts:\\.\root\Microsoft\Windows\Storage')
    disks = []
    for disk in service.ExecQuery('SELECT DeviceId, FriendlyName, MediaType, BusType, Size, '
                                  'HealthStatus FROM MSFT_PhysicalDisk'):
        disks.append({
            'number': int(disk.DeviceId),
            'name': (disk.FriendlyName or '').strip(),
            'media': MEDIA_TYPES.get(disk.MediaType, 'Unspecified'),
            'bus': BUS_TYPES.get(disk.BusType, 'Other'),
            'size': int(disk.Size or 0),
            'health': HEALTH.get(disk.HealthStatus, 'Unknown'),
        })
    # Storage Spaces drives show up as disk numbers of their own, not in the physical list
    known = {disk['number'] for disk in disks}
    service = win32com.client.GetObject(r'winmgmts:\\.\root\cimv2')
    for drive in service.ExecQuery('SELECT Index, Model, Size FROM Win32_DiskDrive'):
        if int(drive.Index) not in known:
            disks.append({'number': int(drive.Index), 'name': (drive.Model or '').strip(),
                          'media': 'Virtual', 'bus': 'Spaces', 'size': int(drive.Size or 0),
                          'health': None})
    return sorted(disks, key=lambda disk: disk['number'])


def list_disks():
    # COM objects must be gone before CoUninitialize, so they live in query_disks only
    import pythoncom
    pythoncom.CoInitialize()
    try:
        return query_disks()
    finally:
        pythoncom.CoUninitialize()
