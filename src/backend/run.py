"""Backend API entry point with scheduled tasks."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import uvicorn

from backend.config import KNOWLEDGE_PIPELINE_INTERVAL

logger = logging.getLogger(__name__)


async def _daily_article_ingest():
    """Ingest today's articles every day at 6:30 AM CET."""
    from backend.wiring import create_brain
    components = create_brain()
    cet = timezone(timedelta(hours=1))
    while True:
        now = datetime.now(cet)
        target = now.replace(hour=6, minute=30, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Next article ingest at %s CET (in %.0fs)", target.strftime("%Y-%m-%d %H:%M"), wait_seconds)
        await asyncio.sleep(wait_seconds)
        try:
            today = datetime.now(cet).strftime("%Y-%m-%d")
            result = components.brain.process_command("ingest", f"{today} {today}", "default", "")
            count = result.get("count", 0) if isinstance(result, dict) else 0
            logger.info("Daily ingest: %d articles for %s", count, today)
        except Exception:
            logger.exception("Daily article ingest failed")


async def _knowledge_pipeline():
    """Run knowledge pipelines periodically."""
    from backend.wiring import create_brain
    components = create_brain()
    while True:
        await asyncio.sleep(KNOWLEDGE_PIPELINE_INTERVAL)
        try:
            components.brain.process_command("knowledge_pipeline", "", "default", "")
        except Exception:
            logger.exception("Knowledge pipeline failed")


@asynccontextmanager
async def lifespan(app):
    """Start background tasks on API startup."""
    tasks = [
        asyncio.create_task(_daily_article_ingest()),
        asyncio.create_task(_knowledge_pipeline()),
    ]
    yield
    for t in tasks:
        t.cancel()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # Patch the app lifespan before running
    from backend.api import app
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="0.0.0.0", port=8100)


if __name__ == "__main__":
    main()
