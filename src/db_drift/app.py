"""DB Drift Guard as a mountable FastAPI sub-app.

The parent (root) app mounts this at `/db`, so all routes here are
relative to that mount point (e.g. `/api/scan` becomes `/db/api/scan`
in the browser).
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from src.db_drift.api.routes import router as api_router

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "ui" / "templates"

app = FastAPI(title="DB Drift Guard")

app.include_router(api_router, prefix="/api")

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
