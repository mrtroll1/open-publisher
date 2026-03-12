"""Backend API entry point with scheduled tasks."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn

from backend.api import app

logger = logging.getLogger(__name__)

GOAL_MONITOR_INTERVAL = int(os.getenv("GOAL_MONITOR_INTERVAL", ""))


async def _goal_monitor_loop():
    from backend.api import db, gemini  # noqa: PLC0415
    from backend.commands.goal_monitor import GoalMonitor  # noqa: PLC0415

    monitor = GoalMonitor(db, gemini)
    while True:
        await asyncio.sleep(GOAL_MONITOR_INTERVAL)
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, monitor.run)
            logger.info("GoalMonitor: %s", result)
        except Exception:
            logger.exception("GoalMonitor failed")


@asynccontextmanager
async def lifespan(_app):
    """Start background tasks on API startup."""
    tasks = [
        asyncio.create_task(_goal_monitor_loop()),
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
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="0.0.0.0", port=8100)


if __name__ == "__main__":
    main()
