# encoding: utf-8


'''
author: Taehong Kim
email: peppy0510@hotmail.com
'''


import copy
import json
import os
import time


APP_DIR = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'PyWinSystem')
TARIFF_PATH = os.path.join(APP_DIR, 'tariffs.json')
LOG_PATH = os.path.join(APP_DIR, 'energy.json')
SAVE_EVERY = 60
DAYS_PER_MONTH = 30.4
LOG_DAYS = 400

# starting points only, from memory of each utility's published tables; check them against
# the current tables and edit tariffs.json, which is written on first run
DEFAULT_TARIFFS = {
    'kr_home': {
        'name': 'Korea, home (progressive)', 'currency': 'KRW',
        'note': 'KEPCO residential low voltage; check kepco.co.kr',
        # [kWh upper limit or null, monthly base fee, price per kWh]
        'tiers': [[200, 910, 120.0], [400, 1600, 214.6], [None, 7300, 307.3]],
        'summer_tiers': [[300, 910, 120.0], [450, 1600, 214.6], [None, 7300, 307.3]],
        'summer_months': [7, 8],
        'per_kwh_extra': 14.0,
        'tax_percent': 10.0, 'fund_percent': 3.7,
    },
    'kr_flat': {
        'name': 'Korea, flat rate', 'currency': 'KRW',
        'note': 'One price per kWh, as for an office on a general service plan',
        'tiers': [[None, 0, 150.0]], 'summer_tiers': None, 'summer_months': [],
        'per_kwh_extra': 0.0, 'tax_percent': 10.0, 'fund_percent': 3.7,
    },
    'us': {
        'name': 'United States, flat rate', 'currency': 'USD',
        'note': 'Rough national residential average; set your utility price',
        'tiers': [[None, 0, 0.17]], 'summer_tiers': None, 'summer_months': [],
        'per_kwh_extra': 0.0, 'tax_percent': 0.0, 'fund_percent': 0.0,
    },
    'jp': {
        'name': 'Japan, TEPCO Juryo Dento B', 'currency': 'JPY',
        'note': 'Three-step meter rate with tax included; base fee is for 30 A',
        'tiers': [[120, 935.25, 29.80], [300, 935.25, 36.40], [None, 935.25, 40.49]],
        'summer_tiers': None, 'summer_months': [],
        'per_kwh_extra': 3.49, 'tax_percent': 0.0, 'fund_percent': 0.0,
    },
}

CURRENCIES = {'KRW': ('₩', 0), 'USD': ('$', 2), 'JPY': ('¥', 0)}


def load_tariffs():
    tariffs = copy.deepcopy(DEFAULT_TARIFFS)
    try:
        with open(TARIFF_PATH, encoding='utf-8') as file:
            stored = json.load(file)
        for key, tariff in stored.items():
            if isinstance(tariff, dict):
                tariffs.setdefault(key, {}).update(tariff)
    except FileNotFoundError:
        save_tariffs(tariffs)
    except (OSError, ValueError):
        pass
    return tariffs


def save_tariffs(tariffs):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(TARIFF_PATH, 'w', encoding='utf-8') as file:
            json.dump(tariffs, file, ensure_ascii=False, indent=2)
            file.write('\n')
    except OSError:
        pass


def get_bill(kwh, tariff, month):
    tiers = tariff.get('tiers') or []
    if month in (tariff.get('summer_months') or []) and tariff.get('summer_tiers'):
        tiers = tariff['summer_tiers']
    # every step's price applies to its slice; the base fee is the one of the last step reached
    energy = base = below = 0.0
    for limit, fee, price in tiers:
        top = kwh if limit is None else min(kwh, limit)
        energy += max(0.0, top - below) * price
        base = fee
        if limit is None or kwh <= limit:
            break
        below = limit
    subtotal = base + energy + kwh * tariff.get('per_kwh_extra', 0.0)
    rates = tariff.get('tax_percent', 0.0) + tariff.get('fund_percent', 0.0)
    return subtotal * (1 + rates / 100.0)


def get_share(kwh, household, tariff, month):
    # tiers apply to the whole meter, so the PC costs what it adds on top of the rest
    return get_bill(household + kwh, tariff, month) - get_bill(household, tariff, month)


def format_money(value, currency):
    symbol, digits = CURRENCIES.get(currency, ('', 2))
    return symbol + format(value, ',.%df' % digits)


class EnergyLog:
    # kWh per day, counted only while the app runs

    def __init__(self):
        self.days = {}
        self.saved = time.monotonic()
        try:
            with open(LOG_PATH, encoding='utf-8') as file:
                stored = json.load(file)
            if isinstance(stored, dict):
                self.days = {key: float(value) for key, value in stored.items()}
        except (OSError, ValueError):
            pass

    def add(self, watts, seconds):
        if watts <= 0 or seconds <= 0:
            return
        day = time.strftime('%Y-%m-%d')
        self.days[day] = self.days.get(day, 0.0) + watts * seconds / 3600000.0
        if time.monotonic() - self.saved >= SAVE_EVERY:
            self.save()

    def save(self):
        self.saved = time.monotonic()
        keep = sorted(self.days)[-LOG_DAYS:]
        self.days = {key: self.days[key] for key in keep}
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(LOG_PATH, 'w', encoding='utf-8') as file:
                json.dump(self.days, file, indent=1)
        except OSError:
            pass

    def get_today(self):
        return self.days.get(time.strftime('%Y-%m-%d'), 0.0)

    def get_month(self):
        prefix = time.strftime('%Y-%m-')
        return sum(value for key, value in self.days.items() if key.startswith(prefix))
