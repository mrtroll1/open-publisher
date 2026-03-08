"""Backend API entry point with scheduled tasks."""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn

from backend.api import app

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app):
    """Start background tasks on API startup."""
    tasks = [
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
