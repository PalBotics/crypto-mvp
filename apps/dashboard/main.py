"""FastAPI application for the crypto-mvp dashboard.

Start with:
    uvicorn apps.dashboard.main:app --reload
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.dashboard.routes import router

app = FastAPI(title="crypto-mvp dashboard", version="0.1.0")
app.include_router(router, prefix="/api")

frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    _index_path = os.path.join(os.path.dirname(__file__), "frontend", "dist", "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("assets/"):
            raise HTTPException(status_code=404)
        return FileResponse(_index_path, media_type="text/html")
