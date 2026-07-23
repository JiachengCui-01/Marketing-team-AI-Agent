"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, MessageCircle, Send, UsersRound, Loader2 } from "lucide-react";
import { listOrgMembers, type OrgMember, type Conversation } from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import type { ImStore } from "@/lib/im-store";

function initial(name: string | null | undefined): string {
  const s = (name || "").trim();
  return s ? s[0].toUpperCase() : "?";
}

function conversationName(c: Conversation): string {
  if (c.type === "group") return c.title || "群聊";
  return c.peer?.username || c.peer?.real_name || "对话";
}

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "numeric", day: "numeric" });
}

export function MessagesPanel({
  onBack,
  halfWidth,
  im,
  meId,
  meName,
  meAvatar,
}: {
  onBack: () => void;
  halfWidth: number;
  im: ImStore;
  meId: string;
  meName: string;
  meAvatar: string | null;
}) {
  const { t } = useI18n();
  const [groupOpen, setGroupOpen] = useState(false);
  const active = im.activeConversation;

  return (
    <>
      <aside className="flex-1 min-w-0 flex flex-col panel-card">
        <header className="col-header">
          <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
            <ArrowLeft size={15} />
            <span>{t.back}</span>
          </button>
          <div className="flex items-center gap-2 mx-auto text-sm font-medium">
            <MessageCircle size={15} className="text-feature-news" />
            <span>{t.messages}</span>
          </div>
          <button
            onClick={() => setGroupOpen(true)}
            className="btn-ghost w-8 h-8"
            title={t.newGroupChat}
            aria-label={t.newGroupChat}
          >
            <UsersRound size={15} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-1.5">
          {im.conversations.length === 0 ? (
            <p className="px-3 py-10 text-center text-sm text-fg-subtle">{t.noConversations}</p>
          ) : (
            im.conversations.map((c) => (
              <button
                key={c.id}
                onClick={() => void im.openConversation(c.id)}
                className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left transition-colors ${
                  c.id === im.activeId ? "bg-accent/15" : "hover:bg-bg-elevated"
                }`}
              >
                <span className="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center text-sm font-medium shrink-0">
                  {c.type === "group" ? <UsersRound size={16} /> : initial(conversationName(c))}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium flex-1">{conversationName(c)}</span>
                    {c.last_message ? (
                      <span className="text-[10px] text-fg-subtle shrink-0">
                        {formatTime(c.last_message.created_at)}
                      </span>
                    ) : null}
                  </span>
                  <span className="block truncate text-xs text-fg-subtle">
                    {c.last_message?.content ?? ""}
                  </span>
                </span>
                {c.unread > 0 ? (
                  <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-semibold flex items-center justify-center shrink-0">
                    {c.unread > 99 ? "99+" : c.unread}
                  </span>
                ) : null}
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="shrink-0 flex flex-col panel-card" style={{ width: halfWidth }}>
        {active ? (
          <Thread
            key={active.id}
            conversation={active}
            im={im}
            meId={meId}
            meName={meName}
            meAvatar={meAvatar}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center px-4 text-center text-sm text-fg-subtle">
            {t.selectConversation}
          </div>
        )}
      </section>

      {groupOpen ? (
        <NewGroupDialog
          meId={meId}
          onClose={() => setGroupOpen(false)}
          onCreate={async (title, ids) => {
            await im.createGroup(title, ids);
            setGroupOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function MsgAvatar({ name, avatar }: { name?: string | null; avatar?: string | null }) {
  if (avatar) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={avatar} alt="" className="w-8 h-8 rounded-full object-cover shrink-0" />;
  }
  return (
    <span className="w-8 h-8 rounded-full bg-accent/15 text-accent flex items-center justify-center text-xs font-medium shrink-0">
      {initial(name)}
    </span>
  );
}

function Thread({
  conversation,
  im,
  meId,
  meName,
  meAvatar,
}: {
  conversation: Conversation;
  im: ImStore;
  meId: string;
  meName: string;
  meAvatar: string | null;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const messages = im.activeMessages;
  const isGroup = conversation.type === "group";

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function submit() {
    const value = text.trim();
    if (!value || sending) return;
    setText("");
    setSending(true);
    try {
      await im.send(value);
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <header className="col-header">
        <div className="flex items-center gap-2 text-sm font-medium">
          {isGroup ? <UsersRound size={15} className="text-feature-news" /> : null}
          <span>{conversationName(conversation)}</span>
          {isGroup ? (
            <span className="text-xs text-fg-subtle">({conversation.member_count})</span>
          ) : null}
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">
        {messages.map((m) => {
          const mine = m.sender_id === meId;
          const senderName = mine
            ? meName
            : isGroup
              ? m.sender_name
              : conversation.peer?.username || conversation.peer?.real_name;
          const senderAvatar = mine ? meAvatar : isGroup ? null : conversation.peer?.avatar;
          return (
            <div key={m.id} className={`flex items-end gap-2 ${mine ? "justify-end" : "justify-start"}`}>
              {!mine ? <MsgAvatar name={senderName} avatar={senderAvatar} /> : null}
              <div className="max-w-[70%]">
                {isGroup && !mine && m.sender_name ? (
                  <div className="mb-0.5 text-[11px] text-fg-subtle">{m.sender_name}</div>
                ) : null}
                <div
                  className={`rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words ${
                    mine ? "bg-accent text-accent-fg" : "bg-bg-elevated text-fg"
                  }`}
                >
                  {m.content}
                </div>
              </div>
              {mine ? <MsgAvatar name={senderName} avatar={senderAvatar} /> : null}
            </div>
          );
        })}
      </div>

      <div className="border-t border-border p-2.5">
        <div className="flex items-end gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            rows={1}
            placeholder={t.messageInputPlaceholder}
            className="flex-1 resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent max-h-32"
          />
          <button
            onClick={() => void submit()}
            disabled={!text.trim() || sending}
            className="btn-accent w-9 h-9 shrink-0"
            aria-label={t.send}
          >
            {sending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
          </button>
        </div>
      </div>
    </>
  );
}

function NewGroupDialog({
  meId,
  onClose,
  onCreate,
}: {
  meId: string;
  onClose: () => void;
  onCreate: (title: string, memberIds: string[]) => Promise<void>;
}) {
  const { locale, t } = useI18n();
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listOrgMembers()
      .then((r) => setMembers(r.members.filter((m) => m.id !== meId)))
      .catch((e) => setError(localizeError(e, locale)))
      .finally(() => setLoading(false));
  }, [locale, meId]);

  const canCreate = useMemo(() => title.trim() && selected.size > 0, [title, selected]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit() {
    if (!canCreate || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate(title.trim(), Array.from(selected));
    } catch (e) {
      setError(localizeError(e, locale));
      setBusy(false);
    }
  }

  return (
    <Modal title={t.newGroupChat} onClose={onClose}>
      <div className="space-y-4">
        <label className="block text-xs font-medium text-fg-muted">
          {t.groupChatName}
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
        </label>

        <div className="text-xs font-medium text-fg-muted">{t.groupChatMembers}</div>
        <div className="max-h-56 overflow-y-auto rounded-lg border border-border divide-y divide-border">
          {loading ? (
            <div className="p-4 text-center text-sm text-fg-subtle">…</div>
          ) : members.length === 0 ? (
            <div className="p-4 text-center text-sm text-fg-subtle">{t.noMembers}</div>
          ) : (
            members.map((m) => (
              <label key={m.id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-bg-subtle">
                <input
                  type="checkbox"
                  checked={selected.has(m.id)}
                  onChange={() => toggle(m.id)}
                  className="accent-accent"
                />
                <span className="w-7 h-7 rounded-full bg-accent/15 text-accent flex items-center justify-center text-xs font-medium">
                  {initial(m.username || m.real_name)}
                </span>
                <span className="text-sm text-fg">{m.username || m.real_name}</span>
              </label>
            ))
          )}
        </div>

        {error ? <p className="text-[11px] text-danger">{error}</p> : null}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle"
          >
            {t.cancel}
          </button>
          <button onClick={() => void submit()} disabled={!canCreate || busy} className="btn-accent px-4 py-2 text-sm">
            {busy ? <Loader2 size={14} className="animate-spin" /> : null}
            {t.newGroupChat}
          </button>
        </div>
      </div>
    </Modal>
  );
}
