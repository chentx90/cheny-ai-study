"""Track long-running video jobs so reload/shutdown can cancel them quickly."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BackgroundJobRunner:
    """Owns asyncio tasks created for video poll/download work."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()

    def spawn(self, coro: Coroutine[Any, Any, T], *, name: str | None = None) -> asyncio.Task[T]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)

        def _done(done: asyncio.Task[Any]) -> None:
            self._tasks.discard(done)
            try:
                exc = done.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                logger.exception("Background job %s failed", done.get_name(), exc_info=exc)

        task.add_done_callback(_done)
        return task

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    async def shutdown(self, *, timeout: float = 3.0) -> None:
        """Cancel outstanding jobs and wait briefly so uvicorn can reload."""
        async with self._lock:
            tasks = list(self._tasks)
            self._tasks.clear()
        if not tasks:
            return
        logger.info("Cancelling %s background video job(s) for shutdown", len(tasks))
        for task in tasks:
            task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Background jobs did not stop within %.1fs; continuing shutdown", timeout)


# Process-wide runner used by API routes / lifespan.
video_job_runner = BackgroundJobRunner()
