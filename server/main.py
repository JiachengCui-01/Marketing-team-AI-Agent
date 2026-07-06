"""FastAPI entrypoint. Run with: `uvicorn server.main:app --reload`."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from . import db, news  # noqa: E402 - must load env first
from .routes import router  # noqa: E402 - must load env first

logger = logging.getLogger("marketing_agent.news")

# How often the scheduler wakes up to check for due news jobs.
_SCHEDULER_INTERVAL_SECONDS = 60


def _is_due(config: dict, now: datetime) -> bool:
    """True if the daily summary for `config` should run at `now` (in the config's tz)."""
    try:
        hh, mm = (int(x) for x in str(config["summary_time"]).split(":"))
    except (ValueError, KeyError):
        return False
    scheduled = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < scheduled:
        return False
    last = config.get("last_run_at")
    if last is None:
        return True
    last_dt = datetime.fromtimestamp(last, tz=now.tzinfo)
    # Run once per day: only if we haven't run since today's scheduled time.
    return last_dt < scheduled


async def _run_due_job(config: dict) -> None:
    try:
        await asyncio.to_thread(news.generate_summary, config)
        logger.info("Generated daily news summary for user %s", config.get("user_id"))
    except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
        # Count the scheduled attempt so a persistent provider failure does not
        # retry every minute. Manual refresh remains available immediately.
        db.set_news_config_last_run(config["user_id"], datetime.now().timestamp())
        logger.warning("News summary failed for user %s: %s", config.get("user_id"), exc)


async def _news_scheduler() -> None:
    """Background loop: generate each user's daily news summary at their configured time.

    NOTE: assumes a single server worker (Render default). With multiple workers this
    would run per worker; add a DB lock before scaling out.
    """
    while True:
        try:
            for config in db.list_enabled_news_configs():
                try:
                    tz = ZoneInfo(config.get("timezone") or "UTC")
                except Exception:  # noqa: BLE001
                    tz = ZoneInfo("UTC")
                if _is_due(config, datetime.now(tz)):
                    await _run_due_job(config)
        except Exception as exc:  # noqa: BLE001 - never let the loop die
            logger.warning("News scheduler tick failed: %s", exc)
        await asyncio.sleep(_SCHEDULER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_news_scheduler())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Marketing Agent API", version="0.2.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    configured = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if configured:
        return configured
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


def _cors_origin_regex() -> str | None:
    return os.environ.get("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    return {"service": "marketing-agent", "docs": "/docs", "api": "/api/health"}
