"""FastAPI entrypoint. Run with: `uvicorn server.main:app --reload`."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from .routes import router  # noqa: E402 - must load env first

app = FastAPI(title="Marketing Agent API", version="0.2.0")


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    configured = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if configured:
        return configured
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {"service": "marketing-agent", "docs": "/docs", "api": "/api/health"}
