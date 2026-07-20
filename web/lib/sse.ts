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
