"""FastAPI application for the crypto-mvp dashboard.

Start with:
    uvicorn apps.dashboard.main:app --reload
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.dashboard.routes import router

app = FastAPI(title="crypto-mvp dashboard", version="0.1.0")
app.include_router(router, prefix="/api")

frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount(
        "/",
        StaticFiles(directory=frontend_dist, html=True),
        name="frontend",
    )
