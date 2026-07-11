"""Per-job in-memory event bus for SSE streaming.

Each job state owns one EventBus instance. update_job() pushes a snapshot
event; subscribers (SSE clients) receive it via per-connection queues.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from threading import Lock
from typing import Any


class EventBus:
    """Thread-safe pub/sub for one job's snapshots.

    Producer (run_job thread) calls publish() with a snapshot dict.
    Consumers (SSE handlers in the asyncio loop) call subscribe() to get a
    queue + the most recent snapshot, then await items from the queue.
    """

    def __init__(self, *, history: int = 50) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._subscribers: set[
            tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any] | None]]
        ] = set()
        self._lock = Lock()
        self._closed = False

    def publish(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            self._history.append(snapshot)
            targets = list(self._subscribers)
        for loop, queue in targets:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, snapshot)

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            return self._history[-1] if self._history else None

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue[dict[str, Any] | None]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        with self._lock:
            self._subscribers.add((loop, queue))
            latest = self._history[-1] if self._history else None
        if latest is not None:
            queue.put_nowait(latest)
        return queue

    def unsubscribe(
        self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any] | None]
    ) -> None:
        with self._lock:
            self._subscribers.discard((loop, queue))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            targets = list(self._subscribers)
            self._subscribers.clear()
        for loop, queue in targets:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(queue.put_nowait, None)


def format_sse(data: dict[str, Any], *, event: str | None = None) -> str:
    """Encode a payload as a single SSE message frame."""
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, default=str)
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)
