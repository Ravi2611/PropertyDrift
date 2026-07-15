"""Unified DriftGuard entrypoint.

Serves the launcher plus both tools on a single port:
    /            -> launcher (pick Property Drift or DB Drift)
    /property/   -> existing Property Drift dashboard + APIs
    /db/         -> DB Drift dashboard + APIs

Run:
    venv/bin/python server.py
    open http://localhost:8051/
"""

from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from src.api.main import app as property_app
from src.db_drift.app import app as db_app

_UI_DIR = Path(__file__).resolve().parent / "src" / "ui"
_HOME_HTML = _UI_DIR / "home.html"

# Attach Property Drift static UI onto its own sub-app so /property/ serves
# index.html and /property/history.html works. StaticFiles must be mounted
# AFTER the API routes so the API always wins.
property_app.mount(
    "/",
    StaticFiles(directory=str(_UI_DIR / "property"), html=True),
    name="property-ui",
)

app = FastAPI(title="DriftGuard")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(str(_HOME_HTML))


app.mount("/property", property_app)
app.mount("/db", db_app)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8051)
