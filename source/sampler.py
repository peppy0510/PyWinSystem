# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import os
import re
import time
import winreg

import psutil

import netinfo

from sensors import Sensors


WSL_PROCESS = 'vmmemwsl'
WSL_CONFIG = os.path.join(os.path.expanduser('~'), '.wslconfig')
LXSS_KEY = r'Software\Microsoft\Windows\CurrentVersion\Lxss'
WSL_DISK = re.compile(r'^(sd[a-z]+|vd[a-z]+|nvme\d+n\d+)$')
SECTOR = 512


def parse_size(text):
    found = re.match(r'^\s*([\d.]+)\s*([KMGT]?)B?\s*$', text or '', re.I)
    if not found:
        return None
    power = ' KMGT'.index(found.group(2).upper() or ' ')
    return int(float(found.group(1)) * 1024 ** power)


def read_wsl_config():
    config = {}
    try:
        with open(WSL_CONFIG, encoding='utf-8') as file:
            section = ''
            for line in file:
                line = line.split('#')[0].strip()
                if line.startswith('['):
                    section = line.strip('[]').lower()
                elif '=' in line and section == 'wsl2':
                    key, value = line.split('=', 1)
                    config[key.strip().lower()] = value.strip()
    except OSError:
        pass
    return {'memory': parse_size(config.get('memory')),
            'processors': int(config['processors']) if config.get('processors', '').isdigit()
            else None,
            'networking': config.get('networkingmode', 'nat')}


def get_default_distro():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, LXSS_KEY) as key:
            default = winreg.QueryValueEx(key, 'DefaultDistribution')[0]
            with winreg.OpenKey(key, default) as distro:
                return winreg.QueryValueEx(distro, 'DistributionName')[0]
    except OSError:
        return None


class Rates:

    def __init__(self):
        self.last = {}

    def update(self, key, values, now):
        previous = self.last.get(key)
        self.last[key] = (now, values)
        if previous is None:
            return None
        seconds = now - previous[0]
        if seconds <= 0:
            return None
        return tuple(max(0, (new - old) / seconds) for new, old in zip(values, previous[1]))


class Gpus:

    def __init__(self):
        self.handles = []
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            self.handles = [pynvml.nvmlDeviceGetHandleByIndex(index)
                            for index in range(pynvml.nvmlDeviceGetCount())]
        except Exception:
            self.nvml = None

    def sample(self):
        gpus = []
        for index, handle in enumerate(self.handles):
            nvml = self.nvml
            try:
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                gpu = {'index': index, 'name': nvml.nvmlDeviceGetName(handle),
                       'util': nvml.nvmlDeviceGetUtilizationRates(handle).gpu,
                       'used': memory.used, 'total': memory.total}
            except Exception:
                continue
            for key, read in (
                    ('temp', lambda: nvml.nvmlDeviceGetTemperature(handle,
                                                                   nvml.NVML_TEMPERATURE_GPU)),
                    ('power', lambda: nvml.nvmlDeviceGetPowerUsage(handle) / 1000.0),
                    ('power_limit', lambda: nvml.nvmlDeviceGetEnforcedPowerLimit(handle) / 1000.0),
                    ('fan', lambda: nvml.nvmlDeviceGetFanSpeed(handle)),
                    ('core_clock', lambda: nvml.nvmlDeviceGetClockInfo(handle,
                                                                       nvml.NVML_CLOCK_GRAPHICS)),
                    ('memory_clock', lambda: nvml.nvmlDeviceGetClockInfo(handle,
                                                                         nvml.NVML_CLOCK_MEM))):
                try:
                    gpu[key] = read()
                except Exception:
                    gpu[key] = None
            gpus.append(gpu)
        return gpus


class Wsl:

    def __init__(self):
        self.config = read_wsl_config()
        self.distro = get_default_distro()
        self.process = None
        self.rates = Rates()

    def find_process(self):
        # \\wsl.localhost is touched only while the VM runs; touching it starts a stopped WSL
        if self.process is not None and self.process.is_running():
            return self.process
        self.process = None
        for process in psutil.process_iter(['name']):
            if (process.info['name'] or '').lower() == WSL_PROCESS:
                self.process = process
                process.cpu_percent(None)
                break
        return self.process

    def read_proc(self, name):
        path = r'\\wsl.localhost\%s\proc\%s' % (self.distro, name.replace('/', '\\'))
        with open(path, encoding='utf-8', errors='replace') as file:
            return file.read()

    def sample(self, now):
        process = self.find_process()
        if process is None:
            return None
        wsl = {'config': self.config, 'distro': self.distro}
        try:
            wsl['host_memory'] = process.memory_info().rss
            wsl['host_cpu'] = process.cpu_percent(None) / psutil.cpu_count()
        except psutil.Error:
            self.process = None
            return None
        if self.distro:
            for read in (self.read_memory, self.read_cpu, self.read_disk, self.read_network):
                try:
                    read(wsl, now)
                except (OSError, ValueError, IndexError, KeyError):
                    pass
        return wsl

    def read_memory(self, wsl, now):
        memory = {}
        for line in self.read_proc('meminfo').splitlines():
            key, _, value = line.partition(':')
            memory[key] = int(value.split()[0]) * 1024
        wsl['memory'] = {'total': memory['MemTotal'], 'available': memory['MemAvailable'],
                         'used': memory['MemTotal'] - memory['MemAvailable']}

    def read_cpu(self, wsl, now):
        cpu = [int(value) for value in self.read_proc('stat').splitlines()[0].split()[1:]]
        idle = cpu[3] + cpu[4]
        rate = self.rates.update('cpu', (sum(cpu), idle), now)
        if rate and rate[0]:
            wsl['cpu'] = 100.0 * (1 - rate[1] / rate[0])

    def read_disk(self, wsl, now):
        read = written = 0
        for line in self.read_proc('diskstats').splitlines():
            parts = line.split()
            if len(parts) > 9 and WSL_DISK.match(parts[2]):
                read += int(parts[5]) * SECTOR
                written += int(parts[9]) * SECTOR
        wsl['disk'] = self.rates.update('disk', (read, written), now)

    def read_network(self, wsl, now):
        # /proc/net links to /proc/self, which the 9P share cannot follow
        received = sent = 0
        for line in self.read_proc('1/net/dev').splitlines()[2:]:
            name, _, values = line.partition(':')
            # mirrored networking adds loopback0 for localhost traffic with Windows
            if name.strip() in ('lo', 'loopback0'):
                continue
            values = values.split()
            received += int(values[0])
            sent += int(values[8])
        wsl['network'] = self.rates.update('network', (received, sent), now)


class Sampler:

    def __init__(self):
        self.rates = Rates()
        self.gpus = Gpus()
        self.wsl = Wsl()
        self.sensors = Sensors()
        psutil.cpu_percent(None, percpu=True)

    def sample(self):
        now = time.monotonic()
        cores = psutil.cpu_percent(None, percpu=True)
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        data = {
            'boot': psutil.boot_time(),
            'cpu': {'total': sum(cores) / max(1, len(cores)), 'cores': cores},
            'memory': {'total': memory.total, 'used': memory.total - memory.available,
                       'available': memory.available},
            'swap': {'total': swap.total, 'used': swap.used},
            'gpus': self.gpus.sample(),
            'disks': {}, 'networks': {},
        }

        for name, counters in sorted((psutil.disk_io_counters(perdisk=True) or {}).items()):
            rate = self.rates.update('disk:' + name, (counters.read_bytes,
                                                      counters.write_bytes), now)
            data['disks'][name] = rate or (0, 0)

        stats = psutil.net_if_stats()
        for name, counters in sorted(psutil.net_io_counters(pernic=True).items()):
            if 'loopback' in name.lower() or not getattr(stats.get(name), 'isup', False):
                continue
            rate = self.rates.update('net:' + name, (counters.bytes_recv,
                                                     counters.bytes_sent), now)
            data['networks'][name] = rate or (0, 0)

        data['addresses'] = netinfo.get_addresses()
        data['sensors'] = self.sensors.sample()
        data['wsl'] = self.wsl.sample(now)
        return data
