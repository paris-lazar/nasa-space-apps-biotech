# Solar Health Chatbot

Chatbot που απαντά με βάση τα vitals του ρολογιού και τα δεδομένα ηλιακής ακτινοβολίας της NASA (NASA POWER API).

## Εκκίνηση

```bash
cd chatbot
pip install -r requirements.txt

# Αντέγραψε το .env.example σε .env και βάλε το Groq key σου (console.groq.com/keys)
# Το .env ΔΕΝ ανεβαίνει στο GitHub (είναι στο .gitignore)

python -m uvicorn app:app --reload
```

Άνοιξε http://localhost:8000

Προαιρετικά: `LAT` / `LON` για τοποθεσία (default Αθήνα), `CHAT_MODEL` για άλλο μοντέλο.

## Endpoints

| Endpoint | Τι κάνει |
|---|---|
| `POST /api/vitals` | Το ρολόι στέλνει `{"heart_rate": 95, "spo2": 98, "skin_temp": 34.2, "steps": 4200}` |
| `GET /api/context` | Τρέχοντα vitals + ηλιακά δεδομένα + σκορ κινδύνου (χρήσιμο και για το dashboard) |
| `POST /api/chat` | `{"message": "...", "history": [...]}` → `{"reply": "...", "context": {...}}` |

Αν το ρολόι δεν έχει στείλει τίποτα τα τελευταία 2 λεπτά, χρησιμοποιούνται simulated vitals.

## Δοκιμή χωρίς ρολόι

```bash
curl -X POST localhost:8000/api/vitals -H "Content-Type: application/json" \
  -d '{"heart_rate": 125, "spo2": 96, "skin_temp": 37.4, "steps": 8000}'
```

## Ενσωμάτωση στο dashboard

Το `<div class="chatbox">` στο `static/chat.html` είναι αυτόνομο. Αντιγράψτε το (μαζί με το CSS και το script) στο dashboard
και ορίστε `const API = "http://localhost:8000"`.
