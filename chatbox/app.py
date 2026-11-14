"""
SolarGuard backend – NASA Space Apps Challenge 2026.

- POST /api/vitals : the watch (or simulator) posts its latest vitals
- GET  /api/context: what the bot currently "sees" (vitals + solar radiation + risk)
- POST /api/chat   : user question -> LLM answer grounded in the current context
- POST /api/scenario: switch the demo scenario (rest / walk / run_sun)
- GET  /           : the main dashboard (static/dashboard.html)
- GET  /chat       : standalone chat box (static/chat.html)
- /api/health/...  : daily health check powered by the team's healthMonitor.py /
                     smartwatch.py / UserInt.py (repo root), see the health section below

Run:
    pip install -r requirements.txt
    create a .env file next to app.py containing:  GROQ_API_KEY=gsk_...
    python -m uvicorn app:app --reload
    -> open http://localhost:8000
"""

import math
import os
import random
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from groq import Groq
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")  # loads GROQ_API_KEY from .env

# The team's health engine lives in the repo root (healthMonitor.py, smartwatch.py,
# UserInt.py). Make it importable whether the server starts from the root or chatbox/.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
try:
    import healthMonitor
    import smartwatch
    import UserInt
    HEALTH_ERROR = None
except Exception as e:  # keep the dashboard running even if the module is missing
    healthMonitor = smartwatch = UserInt = None
    HEALTH_ERROR = f"{type(e).__name__}: {e}"

MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
LAT = float(os.getenv("LAT", "37.98"))   # Athens by default
LON = float(os.getenv("LON", "23.73"))

app = FastAPI(title="Solar Health Chatbot")
app.add_middleware(  # allow calls from a frontend on another origin
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

STATIC = Path(__file__).parent / "static"


# ---------------------------------------------------------------- Vitals ----
class Vitals(BaseModel):
    heart_rate: float | None = None      # bpm
    spo2: float | None = None            # %
    skin_temp: float | None = None       # °C
    steps: int | None = None
    timestamp: float | None = None


latest_vitals: Vitals | None = None


# Watch simulator with demo scenarios. Values drift smoothly toward the
# scenario target (like a real body would), instead of jumping randomly.
SCENARIOS = {
    #            heart rate, SpO2, skin temp, steps/sec, UV/air-temp override
    "rest":    dict(hr=72,  spo2=98.0, skin=33.6, spm=0.0, solar=None),
    "walk":    dict(hr=98,  spo2=97.5, skin=34.6, spm=1.8, solar=None),
    "run_sun": dict(hr=152, spo2=95.5, skin=37.4, spm=2.8,
                    solar={"uv_index": 9.2, "air_temp_c": 34.5}),
}
sim = {"scenario": "rest", "hr": 72.0, "spo2": 98.0, "skin": 33.6,
       "steps": 4200.0, "t": time.time()}


def simulated_vitals() -> Vitals:
    """Simulated vitals, used until a real watch posts data."""
    now = time.time()
    dt = min(now - sim["t"], 30)
    sim["t"] = now
    target = SCENARIOS[sim["scenario"]]
    a = 1 - math.exp(-dt / 15)  # ~15 s time constant to approach the target
    sim["hr"] += (target["hr"] - sim["hr"]) * a + random.gauss(0, 1.2)
    sim["spo2"] += (target["spo2"] - sim["spo2"]) * a + random.gauss(0, 0.1)
    sim["skin"] += (target["skin"] - sim["skin"]) * a + random.gauss(0, 0.03)
    sim["steps"] += target["spm"] * dt
    return Vitals(
        heart_rate=round(sim["hr"]),
        spo2=round(min(sim["spo2"], 100), 1),
        skin_temp=round(sim["skin"], 1),
        steps=int(sim["steps"]),
        timestamp=now,
    )


class Scenario(BaseModel):
    name: str


@app.post("/api/scenario")
def set_scenario(s: Scenario):
    if s.name not in SCENARIOS:
        raise HTTPException(400, f"Unknown scenario. Available: {list(SCENARIOS)}")
    sim["scenario"] = s.name
    return {"ok": True, "scenario": s.name}


@app.post("/api/vitals")
def post_vitals(v: Vitals):
    global latest_vitals
    v.timestamp = v.timestamp or time.time()
    latest_vitals = v
    return {"ok": True}


def current_vitals() -> tuple[Vitals, bool]:
    """Returns (vitals, is_simulated). Real watch data counts as fresh for 2 minutes."""
    if latest_vitals and time.time() - (latest_vitals.timestamp or 0) < 120:
        return latest_vitals, False
    return simulated_vitals(), True


# ---------------------------------------------------- Solar (NASA POWER) ----
_solar_cache: dict = {"t": 0, "data": None}


def solar_data() -> dict:
    """
    Daily data from the NASA POWER API for the configured location:
      ALLSKY_SFC_UV_INDEX : UV index
      ALLSKY_SFC_SW_DWN   : all-sky surface shortwave irradiance (kWh/m²/day)
      T2M                 : air temperature at 2 m (°C)
    POWER data lags a few days, so we take the most recent valid value.
    Cached for 1 hour; falls back to simulated values when offline.
    """
    if _solar_cache["data"] and time.time() - _solar_cache["t"] < 3600:
        return _solar_cache["data"]

    end = date.today()
    start = end - timedelta(days=10)
    params = {
        "parameters": "ALLSKY_SFC_UV_INDEX,ALLSKY_SFC_SW_DWN,T2M",
        "community": "RE",
        "latitude": LAT,
        "longitude": LON,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    try:
        r = httpx.get(
            "https://power.larc.nasa.gov/api/temporal/daily/point",
            params=params, timeout=15,
        )
        r.raise_for_status()
        p = r.json()["properties"]["parameter"]
        out = {"source": "NASA POWER", "lat": LAT, "lon": LON}
        for key, name in [("ALLSKY_SFC_UV_INDEX", "uv_index"),
                          ("ALLSKY_SFC_SW_DWN", "irradiance_kwh_m2_day"),
                          ("T2M", "air_temp_c")]:
            valid = {d: v for d, v in p[key].items() if v != -999}
            if valid:
                d = max(valid)
                out[name] = valid[d]
                out["date"] = d
        data = out
    except Exception as e:  # offline / API down -> demo values
        data = {
            "source": f"simulated (NASA POWER unavailable: {type(e).__name__})",
            "uv_index": round(random.uniform(2, 9), 1),
            "irradiance_kwh_m2_day": round(random.uniform(2, 7), 2),
            "air_temp_c": round(random.uniform(15, 35), 1),
        }
    _solar_cache.update(t=time.time(), data=data)
    return data


# -------------------------------------------------------------- Risk score ---
def risk_score(v: Vitals, s: dict) -> dict:
    """Simple, explainable 0-100 risk score shown on the dashboard and given to the bot."""
    score, reasons = 0, []
    uv = s.get("uv_index") or 0
    if uv >= 8:
        score += 40; reasons.append(f"very high UV ({uv})")
    elif uv >= 6:
        score += 25; reasons.append(f"high UV ({uv})")
    elif uv >= 3:
        score += 10; reasons.append(f"moderate UV ({uv})")
    if (s.get("air_temp_c") or 0) >= 32:
        score += 15; reasons.append(f"heat ({s['air_temp_c']}°C)")
    if (v.heart_rate or 0) >= 110:
        score += 20; reasons.append(f"elevated heart rate ({v.heart_rate:.0f} bpm)")
    if (v.skin_temp or 0) >= 37:
        score += 15; reasons.append(f"high skin temperature ({v.skin_temp}°C)")
    if v.spo2 and v.spo2 < 94:
        score += 20; reasons.append(f"low SpO₂ ({v.spo2}%)")
    score = min(score, 100)
    level = "low" if score < 30 else "moderate" if score < 60 else "high"
    return {"score": score, "level": level, "reasons": reasons}


@app.get("/api/context")
def get_context():
    v, simulated = current_vitals()
    s = dict(solar_data())
    override = SCENARIOS[sim["scenario"]]["solar"] if simulated else None
    if override:  # "run in the sun" demo scenario: midday sun
        s.update(override)
        s["source"] = "demo scenario (" + s.get("source", "") + ")"
    return {
        "vitals": v.model_dump(),
        "vitals_simulated": simulated,
        "scenario": sim["scenario"] if simulated else None,
        "solar": s,
        "risk": risk_score(v, s),
    }



# ------------------------------------------------- Daily health check ---
# Wraps the team's engine: healthMonitor.build_report() reads the profile from
# UserInt and the daily vitals from smartwatch (an uploaded export or simulated).
_health = {"sensors": None, "report": None, "export": None}
_health_lock = threading.Lock()


def _require_health():
    if healthMonitor is None:
        raise HTTPException(503, f"Health module not available ({HEALTH_ERROR}).")


def _report_to_dict(r) -> dict:
    lvl = {healthMonitor.OK: "ok", healthMonitor.WARN: "warn", healthMonitor.ALERT: "alert"}
    return {
        "timestamp": r.timestamp,
        "score": r.score,
        "score_label": healthMonitor.score_label(r.score),
        "metrics": [{"name": m.name, "value": m.value, "status": m.status,
                     "advice": m.advice, "level": lvl[m.level]} for m in r.metrics],
        "extras": [{"label": a, "text": b} for a, b in r.extras],
        "alerts": r.alerts,
        "trend": healthMonitor.trend_summary().strip(),
    }


def _health_state() -> dict:
    return {
        "available": True,
        "profile": {"weight": UserInt.weight, "height": UserInt.height,
                    "bp": f"{UserInt.bloodPressure[0]}/{UserInt.bloodPressure[1]}",
                    "age": UserInt.age, "sex": UserInt.sex, "activity": UserInt.activity},
        "sources": smartwatch.data_source(),
        "export": _health["export"],
        "storm_presets": list(UserInt.STORM_PRESETS),
        "report": _health["report"],
    }


def _rebuild(reread: bool = False, log: bool = True) -> dict:
    """Build a new report. Sensor readings are kept until the watch is re-read,
    so changing the profile does not silently change the vitals."""
    if reread or _health["sensors"] is None:
        _health["sensors"] = healthMonitor.read_sensors()
    try:
        r = healthMonitor.build_report(_health["sensors"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(400, str(e))
    if log:
        healthMonitor.log_report(r)
    _health["report"] = _report_to_dict(r)
    return _health_state()


@app.get("/api/health")
def get_health():
    if healthMonitor is None:
        return {"available": False, "error": HEALTH_ERROR}
    with _health_lock:
        if _health["report"] is None:
            return _rebuild(log=False)
        return _health_state()


class Profile(BaseModel):
    weight: str
    height: str
    bp: str
    age: str
    sex: str = "male"
    activity: str = "light"


@app.post("/api/health/profile")
def set_profile(p: Profile):
    _require_health()
    with _health_lock:
        try:
            UserInt._apply(p.weight, p.height, p.bp, p.age, p.sex, p.activity)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return _rebuild()


@app.post("/api/health/reread")
def reread_watch():
    _require_health()
    with _health_lock:
        return _rebuild(reread=True)


MAX_EXPORT_BYTES = 200 * 1024 * 1024


@app.post("/api/health/upload")
async def upload_export(file: UploadFile = File(...)):
    """Load a smartwatch export (Apple Health .zip/.xml, .csv or .json) via smartwatch.py."""
    _require_health()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".zip", ".xml", ".csv", ".json"):
        raise HTTPException(400, "Unsupported file. Use .zip/.xml (Apple Health), .csv or .json")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"export{suffix}"
        size = 0
        with open(path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_EXPORT_BYTES:
                    raise HTTPException(413, "File too large (max 200 MB).")
                out.write(chunk)
        with _health_lock:
            try:
                found = smartwatch.smartwatch(str(path))
            except Exception as e:
                raise HTTPException(400, f"Could not read the export: {e}")
            _health["export"] = {"filename": file.filename, "found": found}
            return _rebuild(reread=True)


class StormTest(BaseModel):
    storm: str = "off"


@app.post("/api/health/radiation")
def radiation_test(t: StormTest):
    """Runs the team's RAM bit-flip 'canary' test (healthMonitor.run_radiation_test).
    'storm' > off deliberately corrupts cells first, as a demo."""
    _require_health()
    if t.storm not in UserInt.STORM_PRESETS:
        raise HTTPException(400, f"storm must be one of {list(UserInt.STORM_PRESETS)}")
    with _health_lock:
        healthMonitor.run_radiation_test(UserInt.STORM_PRESETS[t.storm])
        return _rebuild()


def health_for_chat() -> dict | None:
    rep = _health["report"]
    if not rep:
        return None
    return {
        "overall_score": f"{rep['score']}/100 ({rep['score_label']})",
        "metrics": [f"{m['name']}: {m['value']} - {m['status']}" for m in rep["metrics"]],
        "notes": [f"{e['label']}: {e['text']}" for e in rep["extras"]],
        "watch_data_source": smartwatch.data_source(),
    }


# -------------------------------------------------------------------- Chat ---
SYSTEM_PROMPT = """You are the health assistant of SolarGuard, an app that combines smartwatch
vitals with NASA solar radiation data (NASA POWER API).

Rules:
- Reply in the same language the user writes in, briefly and warmly (2-5 sentences unless asked for more).
- Base your answers on the CURRENT DATA below and quote the numbers when helpful.
- Give practical advice: sunscreen, shade, hydration, breaks, hours to avoid the sun, etc.
- Do not diagnose. If values look concerning, suggest seeing a doctor,
  and for emergency symptoms tell them to call local emergency services (112 in Europe, 911 in the US).
- If the vitals are simulated or the solar data is not from NASA, you may say so when asked.
- "health_check" (if present) is the user's daily health report: profile-based metrics
  (BMI, blood pressure) and daily watch values (resting HR, sleep, stress...). Use it for
  questions about their general health.
- Its "Solar radiation danger" metric comes from an experimental RAM bit-flip "canary" test
  (a heuristic index, often demo-simulated), not from a radiation sensor. For actual sun
  exposure, rely on the NASA POWER UV and irradiance values.

CURRENT DATA:
{context}
"""


class ChatMessage(BaseModel):
    role: str      # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


_client: Groq | None = None


def client() -> Groq:
    global _client
    if _client is None:
        if not os.getenv("GROQ_API_KEY"):
            raise HTTPException(500, "GROQ_API_KEY is missing (put it in the .env file).")
        _client = Groq()
    return _client


@app.post("/api/chat")
def chat(req: ChatRequest):
    ctx = get_context()
    if healthMonitor is not None:
        ctx["health_check"] = health_for_chat()
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=ctx)}]
    messages += [m.model_dump() for m in req.history[-10:]]  # last 10 messages
    messages.append({"role": "user", "content": req.message})
    try:
        resp = client().chat.completions.create(
            model=MODEL,
            max_tokens=800,
            messages=messages,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"LLM error: {e}")
    reply = resp.choices[0].message.content or ""
    return {"reply": reply, "context": ctx}


@app.get("/")
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/chat")
def chat_page():
    return FileResponse(STATIC / "chat.html")
