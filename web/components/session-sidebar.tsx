"use client";

import { useMemo, useState } from "react";
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
} from "lucide-react";
import { ContextMenu, type MenuItem } from "./context-menu";
import type { GroupRecord, SessionRecord } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type MenuState =
  | { kind: "session"; id: string; x: number; y: number }
  | { kind: "group"; id: string; x: number; y: number }
  | null;

export function SessionSidebar({
  sessions,
  groups,
  activeId,
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
  onOpenNews,
}: {
  sessions: SessionRecord[];
  groups: GroupRecord[];
  activeId: string | null;
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
  onOpenNews: () => void;
}) {
  const { t } = useI18n();
  const [menu, setMenu] = useState<MenuState>(null);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

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
      <aside className="hidden md:flex flex-col items-center w-12 shrink-0 border-r border-border bg-bg-subtle/40 py-2 gap-1">
        <button
          onClick={onToggle}
          className="w-9 h-9 inline-flex items-center justify-center rounded-md hover:bg-bg-elevated text-fg-muted"
          aria-label={t.expandSidebar}
          title={t.expandSidebar}
        >
          <PanelLeft size={16} />
        </button>
        <button
          onClick={onNewChat}
          className="w-9 h-9 inline-flex items-center justify-center rounded-md bg-accent text-accent-fg hover:opacity-90"
          aria-label={t.newChat}
          title={t.newChat}
        >
          <Plus size={16} />
        </button>
        <button
          onClick={onOpenNews}
          className="w-9 h-9 inline-flex items-center justify-center rounded-md hover:bg-bg-elevated text-fg-muted"
          aria-label={t.industryNews}
          title={t.industryNews}
        >
          <Newspaper size={16} />
        </button>
      </aside>
    );
  }

  function openSessionMenu(e: React.MouseEvent, id: string) {
    e.preventDefault();
    setMenu({ kind: "session", id, x: e.clientX, y: e.clientY });
  }
  function openGroupMenu(e: React.MouseEvent, id: string) {
    e.preventDefault();
    setMenu({ kind: "group", id, x: e.clientX, y: e.clientY });
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
      className="hidden md:flex flex-col shrink-0 border-r border-border bg-bg-subtle/40"
      style={{ width: width ?? 256 }}
    >
      <div className="p-2 border-b border-border flex items-center gap-1">
        <button
          onClick={onNewChat}
          className="flex-1 inline-flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-accent text-accent-fg text-sm font-medium hover:opacity-90 transition"
        >
          <Plus size={14} />
          <span>{t.newChat}</span>
        </button>
        <button
          onClick={async () => {
            const name = window.prompt(t.groupNamePrompt);
            if (name && name.trim()) await onCreateGroup(name.trim());
          }}
          className="w-9 h-9 inline-flex items-center justify-center rounded-md border border-border hover:bg-bg-elevated text-fg-muted"
          title={t.newGroup}
          aria-label={t.newGroup}
        >
          <FolderPlus size={14} />
        </button>
        <button
          onClick={onToggle}
          className="w-9 h-9 inline-flex items-center justify-center rounded-md hover:bg-bg-elevated text-fg-muted"
          title={t.collapseSidebar}
          aria-label={t.collapseSidebar}
        >
          <PanelLeftClose size={14} />
        </button>
      </div>

      <div className="px-1.5 pt-2">
        <button
          onClick={onOpenNews}
          className="w-full flex items-center gap-2 px-2.5 py-2 rounded-md hover:bg-bg-elevated text-fg-muted hover:text-fg text-sm font-medium transition"
        >
          <Newspaper size={15} className="text-accent shrink-0" />
          <span className="truncate">{t.industryNews}</span>
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
                      active={s.id === activeId}
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
            active={s.id === activeId}
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
  onSelect,
  onContext,
}: {
  session: SessionRecord;
  active: boolean;
  onSelect: (id: string) => void;
  onContext: (e: React.MouseEvent, id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(session.id)}
      onContextMenu={(e) => onContext(e, session.id)}
      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-sm transition ${
        active
          ? "bg-accent/15 text-fg"
          : "text-fg-muted hover:bg-bg-elevated hover:text-fg"
      }`}
      title={session.name}
    >
      <MessageSquare size={13} className="shrink-0 opacity-70" />
      <span className="truncate flex-1">{session.name}</span>
    </button>
  );
}
