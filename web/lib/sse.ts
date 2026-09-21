"use client";

export type StreamEvent = {
  event: string;
  payload: Record<string, unknown>;
};

/** Run one traced job over SSE and resolve with its terminal payload.

 * The automation refreshes are request/response as far as the caller is
 * concerned — ask for a report, get a report — but the interesting part is the
 * minute in between, which used to be a spinner. This keeps the awaitable shape
 * and hands every event to `onEvent` on the way past, so the trace panel fills
 * in while the promise is still pending.
 */
export function runTracedStream(
  url: string,
  onEvent: (e: StreamEvent) => void,
): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };
    openEventStream(
      url,
      (e) => {
        onEvent(e);
        if (e.event === "result") finish(() => resolve(e.payload));
        else if (e.event === "error" || e.event === "cancelled") {
          finish(() => reject(new Error(String(e.payload.message ?? e.event))));
        }
      },
      // A stream that ends without a terminal event is a broken run, not a
      // finished one — surfacing it as an error is what stops the panel from
      // quietly keeping the previous report and calling it fresh.
      () => finish(() => reject(new Error("Stream ended without a result."))),
      (err) => finish(() => reject(err)),
    );
  });
}

export function openEventStream(
  url: string,
  onEvent: (e: StreamEvent) => void,
  onDone: () => void,
  onError: (err: unknown) => void,
): () => void {
  const controller = new AbortController();
  let terminalReceived = false;
  let closedByCaller = false;

  const handleMessage = (dataText: string) => {
    try {
      const data = JSON.parse(dataText) as StreamEvent;
      onEvent(data);
      if (
        data.event === "result" ||
        data.event === "error" ||
        data.event === "cancelled"
      ) {
        terminalReceived = true;
        controller.abort();
        onDone();
      }
    } catch (err) {
      onError(err);
    }
  };

  const flushFrame = (frame: string) => {
    const dataLines = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (dataLines.length === 0) return;
    handleMessage(dataLines.join("\n"));
  };

  void (async () => {
    let buffer = "";
    try {
      const response = await fetch(url, {
        headers: { Accept: "text/event-stream" },
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`Stream request failed with HTTP ${response.status}`);
      }
      if (!response.body) {
        throw new Error("Stream response did not include a readable body.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (!terminalReceived) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary = buffer.search(/\r?\n\r?\n/);
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary);
          const separatorLength = buffer[boundary] === "\r" ? 4 : 2;
          buffer = buffer.slice(boundary + separatorLength);
          flushFrame(frame);
          boundary = buffer.search(/\r?\n\r?\n/);
        }
      }

      if (buffer.trim()) flushFrame(buffer);
      if (terminalReceived || closedByCaller) return;
      if (!terminalReceived) {
        onError(new Error("Stream closed before a final response was received."));
      }
    } catch (err) {
      if (terminalReceived || closedByCaller || controller.signal.aborted) return;
      onError(err);
    }
  })();

  return () => {
    closedByCaller = true;
    controller.abort();
  };
}
