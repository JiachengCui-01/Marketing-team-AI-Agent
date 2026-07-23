"""In-process pub/sub for IM real-time delivery over SSE.

Single-worker assumption (same as the news scheduler in ``main.py``). With
multiple workers this must be replaced by a shared broker (e.g. Redis pub/sub),
since these queues live in one process's event loop only.

Publishers must run on the event loop thread (async endpoints), because
``asyncio.Queue.put_nowait`` is not thread-safe. The IM send/create endpoints
are declared ``async def`` for exactly this reason.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


def subscribe(user_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[user_id].add(queue)
    return queue


def unsubscribe(user_id: str, queue: asyncio.Queue) -> None:
    subs = _subscribers.get(user_id)
    if not subs:
        return
    subs.discard(queue)
    if not subs:
        _subscribers.pop(user_id, None)


def publish(user_id: str, event: dict[str, Any]) -> None:
    for queue in list(_subscribers.get(user_id, ())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:  # pragma: no cover - queues are unbounded
            pass


def subscriber_count(user_id: str) -> int:
    return len(_subscribers.get(user_id, ()))


def reset_for_tests() -> None:
    _subscribers.clear()
