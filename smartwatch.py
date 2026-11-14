"""
smartwatch.py - simulated smartwatch sensors.

Replace the bodies of these functions with real readings from your device/API.
Units (the contract healthMonitor.py relies on):

    get_sleep()  -> hours slept last night            (float)
    get_hr()     -> resting heart rate, beats/min     (int)
    get_stress() -> stress score, 0 (calm) - 100      (int)
    get_pr()     -> respiratory (pulse-respiration) rate, breaths/min (int)
    get_temp()   -> body/skin temperature, deg Celsius (float)
    get_ox()     -> blood oxygen saturation SpO2, %    (float)
"""

import random


def _clamp(value, low, high):
    return max(low, min(high, value))


def get_sleep():
    return round(_clamp(random.gauss(7.0, 1.0), 3.0, 11.0), 1)


def get_hr():
    return int(_clamp(random.gauss(68, 8), 40, 130))


def get_stress():
    return int(_clamp(random.gauss(40, 18), 0, 100))


def get_pr():
    return int(_clamp(random.gauss(15, 2), 8, 30))


def get_temp():
    return round(_clamp(random.gauss(36.7, 0.3), 34.0, 40.0), 1)


def get_ox():
    return round(_clamp(random.gauss(97.5, 1.0), 85.0, 100.0), 1)