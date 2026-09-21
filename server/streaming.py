"""Bridge a synchronous ``on_event`` callback into an async SSE stream.

:func:`event_stream` is the bridge and knows nothing about what is running: a
worker thread calls ``emit(event, payload)`` whenever it has something to say and
the events come out of an async iterator, with a heartbeat while the worker is
quiet and cancellation when the client goes away.

:func:`orchestrator_event_stream` is that bridge with a chat turn inside it. The
automation analyses use the bare one — they have no conversation and no prompt,
just a pipeline with phases worth naming, and the trace panel they report into is
the same one.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncIterator, Callable

from fastapi import Request

from marketing_agent import llm_client
from marketing_agent.conversation import Conversation
from marketing_agent.orchestrator import run_orchestrator

_DONE = object()
HEARTBEAT_INTERVAL_SECONDS = 10

#: What a worker is handed to report with: ``emit(event_name, payload)``.
Emit = Callable[[str, dict], None]


class Steps:
    """The render's phases, in the shape the chat trace already draws.

    An analysis that takes a minute and shows a spinner is indistinguishable
    from one that has hung, and when it finishes nobody can say which half of
    it was slow or which step found nothing. The chat turn has had a step-by-
    step trace since the beginning; these run the same kind of work — reads,
    two model calls, a validation pass — and reported none of it.

    `orchestrator_step` rather than a family of our own: the panel already
    renders that shape with a tone, an icon and a running/done state, and a
    second vocabulary for the same idea would need a second renderer and drift
    from it. A phase that takes real time announces itself with `running` and
    closes with `done`; a fast one only reports what it found, because a pair
    of cards for something that took 40ms is noise.
    """

    def __init__(self, on_event=None) -> None:
        self._on_event = on_event

    def __bool__(self) -> bool:
        return self._on_event is not None

    def running(self, stage: str, title: str, detail: str = "") -> None:
        self._emit(stage, title, detail, "running")

    def done(self, stage: str, title: str, detail: str = "") -> None:
        self._emit(stage, title, detail, "done")

    def result(self, payload: dict) -> None:
        """The stream's terminal event. Sent by whoever owns the transport, not
        by the pipeline: a pipeline that closed the stream itself would cut off
        the caller's own payload, and two of them would cut off the first."""
        if self._on_event:
            self._on_event("result", payload)

    def _emit(self, stage: str, title: str, detail: str, status: str) -> None:
        if self._on_event:
            self._on_event("orchestrator_step", {"stage": stage, "title": title,
                                                 "detail": detail, "status": status})


async def event_stream(
    work: Callable[[Emit], None],
    *,
    request: Request | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run ``work`` on a thread and yield whatever it emits, as it emits it.

    ``work`` receives the emitter and is otherwise free: it may be a chat turn,
    a market render, or anything else with phases a reader should be able to
    watch. Errors become an ``error`` event rather than a traceback on a dead
    connection — a stream that stops without saying why is the failure this
    exists to avoid.
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

    def emit(event: str, payload: dict) -> None:
        enqueue({"event": event, "payload": payload})

    async def worker() -> None:
        try:
            await asyncio.to_thread(work, emit)
        except Exception as exc:  # noqa: BLE001
            emit("error", {"message": str(exc)})
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
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "payload": {"message": "Still working."}}
                continue
            if item is _DONE:
                return
            yield item
    finally:
        cancelled.set()
        if not task.done():
            task.cancel()


async def orchestrator_event_stream(
    client: llm_client.DeepSeek,
    conversation: Conversation,
    prompt: Any,
    request: Request | None = None,
    on_event_wrapper: Callable[[Callable[[str, dict], None]], Callable[[str, dict], None]] | None = None,
    runner: Callable[..., str] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield orchestrator events as they happen.

    ``prompt`` may be a string or a list of content blocks (for image attachments).
    ``on_event_wrapper`` lets callers intercept events for side effects (persistence,
    artifact binding) while still letting them flow to the SSE client.
    ``runner`` is the turn function ``(client, conversation, prompt, on_event)`` — defaults
    to the marketing orchestrator; the OA copilot passes its own runner here.
    """
    # Resolve at call time (not as a default arg) so tests can monkeypatch the
    # module-level ``run_orchestrator`` symbol.
    if runner is None:
        runner = run_orchestrator

    def work(emit: Emit) -> None:
        # The wrapper wraps the *bridge's* emitter, so a caller's side effects
        # (persistence, artifact binding) still see every event on its way out.
        on_event = on_event_wrapper(emit) if on_event_wrapper else emit
        on_event("started", {"message": "Connected to the marketing agent."})
        try:
            runner(client, conversation, prompt, on_event)
        except Exception as exc:  # noqa: BLE001
            # Caught here rather than left to the bridge: the bridge emits on
            # the raw emitter, which would route a failed turn around the
            # wrapper that writes it into the session history — the turn would
            # show an error on screen and leave no trace of one in the log.
            on_event("error", {"message": str(exc)})

    async for event in event_stream(work, request=request):
        yield event


async def to_sse(stream: AsyncIterator[dict[str, Any]]) -> AsyncIterator[dict[str, str]]:
    """Wrap event dicts in the shape sse-starlette's EventSourceResponse expects."""
    async for event in stream:
        yield {"data": json.dumps(event, default=str)}
