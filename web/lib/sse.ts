"use client";

export type StreamEvent = {
  event: string;
  payload: Record<string, unknown>;
};

export function openEventStream(
  url: string,
  onEvent: (e: StreamEvent) => void,
  onDone: () => void,
  onError: (err: unknown) => void,
): () => void {
  const source = new EventSource(url);
  let terminalReceived = false;

  source.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as StreamEvent;
      onEvent(data);
      // The server emits a terminal event right before closing.
      if (
        data.event === "result" ||
        data.event === "error" ||
        data.event === "cancelled"
      ) {
        terminalReceived = true;
        source.close();
        onDone();
      }
    } catch (err) {
      onError(err);
    }
  };

  source.onerror = (err) => {
    // EventSource fires onerror both on real failures and on normal stream close.
    // We rely on the "result" event to be the canonical "done" signal; if we
    // never got one, surface the error.
    if (source.readyState === EventSource.CLOSED) {
      if (terminalReceived) {
        onDone();
      } else {
        onError(new Error("Stream closed before a final response was received."));
      }
    } else {
      onError(err);
      source.close();
    }
  };

  return () => source.close();
}
