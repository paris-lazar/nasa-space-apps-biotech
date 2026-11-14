# ☀ SolarGuard

**Real-time sun-safety monitoring that combines smartwatch vitals with NASA solar radiation data, plus an AI health assistant that explains what it all means.**

Built for the **NASA Space Apps Challenge 2026**.

🔗 **Live demo:** https://solarguard-mk1n.onrender.com (free hosting: the first load after inactivity can take ~1 minute)

---

## The problem

Sun exposure and heat stress are invisible until it is too late. UV radiation causes sunburn and long-term skin damage, and heat combined with physical exertion can lead to heat exhaustion. Weather apps show the UV index, and smartwatches show your heart rate, but nothing connects the two: *what is the sun doing* and *how is my body reacting right now?*

## Our solution

SolarGuard brings both sides together on one dashboard:

- **Your body (smartwatch):** heart rate, blood oxygen (SpO₂), skin temperature and steps, streamed live.
- **Your environment (NASA):** UV index, solar irradiance and air temperature for your location from the **NASA POWER API**.
- **A risk index (0–100):** a transparent score that combines both, and always shows *why* it has its value (e.g. "very high UV (9.2)", "elevated heart rate (152 bpm)").
- **An AI health assistant:** a chatbot that sees the same live data and answers questions such as *"Is it safe to go for a run now?"* with concrete, practical advice (shade, sunscreen, hydration, breaks). It never diagnoses, and it points users to a doctor or emergency services when values are concerning.

## NASA data used

| Source | Parameters | Used for |
|---|---|---|
| [NASA POWER API](https://power.larc.nasa.gov/) (Prediction Of Worldwide Energy Resources), daily point data | `ALLSKY_SFC_UV_INDEX`: all-sky surface UV index | UV tile, risk score, chatbot context |
| | `ALLSKY_SFC_SW_DWN`: all-sky surface shortwave downward irradiance (kWh/m²/day) | Solar irradiance tile, chatbot context |
| | `T2M`: air temperature at 2 m (°C) | Heat component of the risk score, chatbot context |

POWER data is published with a delay of a few days, so SolarGuard uses the most recent valid daily value for the configured location (default: Athens, Greece). Responses are cached for one hour. If the API is unreachable, the app falls back to clearly labelled estimates so the demo keeps working offline.

## How it works

```
 Smartwatch ──POST /api/vitals──┐
 (or built-in simulator)        │
                                ▼
 NASA POWER API ──────────► FastAPI backend ──► risk score (0-100 + reasons)
                                │      │
                 GET /api/context      POST /api/chat ──► LLM (Groq) with live data as context
                                │      │
                                ▼      ▼
                         Dashboard (HTML/JS): live tiles, charts, risk gauge, chat
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

## Run it locally

```bash
cd chatbox
pip install -r requirements.txt

# Copy .env.example to .env and add a free Groq API key (https://console.groq.com/keys).
# .env is git-ignored and never committed.

python -m uvicorn app:app --reload
```

Open http://localhost:8000 for the dashboard, or http://localhost:8000/chat for the standalone chat.

Optional environment variables: `LAT` / `LON` (location, default Athens) and `CHAT_MODEL` (default `openai/gpt-oss-120b`).

## Deploy (Render, free tier)

- **Root Directory:** `chatbox`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
- **Environment variable:** `GROQ_API_KEY`

## API

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard |
| `GET /chat` | Standalone chat page |
| `GET /api/context` | Current vitals, NASA solar data and risk score |
| `POST /api/vitals` | A watch posts `{"heart_rate": 95, "spo2": 98, "skin_temp": 34.2, "steps": 4200}` |
| `POST /api/scenario` | `{"name": "rest" \| "walk" \| "run_sun"}` switches the demo scenario |
| `POST /api/chat` | `{"message": "...", "history": [...]}` returns `{"reply": "...", "context": {...}}` |

## Project structure

```
chatbox/
├── app.py              # FastAPI backend: NASA POWER, simulator, risk score, chat
├── requirements.txt
├── .env.example        # template for the API key (the real .env is git-ignored)
└── static/
    ├── dashboard.html  # main dashboard (vanilla HTML/CSS/JS, no build step)
    └── chat.html       # standalone chat box
```

## Use of Artificial Intelligence

In line with the NASA Space Apps AI disclosure requirements:

- **AI-assisted development:** Much of the source code in this repository (backend, dashboard and chat UI) and this README were written with the help of **Claude (Anthropic)** as a coding assistant. The team defined the concept and requirements, then reviewed, tested, deployed and iterated on the generated code.
- **AI inside the product:** The health assistant chatbot uses the open-weight large language model **`openai/gpt-oss-120b`, served through the Groq API**. It receives only the current vitals, the NASA data and the risk score as context. It is instructed not to diagnose and to refer users to medical professionals.
- No AI-generated images, video or audio are used, and no NASA branding or design elements were created or modified with AI.

## Limitations & next steps

- Vitals are simulated in the demo. The `POST /api/vitals` endpoint is ready for a real smartwatch integration.
- NASA POWER provides daily values, not real-time ones. A next step is combining it with forecast or near-real-time UV sources.
- The risk score is a heuristic for awareness, **not a medical device**. Thresholds would need validation with health professionals.

## Disclaimer

SolarGuard is a hackathon prototype for educational purposes. It does not provide medical advice. In an emergency, call your local emergency number (112 in Europe).
