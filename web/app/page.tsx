"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { ChatPanel } from "@/components/chat-panel";
import {
  PreviewPanel,
  classifyTotals,
  type TraceEvent,
  type PreviewItem,
} from "@/components/preview-panel";
import { SessionSidebar } from "@/components/session-sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import type { ChatMessage, MessageArtifact } from "@/components/message";
import { deriveStatus } from "@/components/status-chip";
import { useSessionsStore } from "@/lib/sessions-store";
import {
  API_BASE,
  getSessionMessages,
  streamUrl,
  type UploadResponse,
} from "@/lib/api";
import { openEventStream } from "@/lib/sse";

const ACTIVE_KEY = "marketing-agent-active-session";
const LEFT_MIN_WIDTH = 256;
const RIGHT_MIN_WIDTH = 384;

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

export default function HomePage() {
  const store = useSessionsStore();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attached, setAttached] = useState<UploadResponse[]>([]);
  const [preview, setPreview] = useState<PreviewItem | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [leftWidth, setLeftWidth] = useState(LEFT_MIN_WIDTH);
  const [rightWidth, setRightWidth] = useState(RIGHT_MIN_WIDTH);
  const closeRef = useRef<(() => void) | null>(null);

  const maxSidebarWidth = useCallback((side: "left" | "right", min: number) => {
    if (typeof window === "undefined") return min;
    const divisor = side === "right" ? 2 : 4;
    return Math.max(min, Math.floor(window.innerWidth / divisor));
  }, []);

  const beginResize = useCallback(
    (side: "left" | "right", startX: number) => {
      const startWidth = side === "left" ? leftWidth : rightWidth;
      const minWidth = side === "left" ? LEFT_MIN_WIDTH : RIGHT_MIN_WIDTH;

      function onMove(e: MouseEvent) {
        const delta = e.clientX - startX;
        const next =
          side === "left" ? startWidth + delta : startWidth - delta;
        const maxWidth = maxSidebarWidth(side, minWidth);
        const width = Math.min(maxWidth, Math.max(minWidth, next));
        if (side === "left") setLeftWidth(width);
        else setRightWidth(width);
      }

      function onUp() {
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      }

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [leftWidth, rightWidth, maxSidebarWidth],
  );

  useEffect(() => {
    function clampWidths() {
      setLeftWidth((w) =>
        Math.min(
          maxSidebarWidth("left", LEFT_MIN_WIDTH),
          Math.max(LEFT_MIN_WIDTH, w),
        ),
      );
      setRightWidth((w) =>
        Math.min(
          maxSidebarWidth("right", RIGHT_MIN_WIDTH),
          Math.max(RIGHT_MIN_WIDTH, w),
        ),
      );
    }
    window.addEventListener("resize", clampWidths);
    clampWidths();
    return () => window.removeEventListener("resize", clampWidths);
  }, [maxSidebarWidth]);

  // Restore active session id.
  useEffect(() => {
    const stored =
      typeof window !== "undefined"
        ? window.localStorage.getItem(ACTIVE_KEY)
        : null;
    if (stored) setActiveId(stored);
  }, []);

  const loadSession = useCallback(async (id: string) => {
    setActiveId(id);
    window.localStorage.setItem(ACTIVE_KEY, id);
    setTrace([]);
    setPreview(null);
    try {
      const { messages: stored } = await getSessionMessages(id);
      setMessages(
        stored.map((m) => ({
          id: newId(),
          role: m.role,
          content: m.content,
          artifacts: m.artifacts,
        })),
      );
    } catch {
      setMessages([]);
    }
  }, []);

  const handleNewChat = useCallback(async () => {
    if (closeRef.current) {
      closeRef.current();
      closeRef.current = null;
    }
    setBusy(false);
    setMessages([]);
    setTrace([]);
    setAttached([]);
    setPreview(null);
    const id = await store.createSession();
    setActiveId(id);
    window.localStorage.setItem(ACTIVE_KEY, id);
  }, [store]);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (activeId) return activeId;
    const id = await store.createSession();
    setActiveId(id);
    window.localStorage.setItem(ACTIVE_KEY, id);
    return id;
  }, [activeId, store]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setTrace([]);

    const userMsg: ChatMessage = { id: newId(), role: "user", content: text };
    const pendingId = newId();
    const pendingMsg: ChatMessage = {
      id: pendingId,
      role: "assistant",
      content: "",
      pending: true,
      status: deriveStatus([]),
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

    const fileIds = attached.map((a) => a.file_id);
    const url = streamUrl(sid, text, fileIds);

    const recoverAfterStreamError = async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      try {
        const { messages: stored } = await getSessionMessages(sid);
        const hydrated = stored.map((m) => ({
          id: newId(),
          role: m.role,
          content: m.content,
          artifacts: m.artifacts,
        }));
        const recoveredAssistant = [...hydrated]
          .reverse()
          .find((msg) => msg.role === "assistant" && msg.content.trim().length > 0);

        if (recoveredAssistant) {
          setMessages(hydrated);
          store.touch();
          return;
        }
      } catch (recoveryErr) {
        console.error("stream recovery failed", recoveryErr);
      }

      setMessages((m) =>
        m.map((msg) =>
          msg.id === pendingId && msg.pending
            ? {
                ...msg,
                pending: false,
                status: undefined,
                content:
                  msg.content ||
                  `Connection error. Could not keep a live stream open to ${API_BASE}. Please refresh and try again.`,
              }
            : msg,
        ),
      );
    };

    const close = openEventStream(
      url,
      (e) => {
        const traced = { ...e, ts: Date.now() } as TraceEvent;
        setTrace((t) => {
          const next = [...t, traced];
          // Update the pending bubble's status chip from the latest trace.
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId && msg.pending && msg.content.length === 0
                ? { ...msg, status: deriveStatus(next) }
                : msg,
            ),
          );
          return next;
        });

        if (e.event === "assistant_delta") {
          const delta = String(e.payload.delta ?? "");
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? { ...msg, content: msg.content + delta, status: undefined }
                : msg,
            ),
          );
        } else if (e.event === "artifact_created") {
          const artifact: MessageArtifact = {
            artifact_id: String(e.payload.artifact_id),
            filename: String(e.payload.filename),
            mime: String(e.payload.mime ?? "application/pdf"),
          };
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? { ...msg, artifacts: [...(msg.artifacts ?? []), artifact] }
                : msg,
            ),
          );
          // Auto-select in preview pane.
          setPreview({
            source: "artifact",
            id: artifact.artifact_id,
            filename: artifact.filename,
            mime: artifact.mime,
          });
        } else if (e.event === "result") {
          const finalText = String(e.payload.text ?? "");
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId
                ? {
                    ...msg,
                    pending: false,
                    status: undefined,
                    content: finalText || msg.content,
                  }
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
                    status: undefined,
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
                    status: undefined,
                    content:
                      msg.content ||
                      `**Cancelled:** ${String(e.payload.message ?? "The connection was closed.")}`,
                  }
                : msg,
            ),
          );
        }
      },
      () => {
        setBusy(false);
        closeRef.current = null;
        store.touch();
      },
      (err) => {
        console.error("stream error", err);
        void recoverAfterStreamError();
        setBusy(false);
        closeRef.current = null;
      },
    );
    closeRef.current = close;
    // Clear attachments after sending.
    setAttached([]);
  }, [input, busy, attached, ensureSession, store]);

  const onPreviewUpload = useCallback((f: UploadResponse) => {
    setPreview({
      source: "upload",
      id: f.file_id,
      filename: f.original_name,
      mime: f.mime,
    });
  }, []);

  const onPreviewArtifact = useCallback((a: MessageArtifact) => {
    setPreview({
      source: "artifact",
      id: a.artifact_id,
      filename: a.filename,
      mime: a.mime,
    });
  }, []);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      await store.deleteSession(id);
      if (id === activeId) {
        setActiveId(null);
        setMessages([]);
        setTrace([]);
        setPreview(null);
        window.localStorage.removeItem(ACTIVE_KEY);
      }
    },
    [store, activeId],
  );

  const handleDeleteGroup = useCallback(
    async (id: string) => {
      // Sessions in this group are about to be cascade-deleted server-side.
      const affected = store.sessions.filter((s) => s.group_id === id);
      await store.deleteGroup(id);
      if (activeId && affected.some((s) => s.id === activeId)) {
        setActiveId(null);
        setMessages([]);
        setTrace([]);
        setPreview(null);
        window.localStorage.removeItem(ACTIVE_KEY);
      }
    },
    [store, activeId],
  );

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
            <ThemeToggle />
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <SessionSidebar
          sessions={store.sessions}
          groups={store.groups}
          activeId={activeId}
          collapsed={collapsed}
          width={leftWidth}
          onToggle={() => setCollapsed((c) => !c)}
          onSelect={loadSession}
          onNewChat={handleNewChat}
          onRenameSession={store.renameSession}
          onMoveSession={store.moveSession}
          onDeleteSession={handleDeleteSession}
          onCreateGroup={store.createGroup}
          onRenameGroup={store.renameGroup}
          onDeleteGroup={handleDeleteGroup}
        />
        {!collapsed ? (
          <ResizeHandle
            side="left"
            onMouseDown={(e) => beginResize("left", e.clientX)}
          />
        ) : null}
        <ChatPanel
          messages={messages}
          input={input}
          setInput={setInput}
          onSend={handleSend}
          busy={busy}
          attached={attached}
          onAttach={(f) => setAttached((a) => [...a, f])}
          onRemoveAttached={(id) =>
            setAttached((a) => a.filter((f) => f.file_id !== id))
          }
          onPreviewUpload={onPreviewUpload}
          onPreviewArtifact={onPreviewArtifact}
        />
        {!previewCollapsed ? (
          <ResizeHandle
            side="right"
            onMouseDown={(e) => beginResize("right", e.clientX)}
          />
        ) : null}
        <PreviewPanel
          events={trace}
          totals={totals}
          preview={preview}
          collapsed={previewCollapsed}
          width={rightWidth}
          onToggle={() => setPreviewCollapsed((c) => !c)}
          defaultTab={preview ? "preview" : "trace"}
        />
      </div>
    </main>
  );
}

function ResizeHandle({
  side,
  onMouseDown,
}: {
  side: "left" | "right";
  onMouseDown: (e: React.MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      aria-label={`Resize ${side} panel`}
      onMouseDown={onMouseDown}
      className={`hidden ${
        side === "left" ? "md:block" : "lg:block"
      } w-1 shrink-0 cursor-col-resize bg-transparent hover:bg-accent/30 focus:bg-accent/30 focus:outline-none transition`}
    />
  );
}
