"""
Chatbot backend για το NASA Space Apps project.

- POST /api/vitals : το ρολόι (ή ο simulator) στέλνει τα τελευταία vitals
- GET  /api/context: τι "βλέπει" τώρα το bot (vitals + ηλιακή ακτινοβολία)
- POST /api/chat   : ερώτηση χρήστη -> απάντηση από το LLM με βάση το context
- GET  /           : το chat box (static/chat.html)

Τρέξιμο:
    pip install -r requirements.txt
    φτιάξε αρχείο .env δίπλα στο app.py με:  GROQ_API_KEY=gsk_...
    python -m uvicorn app:app --reload
    -> άνοιξε http://localhost:8000
"""

import os
import random
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from groq import Groq
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")  # διαβάζει το GROQ_API_KEY από το .env

MODEL = os.getenv("CHAT_MODEL", "openai/gpt-oss-120b")
LAT = float(os.getenv("LAT", "37.98"))   # Αθήνα by default
LON = float(os.getenv("LON", "23.73"))

app = FastAPI(title="Solar Health Chatbot")
app.add_middleware(  # για να μπορεί να το καλεί και το dashboard από άλλο port
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


def simulated_vitals() -> Vitals:
    """Ψεύτικα vitals μέχρι να συνδεθεί το πραγματικό ρολόι."""
    return Vitals(
        heart_rate=round(random.gauss(88, 10)),
        spo2=round(random.uniform(95, 99), 1),
        skin_temp=round(random.uniform(33.5, 36.5), 1),
        steps=random.randint(2000, 9000),
        timestamp=time.time(),
    )


@app.post("/api/vitals")
def post_vitals(v: Vitals):
    global latest_vitals
    v.timestamp = v.timestamp or time.time()
    latest_vitals = v
    return {"ok": True}


def current_vitals() -> tuple[Vitals, bool]:
    """Επιστρέφει (vitals, is_simulated). Τα πραγματικά θεωρούνται φρέσκα για 2 λεπτά."""
    if latest_vitals and time.time() - (latest_vitals.timestamp or 0) < 120:
        return latest_vitals, False
    return simulated_vitals(), True


# ---------------------------------------------------- Solar (NASA POWER) ----
_solar_cache: dict = {"t": 0, "data": None}


def solar_data() -> dict:
    """
    Ημερήσια δεδομένα από το NASA POWER API για την τοποθεσία:
      ALLSKY_SFC_UV_INDEX : UV index
      ALLSKY_SFC_SW_DWN   : ηλιακή ακτινοβολία στην επιφάνεια (kWh/m²/day)
      T2M                 : θερμοκρασία αέρα στα 2m (°C)
    Το POWER έχει καθυστέρηση λίγων ημερών, οπότε παίρνουμε την πιο πρόσφατη έγκυρη τιμή.
    Cache 1 ώρα, fallback σε simulated αν δεν υπάρχει δίκτυο.
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
    except Exception as e:  # χωρίς δίκτυο / API down -> demo τιμές
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
    """Απλό, εξηγήσιμο σκορ 0-100. Το ίδιο μπορεί να το δείχνει και το dashboard."""
    score, reasons = 0, []
    uv = s.get("uv_index") or 0
    if uv >= 8:
        score += 40; reasons.append(f"πολύ υψηλό UV ({uv})")
    elif uv >= 6:
        score += 25; reasons.append(f"υψηλό UV ({uv})")
    elif uv >= 3:
        score += 10; reasons.append(f"μέτριο UV ({uv})")
    if (s.get("air_temp_c") or 0) >= 32:
        score += 15; reasons.append(f"ζέστη ({s['air_temp_c']}°C)")
    if (v.heart_rate or 0) >= 110:
        score += 20; reasons.append(f"αυξημένοι παλμοί ({v.heart_rate} bpm)")
    if (v.skin_temp or 0) >= 37:
        score += 15; reasons.append(f"υψηλή θερμοκρασία δέρματος ({v.skin_temp}°C)")
    if v.spo2 and v.spo2 < 94:
        score += 20; reasons.append(f"χαμηλό SpO₂ ({v.spo2}%)")
    score = min(score, 100)
    level = "low" if score < 30 else "moderate" if score < 60 else "high"
    return {"score": score, "level": level, "reasons": reasons}


@app.get("/api/context")
def get_context():
    v, simulated = current_vitals()
    s = solar_data()
    return {
        "vitals": v.model_dump(),
        "vitals_simulated": simulated,
        "solar": s,
        "risk": risk_score(v, s),
    }


# -------------------------------------------------------------------- Chat ---
SYSTEM_PROMPT = """Είσαι ο βοηθός υγείας μιας εφαρμογής που συνδυάζει δεδομένα από ένα smartwatch
με δεδομένα ηλιακής ακτινοβολίας της NASA (NASA POWER API).

Κανόνες:
- Απάντα στη γλώσσα του χρήστη, σύντομα και φιλικά (2-5 προτάσεις, εκτός αν ζητηθεί περισσότερο).
- Βάσισε τις απαντήσεις σου στα ΤΡΕΧΟΝΤΑ ΔΕΔΟΜΕΝΑ παρακάτω και ανέφερε τους αριθμούς όταν βοηθάει.
- Δώσε πρακτικές συμβουλές: αντηλιακό, σκιά, νερό, διάλειμμα, ώρες αποφυγής ήλιου κ.λπ.
- Δεν κάνεις διάγνωση. Αν οι τιμές δείχνουν κάτι ανησυχητικό, πρότεινε να μιλήσει με γιατρό,
  και για επείγοντα συμπτώματα να καλέσει το 112.
- Αν τα vitals είναι simulated ή τα ηλιακά δεδομένα δεν είναι από τη NASA, μπορείς να το αναφέρεις αν ρωτηθείς.

ΤΡΕΧΟΝΤΑ ΔΕΔΟΜΕΝΑ:
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
            raise HTTPException(500, "Λείπει το GROQ_API_KEY (βάλ' το στο αρχείο .env).")
        _client = Groq()
    return _client


@app.post("/api/chat")
def chat(req: ChatRequest):
    ctx = get_context()
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=ctx)}]
    messages += [m.model_dump() for m in req.history[-10:]]  # τελευταία 10 μηνύματα
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
        raise HTTPException(502, f"Σφάλμα LLM: {e}")
    reply = resp.choices[0].message.content or ""
    return {"reply": reply, "context": ctx}


@app.get("/")
def index():
    return FileResponse(STATIC / "chat.html")
