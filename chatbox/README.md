# SolarGuard web app

This folder contains the web dashboard and API. **See the [main README](../README.md)** for the full project description, NASA data, architecture and AI disclosure.

## Quick start

```bash
cd chatbox
pip install -r requirements.txt
# copy .env.example to .env and add your GROQ_API_KEY
python -m uvicorn app:app --reload
```

Open http://localhost:8000
