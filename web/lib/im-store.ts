"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createConversation,
  getAuthToken,
  getConversationMessages,
  imStreamUrl,
  listConversations,
  markConversationRead,
  sendConversationMessage,
  type Conversation,
  type ImMessage,
} from "./api";
import { openEventStream } from "./sse";

const RECONNECT_DELAY_MS = 2000;

// Owns a single user-level SSE connection to /api/im/stream (with auto-reconnect)
// and the client-side IM state: conversation list, per-conversation message
// history, active conversation, and total unread count for the sidebar badge.
export function useImStore(userId: string | null) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messagesByConv, setMessagesByConv] = useState<Record<string, ImMessage[]>>({});
  const [activeId, setActiveIdState] = useState<string | null>(null);
  const activeRef = useRef<string | null>(null);
  const knownIdsRef = useRef<Set<string>>(new Set());

  const setActiveId = useCallback((id: string | null) => {
    activeRef.current = id;
    setActiveIdState(id);
  }, []);

  const refresh = useCallback(async () => {
    if (!getAuthToken()) return;
    try {
      setConversations(await listConversations());
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

  const send = useCallback(
    async (content: string) => {
      const id = activeRef.current;
      const text = content.trim();
      if (!id || !text) return;
      const msg = await sendConversationMessage(id, text);
      setMessagesByConv((m) => {
        const cur = m[id] ?? [];
        if (cur.some((x) => x.id === msg.id)) return m;
        return { ...m, [id]: [...cur, msg] };
      });
      await refresh();
    },
    [refresh],
  );

  const applyIncoming = useCallback(
    (msg: ImMessage) => {
      const cid = msg.conversation_id;
      const isActive = activeRef.current === cid;
      const mine = msg.sender_id === userId;

      setMessagesByConv((m) => {
        // Only merge into a history we already hold; unopened threads hydrate on open.
        if (!m[cid]) return m;
        if (m[cid].some((x) => x.id === msg.id)) return m;
        return { ...m, [cid]: [...m[cid], msg] };
      });

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
  }, [userId, applyIncoming, refresh]);

  useEffect(() => {
    knownIdsRef.current = new Set(conversations.map((c) => c.id));
  }, [conversations]);

  const unreadTotal = conversations.reduce((n, c) => n + (c.unread || 0), 0);
  const activeMessages = activeId ? messagesByConv[activeId] ?? [] : [];
  const activeConversation = conversations.find((c) => c.id === activeId) ?? null;

  return {
    conversations,
    activeId,
    activeConversation,
    activeMessages,
    unreadTotal,
    refresh,
    openConversation,
    openDirect,
    createGroup,
    send,
    setActiveId,
  };
}

export type ImStore = ReturnType<typeof useImStore>;
