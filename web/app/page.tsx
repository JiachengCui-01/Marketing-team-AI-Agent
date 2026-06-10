"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles, RefreshCw } from "lucide-react";
import { ChatPanel } from "@/components/chat-panel";
import {
  TracePanel,
  type TraceEvent,
  classifyTotals,
} from "@/components/trace-panel";
import { ThemeToggle } from "@/components/theme-toggle";
import type { ChatMessage } from "@/components/message";
import {
  createSession,
  deleteSession,
  streamUrl,
  type UploadResponse,
} from "@/lib/api";
import { openEventStream } from "@/lib/sse";

const SESSION_KEY = "marketing-agent-session-id";

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

export default function HomePage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attached, setAttached] = useState<UploadResponse | null>(null);
  const closeRef = useRef<(() => void) | null>(null);

  // Restore session id from localStorage on first mount.
  useEffect(() => {
    const stored =
      typeof window !== "undefined"
        ? window.localStorage.getItem(SESSION_KEY)
        : null;
    if (stored) {
      setSessionId(stored);
    }
  }, []);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId;
    const { session_id } = await createSession();
    window.localStorage.setItem(SESSION_KEY, session_id);
    setSessionId(session_id);
    return session_id;
  }, [sessionId]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setTrace([]);

    const userMsg: ChatMessage = {
      id: newId(),
      role: "user",
      content: text,
    };
    const pendingId = newId();
    const pendingMsg: ChatMessage = {
      id: pendingId,
      role: "assistant",
      content: "",
      pending: true,
    };
    setMessages((m) => [...m, userMsg, pendingMsg]);

    let sid: string;
    try {
      sid = await ensureSession();
    } catch (e) {
      setMessages((m) =>
        m.map((msg) =>
          msg.id === pendingId
            ? { ...msg, pending: false, content: `Failed to start session: ${String(e)}` }
            : msg,
        ),
      );
      setBusy(false);
      return;
    }

    const url = streamUrl(sid, text, attached?.file_id);
    const close = openEventStream(
      url,
      (e) => {
        setTrace((t) => [...t, { ...e, ts: Date.now() }]);
        if (e.event === "result") {
          const finalText = String(e.payload.text ?? "");
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? { ...msg, pending: false, content: finalText }
                : msg,
            ),
          );
        } else if (e.event === "error") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? {
                    ...msg,
                    pending: false,
                    content: `**Error:** ${String(e.payload.message ?? "")}`,
                  }
                : msg,
            ),
          );
        } else if (e.event === "cancelled") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? {
                    ...msg,
                    pending: false,
                    content: `**Cancelled:** ${String(e.payload.message ?? "The connection was closed.")}`,
                  }
                : msg,
            ),
          );
        }
      },
      () => {
        setBusy(false);
        closeRef.current = null;
      },
      (err) => {
        console.error("stream error", err);
        setMessages((m) =>
          m.map((msg) =>
            msg.id === pendingId && msg.pending
              ? {
                  ...msg,
                  pending: false,
                  content: "Connection error. Is the API server running on :8000?",
                }
              : msg,
          ),
        );
        setBusy(false);
        closeRef.current = null;
      },
    );
    closeRef.current = close;
  }, [input, busy, attached, ensureSession]);

  const handleReset = useCallback(async () => {
    if (closeRef.current) {
      closeRef.current();
      closeRef.current = null;
    }
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        /* ignore */
      }
    }
    window.localStorage.removeItem(SESSION_KEY);
    setSessionId(null);
    setMessages([]);
    setTrace([]);
    setAttached(null);
    setBusy(false);
  }, [sessionId]);

  const totals = classifyTotals(trace);

  return (
    <main className="h-screen flex flex-col">
      <header className="border-b border-border bg-bg-elevated/60 backdrop-blur">
        <div className="px-4 py-3 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent text-accent-fg flex items-center justify-center">
            <Sparkles size={16} />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight">
              Marketing Agent
            </h1>
            <p className="text-[11px] text-fg-subtle">
              Content · Analytics · Research
            </p>
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg px-2.5 py-1.5 rounded-md hover:bg-bg-subtle transition"
            >
              <RefreshCw size={13} />
              <span>New chat</span>
            </button>
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <ChatPanel
          messages={messages}
          input={input}
          setInput={setInput}
          onSend={handleSend}
          busy={busy}
          attached={attached}
          onAttached={setAttached}
          onCleared={() => setAttached(null)}
        />
        <TracePanel events={trace} totals={totals} />
      </div>
    </main>
  );
}
