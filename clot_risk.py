"""
clot_risk.py - blood clot (VTE) risk estimate from a D-dimer measurement,
e.g. taken by the astronaut with the ACTIS device (Acute Care Testing in Space).

No external libraries needed (Python 3.9+).

Usage in the main program:

    from clot_risk import clot_risk, clot_risk_report

    clot_risk(620, "ng/mL FEU")                 # -> 27.8  (percent)
    clot_risk(0.62, "mg/L FEU", age=45)         # same value, different unit
    clot_risk(620, "ng/mL FEU", age=58,
              symptoms=["leg_swelling_or_pain"])  # -> higher

    clot_risk_report(620, "ng/mL FEU")          # dict with level + advice

IMPORTANT - READ THIS:
D-dimer alone can NOT give a true clot probability. It is a "rule-out" test:
a low value makes a clot unlikely, a high value only means "something is
clotting/breaking down" (it also rises with injury, inflammation, infection,
age...). The percentage returned here is a simple heuristic RISK SCORE made
for the hackathon demo, not a diagnosis. Confirmation needs ultrasound and a
flight surgeon.
"""
import math

# Conversion factors to ng/mL FEU (fibrinogen equivalent units).
# DDU values are about half of FEU values, so DDU -> FEU is x2.
# A plain "ng/mL" or "mg/L" is assumed to be FEU - CHECK what your device reports.
_UNIT_TO_NG_ML_FEU = {
    "ng/ml feu": 1.0,
    "ng/ml": 1.0,
    "ug/l feu": 1.0,
    "ug/l": 1.0,
    "ng/ml ddu": 2.0,
    "ug/l ddu": 2.0,
    "mg/l feu": 1000.0,
    "mg/l": 1000.0,
    "ug/ml feu": 1000.0,
    "ug/ml": 1000.0,
    "mg/l ddu": 2000.0,
    "ug/ml ddu": 2000.0,
}

STANDARD_CUTOFF = 500.0       # ng/mL FEU, usual cut-off on Earth
URGENT_SYMPTOMS = "chest_pain_or_breathlessness"
SYMPTOMS = {
    "leg_swelling_or_pain": "leg swelling, pain or redness",
    "neck_or_arm_swelling": "neck, face or arm swelling / pain (jugular / upper-limb vein)",
    URGENT_SYMPTOMS: "chest pain, shortness of breath or coughing blood",
}
_SYMPTOM_ODDS = 1.8           # each symptom group multiplies the odds by this


def _to_ng_ml_feu(value, unit):
    key = " ".join(str(unit).strip().lower().replace("µ", "u").split())
    if key not in _UNIT_TO_NG_ML_FEU:
        raise ValueError(f"Unknown unit '{unit}'. Use one of: "
                         + ", ".join(sorted(_UNIT_TO_NG_ML_FEU)))
    return value * _UNIT_TO_NG_ML_FEU[key]


def _cutoff(age):
    """Age-adjusted cut-off: age x 10 ng/mL FEU for people over 50."""
    if age is not None and age > 50:
        return max(STANDARD_CUTOFF, age * 10.0)
    return STANDARD_CUTOFF


def clot_risk(d_dimer, unit="ng/mL FEU", age=None, symptoms=None):
    """Blood clot risk score in percent (0-100, one decimal).

    d_dimer  : the number shown by the device (e.g. ACTIS)
    unit     : unit shown by the device, e.g. "ng/mL FEU", "mg/L FEU", "ng/mL DDU"
    age      : optional, years (uses the age-adjusted cut-off over 50)
    symptoms : optional list from SYMPTOMS keys, e.g. ["leg_swelling_or_pain"]
    """
    return clot_risk_report(d_dimer, unit, age, symptoms)["risk_percent"]


def clot_risk_report(d_dimer, unit="ng/mL FEU", age=None, symptoms=None):
    """Same as clot_risk() but returns everything the app may want to show."""
    try:
        value = float(d_dimer)
    except (TypeError, ValueError):
        raise ValueError("d_dimer must be a number")
    if not math.isfinite(value) or value < 0:
        raise ValueError("d_dimer must be a number >= 0")
    symptoms = list(symptoms or [])
    for s in symptoms:
        if s not in SYMPTOMS:
            raise ValueError(f"Unknown symptom '{s}'. Use: {sorted(SYMPTOMS)}")

    ng = _to_ng_ml_feu(value, unit)
    cutoff = _cutoff(age)
    ratio = ng / cutoff

    # Heuristic mapping: 0.5x cut-off ~ 6 %, 1x ~ 20 %, 2x ~ 50 %, 4x ~ 80 %, 10x ~ 96 %
    p = ratio ** 2 / (ratio ** 2 + 4)
    # Symptoms raise the odds
    if symptoms:
        odds = (p / (1 - p)) * (_SYMPTOM_ODDS ** len(symptoms)) if p < 1 else float("inf")
        p = odds / (1 + odds)
    percent = round(min(p * 100, 99.0), 1)

    if percent < 25:
        level = "low"
    elif percent < 50:
        level = "moderate"
    elif percent < 75:
        level = "high"
    else:
        level = "very high"

    urgent = URGENT_SYMPTOMS in symptoms
    if urgent:
        advice = ("Chest pain / breathlessness with a raised clot risk is an emergency: "
                  "contact the flight surgeon immediately.")
    elif level == "low":
        advice = ("Clot unlikely. Keep exercising, stay hydrated and repeat the test "
                  "on schedule or if symptoms appear.")
    elif level == "moderate":
        advice = ("Above the usual range. Repeat the test and report the result to the "
                  "flight surgeon; watch for swelling or pain.")
    else:
        advice = ("High result. Contact the flight surgeon now: an ultrasound check "
                  "of the veins is needed to confirm or exclude a clot.")

    return {
        "risk_percent": percent,
        "level": level,
        "d_dimer_ng_ml_feu": round(ng, 1),
        "cutoff_ng_ml_feu": cutoff,
        "above_cutoff": ng >= cutoff,
        "symptoms": symptoms,
        "urgent": urgent,
        "advice": advice,
        "disclaimer": "Heuristic risk score for a hackathon demo, not a medical diagnosis.",
    }


if __name__ == "__main__":
    # Simple question-and-answer mode for the astronaut: python clot_risk.py
    print("D-dimer blood clot risk (ACTIS)")
    value = float(input("D-dimer value shown by the device: "))
    unit = input("Unit [ng/mL FEU]: ").strip() or "ng/mL FEU"
    age_txt = input("Age (optional): ").strip()
    print("Symptoms:")
    chosen = []
    for key, text in SYMPTOMS.items():
        if input(f"  {text}? (y/n) ").strip().lower().startswith("y"):
            chosen.append(key)
    r = clot_risk_report(value, unit, int(age_txt) if age_txt else None, chosen)
    print(f"\nClot risk: {r['risk_percent']} %  ({r['level']})")
    print(r["advice"])
    print(r["disclaimer"])
