# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import smart


ENERGY_OBJECT = 'Energy Meter'
ENERGY_PARTS = {'RAPL_Package0_PKG': 'package', 'RAPL_Package0_PP0': 'cores',
                'RAPL_Package0_PP1': 'graphics', 'RAPL_Package0_DRAM': 'dram'}
LHM_NAMESPACE = r'winmgmts:\\.\root\LibreHardwareMonitor'
LHM_TYPES = ('Temperature', 'Fan')
LHM_HARDWARE = ('Cpu', 'Motherboard', 'SuperIO')
SLOW_EVERY = 5


class EnergyMeter:
    # Windows exposes Intel RAPL as a performance counter in milliwatts, no driver needed

    def __init__(self):
        self.query = None
        self.counters = {}
        try:
            import win32pdh
            self.pdh = win32pdh
            _, instances = win32pdh.EnumObjectItems(None, None, ENERGY_OBJECT,
                                                    win32pdh.PERF_DETAIL_WIZARD)
            self.query = win32pdh.OpenQuery()
            for instance in instances:
                if instance in ENERGY_PARTS:
                    path = rf'\{ENERGY_OBJECT}({instance})\Power'
                    self.counters[ENERGY_PARTS[instance]] = win32pdh.AddEnglishCounter(
                        self.query, path)
            win32pdh.CollectQueryData(self.query)
        except Exception:
            self.query = None

    def sample(self):
        if self.query is None:
            return {}
        try:
            self.pdh.CollectQueryData(self.query)
        except Exception:
            return {}
        watts = {}
        for name, counter in self.counters.items():
            try:
                value = self.pdh.GetFormattedCounterValue(counter, self.pdh.PDH_FMT_DOUBLE)[1]
            except Exception:
                continue
            if value > 0:
                watts[name] = value / 1000.0
        return watts


class HardwareMonitor:
    # CPU and mainboard sensors need a kernel driver; LibreHardwareMonitor publishes
    # them to WMI while it runs, so they are read from there when it is up

    def sample(self):
        import pythoncom
        pythoncom.CoInitialize()
        try:
            return self.query()
        except Exception:
            return None
        finally:
            pythoncom.CoUninitialize()

    def query(self):
        import win32com.client
        service = win32com.client.GetObject(LHM_NAMESPACE)
        # GPUs and drives are read directly already, so only these are taken from it
        hardware = {item.Identifier: item.Name for item in service.ExecQuery(
            'SELECT Identifier, Name, HardwareType FROM Hardware')
            if item.HardwareType in LHM_HARDWARE}
        found = []
        for item in service.ExecQuery('SELECT Name, SensorType, Value, Parent FROM Sensor'):
            if (item.SensorType in LHM_TYPES and item.Value is not None
                    and item.Parent in hardware):
                found.append({'type': item.SensorType, 'name': item.Name,
                              'hardware': hardware[item.Parent], 'value': float(item.Value)})
        return found


class Sensors:

    def __init__(self):
        self.energy = EnergyMeter()
        self.monitor = HardwareMonitor()
        self.nvme = {}
        self.hdd = []
        self.count = 0
        self.slow = {'nvme': {}, 'nvme_power': {}, 'spinning': {}, 'monitor': None}

    def set_disks(self, found):
        nvme = {}
        for disk in found:
            if disk['bus'] == 'NVMe':
                try:
                    nvme[disk['number']] = smart.read_nvme_power(disk['number'])
                except Exception:
                    nvme[disk['number']] = None
        self.nvme = nvme
        self.hdd = [disk['number'] for disk in found if disk['media'] == 'HDD']
        self.count = 0

    def sample(self):
        # drive and WMI reads are slower, so they run every few samples
        if self.count % SLOW_EVERY == 0:
            temps = {}
            for number in self.nvme:
                try:
                    health = smart.read_nvme(number)
                except Exception:
                    health = None
                if health:
                    temps[number] = health['temperature']
            spinning = {number: smart.is_spinning(number) for number in self.hdd}
            self.slow = {'nvme': temps, 'nvme_power': dict(self.nvme), 'spinning': spinning,
                         'monitor': self.monitor.sample()}
        self.count += 1
        return dict(self.slow, cpu_power=self.energy.sample())
