"""FastAPI application for the crypto-mvp dashboard.

Start with:
    uvicorn apps.dashboard.main:app --reload
"""

from fastapi import FastAPI

from apps.dashboard.routes import router

app = FastAPI(title="crypto-mvp dashboard", version="0.1.0")
app.include_router(router)
