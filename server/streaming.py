"""Bridge the orchestrator's synchronous on_event callback into an async SSE stream."""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncIterator

import anthropic
from fastapi import Request

from marketing_agent.conversation import Conversation
from marketing_agent.orchestrator import run_orchestrator

_DONE = object()


async def orchestrator_event_stream(
    client: anthropic.Anthropic,
    conversation: Conversation,
    prompt: str,
    request: Request | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield orchestrator events as they happen.

    The Anthropic call is blocking, so it runs in a worker thread. If the
    browser disconnects, the already-started model call may still finish, but
    no further events are enqueued or sent to the client.
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    cancelled = threading.Event()

    def enqueue(event: dict[str, Any]) -> None:
        if cancelled.is_set():
            return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:
            pass

    def on_event(event: str, payload: dict) -> None:
        enqueue({"event": event, "payload": payload})

    async def worker() -> None:
        try:
            await asyncio.to_thread(run_orchestrator, client, conversation, prompt, on_event)
        except Exception as exc:  # noqa: BLE001
            enqueue({"event": "error", "payload": {"message": str(exc)}})
        finally:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)
            except RuntimeError:
                pass

    task = asyncio.create_task(worker())
    try:
        while True:
            if request is not None and await request.is_disconnected():
                cancelled.set()
                yield {"event": "cancelled", "payload": {"message": "Client disconnected."}}
                return
            item = await queue.get()
            if item is _DONE:
                return
            yield item
    finally:
        cancelled.set()
        if not task.done():
            task.cancel()


async def to_sse(stream: AsyncIterator[dict[str, Any]]) -> AsyncIterator[dict[str, str]]:
    """Wrap event dicts in the shape sse-starlette's EventSourceResponse expects."""
    async for event in stream:
        yield {"data": json.dumps(event, default=str)}
