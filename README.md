# ☀ SolarGuard

**Real-time sun-safety monitoring that combines smartwatch vitals with NASA solar radiation data, plus an AI health assistant that explains what it all means.**

Built for the **NASA Space Apps Challenge 2026**.

🔗 **Live demo:** https://solarguard-mk1n.onrender.com (free hosting: the first load after inactivity can take ~1 minute)

---

## The problem

Sun exposure and heat stress are invisible until it is too late. UV radiation causes sunburn and long-term skin damage, and heat combined with physical exertion can lead to heat exhaustion. Weather apps show the UV index, and smartwatches show your heart rate, but nothing connects the two: *what is the sun doing* and *how is my body reacting right now?*

## Our solution

SolarGuard brings everything together on one web dashboard:

- **Your body, live (smartwatch):** heart rate, blood oxygen (SpO₂), skin temperature and steps, streamed in real time.
- **Your environment (NASA):** UV index, solar irradiance and air temperature for your location from the **NASA POWER API**.
- **Sun-safety risk index (0–100):** a transparent score that combines both and always shows *why* it has its value (e.g. "very high UV (9.2)", "elevated heart rate (152 bpm)").
- **Daily health check:** enter your profile (weight, height, blood pressure, age, sex, activity level) and load a smartwatch export (Apple Health, CSV or JSON). You get an overall health score and a per-metric assessment (BMI, blood pressure, resting heart rate, SpO₂, respiratory rate, temperature, sleep, stress) based on clinical reference ranges, plus daily energy, hydration, protein and heart-rate-zone guidance.
- **AI health assistant:** a chatbot that sees the live vitals, the NASA data and the daily health report, and answers questions such as *"Is it safe to go for a run now?"* or *"How is my overall health today?"* with practical advice. It never diagnoses, and it refers users to a doctor or emergency services when values are concerning.

## NASA data used

| Source | Parameters | Used for |
|---|---|---|
| [NASA POWER API](https://power.larc.nasa.gov/) (Prediction Of Worldwide Energy Resources), daily point data | `ALLSKY_SFC_UV_INDEX`: all-sky surface UV index | UV tile, risk score, chatbot context |
| | `ALLSKY_SFC_SW_DWN`: all-sky surface shortwave downward irradiance (kWh/m²/day) | Solar irradiance tile, chatbot context |
| | `T2M`: air temperature at 2 m (°C) | Heat component of the risk score, chatbot context |

POWER data is published with a delay of a few days, so SolarGuard uses the most recent valid daily value for the configured location (default: Athens, Greece). Responses are cached for one hour. If the API is unreachable, the app falls back to clearly labelled estimates so the demo keeps working offline.

## How it works

```
 Smartwatch (live) ──POST /api/vitals──┐
 (or built-in simulator)               │
                                       ▼
 NASA POWER API ─────────────────► FastAPI backend ──► sun-safety risk score (0-100 + reasons)
                                       ▲     │
 Watch export + profile ──► healthMonitor.py / smartwatch.py ──► daily health report
                                             │
            GET /api/context, /api/health    POST /api/chat ──► LLM (Groq) with all of the above as context
                                             ▼
          Dashboard (HTML/JS): live tiles, charts, risk gauge, daily health check, chat
```

### Risk score

| Factor | Points |
|---|---|
| UV ≥ 8 / ≥ 6 / ≥ 3 | +40 / +25 / +10 |
| Air temperature ≥ 32 °C | +15 |
| Heart rate ≥ 110 bpm | +20 |
| Skin temperature ≥ 37 °C | +15 |
| SpO₂ < 94 % | +20 |

**0–29 Low · 30–59 Moderate · 60–100 High**, capped at 100. The rules are deliberately simple so that every point can be explained to the user.

### Demo scenarios

Until a real watch sends data, a built-in simulator produces realistic vitals that drift smoothly toward a target, the way a real body would. The dashboard offers three scenarios: **Resting**, **Walking** and **Running in the sun**. The last one also simulates midday sun (UV 9.2, 34.5 °C) and is labelled "demo scenario" in the UI.

## Daily health check (health engine)

The health engine lives in the repository root and also runs as a standalone desktop app:

| File | Role |
|---|---|
| `healthMonitor.py` | Analysis engine: classifies each metric against published reference ranges (WHO BMI classes, ACC/AHA 2017 blood pressure, AHA resting heart rate, NEWS2 respiratory rate, WHO/BTS SpO₂, AASM/NSF sleep, Mifflin-St Jeor energy, Tanaka max HR + Karvonen zones, WHO 2020 activity). Computes an overall score, flags combined risks and logs every check to `health_log.csv` for trends. |
| `smartwatch.py` | Reads a smartwatch **export** (Apple Health `.zip`/`.xml`, CSV in long or wide format, JSON) and exposes simple getters (sleep, resting HR, stress, respiratory rate, temperature, SpO₂). If no export is loaded, or a metric is missing, it falls back to clearly labelled simulated values. Stress is taken from the watch, or estimated from HRV, resting HR, breathing rate and sleep. |
| `UserInt.py` | User profile and the desktop UI (PySide6 window, or console with `--cli`). |

The web dashboard calls this same engine through the API (`/api/health/...`), so the desktop app and the web app always give the same assessment.

**Experimental: radiation "canary".** `healthMonitor.py` also includes an experimental test that fills ~100 MB of RAM with `None` and counts cells that have changed, as a proxy for radiation-induced bit flips (single-event upsets). The share of changed cells is mapped to NOAA's S1–S5 radiation-storm scale. On the ground, real bit flips are extremely rare (atmosphere, magnetic field, ECC memory), so the dashboard offers demo "storm" presets that corrupt cells on purpose. This is a heuristic index, not a dosimeter. For actual sun exposure, SolarGuard relies on the NASA POWER data.

## Run it locally

```bash
cd chatbox
pip install -r requirements.txt

# Copy .env.example to .env and add a free Groq API key (https://console.groq.com/keys).
# .env is git-ignored and never committed.

python -m uvicorn app:app --reload
```

Open http://localhost:8000 for the dashboard.

Optional environment variables: `LAT` / `LON` (location, default Athens) and `CHAT_MODEL` (default `openai/gpt-oss-120b`).

**Desktop app only (no web):** from the repository root run `pip install PySide6` and then `python UserInt.py` (or `python UserInt.py --cli` for the console version).

**Load a real smartwatch export from the command line:** `python smartwatch.py export.zip`

## Deploy (Render, free tier)

- **Root Directory:** *(leave empty, i.e. the repository root, so the web app can import the health engine)*
- **Build Command:** `pip install -r chatbox/requirements.txt`
- **Start Command:** `uvicorn app:app --app-dir chatbox --host 0.0.0.0 --port $PORT`
- **Environment variable:** `GROQ_API_KEY`

## API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard |
| `GET /api/context` | Live vitals, NASA solar data and sun-safety risk score |
| `POST /api/vitals` | A watch posts `{"heart_rate": 95, "spo2": 98, "skin_temp": 34.2, "steps": 4200}` |
| `POST /api/scenario` | `{"name": "rest" \| "walk" \| "run_sun"}` switches the live demo scenario |
| `GET /api/health` | Current daily health report, profile and data sources |
| `POST /api/health/profile` | `{"weight": "70", "height": "175", "bp": "120/80", "age": "30", "sex": "male", "activity": "light"}` |
| `POST /api/health/upload` | Multipart upload of a smartwatch export (`.zip`, `.xml`, `.csv`, `.json`) |
| `POST /api/health/reread` | Re-read the daily watch values |
| `POST /api/health/radiation` | `{"storm": "off" \| "minor" \| "moderate" \| "strong" \| "severe" \| "extreme"}` runs the radiation canary |
| `POST /api/chat` | `{"message": "...", "history": [...]}` returns `{"reply": "...", "context": {...}}` |

## Project structure

```
├── healthMonitor.py    # health analysis engine (reference ranges, score, trends, radiation canary)
├── smartwatch.py       # smartwatch export reader (Apple Health / CSV / JSON) with simulated fallback
├── UserInt.py          # user profile + desktop UI (PySide6 / console)
├── radiation_detector.py # memory bit-flip radiation detector (SEU counting, Poisson/Bayes probability)
├── health_log.csv      # history of health checks (used for trends)
└── chatbox/            # web app
    ├── app.py          # FastAPI backend: NASA POWER, live simulator, risk score, health API, chat
    ├── requirements.txt
    ├── .env.example    # template for the API key (the real .env is git-ignored)
    └── static/
        └── dashboard.html  # main dashboard with the built-in chat (vanilla HTML/CSS/JS, no build step)
```

## Use of Artificial Intelligence

In line with the NASA Space Apps AI disclosure requirements:

- **AI-assisted development:** The web application in `chatbox/` (backend, dashboard, chat UI), its integration with the health engine, and this README were written with the help of **Claude (Anthropic)** as a coding assistant. The team defined the concept and requirements, then reviewed, tested, deployed and iterated on the generated code.
- **AI inside the product:** The health assistant chatbot uses the open-weight large language model **`openai/gpt-oss-120b`, served through the Groq API**. It receives only the current vitals, the NASA data, the risk score and the daily health report as context. It is instructed not to diagnose and to refer users to medical professionals.
- No AI-generated images, video or audio are used, and no NASA branding or design elements were created or modified with AI.

## Limitations & next steps

- Live vitals are simulated in the demo. `POST /api/vitals` is ready for a real-time watch integration, and daily values can already come from a real watch export.
- NASA POWER provides daily values, not real-time ones. A next step is combining it with forecast or near-real-time UV sources.
- The health profile is shared by everyone using the same server (prototype). User accounts and a database for long-term history (e.g. sleep) are next.
- The risk score and health assessment are informational heuristics, **not a medical device**. Thresholds would need validation with health professionals.

## Disclaimer

SolarGuard is a hackathon prototype for educational purposes. It does not provide medical advice. In an emergency, call your local emergency number (112 in Europe).
