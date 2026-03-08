"""Backend API entry point with scheduled tasks."""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn

from backend.api import app
from backend.config import KNOWLEDGE_PIPELINE_INTERVAL
from backend.wiring import create_brain

logger = logging.getLogger(__name__)

async def _knowledge_pipeline():
    """Run knowledge pipelines periodically."""
    components = create_brain()
    while True:
        await asyncio.sleep(KNOWLEDGE_PIPELINE_INTERVAL)
        try:
            components.brain.process_command("knowledge_pipeline", "", "default", "")
        except Exception:
            logger.exception("Knowledge pipeline failed")


@asynccontextmanager
async def lifespan(_app):
    """Start background tasks on API startup."""
    tasks = [
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
    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="0.0.0.0", port=8100)


if __name__ == "__main__":
    main()
