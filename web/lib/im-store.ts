"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createConversation,
  getAuthToken,
  getConversationMessages,
  imStreamUrl,
  listConversations,
  markConversationRead,
  sendConversationFile,
  sendConversationMessage,
  uploadFile,
  type Conversation,
  type ImMessage,
} from "./api";
import { openEventStream } from "./sse";

const RECONNECT_DELAY_MS = 2000;

// Client-side send lifecycle overlaid on the server message: `_status` is only
// present while a message is optimistic (before the server confirms it).
export type ClientImMessage = ImMessage & { _status?: "sending" | "failed" };

type MsgMap = Record<string, ClientImMessage[]>;

function tempId(): string {
  return `tmp-${(globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`)}`;
}

// Replace the matching optimistic message (by temp id, or the first pending one
// with identical sender+content for SSE echoes) with the confirmed server copy,
// de-duplicating by real id.
function mergeReal(map: MsgMap, cid: string, msg: ImMessage, temp?: string): MsgMap {
  const arr = map[cid];
  if (!arr) return map;
  let filtered: ClientImMessage[];
  if (temp) {
    filtered = arr.filter((x) => x.id !== temp);
  } else {
    const idx = arr.findIndex(
      (x) => x._status === "sending" && x.sender_id === msg.sender_id && x.content === msg.content,
    );
    filtered = idx === -1 ? arr : [...arr.slice(0, idx), ...arr.slice(idx + 1)];
  }
  if (filtered.some((x) => x.id === msg.id)) return { ...map, [cid]: filtered };
  return { ...map, [cid]: [...filtered, msg] };
}

// Owns a single user-level SSE connection to /api/im/stream (with auto-reconnect)
// and the client-side IM state: conversation list, per-conversation message
// history, active conversation, and total unread count for the sidebar badge.
export function useImStore(userId: string | null) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messagesByConv, setMessagesByConv] = useState<MsgMap>({});
  const [activeId, setActiveIdState] = useState<string | null>(null);
  // Per-conversation timestamp up to which the other side has read (direct chats).
  const [peerReadByConv, setPeerReadByConv] = useState<Record<string, number>>({});
  const activeRef = useRef<string | null>(null);
  const knownIdsRef = useRef<Set<string>>(new Set());

  const setActiveId = useCallback((id: string | null) => {
    activeRef.current = id;
    setActiveIdState(id);
  }, []);

  const refresh = useCallback(async () => {
    if (!getAuthToken()) return;
    try {
      const convs = await listConversations();
      setConversations(convs);
      setPeerReadByConv((prev) => {
        const next = { ...prev };
        for (const c of convs) {
          const at = c.peer_last_read_at;
          if (at != null) next[c.id] = Math.max(next[c.id] ?? 0, at);
        }
        return next;
      });
    } catch (err) {
      console.error("conversations refresh failed", err);
    }
  }, []);

  const loadMessages = useCallback(async (id: string) => {
    try {
      const msgs = await getConversationMessages(id, { limit: 100 });
      setMessagesByConv((m) => ({ ...m, [id]: msgs }));
    } catch (err) {
      console.error("load messages failed", err);
    }
  }, []);

  const markRead = useCallback(async (id: string) => {
    setConversations((cs) => cs.map((c) => (c.id === id ? { ...c, unread: 0 } : c)));
    try {
      await markConversationRead(id);
    } catch {
      /* best-effort */
    }
  }, []);

  const openConversation = useCallback(
    async (id: string) => {
      setActiveId(id);
      await loadMessages(id);
      await markRead(id);
    },
    [loadMessages, markRead, setActiveId],
  );

  const openDirect = useCallback(
    async (peerId: string) => {
      const conv = await createConversation({ type: "direct", peer_id: peerId });
      await refresh();
      await openConversation(conv.id);
      return conv.id;
    },
    [refresh, openConversation],
  );

  const createGroup = useCallback(
    async (title: string, memberIds: string[]) => {
      const conv = await createConversation({ type: "group", title, member_ids: memberIds });
      await refresh();
      await openConversation(conv.id);
      return conv.id;
    },
    [refresh, openConversation],
  );

  // Append an optimistic message immediately, then reconcile with the server
  // copy on success (or flag it failed) — the send never blocks the composer.
  const runOptimistic = useCallback(
    async (id: string, optimistic: ClientImMessage, doSend: () => Promise<ImMessage>) => {
      const temp = optimistic.id;
      setMessagesByConv((m) => ({ ...m, [id]: [...(m[id] ?? []), optimistic] }));
      try {
        const msg = await doSend();
        setMessagesByConv((m) => mergeReal(m, id, msg, temp));
        void refresh();
      } catch (err) {
        console.error("send failed", err);
        setMessagesByConv((m) => {
          const arr = m[id];
          if (!arr) return m;
          return { ...m, [id]: arr.map((x) => (x.id === temp ? { ...x, _status: "failed" } : x)) };
        });
      }
    },
    [refresh],
  );

  const send = useCallback(
    async (content: string) => {
      const id = activeRef.current;
      const text = content.trim();
      if (!id || !text || !userId) return;
      const optimistic: ClientImMessage = {
        id: tempId(),
        conversation_id: id,
        sender_id: userId,
        kind: "text",
        content: text,
        created_at: Date.now() / 1000,
        _status: "sending",
      };
      await runOptimistic(id, optimistic, () => sendConversationMessage(id, text));
    },
    [runOptimistic, userId],
  );

  const sendFile = useCallback(
    async (file: File) => {
      const id = activeRef.current;
      if (!id || !userId) return;
      const optimistic: ClientImMessage = {
        id: tempId(),
        conversation_id: id,
        sender_id: userId,
        kind: "file",
        content: JSON.stringify({ name: file.name, size: file.size, mime: file.type }),
        created_at: Date.now() / 1000,
        _status: "sending",
      };
      await runOptimistic(id, optimistic, async () => {
        const up = await uploadFile(file);
        return sendConversationFile(id, up);
      });
    },
    [runOptimistic, userId],
  );

  const applyIncoming = useCallback(
    (msg: ImMessage) => {
      const cid = msg.conversation_id;
      const isActive = activeRef.current === cid;
      const mine = msg.sender_id === userId;

      // Only merge into a history we already hold; unopened threads hydrate on
      // open. For my own echo this also clears the matching optimistic copy.
      setMessagesByConv((m) => mergeReal(m, cid, msg));

      // Unknown conversation (e.g. a brand-new thread): hydrate the whole list
      // outside the reducer to keep this updater pure.
      if (!knownIdsRef.current.has(cid)) {
        void refresh();
        if (isActive && !mine) void markConversationRead(cid);
        return;
      }

      setConversations((cs) => {
        const idx = cs.findIndex((c) => c.id === cid);
        if (idx === -1) return cs;
        const conv = cs[idx];
        const updated: Conversation = {
          ...conv,
          last_message: {
            sender_id: msg.sender_id,
            kind: msg.kind,
            content: msg.content,
            created_at: msg.created_at,
          },
          updated_at: msg.created_at,
          unread: isActive || mine ? conv.unread : conv.unread + 1,
        };
        const next = [...cs];
        next.splice(idx, 1);
        return [updated, ...next];
      });

      if (isActive && !mine) void markConversationRead(cid);
    },
    [refresh, userId],
  );

  const applyRead = useCallback((cid: string, lastReadAt: number) => {
    setPeerReadByConv((prev) => ({ ...prev, [cid]: Math.max(prev[cid] ?? 0, lastReadAt) }));
  }, []);

  useEffect(() => {
    if (!userId || !getAuthToken()) return;
    let closed = false;
    let close: (() => void) | null = null;
    let retry: number | null = null;

    const scheduleReconnect = () => {
      if (closed || retry != null) return;
      retry = window.setTimeout(() => {
        retry = null;
        connect();
      }, RECONNECT_DELAY_MS);
    };

    const connect = () => {
      if (closed) return;
      close = openEventStream(
        imStreamUrl(),
        (e) => {
          if (e.event === "im_message") applyIncoming(e.payload as unknown as ImMessage);
          else if (e.event === "conversation_updated") void refresh();
          else if (e.event === "conversation_read") {
            const p = e.payload as unknown as { conversation_id: string; last_read_at: number };
            applyRead(p.conversation_id, p.last_read_at);
          }
        },
        () => {
          if (!closed) scheduleReconnect();
        },
        () => {
          if (!closed) scheduleReconnect();
        },
      );
    };

    void refresh();
    connect();

    return () => {
      closed = true;
      if (close) close();
      if (retry != null) window.clearTimeout(retry);
    };
  }, [userId, applyIncoming, applyRead, refresh]);

  useEffect(() => {
    knownIdsRef.current = new Set(conversations.map((c) => c.id));
  }, [conversations]);

  const unreadTotal = conversations.reduce((n, c) => n + (c.unread || 0), 0);
  const activeMessages = activeId ? messagesByConv[activeId] ?? [] : [];
  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;

  const activePeerReadAt = activeId ? peerReadByConv[activeId] ?? null : null;

  return {
    conversations,
    activeId,
    activeConversation,
    activeMessages,
    activePeerReadAt,
    unreadTotal,
    refresh,
    openConversation,
    openDirect,
    createGroup,
    send,
    sendFile,
    setActiveId,
  };
}

export type ImStore = ReturnType<typeof useImStore>;
