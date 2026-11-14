"""
healthMonitor.py - health analysis engine.

Data sources
    smartwatch.py : get_sleep() get_hr() get_stress() get_pr() get_temp() get_ox()
    UserInt.py    : weight (kg), height (cm), bloodPressure (sys, dia)
                    optional: age, sex, activity (defaults used if missing)

Reference standards used (all adult-oriented):
    BMI classes ........ WHO (1995/2000/2004)
    Blood pressure ..... ACC/AHA 2017 guideline (hypotension: <90/60 common clinical cut-off)
    Resting heart rate . 60-100 bpm normal range (AHA); <60 bradycardia, >100 tachycardia
    Max heart rate ..... Tanaka et al. 2001: 208 - 0.7 x age
    Heart-rate zones ... Karvonen / heart-rate reserve, ACSM intensity classes
    Respiratory rate ... NEWS2 (Royal College of Physicians, 2017) bands
    Body temperature ... 36.1-37.2 C normal; >=38.0 C fever; <35.0 C hypothermia
    SpO2 ............... >=95 % normal; <90 % hypoxaemia (WHO/BTS oxygen guidance)
    Sleep .............. AASM/SRS consensus 2015 and National Sleep Foundation 2015
    Energy needs ....... Mifflin-St Jeor 1990 (BMR) x activity factor
    Hydration .......... ~30-35 mL per kg body weight per day (EFSA total water intake as reference)
    Protein ............ RDA 0.8 g per kg per day
    Physical activity .. WHO 2020: 150-300 min/week moderate or 75-150 min vigorous

NOT a medical device. Results are informational and never replace a doctor.
"""

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime

import smartwatch
import UserInt

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "health_log.csv")

OK, WARN, ALERT = 0, 1, 2
TAGS = {OK: "[ OK ]", WARN: "[ !  ]", ALERT: "[ !! ]"}

ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


@dataclass
class Metric:
    name: str
    value: str
    status: str
    advice: str = ""
    level: int = OK


@dataclass
class Report:
    timestamp: str
    metrics: list = field(default_factory=list)
    extras: list = field(default_factory=list)     # (label, text) info lines
    alerts: list = field(default_factory=list)
    score: int = 100
    raw: dict = field(default_factory=dict)


# ============================================================ profile handling
def get_profile():
    """Read values from UserInt at call time (so UI changes are always seen)."""
    profile = {
        "weight": float(UserInt.weight),
        "height": float(UserInt.height),
        "bp": parse_blood_pressure(UserInt.bloodPressure),
        "age": int(getattr(UserInt, "age", 30)),
        "sex": str(getattr(UserInt, "sex", "male")).lower(),
        "activity": str(getattr(UserInt, "activity", "light")).lower(),
    }
    validate_profile(profile)
    return profile


def parse_blood_pressure(bp):
    """Accepts (120, 80), [120, 80], '120/80' or {'systolic':120,'diastolic':80}."""
    if isinstance(bp, dict):
        return int(bp["systolic"]), int(bp["diastolic"])
    if isinstance(bp, str):
        parts = [p for p in bp.replace(",", "/").replace(" ", "/").split("/") if p]
        if len(parts) != 2:
            raise ValueError("Blood pressure must look like 120/80")
        return int(parts[0]), int(parts[1])
    sys_, dia = bp
    return int(sys_), int(dia)


def validate_profile(p):
    if not 20 <= p["weight"] <= 400:
        raise ValueError("Weight must be between 20 and 400 kg")
    if not 80 <= p["height"] <= 250:
        raise ValueError("Height must be between 80 and 250 cm")
    sys_, dia = p["bp"]
    if not (50 <= sys_ <= 300 and 30 <= dia <= 200 and sys_ > dia):
        raise ValueError("Blood pressure values are not plausible (systolic must exceed diastolic)")
    if not 18 <= p["age"] <= 110:
        raise ValueError("This app's reference ranges are for adults (age 18-110)")
    if p["sex"] not in ("male", "female"):
        raise ValueError("Sex must be 'male' or 'female'")
    if p["activity"] not in ACTIVITY_FACTORS:
        raise ValueError("Activity must be one of: " + ", ".join(ACTIVITY_FACTORS))


# ============================================================ body measurements
def calc_bmi(weight_kg, height_cm):
    m = height_cm / 100
    return weight_kg / (m * m)


def classify_bmi(bmi):
    """WHO classification."""
    if bmi < 16.0:
        return "Severe thinness", ALERT
    if bmi < 17.0:
        return "Moderate thinness", WARN
    if bmi < 18.5:
        return "Mild thinness (underweight)", WARN
    if bmi < 25.0:
        return "Normal weight", OK
    if bmi < 30.0:
        return "Overweight (pre-obese)", WARN
    if bmi < 35.0:
        return "Obesity class I", WARN
    if bmi < 40.0:
        return "Obesity class II", ALERT
    return "Obesity class III", ALERT


def healthy_weight_range(height_cm):
    """Weights giving BMI 18.5 - 24.9."""
    m2 = (height_cm / 100) ** 2
    return 18.5 * m2, 24.9 * m2


def ideal_weight_devine(height_cm, sex):
    inches_over_60 = max(0.0, height_cm / 2.54 - 60)
    base, per_inch = (50.0, 2.3) if sex == "male" else (45.5, 2.3)
    return base + per_inch * inches_over_60


def bmr_mifflin(weight_kg, height_cm, age, sex):
    """Mifflin-St Jeor basal metabolic rate, kcal/day."""
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)


def daily_energy_kcal(bmr, activity):
    return bmr * ACTIVITY_FACTORS[activity]


def daily_water_ml(weight_kg):
    """Returns (low, high) mL/day, 30-35 mL per kg."""
    return 30 * weight_kg, 35 * weight_kg


def daily_protein_g(weight_kg):
    return 0.8 * weight_kg


# ============================================================ blood pressure
def classify_blood_pressure(sys_, dia):
    """ACC/AHA 2017 categories (higher of the two readings decides)."""
    if sys_ > 180 or dia > 120:
        return "Hypertensive crisis", ALERT, "Seek urgent medical care, especially with chest pain, headache, vision change or breathlessness."
    if sys_ >= 140 or dia >= 90:
        return "Hypertension stage 2", ALERT, "See a doctor soon; treatment is usually recommended."
    if sys_ >= 130 or dia >= 80:
        return "Hypertension stage 1", WARN, "Discuss with a doctor; lifestyle changes (salt <5 g/day, DASH diet, exercise, weight) help."
    if sys_ >= 120:
        return "Elevated", WARN, "Lifestyle measures recommended; recheck regularly."
    if sys_ < 90 or dia < 60:
        return "Low blood pressure (hypotension)", WARN, "Harmless if no symptoms; see a doctor if dizzy, faint or tired."
    return "Normal", OK, "Keep it up: activity, low salt, limited alcohol."


def mean_arterial_pressure(sys_, dia):
    return dia + (sys_ - dia) / 3


def pulse_pressure(sys_, dia):
    return sys_ - dia


# ============================================================ heart rate
def max_heart_rate_tanaka(age):
    return 208 - 0.7 * age


def classify_resting_hr(hr, age):
    if hr < 40:
        return "Very low", ALERT, "Seek care, particularly with dizziness or fainting."
    if hr < 60:
        return "Bradycardia range", OK, "Common and healthy in trained people; check with a doctor if you have symptoms."
    if hr <= 100:
        if hr <= 70:
            return "Normal (good)", OK, "Lower resting rates are linked with better cardiovascular fitness."
        return "Normal", OK, "Regular aerobic exercise can lower resting heart rate over time."
    if hr <= 120:
        return "Tachycardia range", WARN, "If you were at rest, consider caffeine, stress, fever, dehydration; see a doctor if persistent."
    return "Marked tachycardia", ALERT, "Seek medical advice, especially with chest pain, dizziness or breathlessness."


def heart_rate_zones(resting_hr, age):
    """Karvonen zones (heart-rate reserve) with ACSM intensity bands."""
    hr_max = max_heart_rate_tanaka(age)
    reserve = hr_max - resting_hr

    def zone(lo, hi):
        return round(resting_hr + lo * reserve), round(resting_hr + hi * reserve)

    return {
        "Light (30-39% HRR)": zone(0.30, 0.39),
        "Moderate (40-59% HRR)": zone(0.40, 0.59),
        "Vigorous (60-89% HRR)": zone(0.60, 0.89),
    }


# ============================================================ other vitals
def classify_respiratory_rate(rr):
    """NEWS2 bands."""
    if rr <= 8:
        return "Dangerously low", ALERT, "Seek urgent medical help."
    if rr <= 11:
        return "Low", WARN, "Recheck at rest; see a doctor if it persists."
    if rr <= 20:
        return "Normal", OK, "Normal adult resting range is 12-20 breaths/min."
    if rr <= 24:
        return "Raised", WARN, "Recheck at rest; fever, anxiety, exertion or infection can raise it."
    return "High", ALERT, "Seek medical advice, particularly with breathlessness."


def classify_temperature(t):
    if t < 35.0:
        return "Hypothermia range", ALERT, "Warm up and seek medical help if it is confirmed."
    if t < 36.1:
        return "Slightly low", WARN, "Wrist/skin readings run lower than core temperature; recheck."
    if t <= 37.2:
        return "Normal", OK, "Normal range is about 36.1-37.2 C."
    if t < 38.0:
        return "Slightly raised", WARN, "Rest, drink fluids, and recheck."
    if t < 39.5:
        return "Fever", WARN, "Rest and fluids; see a doctor if it lasts over 3 days or you feel very unwell."
    return "High fever", ALERT, "Seek medical care."


def classify_spo2(spo2):
    if spo2 >= 95:
        return "Normal", OK, "Normal oxygen saturation is 95-100 %."
    if spo2 >= 92:
        return "Borderline low", WARN, "Recheck at rest with warm hands; watch for breathlessness."
    if spo2 >= 90:
        return "Low", ALERT, "Seek medical advice, particularly with symptoms."
    return "Very low (hypoxaemia)", ALERT, "Seek urgent medical care."


def recommended_sleep_range(age):
    """AASM/SRS and National Sleep Foundation: hours per night."""
    if age >= 65:
        return 7, 8
    return 7, 9


def classify_sleep(hours, age):
    lo, hi = recommended_sleep_range(age)
    if hours < 5:
        return "Severe sleep deficit", ALERT, f"Aim for {lo}-{hi} h; chronic short sleep raises cardiometabolic and mental-health risk."
    if hours < lo:
        return "Below recommendation", WARN, f"Aim for {lo}-{hi} h: consistent schedule, dark cool room, no screens/caffeine late."
    if hours <= hi:
        return "Within recommendation", OK, f"{lo}-{hi} h is the recommended range."
    return "Longer than usual", WARN, "Regularly sleeping much longer than recommended can accompany health issues; mention it to a doctor if persistent."


def classify_stress(score):
    """Smartwatch scale 0-100 (device-dependent; typical bands)."""
    if score < 30:
        return "Low", OK, "Good recovery state."
    if score < 60:
        return "Moderate", OK, "Normal daily load; schedule short breaks."
    if score < 80:
        return "High", WARN, "Try slow breathing (about 6 breaths/min), a walk, or a short break."
    return "Very high", WARN, "Prioritise rest; if stress is constant, consider talking to a professional."


# ============================================================ sensor reading
SENSOR_LIMITS = {          # physiologically plausible raw ranges
    "sleep": (0, 24),
    "hr": (20, 250),
    "stress": (0, 100),
    "pr": (3, 60),
    "temp": (30, 45),
    "ox": (50, 100),
}


def read_sensors():
    """Call the watch; a failed or implausible sensor becomes None."""
    getters = {
        "sleep": smartwatch.get_sleep,
        "hr": smartwatch.get_hr,
        "stress": smartwatch.get_stress,
        "pr": smartwatch.get_pr,
        "temp": smartwatch.get_temp,
        "ox": smartwatch.get_ox,
    }
    data = {}
    for key, getter in getters.items():
        try:
            value = float(getter())
            lo, hi = SENSOR_LIMITS[key]
            data[key] = value if lo <= value <= hi else None
        except Exception:
            data[key] = None
    return data


# ============================================================ report building
def build_report():
    p = get_profile()
    s = read_sensors()
    r = Report(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"))
    r.raw = {**s, "weight": p["weight"], "height": p["height"],
             "sys": p["bp"][0], "dia": p["bp"][1]}

    # --- body
    bmi = calc_bmi(p["weight"], p["height"])
    label, lvl = classify_bmi(bmi)
    lo_w, hi_w = healthy_weight_range(p["height"])
    r.metrics.append(Metric("BMI", f"{bmi:.1f} kg/m2", label,
                            f"Healthy weight for your height: {lo_w:.0f}-{hi_w:.0f} kg.", lvl))
    r.raw["bmi"] = round(bmi, 1)

    # --- blood pressure
    sys_, dia = p["bp"]
    label, lvl, advice = classify_blood_pressure(sys_, dia)
    map_ = mean_arterial_pressure(sys_, dia)
    pp = pulse_pressure(sys_, dia)
    extra = f" MAP {map_:.0f} mmHg, pulse pressure {pp} mmHg."
    if pp > 60:
        extra += " Wide pulse pressure (>60) can indicate arterial stiffness."
        lvl = max(lvl, WARN)
    r.metrics.append(Metric("Blood pressure", f"{sys_}/{dia} mmHg", label, advice + extra, lvl))

    # --- watch vitals
    def add(key, name, fmt, classifier, *args):
        if s[key] is None:
            r.metrics.append(Metric(name, "n/a", "Sensor error or no data",
                                    "Re-fit the watch and measure again.", WARN))
            return
        label, lvl, advice = classifier(s[key], *args)
        r.metrics.append(Metric(name, fmt.format(s[key]), label, advice, lvl))

    add("hr", "Resting heart rate", "{:.0f} bpm", classify_resting_hr, p["age"])
    add("ox", "Blood oxygen (SpO2)", "{:.1f} %", classify_spo2)
    add("pr", "Respiratory rate", "{:.0f} /min", classify_respiratory_rate)
    add("temp", "Temperature", "{:.1f} C", classify_temperature)
    add("sleep", "Sleep (last night)", "{:.1f} h", classify_sleep, p["age"])
    add("stress", "Stress score", "{:.0f} /100", classify_stress)

    # --- informational numbers
    bmr = bmr_mifflin(p["weight"], p["height"], p["age"], p["sex"])
    r.extras.append(("Energy", f"BMR {bmr:.0f} kcal/day; maintenance about "
                               f"{daily_energy_kcal(bmr, p['activity']):.0f} kcal/day ({p['activity']} activity)."))
    wl, wh = daily_water_ml(p["weight"])
    r.extras.append(("Hydration", f"About {wl/1000:.1f}-{wh/1000:.1f} L of fluids per day (more in heat or exercise)."))
    r.extras.append(("Protein", f"RDA minimum about {daily_protein_g(p['weight']):.0f} g/day."))
    r.extras.append(("Ideal weight", f"Devine formula: {ideal_weight_devine(p['height'], p['sex']):.0f} kg (reference only; BMI range above is preferred)."))
    if s["hr"] is not None:
        hr_max = max_heart_rate_tanaka(p["age"])
        zones = heart_rate_zones(s["hr"], p["age"])
        zone_text = "; ".join(f"{k}: {a}-{b} bpm" for k, (a, b) in zones.items())
        r.extras.append(("Heart-rate zones", f"Max HR about {hr_max:.0f} bpm. {zone_text}."))
    r.extras.append(("Activity goal", "WHO: 150-300 min/week moderate (or 75-150 min vigorous) plus strength work 2 days/week."))

    # --- combined-risk rules
    names = {m.name: m for m in r.metrics}
    if names["Blood pressure"].level >= WARN and names["BMI"].level >= WARN:
        r.extras.append(("Combined risk", "Raised blood pressure together with excess weight increases cardiovascular risk; a medical check-up is advisable."))
    if s["sleep"] is not None and s["stress"] is not None and s["sleep"] < 6 and s["stress"] >= 60:
        r.extras.append(("Combined risk", "Short sleep together with high stress: prioritise recovery today."))
    if s["temp"] is not None and s["hr"] is not None and s["temp"] >= 37.8 and s["hr"] > 90:
        r.extras.append(("Combined risk", "Raised temperature with fast heart rate may signal infection; rest, hydrate, monitor."))

    # --- alerts and score
    for m in r.metrics:
        if m.level == ALERT:
            r.alerts.append(f"{m.name}: {m.value} - {m.status}")
    score = 100
    for m in r.metrics:
        score -= {OK: 0, WARN: 8, ALERT: 18}[m.level]
    r.score = max(0, score)
    return r


def score_label(score):
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 55:
        return "Fair"
    return "Needs attention"


def format_report(r):
    lines = []
    lines.append("=" * 78)
    lines.append(f" HEALTH REPORT  -  {r.timestamp}")
    lines.append("=" * 78)
    for m in r.metrics:
        lines.append(f"{TAGS[m.level]} {m.name:<22} {m.value:<14} {m.status}")
        if m.advice:
            lines.append(f"         -> {m.advice}")
    lines.append("-" * 78)
    for label, text in r.extras:
        lines.append(f" {label}: {text}")
    lines.append("-" * 78)
    lines.append(f" Overall score: {r.score}/100 ({score_label(r.score)})")
    if r.alerts:
        lines.append("")
        lines.append(" ATTENTION - consider medical advice for:")
        for a in r.alerts:
            lines.append(f"   * {a}")
        lines.append(" If you have chest pain, severe breathlessness, fainting or confusion, call emergency services (112 in Greece/EU).")
    lines.append("")
    lines.append(" Informational only - not a medical device and not a diagnosis.")
    trend = trend_summary()
    if trend:
        lines.append("")
        lines.append(trend)
    return "\n".join(lines)


# ============================================================ history / trends
LOG_FIELDS = ["timestamp", "weight", "height", "bmi", "sys", "dia",
              "hr", "ox", "pr", "temp", "sleep", "stress", "score"]


def log_report(r):
    new_file = not os.path.exists(LOG_FILE)
    try:
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            row = dict(r.raw)
            row["timestamp"] = r.timestamp
            row["score"] = r.score
            writer.writerow(row)
    except OSError:
        pass  # logging must never crash the app


def trend_summary(last_n=7):
    """Compare the average of previous entries with the latest one."""
    try:
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return ""
    if len(rows) < 2:
        return ""
    recent = rows[-last_n:]
    latest = recent[-1]
    previous = recent[:-1]

    def avg(key):
        vals = [float(x[key]) for x in previous if x.get(key) not in (None, "")]
        return sum(vals) / len(vals) if vals else None

    parts = []
    for key, label in (("score", "score"), ("hr", "resting HR"), ("sleep", "sleep h"), ("weight", "weight kg")):
        a = avg(key)
        if a is not None and latest.get(key) not in (None, ""):
            parts.append(f"{label}: {float(latest[key]):.1f} (avg of previous {len(previous)}: {a:.1f})")
    return " Trend: " + "; ".join(parts) if parts else ""


# ============================================================ entry point
def run():
    try:
        report = build_report()
    except ValueError as err:
        print(f"Cannot analyse: {err}")
        return None
    log_report(report)
    print(format_report(report))
    return report


if __name__ == "__main__":
    run()