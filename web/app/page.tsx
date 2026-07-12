"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { useTheme } from "next-themes";
import {
  AuthScreen,
  SwitchAccountPanel,
  UserMenu,
} from "@/components/auth-ui";
import { ChatPanel } from "@/components/chat-panel";
import {
  PreviewPanel,
  classifyTotals,
  type TraceEvent,
  type PreviewItem,
} from "@/components/preview-panel";
import { SessionSidebar } from "@/components/session-sidebar";
import { NewsPanel } from "@/components/news-panel";
import { MarketingImagePanel } from "@/components/image-panel";
import { Spinner } from "@/components/ui/spinner";
import type { ChatMessage, MessageArtifact } from "@/components/message";
import { deriveStatus } from "@/components/status-chip";
import { useI18n } from "@/lib/i18n";
import { getUserLocale, getUserTheme } from "@/lib/user-settings";
import { useSessionsStore } from "@/lib/sessions-store";
import {
  API_BASE,
  completeSession,
  getMe,
  getSessionMessages,
  logoutUser,
  setAuthToken,
  streamUrl,
  type UploadResponse,
  type UserProfile,
} from "@/lib/api";
import { openEventStream } from "@/lib/sse";

const ACTIVE_KEY = "marketing-agent-active-session";
const LEFT_MIN_WIDTH = 256;
const RIGHT_MIN_WIDTH = 384;

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

export default function HomePage() {
  const { t, setLocale } = useI18n();
  const { setTheme } = useTheme();
  const store = useSessionsStore();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [attached, setAttached] = useState<UploadResponse[]>([]);
  const [preview, setPreview] = useState<PreviewItem | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [view, setView] = useState<"chat" | "news" | "image">("chat");
  const [leftWidth, setLeftWidth] = useState(LEFT_MIN_WIDTH);
  const [rightWidth, setRightWidth] = useState(RIGHT_MIN_WIDTH);
  const closeRef = useRef<(() => void) | null>(null);

  const applyUserSettings = useCallback(
    (profile: UserProfile) => {
      setLocale(getUserLocale(profile.account));
      setTheme(getUserTheme(profile.account));
    },
    [setLocale, setTheme],
  );

  const activeKey = useCallback(
    (profile: UserProfile | null = user) =>
      profile ? `${ACTIVE_KEY}:${profile.account}` : ACTIVE_KEY,
    [user],
  );

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
    if (!user) return;
    const stored =
      typeof window !== "undefined"
        ? window.localStorage.getItem(activeKey(user))
        : null;
    if (stored) setActiveId(stored);
  }, [activeKey, user]);

  useEffect(() => {
    getMe()
      .then((profile) => {
        applyUserSettings(profile);
        setUser(profile);
        void store.refresh();
      })
      .catch(() => {
        setAuthToken(null);
        setUser(null);
      })
      .finally(() => setAuthLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applyUserSettings]);

  const loadSession = useCallback(
    async (id: string) => {
      setView("chat");
      setActiveId(id);
      window.localStorage.setItem(activeKey(), id);
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
    },
    [activeKey],
  );

  const handleNewChat = useCallback(async () => {
    if (closeRef.current) {
      closeRef.current();
      closeRef.current = null;
    }
    setView("chat");
    setBusy(false);
    setMessages([]);
    setTrace([]);
    setAttached([]);
    setPreview(null);
    const id = await store.createSession();
    setActiveId(id);
    window.localStorage.setItem(activeKey(), id);
  }, [activeKey, store]);

  const ensureSession = useCallback(async (): Promise<string> => {
    if (activeId) {
      try {
        await getSessionMessages(activeId);
        return activeId;
      } catch {
        window.localStorage.removeItem(activeKey());
        setActiveId(null);
      }
    }
    const id = await store.createSession();
    setActiveId(id);
    window.localStorage.setItem(activeKey(), id);
    return id;
  }, [activeId, activeKey, store]);

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
      status: deriveStatus([], t),
    };
    setMessages((m) => [...m, userMsg, pendingMsg]);

    let sid: string;
    try {
      sid = await ensureSession();
    } catch (e) {
      setMessages((m) =>
        m.map((msg) =>
          msg.id === pendingId
            ? { ...msg, pending: false, content: `${t.failedToStartSession}: ${String(e)}` }
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

      try {
        const completed = await completeSession(sid, text, fileIds);
        const fallbackEvents = Array.isArray(completed.events)
          ? (completed.events as TraceEvent[]).map((event) => ({
              ...event,
              ts: Date.now(),
            }))
          : [];
        if (fallbackEvents.length > 0) {
          setTrace((t) => [...t, ...fallbackEvents]);
        }
        setMessages((m) =>
          m.map((msg) =>
            msg.id === pendingId
              ? {
                  ...msg,
                  pending: false,
                  status: undefined,
                  content:
                    completed.text ||
                    (completed.ok
                      ? `${t.error}: ${t.noTextReturned}`
                      : `${t.error}: ${t.noMessageReturned}`),
                }
              : msg,
          ),
        );
        store.touch();
        return;
      } catch (fallbackErr) {
        console.error("non-stream fallback failed", fallbackErr);
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
                  `${t.error}: ${API_BASE}`,
              }
            : msg,
        ),
      );
    };

    const close = openEventStream(
      url,
      (e) => {
        const traced = { ...e, ts: Date.now() } as TraceEvent;
        setTrace((prevTrace) => {
          const next = [...prevTrace, traced];
          // Update the pending bubble's status chip from the latest trace.
          setMessages((m) =>
            m.map((msg) =>
              msg.id === pendingId && msg.pending && msg.content.length === 0
                ? { ...msg, status: deriveStatus(next, t) }
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
                    content: `**${t.error}:** ${String(e.payload.message ?? "")}`,
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
                      `**${t.streamCancelled}:** ${String(e.payload.message ?? t.connectionClosed)}`,
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
  }, [input, busy, attached, ensureSession, store, t]);

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
        window.localStorage.removeItem(activeKey());
      }
    },
    [store, activeId, activeKey],
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
        window.localStorage.removeItem(activeKey());
      }
    },
    [store, activeId, activeKey],
  );

  const handleAuthenticated = useCallback(
    (token: string, profile: UserProfile) => {
      setAuthToken(token);
      applyUserSettings(profile);
      setUser(profile);
      setSwitchOpen(false);
      setView("chat");
      setActiveId(null);
      setMessages([]);
      setTrace([]);
      setPreview(null);
      setAttached([]);
      void store.refresh();
    },
    [applyUserSettings, store],
  );

  const handleLogout = useCallback(async () => {
    if (closeRef.current) {
      closeRef.current();
      closeRef.current = null;
    }
    await logoutUser().catch(() => undefined);
    setUser(null);
    setView("chat");
    setActiveId(null);
    setMessages([]);
    setTrace([]);
    setPreview(null);
    setAttached([]);
  }, []);

  const totals = classifyTotals(trace);

  if (authLoading) {
    return (
      <main className="auth-loading-screen h-screen flex items-center justify-center bg-bg-subtle">
        <div className="flex flex-col items-center justify-center gap-4 animate-fade-in">
          <Spinner size={44} label={t.loadingAccount} variant="account" className="auth-loading-mark flex-col gap-3" />
        </div>
      </main>
    );
  }

  if (!user) {
    return <AuthScreen onAuthenticated={handleAuthenticated} />;
  }

  return (
    <main className="h-screen flex flex-col bg-bg-subtle">
      <header className="relative z-50 bg-bg-subtle px-1.5 pt-1.5">
        <div className="frost-bar h-14 rounded-2xl border border-border px-4 py-3 flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent text-accent-fg flex items-center justify-center">
            <Sparkles size={16} />
          </div>
          <div>
            <h1 className="text-sm font-semibold tracking-tight">
              {t.appName}
            </h1>
            <p className="text-[11px] text-fg-subtle">
              {t.navSubtitle}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-1">
            <UserMenu
              user={user}
              onUserChange={setUser}
              onLogout={handleLogout}
              onSwitchAccount={() => setSwitchOpen(true)}
            />
          </div>
        </div>
      </header>

      <div className="flex flex-1 gap-1 p-1.5 bg-bg-subtle overflow-hidden">
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
          onOpenNews={() => setView("news")}
          onOpenImage={() => setView("image")}
        />
        {!collapsed ? (
          <ResizeHandle
            side="left"
            onMouseDown={(e) => beginResize("left", e.clientX)}
          />
        ) : null}
        {view === "news" ? (
          <NewsPanel key={user.id} onBack={() => setView("chat")} />
        ) : view === "image" ? (
          <MarketingImagePanel
            key={user.id}
            onBack={() => setView("chat")}
            onPreview={setPreview}
          />
        ) : (
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
            userAvatar={user.avatar}
          />
        )}
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
      <SwitchAccountPanel
        open={switchOpen}
        onClose={() => setSwitchOpen(false)}
        onAuthenticated={handleAuthenticated}
      />
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
  const { t } = useI18n();
  return (
    <button
      type="button"
      aria-label={t.resizePanel(side)}
      onMouseDown={onMouseDown}
      className={`hidden ${
        side === "left" ? "md:block" : "lg:block"
      } w-1 my-6 shrink-0 cursor-col-resize rounded-full bg-transparent hover:bg-accent/40 focus:bg-accent/40 focus:outline-none transition-colors`}
    />
  );
}
