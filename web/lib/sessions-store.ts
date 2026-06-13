"use client";

import { useEffect, useState, useCallback } from "react";
import {
  listSessions,
  listGroups,
  createSession as apiCreateSession,
  updateSession as apiUpdateSession,
  deleteSession as apiDeleteSession,
  createGroup as apiCreateGroup,
  renameGroup as apiRenameGroup,
  deleteGroup as apiDeleteGroup,
  type SessionRecord,
  type GroupRecord,
} from "./api";

export function useSessionsStore() {
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [groups, setGroups] = useState<GroupRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [s, g] = await Promise.all([listSessions(), listGroups()]);
      setSessions(s);
      setGroups(g);
    } catch (err) {
      console.error("sessions refresh failed", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const createSession = useCallback(
    async (opts: { name?: string; group_id?: string | null } = {}) => {
      const rec = await apiCreateSession(opts);
      await refresh();
      return rec.session_id;
    },
    [refresh],
  );

  const renameSession = useCallback(
    async (id: string, name: string) => {
      await apiUpdateSession(id, { name });
      await refresh();
    },
    [refresh],
  );

  const moveSession = useCallback(
    async (id: string, group_id: string | null) => {
      await apiUpdateSession(id, { group_id });
      await refresh();
    },
    [refresh],
  );

  const deleteSession = useCallback(
    async (id: string) => {
      await apiDeleteSession(id);
      await refresh();
    },
    [refresh],
  );

  const createGroup = useCallback(
    async (name: string) => {
      const rec = await apiCreateGroup(name);
      await refresh();
      return rec.id;
    },
    [refresh],
  );

  const renameGroup = useCallback(
    async (id: string, name: string) => {
      await apiRenameGroup(id, name);
      await refresh();
    },
    [refresh],
  );

  const deleteGroup = useCallback(
    async (id: string) => {
      await apiDeleteGroup(id);
      await refresh();
    },
    [refresh],
  );

  // Touch session updated_at locally by re-fetching (called after a turn completes).
  const touch = useCallback(async () => {
    refresh();
  }, [refresh]);

  return {
    sessions,
    groups,
    loading,
    refresh,
    touch,
    createSession,
    renameSession,
    moveSession,
    deleteSession,
    createGroup,
    renameGroup,
    deleteGroup,
  };
}
