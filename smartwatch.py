"""
smartwatch.py - reads a smartwatch EXPORT file (given manually by the user)
and gives the main program simple values through small functions.

No external libraries needed (Python 3.9+).

Supported export files:
  * Apple Health : export.zip or export.xml
  * CSV          : long format  ts,metric,value
                   or wide format  ts,heart_rate,spo2,temperature,...
  * JSON         : list of records (same fields as the CSV)

Usage in the main program (drop-in replacement for the simulated smartwatch.py):

    import smartwatch
    smartwatch.smartwatch("export.zip")   # optional: load the user's export once

    smartwatch.get_sleep()    # float  hours slept last night
    smartwatch.get_hr()       # int    resting heart rate, bpm
    smartwatch.get_stress()   # int    stress score 0-100
    smartwatch.get_pr()       # int    respiratory rate, breaths/min
    smartwatch.get_temp()     # float  temperature, deg C
    smartwatch.get_ox()       # float  SpO2, %

Without a loaded export (or for metrics the export lacks) these return
simulated values, so the health monitor always gets a number.
smartwatch.data_source() shows which values are real ("export") or "simulated".
Extra: get_bp() -> (systolic, diastolic) or (None, None).
"""
import csv
import json
import random
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ---------------------------------------------------------------- state ----
_DATA = {}    # metric -> [(timestamp, value), ...]
_SLEEP = []   # [(start_ts, end_ts), ...]   (Apple Health sleep intervals)

# Column / metric names we understand -> internal name
_ALIASES = {
    "heart_rate": ["heart_rate", "heartrate", "hr", "pulse", "bpm"],
    "resting_hr": ["resting_hr", "resting_heart_rate", "rhr"],
    "hrv": ["hrv", "hrv_rmssd", "hrv_sdnn", "heart_rate_variability"],
    "resp_rate": ["resp_rate", "respiratory_rate", "breathing_rate", "respiration"],
    "spo2": ["spo2", "oxygen", "oxygen_saturation", "blood_oxygen"],
    "systolic": ["systolic", "bp_systolic", "blood_pressure_systolic"],
    "diastolic": ["diastolic", "bp_diastolic", "blood_pressure_diastolic"],
    "temp": ["temp", "temperature", "body_temperature", "skin_temperature",
             "wrist_temperature"],
    "sleep_hours": ["sleep_hours", "sleep_total_h", "sleep", "sleep_duration_h"],
    "stress": ["stress", "stress_score"],
}
_LOOKUP = {a: key for key, names in _ALIASES.items() for a in names}

_APPLE_TYPES = {
    "HKQuantityTypeIdentifierHeartRate": "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
    "HKQuantityTypeIdentifierRespiratoryRate": "resp_rate",
    "HKQuantityTypeIdentifierOxygenSaturation": "spo2",
    "HKQuantityTypeIdentifierBloodPressureSystolic": "systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "diastolic",
    "HKQuantityTypeIdentifierBodyTemperature": "temp",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": "temp",
}
_TS_COLUMNS = ("ts", "timestamp", "time", "date", "datetime", "startdate")


# -------------------------------------------------------------- helpers ----
def _norm(name):
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _ts(value):
    """Epoch seconds from epoch / ISO string / Apple Health date."""
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _clean(metric, value):
    """Fix common unit differences."""
    if metric == "spo2" and value <= 1.0:       # Apple stores 0.97 = 97 %
        value *= 100
    if metric == "temp" and value > 50:         # Fahrenheit -> Celsius
        value = (value - 32) / 1.8
    return value


def _add(metric, ts, value):
    _DATA.setdefault(metric, []).append((ts, _clean(metric, float(value))))


def _add_record(rec, row_no):
    """One CSV/JSON record, long or wide format."""
    rec = {_norm(k): v for k, v in rec.items()}
    ts = row_no
    for col in _TS_COLUMNS:
        if rec.get(col) not in (None, ""):
            ts = _ts(rec[col])
            break
    if "metric" in rec and "value" in rec:
        metric = _LOOKUP.get(_norm(rec["metric"]))
        if metric and rec["value"] not in (None, ""):
            _add(metric, ts, rec["value"])
        return
    for col, val in rec.items():
        metric = _LOOKUP.get(col)
        if metric and val not in (None, ""):
            try:
                _add(metric, ts, val)
            except ValueError:
                pass


def _recent(metric, hours=24):
    """Values from the last `hours` of data (counted from the newest record)."""
    rows = _DATA.get(metric, [])
    if not rows:
        return []
    newest = max(t for t, _ in rows)
    return [v for t, v in rows if t >= newest - hours * 3600]


def _avg(values, digits=1):
    return round(sum(values) / len(values), digits) if values else None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# -------------------------------------------------------------- loaders ----
def _load_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, rec in enumerate(csv.DictReader(f)):
            _add_record(rec, i)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("records") or data.get("data") or [data]
    for i, rec in enumerate(data):
        _add_record(rec, i)


def _parse_apple(stream):
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag != "Record":
            el.clear()
            continue
        rtype = el.get("type")
        if rtype in _APPLE_TYPES:
            try:
                _add(_APPLE_TYPES[rtype], _ts(el.get("startDate")), el.get("value"))
            except (TypeError, ValueError):
                pass
        elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
            if "Asleep" in (el.get("value") or ""):   # skip InBed / Awake
                _SLEEP.append((_ts(el.get("startDate")), _ts(el.get("endDate"))))
        el.clear()


def _load_apple(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist()
                        if n.endswith("export.xml") and "cda" not in n.lower())
            with z.open(name) as f:
                _parse_apple(f)
    else:
        _parse_apple(path)


# ------------------------------------------------------- main loader fn ----
def smartwatch(path):
    """Load the export file the user gave. Call this once at the start.
    Returns a short report of what was found."""
    _DATA.clear()
    _SLEEP.clear()
    _SOURCE.clear()
    low = path.lower()
    if low.endswith(".csv"):
        _load_csv(path)
    elif low.endswith(".json"):
        _load_json(path)
    elif low.endswith(".xml") or low.endswith(".zip"):
        _load_apple(path)
    else:
        raise ValueError("Unsupported file. Use .zip/.xml (Apple Health), .csv or .json")
    report = {m: len(rows) for m, rows in _DATA.items()}
    if _SLEEP:
        report["sleep_intervals"] = len(_SLEEP)
    return report


# ------------------------------------------------- the small functions ----
# Contract used by healthMonitor.py (same names, types and units):
#
#   get_sleep()  -> float  hours slept last night
#   get_hr()     -> int    resting heart rate, beats/min
#   get_stress() -> int    stress score 0 (calm) - 100
#   get_pr()     -> int    respiratory rate, breaths/min
#   get_temp()   -> float  body/skin temperature, deg Celsius
#   get_ox()     -> float  blood oxygen saturation SpO2, %
#
# If no export is loaded (or the export does not contain a metric) the
# function returns a SIMULATED value, so healthMonitor.py never receives None.
# Set FALLBACK_TO_SIMULATED = False to get a LookupError instead.
# data_source() tells which values are real and which are simulated.
# Real values are NOT clamped: an abnormal reading (e.g. SpO2 88 %) must reach
# the health monitor unchanged.

FALLBACK_TO_SIMULATED = True
_SOURCE = {}

_SIMULATED = {
    "sleep": lambda: round(_clamp(random.gauss(7.0, 1.0), 3.0, 11.0), 1),
    "hr": lambda: int(_clamp(random.gauss(68, 8), 40, 130)),
    "stress": lambda: int(_clamp(random.gauss(40, 18), 0, 100)),
    "pr": lambda: int(_clamp(random.gauss(15, 2), 8, 30)),
    "temp": lambda: round(_clamp(random.gauss(36.7, 0.3), 34.0, 40.0), 1),
    "ox": lambda: round(_clamp(random.gauss(97.5, 1.0), 85.0, 100.0), 1),
}


def _real_or_simulated(name, real):
    if real is not None:
        _SOURCE[name] = "export"
        return real
    if not FALLBACK_TO_SIMULATED:
        raise LookupError(f"No '{name}' data in the loaded export")
    _SOURCE[name] = "simulated"
    return _SIMULATED[name]()


def data_source():
    """{'hr': 'export' | 'simulated', ...} for the values read so far."""
    return dict(_SOURCE)


# --- raw readers: return None when the export has no such data ---
def _raw_sleep():
    if _SLEEP:
        # merge overlapping intervals (iPhone + Watch often record the same sleep)
        merged = []
        for s, e in sorted(_SLEEP):
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        # group into sessions: a gap of more than 3 h starts a new session
        sessions, current, prev_end = [], 0.0, None
        for s, e in merged:
            if prev_end is not None and s - prev_end > 3 * 3600:
                sessions.append(current)
                current = 0.0
            current += e - s
            prev_end = e
        sessions.append(current)
        # last session of at least 2 h (ignores short naps), else the last one
        full = [x for x in sessions if x >= 2 * 3600]
        return round((full[-1] if full else sessions[-1]) / 3600, 1)
    rows = _DATA.get("sleep_hours")
    if rows:
        value = max(rows)[1]                 # latest record
        return round(value / 60 if value > 24 else value, 1)   # minutes -> hours
    return None


def _raw_hr(hours=24):
    rhr = _avg(_recent("resting_hr", hours))
    if rhr is None:                           # no resting HR: low end of all HR
        hr = sorted(_recent("heart_rate", hours))
        rhr = hr[int(0.10 * len(hr))] if hr else None
    return rhr


def _raw_stress(hours=24):
    """Watch's own stress value if present, otherwise computed from HRV,
    resting HR, breathing rate and sleep (simple heuristic, not a diagnosis)."""
    own = _avg(_recent("stress", hours))
    if own is not None:
        return _clamp(own, 0, 100)
    rhr = _raw_hr(hours)
    hrv = _avg(_recent("hrv", hours))
    resp = _avg(_recent("resp_rate", hours))
    sleep_h = _raw_sleep()
    parts = []   # (weight, 0 = good .. 1 = bad)
    if hrv is not None:
        parts.append((0.35, _clamp((60 - hrv) / 40, 0, 1)))
    if rhr is not None:
        parts.append((0.25, _clamp((rhr - 60) / 30, 0, 1)))
    if resp is not None:
        parts.append((0.15, _clamp((resp - 14) / 8, 0, 1)))
    if sleep_h is not None:
        parts.append((0.25, _clamp((7.5 - sleep_h) / 4, 0, 1)))
    if not parts:
        return None
    total = sum(w for w, _ in parts)
    return 100 * sum(w * s for w, s in parts) / total


def _to_int(x):
    return None if x is None else int(round(x))


# --- public functions (the contract) ---
def get_sleep():
    """Hours slept during the most recent night (float)."""
    return _real_or_simulated("sleep", _raw_sleep())


def get_hr(hours=24):
    """Resting heart rate, beats/min (int)."""
    return _real_or_simulated("hr", _to_int(_raw_hr(hours)))


def get_stress(hours=24):
    """Stress score 0-100 (int)."""
    return _real_or_simulated("stress", _to_int(_raw_stress(hours)))


def get_pr(hours=24):
    """Respiratory rate, breaths/min (int)."""
    return _real_or_simulated("pr", _to_int(_avg(_recent("resp_rate", hours))))


def get_temp(hours=24):
    """Body/skin temperature in degrees Celsius (float)."""
    return _real_or_simulated("temp", _avg(_recent("temp", hours)))


def get_ox(hours=24):
    """Blood oxygen saturation SpO2 in % (float)."""
    return _real_or_simulated("ox", _avg(_recent("spo2", hours)))


# --- extra (not part of the contract) ---
def get_bp(hours=24):
    """Blood pressure -> (systolic, diastolic) mmHg, or (None, None).
    Most watches do not measure it, so there is no simulated fallback."""
    s, d = _avg(_recent("systolic", hours), 0), _avg(_recent("diastolic", hours), 0)
    return (int(s), int(d)) if s is not None and d is not None else (None, None)


# short aliases from the first version
ss = get_stress
ox = get_ox


def summary():
    """All contract values at once (e.g. to send to the main program as JSON)."""
    return {
        "sleep": get_sleep(),
        "hr": get_hr(),
        "stress": get_stress(),
        "pr": get_pr(),
        "temp": get_temp(),
        "ox": get_ox(),
        "source": data_source(),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python smartwatch.py <export.zip | export.xml | file.csv | file.json>")
    print("Loaded:", smartwatch(sys.argv[1]))
    print(json.dumps(summary(), indent=2))