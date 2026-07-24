"use client";

import { useMemo, useRef, useState } from "react";
import {
  Plus,
  MessageSquare,
  Folder,
  FolderOpen,
  Pencil,
  Trash2,
  FolderPlus,
  FolderInput,
  PanelLeftClose,
  PanelLeft,
  Newspaper,
  Image as ImageIcon,
  MessageCircle,
  Contact,
  Sparkles,
  FileCheck2,
  CheckSquare,
  Calendar,
  BookOpen,
} from "lucide-react";
import { ContextMenu, type MenuItem } from "./context-menu";
import type { GroupRecord, SessionRecord } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type MenuState =
  | { kind: "session"; id: string; x: number; y: number }
  | { kind: "group"; id: string; x: number; y: number }
  | null;

const CONTEXT_MENU_WIDTH = 200;
const CONTEXT_MENU_EDGE_GAP = 12;

export function SessionSidebar({
  sessions,
  groups,
  activeId,
  runningIds,
  collapsed,
  width,
  onToggle,
  onSelect,
  onNewChat,
  onRenameSession,
  onMoveSession,
  onDeleteSession,
  onCreateGroup,
  onRenameGroup,
  onDeleteGroup,
  onOpenOa,
  onOpenApprovals,
  onOpenTasks,
  onOpenCalendar,
  onOpenKb,
  onOpenMessages,
  onOpenContacts,
  onOpenNews,
  onOpenImage,
  messageUnread,
}: {
  sessions: SessionRecord[];
  groups: GroupRecord[];
  activeId: string | null;
  runningIds?: string[];
  collapsed: boolean;
  width?: number;
  onToggle: () => void;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onRenameSession: (id: string, name: string) => void;
  onMoveSession: (id: string, groupId: string | null) => void;
  onDeleteSession: (id: string) => void;
  onCreateGroup: (name: string) => Promise<string> | void;
  onRenameGroup: (id: string, name: string) => void;
  onDeleteGroup: (id: string) => void;
  onOpenOa: () => void;
  onOpenApprovals: () => void;
  onOpenTasks: () => void;
  onOpenCalendar: () => void;
  onOpenKb: () => void;
  onOpenMessages: () => void;
  onOpenContacts: () => void;
  onOpenNews: () => void;
  onOpenImage: () => void;
  messageUnread?: number;
}) {
  const { t } = useI18n();
  const sidebarRef = useRef<HTMLElement | null>(null);
  const [menu, setMenu] = useState<MenuState>(null);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const running = useMemo(() => new Set(runningIds ?? []), [runningIds]);

  const ungrouped = useMemo(
    () => sessions.filter((s) => !s.group_id),
    [sessions],
  );
  const byGroup = useMemo(() => {
    const m: Record<string, SessionRecord[]> = {};
    for (const s of sessions) {
      if (s.group_id) (m[s.group_id] ||= []).push(s);
    }
    return m;
  }, [sessions]);

  if (collapsed) {
    return (
      <aside className="hidden md:flex flex-col items-center w-12 shrink-0 py-2 gap-1 panel-card">
        <button
          onClick={onToggle}
          className="btn-ghost w-9 h-9"
          aria-label={t.expandSidebar}
          title={t.expandSidebar}
        >
          <PanelLeft size={16} />
        </button>
        <button
          onClick={onNewChat}
          className="btn-accent w-9 h-9"
          aria-label={t.newChat}
          title={t.newChat}
        >
          <Plus size={16} />
        </button>
        <button
          onClick={onOpenOa}
          className="btn-ghost w-9 h-9"
          aria-label={t.oaCopilot}
          title={t.oaCopilot}
        >
          <Sparkles size={16} className="text-accent" />
        </button>
        <button
          onClick={onOpenApprovals}
          className="btn-ghost w-9 h-9"
          aria-label={t.approvals}
          title={t.approvals}
        >
          <FileCheck2 size={16} className="text-feature-image" />
        </button>
        <button
          onClick={onOpenTasks}
          className="btn-ghost w-9 h-9"
          aria-label={t.tasks}
          title={t.tasks}
        >
          <CheckSquare size={16} className="text-feature-image" />
        </button>
        <button
          onClick={onOpenCalendar}
          className="btn-ghost w-9 h-9"
          aria-label={t.calendar}
          title={t.calendar}
        >
          <Calendar size={16} className="text-feature-news" />
        </button>
        <button
          onClick={onOpenKb}
          className="btn-ghost w-9 h-9"
          aria-label={t.knowledgeBase}
          title={t.knowledgeBase}
        >
          <BookOpen size={16} className="text-feature-image" />
        </button>
        <button
          onClick={onOpenMessages}
          className="btn-ghost w-9 h-9 relative"
          aria-label={t.messages}
          title={t.messages}
        >
          <MessageCircle size={16} className="text-feature-news" />
          {messageUnread ? (
            <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-danger" aria-hidden />
          ) : null}
        </button>
        <button
          onClick={onOpenContacts}
          className="btn-ghost w-9 h-9"
          aria-label={t.contacts}
          title={t.contacts}
        >
          <Contact size={16} className="text-feature-image" />
        </button>
        <button
          onClick={onOpenNews}
          className="btn-ghost w-9 h-9"
          aria-label={t.industryNews}
          title={t.industryNews}
        >
          <Newspaper size={16} className="text-feature-news" />
        </button>
        <button
          onClick={onOpenImage}
          className="btn-ghost w-9 h-9"
          aria-label={t.marketingImage}
          title={t.marketingImage}
        >
          <ImageIcon size={16} className="text-feature-image" />
        </button>
      </aside>
    );
  }

  function contextMenuPoint(e: React.MouseEvent): { x: number; y: number } {
    const rect = sidebarRef.current?.getBoundingClientRect();
    if (!rect) return { x: e.clientX, y: e.clientY };

    const minLeft = rect.left + CONTEXT_MENU_EDGE_GAP;
    const maxLeft = Math.max(
      minLeft,
      rect.right - CONTEXT_MENU_WIDTH - CONTEXT_MENU_EDGE_GAP,
    );
    return {
      x: Math.min(Math.max(e.clientX, minLeft), maxLeft),
      y: e.clientY,
    };
  }

  function openSessionMenu(e: React.MouseEvent, id: string) {
    e.preventDefault();
    setMenu({ kind: "session", id, ...contextMenuPoint(e) });
  }
  function openGroupMenu(e: React.MouseEvent, id: string) {
    e.preventDefault();
    setMenu({ kind: "group", id, ...contextMenuPoint(e) });
  }

  function buildSessionMenu(id: string): MenuItem[] {
    const moveItems: MenuItem[] = [
      ...groups.map((g) => ({
        label: g.name,
        icon: Folder,
        onClick: () => onMoveSession(id, g.id),
      })),
      ...(groups.length ? [{ type: "separator" as const }] : []),
      {
        label: t.ungrouped,
        icon: FolderInput,
        onClick: () => onMoveSession(id, null),
      },
      {
        label: t.newGroup,
        icon: FolderPlus,
        onClick: async () => {
          const name = window.prompt(t.groupNamePrompt);
          if (!name) return;
          const newId = await onCreateGroup(name.trim());
          if (typeof newId === "string") onMoveSession(id, newId);
        },
      },
    ];

    return [
      {
        label: t.rename,
        icon: Pencil,
        onClick: () => {
          const current = sessions.find((s) => s.id === id);
          const name = window.prompt(t.renameChatPrompt, current?.name ?? "");
          if (name && name.trim()) onRenameSession(id, name.trim());
        },
      },
      {
        type: "submenu",
        label: t.moveToGroup,
        icon: FolderInput,
        items: moveItems,
      },
      { type: "separator" },
      {
        label: t.deleteChat,
        icon: Trash2,
        danger: true,
        onClick: () => {
          if (window.confirm(t.deleteChatConfirm))
            onDeleteSession(id);
        },
      },
    ];
  }

  function buildGroupMenu(id: string): MenuItem[] {
    return [
      {
        label: t.renameGroup,
        icon: Pencil,
        onClick: () => {
          const current = groups.find((g) => g.id === id);
          const name = window.prompt(t.renameGroupPrompt, current?.name ?? "");
          if (name && name.trim()) onRenameGroup(id, name.trim());
        },
      },
      { type: "separator" },
      {
        label: t.deleteGroup,
        icon: Trash2,
        danger: true,
        onClick: () => {
          if (
            window.confirm(
              t.deleteGroupConfirm,
            )
          )
            onDeleteGroup(id);
        },
      },
    ];
  }

  return (
    <aside
      ref={sidebarRef}
      className="hidden md:flex flex-col shrink-0 panel-card"
      style={{ width: width ?? 256 }}
    >
      <div className="col-header">
        <button
          onClick={onNewChat}
          className="btn-accent flex-1 h-8 px-3 text-sm"
        >
          <Plus size={14} />
          <span>{t.newChat}</span>
        </button>
        <button
          onClick={async () => {
            const name = window.prompt(t.groupNamePrompt);
            if (name && name.trim()) await onCreateGroup(name.trim());
          }}
          className="btn-ghost w-8 h-8 border border-border"
          title={t.newGroup}
          aria-label={t.newGroup}
        >
          <FolderPlus size={14} />
        </button>
        <button
          onClick={onToggle}
          className="btn-ghost w-8 h-8"
          title={t.collapseSidebar}
          aria-label={t.collapseSidebar}
        >
          <PanelLeftClose size={14} />
        </button>
      </div>

      <div className="px-1.5 pt-2 space-y-0.5">
        <button
          onClick={onOpenOa}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <Sparkles size={15} className="text-accent shrink-0" />
          <span className="truncate">{t.oaCopilot}</span>
        </button>
        <button
          onClick={onOpenApprovals}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <FileCheck2 size={15} className="text-feature-image shrink-0" />
          <span className="truncate">{t.approvals}</span>
        </button>
        <button
          onClick={onOpenTasks}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <CheckSquare size={15} className="text-feature-image shrink-0" />
          <span className="truncate">{t.tasks}</span>
        </button>
        <button
          onClick={onOpenCalendar}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <Calendar size={15} className="text-feature-news shrink-0" />
          <span className="truncate">{t.calendar}</span>
        </button>
        <button
          onClick={onOpenKb}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <BookOpen size={15} className="text-feature-image shrink-0" />
          <span className="truncate">{t.knowledgeBase}</span>
        </button>
        <button
          onClick={onOpenMessages}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <MessageCircle size={15} className="text-feature-news shrink-0" />
          <span className="truncate flex-1 text-left">{t.messages}</span>
          {messageUnread ? (
            <span className="ml-auto min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-semibold flex items-center justify-center">
              {messageUnread > 99 ? "99+" : messageUnread}
            </span>
          ) : null}
        </button>
        <button
          onClick={onOpenContacts}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <Contact size={15} className="text-feature-image shrink-0" />
          <span className="truncate">{t.contacts}</span>
        </button>
        <button
          onClick={onOpenNews}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <Newspaper size={15} className="text-feature-news shrink-0" />
          <span className="truncate">{t.industryNews}</span>
        </button>
        <button
          onClick={onOpenImage}
          className="btn-ghost w-full justify-start px-2.5 py-2 text-sm font-medium"
        >
          <ImageIcon size={15} className="text-feature-image shrink-0" />
          <span className="truncate">{t.marketingImage}</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2 px-1.5 text-sm">
        {groups.length === 0 && sessions.length === 0 ? (
          <p className="px-3 py-6 text-xs text-fg-subtle text-center">
            {t.noChats}
          </p>
        ) : null}

        {groups.map((g) => {
          const open = openGroups[g.id] ?? true;
          const inside = byGroup[g.id] ?? [];
          return (
            <div key={g.id} className="mb-1">
              <button
                onClick={() => setOpenGroups((s) => ({ ...s, [g.id]: !open }))}
                onContextMenu={(e) => openGroupMenu(e, g.id)}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-md hover:bg-bg-elevated text-fg-muted text-xs font-medium"
              >
                {open ? <FolderOpen size={13} /> : <Folder size={13} />}
                <span className="truncate flex-1 text-left">{g.name}</span>
                <span className="text-fg-subtle text-[10px]">{inside.length}</span>
              </button>
              {open && (
                <div className="ml-3 border-l border-border/60 pl-1">
                  {inside.map((s) => (
                    <SessionRow
                      key={s.id}
                      session={s}
                      active={!!activeId && s.id === activeId}
                      running={running.has(s.id)}
                      onSelect={onSelect}
                      onContext={openSessionMenu}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {ungrouped.length > 0 && groups.length > 0 ? (
          <div className="px-2 mt-2 mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
            {t.ungrouped}
          </div>
        ) : null}
        {ungrouped.map((s) => (
          <SessionRow
            key={s.id}
            session={s}
            active={!!activeId && s.id === activeId}
            running={running.has(s.id)}
            onSelect={onSelect}
            onContext={openSessionMenu}
          />
        ))}
      </div>

      {menu && menu.kind === "session" && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={buildSessionMenu(menu.id)}
          onClose={() => setMenu(null)}
        />
      )}
      {menu && menu.kind === "group" && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={buildGroupMenu(menu.id)}
          onClose={() => setMenu(null)}
        />
      )}
    </aside>
  );
}

function SessionRow({
  session,
  active,
  running,
  onSelect,
  onContext,
}: {
  session: SessionRecord;
  active: boolean;
  running?: boolean;
  onSelect: (id: string) => void;
  onContext: (e: React.MouseEvent, id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(session.id)}
      onContextMenu={(e) => onContext(e, session.id)}
      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left text-sm transition-all duration-150 ease-macos active:scale-[0.99] ${
        active
          ? "bg-accent/15 text-fg"
          : "text-fg-muted hover:bg-bg-elevated hover:text-fg"
      }`}
      title={session.name}
    >
      <MessageSquare size={13} className={`shrink-0 ${active ? "text-accent" : "opacity-70"}`} />
      <span className="truncate flex-1">{session.name}</span>
      {running ? <span className="session-running-indicator" aria-hidden /> : null}
    </button>
  );
}
