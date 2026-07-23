"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  MessageCircle,
  Paperclip,
  Send,
  UsersRound,
  Loader2,
  FileText,
  Download,
} from "lucide-react";
import {
  conversationFileDownloadUrl,
  listOrgMembers,
  type OrgMember,
  type Conversation,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import type { I18nText } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import type { ClientImMessage, ImStore } from "@/lib/im-store";

function initial(name: string | null | undefined): string {
  const s = (name || "").trim();
  return s ? s[0].toUpperCase() : "?";
}

function conversationName(c: Conversation): string {
  if (c.type === "group") return c.title || "群聊";
  return c.peer?.username || c.peer?.real_name || "对话";
}

type FileMeta = { file_id?: string; name?: string; size?: number; mime?: string; ext?: string };

function parseFileMeta(content: string): FileMeta {
  try {
    return JSON.parse(content) as FileMeta;
  } catch {
    return {};
  }
}

function formatBytes(n?: number): string {
  if (!n || n <= 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function lastPreview(c: Conversation, t: I18nText): string {
  const m = c.last_message;
  if (!m) return "";
  if (m.kind === "file") {
    const meta = parseFileMeta(m.content);
    return `${t.fileLabel} ${meta.name ?? ""}`.trim();
  }
  return m.content;
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
                {c.type === "direct" && c.peer?.avatar ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={c.peer.avatar}
                    alt=""
                    className="w-9 h-9 rounded-full object-cover shrink-0"
                  />
                ) : (
                  <span className="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center text-sm font-medium shrink-0">
                    {c.type === "group" ? <UsersRound size={16} /> : initial(conversationName(c))}
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium flex-1">{conversationName(c)}</span>
                    {c.last_message ? (
                      <span className="text-[10px] text-fg-subtle shrink-0">
                        {formatTime(c.last_message.created_at)}
                      </span>
                    ) : null}
                  </span>
                  <span className="block truncate text-xs text-fg-subtle">{lastPreview(c, t)}</span>
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

function statusLabel(
  m: ClientImMessage,
  isGroup: boolean,
  peerReadAt: number | null,
  t: I18nText,
): string {
  if (m._status === "sending") return t.msgSending;
  if (m._status === "failed") return t.msgFailed;
  if (!isGroup && peerReadAt != null && peerReadAt >= m.created_at) return t.msgRead;
  return t.msgDelivered;
}

function FileBubble({
  msg,
  conversationId,
  mine,
}: {
  msg: ClientImMessage;
  conversationId: string;
  mine: boolean;
}) {
  const meta = parseFileMeta(msg.content);
  const uploading = msg._status === "sending" || !meta.file_id;
  const url = meta.file_id ? conversationFileDownloadUrl(conversationId, meta.file_id) : null;
  const isImage = (meta.mime || "").startsWith("image/");

  if (isImage && url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <a href={url} target="_blank" rel="noreferrer" className="block">
        <img
          src={url}
          alt={meta.name || ""}
          className="max-w-[220px] max-h-[220px] rounded-xl object-cover"
        />
      </a>
    );
  }

  const inner = (
    <div
      className={`flex items-center gap-2.5 rounded-xl px-3 py-2 ${
        mine ? "bg-accent text-accent-fg" : "bg-bg-elevated text-fg"
      }`}
    >
      <span
        className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
          mine ? "bg-white/20" : "bg-bg-subtle"
        }`}
      >
        {uploading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
      </span>
      <span className="min-w-0">
        <span className="block truncate max-w-[160px] text-sm">{meta.name || "文件"}</span>
        {meta.size ? (
          <span className={`block text-[10px] ${mine ? "text-accent-fg/80" : "text-fg-subtle"}`}>
            {formatBytes(meta.size)}
          </span>
        ) : null}
      </span>
      {url ? <Download size={14} className={mine ? "text-accent-fg/80" : "text-fg-subtle"} /> : null}
    </div>
  );

  return url ? (
    <a href={url} target="_blank" rel="noreferrer" className="block">
      {inner}
    </a>
  ) : (
    inner
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
  const fileRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const messages = im.activeMessages;
  const isGroup = conversation.type === "group";
  const peerReadAt = im.activePeerReadAt;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Sending is optimistic and never blocks the composer — the message appears
  // immediately with a "sending" tag and reconciles when the server confirms.
  function submit() {
    const value = text.trim();
    if (!value) return;
    setText("");
    void im.send(value);
  }

  function pickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) void im.sendFile(f);
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
              <div className={`max-w-[70%] flex flex-col ${mine ? "items-end" : "items-start"}`}>
                {isGroup && !mine && m.sender_name ? (
                  <div className="mb-0.5 text-[11px] text-fg-subtle">{m.sender_name}</div>
                ) : null}
                {m.kind === "file" ? (
                  <FileBubble msg={m} conversationId={conversation.id} mine={mine} />
                ) : (
                  <div
                    className={`rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words ${
                      mine ? "bg-accent text-accent-fg" : "bg-bg-elevated text-fg"
                    }`}
                  >
                    {m.content}
                  </div>
                )}
                {mine ? (
                  <div
                    className={`mt-0.5 text-[10px] ${
                      m._status === "failed" ? "text-danger" : "text-fg-subtle"
                    }`}
                  >
                    {statusLabel(m, isGroup, peerReadAt, t)}
                  </div>
                ) : null}
              </div>
              {mine ? <MsgAvatar name={senderName} avatar={senderAvatar} /> : null}
            </div>
          );
        })}
      </div>

      <div className="border-t border-border p-2.5">
        <div className="flex items-end gap-2">
          <input ref={fileRef} type="file" className="hidden" onChange={pickFile} />
          <button
            onClick={() => fileRef.current?.click()}
            className="btn-ghost w-9 h-9 shrink-0"
            title={t.attachFile}
            aria-label={t.attachFile}
          >
            <Paperclip size={16} />
          </button>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            placeholder={t.messageInputPlaceholder}
            className="flex-1 resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent max-h-32"
          />
          <button
            onClick={submit}
            disabled={!text.trim()}
            className="btn-accent w-9 h-9 shrink-0"
            aria-label={t.send}
          >
            <Send size={15} />
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
