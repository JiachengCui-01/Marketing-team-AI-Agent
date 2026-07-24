"use client";

import type { OaDraft } from "@/lib/api";

// Persists AI draft cards (and their confirmed state) per session in localStorage so
// they survive page reloads / restarts, not just in-memory view switches.
const KEY = "oa-drafts-v1";
const MAX_PER_SESSION = 40;

type DraftStatus = { status: "submitted" | "error" | "cancelled"; note: string };
type Store = { drafts: Record<string, OaDraft[]>; status: Record<string, DraftStatus> };

function read(): Store {
  if (typeof window === "undefined") return { drafts: {}, status: {} };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(KEY) || "{}");
    return { drafts: parsed.drafts ?? {}, status: parsed.status ?? {} };
  } catch {
    return { drafts: {}, status: {} };
  }
}

function write(s: Store): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* quota / disabled storage — non-fatal */
  }
}

export function appendDraft(sessionId: string, draft: OaDraft): void {
  if (!sessionId) return;
  const s = read();
  const list = s.drafts[sessionId] ?? [];
  list.push(draft);
  s.drafts[sessionId] = list.slice(-MAX_PER_SESSION);
  write(s);
}

export function listDrafts(sessionId: string): OaDraft[] {
  return read().drafts[sessionId] ?? [];
}

export function getDraftStatus(id: string): DraftStatus | undefined {
  return read().status[id];
}

export function setDraftStatus(id: string, status: DraftStatus): void {
  const s = read();
  s.status[id] = status;
  write(s);
}
