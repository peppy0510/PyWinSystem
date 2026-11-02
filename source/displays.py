# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com

One screen held from both sides: the monitor itself over DDC/CI and the graphics card's gamma
lookup table. Which side works differs per monitor, so only the working side is shown.

A DDC write takes tens of milliseconds. Called while a slider drags it would stall the window,
so the writes go through one worker that keeps only the last value of each code.
'''


import threading

import ddcci
import gamma
import monitors


HARDWARE_CODES = (ddcci.BRIGHTNESS, ddcci.CONTRAST, ddcci.INPUT_SOURCE, ddcci.VOLUME,
                  ddcci.RED_GAIN, ddcci.GREEN_GAIN, ddcci.BLUE_GAIN)

# these values leave the picture untouched
DEFAULT_SOFTWARE = {'brightness': 1.0, 'contrast': 1.0, 'kelvin': gamma.NEUTRAL_KELVIN,
                    'red': 1.0, 'green': 1.0, 'blue': 1.0}

# a few common EDID vendor codes; anything else shows as the bare code
MANUFACTURERS = {'ACR': 'Acer', 'AOC': 'AOC', 'AUS': 'ASUS', 'BNQ': 'BenQ', 'DEL': 'Dell',
                 'GSM': 'LG', 'HWP': 'HP', 'LEN': 'Lenovo', 'MSI': 'MSI', 'PHL': 'Philips',
                 'SAM': 'Samsung', 'SNY': 'Sony', 'VSC': 'ViewSonic', 'GBT': 'Gigabyte',
                 'HPN': 'HP', 'IVM': 'iiyama', 'NEC': 'NEC', 'EIZ': 'EIZO', 'APP': 'Apple'}


class HardwareWorker(threading.Thread):
    '''Owns every DDC write. A monitor's I2C takes one at a time, so a queue is faster, and of
    the writes waiting only the last value of each code needs sending.'''

    def __init__(self):
        super().__init__(daemon=True)
        self.pending = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.running = True

    def submit(self, handle, code, value):
        if handle is None:
            return
        with self.lock:
            self.pending[(handle, code)] = int(value)
        self.wake.set()

    def stop(self):
        self.running = False
        self.wake.set()

    def run(self):
        while self.running:
            self.wake.wait()
            self.wake.clear()

            while self.running:
                with self.lock:
                    if not self.pending:
                        break
                    (handle, code), value = self.pending.popitem()
                ddcci.set_vcp(handle, code, value)


class Display():

    def __init__(self, info, handles, worker):
        self.info = info
        self.monitors = handles
        self.worker = worker
        self.device = info['device']
        self.key = info.get('key') or info['device']
        self.label = info.get('label') or info.get('name') or 'Display'

        # handle 0 is a real handle; only None means there is none
        self.handle = handles[0].handle if handles is not None else None
        self.capabilities = {}
        self.capabilities_text = ''
        self.values = {}
        self.limits = {}
        self.choices = {}
        # what the monitor held when the app started; the best place to go back to, as MCCS
        # tells no factory value per code
        self.defaults = {}

        self.gamma_dc = gamma.open_device(self.device)
        self.software = dict(DEFAULT_SOFTWARE)

    def probe(self, cached=None):
        '''The capabilities decide which codes work, never a read alone: some monitors answer
        a plausible value for a code they do not support.

        Fetching the capabilities string takes about 4 seconds (923 bytes read over I2C one
        at a time). It stays the same while the monitor does, so a stored one skips that.'''
        if self.handle is None:
            return

        text = cached or ddcci.get_capabilities(self.handle)
        self.capabilities = ddcci.parse_capabilities(text)
        supported = self.capabilities.get('vcp') or {}

        for code in HARDWARE_CODES:
            if code not in supported:
                continue
            reply = ddcci.get_vcp(self.handle, code)
            if reply is None:
                continue
            self.values[code], self.limits[code] = reply
            self.defaults[code] = reply[0]
            if supported[code]:
                self.choices[code] = supported[code]

        if self.values:
            self.capabilities_text = text
        elif cached:
            # a stale or foreign stored string reads no code at all; only then ask again
            self.probe()

    def has_hardware(self):
        return bool(self.values)

    def supports(self, code):
        return code in self.values

    def get_hardware(self, code):
        return self.values.get(code, 0)

    def get_limit(self, code):
        return self.limits.get(code, 100)

    def get_default(self, code):
        return self.defaults.get(code, 0)

    def set_hardware(self, code, value):
        if code not in self.values:
            return
        self.values[code] = int(value)
        self.worker.submit(self.handle, code, value)

    def get_software(self, name):
        return self.software[name]

    def set_software(self, name, value):
        self.software[name] = value
        self.apply_software()

    def is_software_neutral(self):
        return self.software == DEFAULT_SOFTWARE

    def get_channels(self):
        return (self.software['red'], self.software['green'], self.software['blue'])

    def apply_software(self):
        return apply_stored(self.gamma_dc, self.software)

    def reset_software(self):
        self.software = dict(DEFAULT_SOFTWARE)
        return self.apply_software()

    def load_software(self, stored):
        for name in DEFAULT_SOFTWARE:
            if name in stored:
                self.software[name] = stored[name]

    def get_diagonal(self):
        return monitors.get_diagonal(self.info)

    def get_identity(self):
        # what the EDID says about the panel itself, for the Details rows
        info = self.info
        rows = []
        code = info.get('manufacturer')
        if code:
            name = MANUFACTURERS.get(code, code)
            rows.append(('Manufacturer', 'EDID vendor code',
                         name if name == code else f'{name} ({code})'))
        if info.get('product') is not None:
            rows.append(('Product code', 'Model number the panel reports',
                         f'0x{int(info["product"]):04X}'))
        serial = info.get('serial') or (str(info['serial_number'])
                                        if info.get('serial_number') else '')
        if serial:
            rows.append(('Serial number', 'As the panel reports it', serial))
        if info.get('year'):
            week = info.get('week') or 0
            # week 255 marks a model year instead of a date of manufacture
            if week == 255:
                rows.append(('Model year', 'As the panel reports it', str(info['year'])))
            else:
                made = f'{info["year"]} week {int(week)}' if 0 < week <= 54 else str(info['year'])
                rows.append(('Manufactured', 'As the panel reports it', made))
        if info.get('width_cm') and info.get('height_cm'):
            rows.append(('Screen size', 'Visible area', f'{int(info["width_cm"])} × '
                         f'{int(info["height_cm"])} cm · {int(self.get_diagonal())}″'))
        return rows

    def get_summary(self):
        parts = []
        if self.info.get('width'):
            parts.append(f'{int(self.info["width"])} × {int(self.info["height"])}')
        if self.info.get('frequency'):
            parts.append(f'{int(self.info["frequency"])} Hz')
        if self.get_diagonal():
            parts.append(f'{int(self.get_diagonal())}″')
        return ' · '.join(parts)

    def get_port(self):
        # the port number as the driver counts them, 1 for the first
        output = self.info.get('output')
        if output and self.info.get('connector') is not None:
            output += f' {int(self.info["connector"]) + 1}'
        return output or ''

    def close(self):
        gamma.close_device(self.gamma_dc)
        self.gamma_dc = None
        if self.monitors:
            ddcci.destroy_handles(self.monitors)
            self.monitors = None
            self.handle = None


class DisplayManager():

    def __init__(self):
        self.worker = HardwareWorker()
        self.worker.start()
        self.displays = []

    def refresh(self, cache=None):
        self.release()
        cache = cache or {}
        handles = ddcci.enumerate_handles()
        # left to right with numbered twins, so the list matches the desk without counting
        self.displays = [Display(info, handles.get(info['device']), self.worker)
                         for info in monitors.read_monitors()]
        for display in self.displays:
            display.probe(cache.get(display.key))
        return self.displays

    def store_capabilities(self):
        return {display.key: display.capabilities_text for display in self.displays
                if display.capabilities_text}

    def load(self, stored):
        for display in self.displays:
            values = stored.get(display.key)
            if values:
                display.load_software(values)

    def store(self):
        return {display.key: dict(display.software) for display in self.displays
                if not display.is_software_neutral()}

    def apply_software(self):
        # an untouched display is left as it is: opening the page changes no screen
        for display in self.displays:
            if not display.is_software_neutral():
                display.apply_software()

    def reset_software(self):
        for display in self.displays:
            display.reset_software()

    def release(self):
        for display in self.displays:
            display.close()
        self.displays = []

    def close(self):
        self.worker.stop()
        self.release()


def apply_stored(handle, software):
    channels = (software['red'], software['green'], software['blue'])
    ramp = gamma.build_ramp(software['brightness'], software['contrast'], software['kelvin'],
                            channels)
    # the driver blinks the screen on every write, even of the ramp it already has
    current = gamma.read_ramp(handle)
    if current is not None and bytes(current) == bytes(ramp):
        return True
    return gamma.apply_ramp(handle, ramp)


def restore_gamma(stored):
    '''Applies the stored gamma of every connected screen without the window, DDC or the
    4-second capabilities read: the screens Windows reset after a sign-in or a sleep.'''
    restored = []
    for info in monitors.read_monitors():
        values = stored.get(info.get('key') or info['device'])
        if not values:
            continue
        software = dict(DEFAULT_SOFTWARE)
        software.update({k: v for k, v in values.items() if k in DEFAULT_SOFTWARE})
        handle = gamma.open_device(info['device'])
        if apply_stored(handle, software):
            restored.append(info.get('label') or info['device'])
        gamma.close_device(handle)
    return restored
