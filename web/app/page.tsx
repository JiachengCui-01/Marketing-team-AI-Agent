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
import { MessagesPanel } from "@/components/messages-panel";
import { ContactsPanel } from "@/components/contacts-panel";
import { ApprovalsPanel } from "@/components/approvals-panel";
import { TasksPanel } from "@/components/tasks-panel";
import { CalendarPanel } from "@/components/calendar-panel";
import { HeaderCalendar } from "@/components/header-calendar";
import { Spinner } from "@/components/ui/spinner";
import type { ChatMessage, MessageArtifact } from "@/components/message";
import { deriveStatus } from "@/components/status-chip";
import { useI18n } from "@/lib/i18n";
import { getUserLocale, getUserTheme } from "@/lib/user-settings";
import { useSessionsStore } from "@/lib/sessions-store";
import { useImStore } from "@/lib/im-store";
import {
  API_BASE,
  artifactDownloadUrl,
  completeSession,
  getMe,
  getSessionMessages,
  logoutUser,
  setAuthToken,
  streamUrl,
  type OaDraft,
  type UploadResponse,
  type UserProfile,
} from "@/lib/api";
import { openEventStream } from "@/lib/sse";

const ACTIVE_KEY = "marketing-agent-active-session";
const LEFT_MIN_WIDTH = 256;
const RIGHT_MIN_WIDTH = 384;

type DirectoryHandle = FileSystemDirectoryHandle;

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

function safeFilename(name: string): string {
  return name.replace(/[<>:"/\\|?*\x00-\x1F]/g, "_").slice(0, 160) || "artifact";
}

async function saveArtifactToWorkspace(
  handle: DirectoryHandle | null,
  artifact: MessageArtifact,
  workspaceName: string | null,
) {
  if (!handle || !workspaceName) return;
  try {
    const res = await fetch(artifactDownloadUrl(artifact.artifact_id));
    if (!res.ok) return;
    const blob = await res.blob();
    const fileHandle = await handle.getFileHandle(safeFilename(artifact.filename), { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(blob);
    await writable.close();
  } catch (error) {
    console.warn("workspace artifact save failed", error);
  }
}

export default function HomePage() {
  const { t, setLocale } = useI18n();
  const { setTheme } = useTheme();
  const store = useSessionsStore();
  const [user, setUser] = useState<UserProfile | null>(null);
  const im = useImStore(user?.id ?? null);
  const [authLoading, setAuthLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messagesBySession, setMessagesBySession] = useState<Record<string, ChatMessage[]>>({});
  const [traceBySession, setTraceBySession] = useState<Record<string, TraceEvent[]>>({});
  const [runningSessions, setRunningSessions] = useState<Record<string, boolean>>({});
  const [input, setInput] = useState("");
  const [attached, setAttached] = useState<UploadResponse[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [workspaceFileIds, setWorkspaceFileIds] = useState<string[]>([]);
  const [workspaceName, setWorkspaceName] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewItem | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [previewCollapsed, setPreviewCollapsed] = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const [view, setView] = useState<
    | "chat"
    | "news"
    | "image"
    | "messages"
    | "contacts"
    | "approvals"
    | "tasks"
    | "calendar"
  >("chat");
  const [leftWidth, setLeftWidth] = useState(LEFT_MIN_WIDTH);
  const [rightWidth, setRightWidth] = useState(RIGHT_MIN_WIDTH);
  // Collaboration views (messages/contacts) use a different layout: the right
  // column is pinned to half the viewport, and the session sidebar shares the
  // left half with the panel's list column via a draggable divider.
  const [collabSidebarWidth, setCollabSidebarWidth] = useState(LEFT_MIN_WIDTH);
  const [halfWidth, setHalfWidth] = useState(() =>
    typeof window !== "undefined" ? Math.floor(window.innerWidth / 2) : 640,
  );
  const closeRefs = useRef<Map<string, () => void>>(new Map());
  const activeIdRef = useRef<string | null>(null);
  const workspaceHandleRef = useRef<DirectoryHandle | null>(null);

  const messages = activeId ? messagesBySession[activeId] ?? [] : [];
  const trace = activeId ? traceBySession[activeId] ?? [] : [];
  const busy = activeId ? !!runningSessions[activeId] : false;
  const isCollab = view === "messages" || view === "contacts";

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

  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  const setSessionMessages = useCallback(
    (sessionId: string, updater: (messages: ChatMessage[]) => ChatMessage[]) => {
      setMessagesBySession((current) => ({
        ...current,
        [sessionId]: updater(current[sessionId] ?? []),
      }));
    },
    [],
  );

  const setSessionTrace = useCallback(
    (sessionId: string, updater: (events: TraceEvent[]) => TraceEvent[]) => {
      setTraceBySession((current) => ({
        ...current,
        [sessionId]: updater(current[sessionId] ?? []),
      }));
    },
    [],
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

  const beginCollabResize = useCallback(
    (startX: number) => {
      const startWidth = collabSidebarWidth;
      const maxWidth = Math.max(LEFT_MIN_WIDTH, halfWidth - LEFT_MIN_WIDTH);

      function onMove(e: MouseEvent) {
        const next = startWidth + (e.clientX - startX);
        setCollabSidebarWidth(Math.min(maxWidth, Math.max(LEFT_MIN_WIDTH, next)));
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
    [collabSidebarWidth, halfWidth],
  );

  useEffect(() => {
    function clampWidths() {
      const half = Math.floor(window.innerWidth / 2);
      setHalfWidth(half);
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
      setCollabSidebarWidth((w) =>
        Math.min(Math.max(LEFT_MIN_WIDTH, half - LEFT_MIN_WIDTH), Math.max(LEFT_MIN_WIDTH, w)),
      );
    }
    window.addEventListener("resize", clampWidths);
    clampWidths();
    return () => window.removeEventListener("resize", clampWidths);
  }, [maxSidebarWidth]);

  // Start authenticated users in a temporary blank chat. A real session is
  // created only after the first message is sent.
  useEffect(() => {
    if (!user) return;
    setActiveId(null);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(activeKey(user));
    }
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
      setPreview(null);
      if (messagesBySession[id]) return;
      try {
        const { messages: stored } = await getSessionMessages(id);
        setMessagesBySession((current) => ({
          ...current,
          [id]: stored.map((m) => ({
            id: newId(),
            role: m.role,
            content: m.content,
            artifacts: m.artifacts,
          })),
        }));
      } catch {
        setMessagesBySession((current) => ({ ...current, [id]: [] }));
      }
    },
    [activeKey, messagesBySession],
  );

  const handleNewChat = useCallback(async () => {
    setView("chat");
    setAttached([]);
    setPreview(null);
    setActiveId(null);
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(activeKey());
    }
  }, [activeKey]);

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

  const handleClarificationRequest = useCallback(
    async (prompt: string, assistantText: string) => {
      const text = prompt.trim();
      if (!text || busy) return;
      setInput("");
      let sid: string;
      try {
        sid = await ensureSession();
      } catch (e) {
        if (activeId) {
          setSessionMessages(activeId, (m) => [
            ...m,
            { id: newId(), role: "assistant", content: `${t.failedToStartSession}: ${String(e)}` },
          ]);
        }
        return;
      }
      setTraceBySession((current) => ({ ...current, [sid]: [] }));
      setSessionMessages(sid, (m) => [
        ...m,
        { id: newId(), role: "user", content: text },
        { id: newId(), role: "assistant", content: assistantText },
      ]);
      store.touch();
    },
    [activeId, busy, ensureSession, setSessionMessages, store, t],
  );

  const handleSend = useCallback(async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || busy) return;
    setInput("");

    let sid: string;
    try {
      sid = await ensureSession();
    } catch (e) {
      if (activeId) {
        setSessionMessages(activeId, (m) => [
          ...m,
          { id: newId(), role: "assistant", content: `${t.failedToStartSession}: ${String(e)}` },
        ]);
      }
      return;
    }

    setRunningSessions((current) => ({ ...current, [sid]: true }));
    setTraceBySession((current) => ({ ...current, [sid]: [] }));

    const userMsg: ChatMessage = { id: newId(), role: "user", content: text };
    const pendingId = newId();
    const pendingMsg: ChatMessage = {
      id: pendingId,
      role: "assistant",
      content: "",
      pending: true,
      status: deriveStatus([], t),
    };
    setSessionMessages(sid, (m) => [...m, userMsg, pendingMsg]);

    const fileIds = Array.from(new Set([...attached.map((a) => a.file_id), ...workspaceFileIds]));
    const skillIds = selectedSkillIds;
    const url = streamUrl(sid, text, fileIds, skillIds);

    const updatePending = (updater: (msg: ChatMessage) => ChatMessage) => {
      setSessionMessages(sid, (current) =>
        current.map((msg) => (msg.id === pendingId ? updater(msg) : msg)),
      );
    };

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
          setMessagesBySession((current) => ({ ...current, [sid]: hydrated }));
          store.touch();
          return;
        }
      } catch (recoveryErr) {
        console.error("stream recovery failed", recoveryErr);
      }

      try {
        const completed = await completeSession(sid, text, fileIds, skillIds);
        const fallbackEvents = Array.isArray(completed.events)
          ? (completed.events as TraceEvent[]).map((event) => ({
              ...event,
              ts: Date.now(),
            }))
          : [];
        if (fallbackEvents.length > 0) {
          setSessionTrace(sid, (events) => [...events, ...fallbackEvents]);
        }
        updatePending((msg) => ({
          ...msg,
          pending: false,
          status: undefined,
          content:
            completed.text ||
            (completed.ok
              ? `${t.error}: ${t.noTextReturned}`
              : `${t.error}: ${t.noMessageReturned}`),
        }));
        store.touch();
        return;
      } catch (fallbackErr) {
        console.error("non-stream fallback failed", fallbackErr);
      }

      updatePending((msg) =>
        msg.pending
          ? {
              ...msg,
              pending: false,
              status: undefined,
              content: msg.content || `${t.error}: ${API_BASE}`,
            }
          : msg,
      );
    };

    const close = openEventStream(
      url,
      (e) => {
        const traced = { ...e, ts: Date.now() } as TraceEvent;
        setSessionTrace(sid, (prevTrace) => {
          const next = [...prevTrace, traced];
          updatePending((msg) =>
            msg.pending && msg.content.length === 0
              ? { ...msg, status: deriveStatus(next, t) }
              : msg,
          );
          return next;
        });

        if (e.event === "assistant_delta") {
          const delta = String(e.payload.delta ?? "");
          updatePending((msg) => ({ ...msg, content: msg.content + delta, status: undefined }));
        } else if (e.event === "artifact_created") {
          const artifact: MessageArtifact = {
            artifact_id: String(e.payload.artifact_id),
            filename: String(e.payload.filename),
            mime: String(e.payload.mime ?? "application/pdf"),
          };
          updatePending((msg) => ({ ...msg, artifacts: [...(msg.artifacts ?? []), artifact] }));
          if (activeIdRef.current === sid) {
            setPreview({
              source: "artifact",
              id: artifact.artifact_id,
              filename: artifact.filename,
              mime: artifact.mime,
            });
          }
        } else if (e.event === "oa_draft") {
          const draft = e.payload as unknown as OaDraft;
          updatePending((msg) => ({ ...msg, drafts: [...(msg.drafts ?? []), draft] }));
        } else if (e.event === "result") {
          const finalText = String(e.payload.text ?? "");
          updatePending((msg) => ({
            ...msg,
            pending: false,
            status: undefined,
            content: finalText || msg.content,
          }));
        } else if (e.event === "error") {
          updatePending((msg) => ({
            ...msg,
            pending: false,
            status: undefined,
            content: `**${t.error}:** ${String(e.payload.message ?? "")}`,
          }));
        } else if (e.event === "cancelled") {
          updatePending((msg) => ({
            ...msg,
            pending: false,
            status: undefined,
            content:
              msg.content ||
              `**${t.streamCancelled}:** ${String(e.payload.message ?? t.connectionClosed)}`,
          }));
        }
      },
      () => {
        setRunningSessions((current) => ({ ...current, [sid]: false }));
        closeRefs.current.delete(sid);
        store.touch();
      },
      (err) => {
        console.error("stream error", err);
        void recoverAfterStreamError();
        setRunningSessions((current) => ({ ...current, [sid]: false }));
        closeRefs.current.delete(sid);
      },
    );
    closeRefs.current.set(sid, close);
    // Clear attachments after sending.
    setAttached([]);
  }, [input, busy, activeId, attached, workspaceFileIds, selectedSkillIds, ensureSession, setSessionMessages, setSessionTrace, store, t]);
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
      closeRefs.current.get(id)?.();
      closeRefs.current.delete(id);
      await store.deleteSession(id);
      setMessagesBySession((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      setTraceBySession((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      setRunningSessions((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      if (id === activeId) {
        setActiveId(null);
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
      for (const session of affected) {
        closeRefs.current.get(session.id)?.();
        closeRefs.current.delete(session.id);
      }
      await store.deleteGroup(id);
      setMessagesBySession((current) => {
        const next = { ...current };
        for (const session of affected) delete next[session.id];
        return next;
      });
      setTraceBySession((current) => {
        const next = { ...current };
        for (const session of affected) delete next[session.id];
        return next;
      });
      setRunningSessions((current) => {
        const next = { ...current };
        for (const session of affected) delete next[session.id];
        return next;
      });
      if (activeId && affected.some((s) => s.id === activeId)) {
        setActiveId(null);
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
      for (const close of closeRefs.current.values()) close();
      closeRefs.current.clear();
      setMessagesBySession({});
      setTraceBySession({});
      setRunningSessions({});
      setPreview(null);
      setAttached([]);
      void store.refresh();
    },
    [applyUserSettings, store],
  );

  const handleLogout = useCallback(async () => {
    for (const close of closeRefs.current.values()) close();
    closeRefs.current.clear();
    await logoutUser().catch(() => undefined);
    setUser(null);
    setView("chat");
    setActiveId(null);
    setMessagesBySession({});
    setTraceBySession({});
    setRunningSessions({});
    setPreview(null);
    setAttached([]);
  }, []);

  const handleMessageUser = useCallback(
    async (peerRef: string) => {
      setView("messages");
      try {
        if (peerRef.startsWith("conversation:")) {
          await im.openConversation(peerRef.slice("conversation:".length));
        } else {
          await im.openDirect(peerRef);
        }
      } catch (err) {
        console.error("open conversation failed", err);
      }
    },
    [im],
  );

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
          <div className="absolute left-1/2 -translate-x-1/2 hidden md:block">
            <HeaderCalendar onOpen={() => setView("calendar")} />
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
          runningIds={Object.keys(runningSessions).filter((id) => runningSessions[id])}
          collapsed={collapsed}
          width={isCollab ? collabSidebarWidth : leftWidth}
          onToggle={() => setCollapsed((c) => !c)}
          onSelect={loadSession}
          onNewChat={handleNewChat}
          onRenameSession={store.renameSession}
          onMoveSession={store.moveSession}
          onDeleteSession={handleDeleteSession}
          onCreateGroup={store.createGroup}
          onRenameGroup={store.renameGroup}
          onDeleteGroup={handleDeleteGroup}
          onOpenApprovals={() => setView("approvals")}
          onOpenTasks={() => setView("tasks")}
          onOpenMessages={() => setView("messages")}
          onOpenContacts={() => setView("contacts")}
          onOpenNews={() => setView("news")}
          onOpenImage={() => setView("image")}
          messageUnread={im.unreadTotal}
        />
        {!collapsed ? (
          <ResizeHandle
            side="left"
            onMouseDown={(e) =>
              isCollab ? beginCollabResize(e.clientX) : beginResize("left", e.clientX)
            }
          />
        ) : null}
        {isCollab ? (
          view === "messages" ? (
            <MessagesPanel
              key={user.id}
              onBack={() => setView("chat")}
              halfWidth={halfWidth}
              im={im}
              meId={user.id}
              meName={user.username}
              meAvatar={user.avatar}
            />
          ) : (
            <ContactsPanel
              key={user.id}
              onBack={() => setView("chat")}
              halfWidth={halfWidth}
              meId={user.id}
              onMessageUser={handleMessageUser}
            />
          )
        ) : (
          <>
        {view === "approvals" ? (
          <ApprovalsPanel key={user.id} onBack={() => setView("chat")} />
        ) : view === "tasks" ? (
          <TasksPanel key={user.id} onBack={() => setView("chat")} />
        ) : view === "calendar" ? (
          <CalendarPanel key={user.id} onBack={() => setView("chat")} />
        ) : view === "news" ? (
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
            onClarificationRequest={handleClarificationRequest}
            onPreviewUpload={onPreviewUpload}
            onPreviewArtifact={onPreviewArtifact}
            onDownloadArtifact={
              workspaceName
                ? (artifact) => void saveArtifactToWorkspace(workspaceHandleRef.current, artifact, workspaceName)
                : undefined
            }
            userAvatar={user.avatar}
            selectedSkillIds={selectedSkillIds}
            setSelectedSkillIds={setSelectedSkillIds}
            workspaceFileIds={workspaceFileIds}
            setWorkspaceFileIds={setWorkspaceFileIds}
            onWorkspaceSelected={(handle, name) => {
              workspaceHandleRef.current = handle;
              setWorkspaceName(name);
            }}
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
          onDownloadArtifact={
            workspaceName
              ? (item) =>
                  void saveArtifactToWorkspace(
                    workspaceHandleRef.current,
                    { artifact_id: item.id, filename: item.filename, mime: item.mime },
                    workspaceName,
                  )
              : undefined
          }
          defaultTab={preview ? "preview" : "trace"}
        />
          </>
        )}
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
