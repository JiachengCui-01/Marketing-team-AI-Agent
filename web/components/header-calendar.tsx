"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarDays, ChevronRight } from "lucide-react";
import { listCalendar, type CalendarEvent } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function isToday(ts: number): boolean {
  const d = new Date(ts * 1000);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

/** Compact schedule summary shown in the center of the top bar; doubles as the calendar
 * entry. Uses only theme tokens so it blends into every theme without standing out. */
export function HeaderCalendar({ onOpen }: { onOpen: () => void }) {
  const { locale } = useI18n();
  const [events, setEvents] = useState<CalendarEvent[]>([]);

  const load = useCallback(async () => {
    try {
      setEvents(await listCalendar(true));
    } catch {
      /* silent — header widget must never surface errors */
    }
  }, []);

  useEffect(() => {
    load();
    // Light polling keeps the summary fresh after the AI or manual add.
    const id = window.setInterval(load, 60_000);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  const zh = locale === "zh";
  const next = events[0];
  const todayCount = events.filter((e) => isToday(e.start_at)).length;

  let summary: string;
  if (!next) {
    summary = zh ? "今日暂无日程" : "No events today";
  } else {
    const time = new Date(next.start_at * 1000).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
    const title = next.title.length > 10 ? next.title.slice(0, 10) + "…" : next.title;
    const count = todayCount || events.length;
    summary = zh
      ? `今日 ${count} 项 · ${time} ${title}`
      : `${count} today · ${time} ${title}`;
  }

  return (
    <button
      onClick={onOpen}
      title={zh ? "查看日程" : "Open calendar"}
      className="group inline-flex items-center gap-2 rounded-full border border-border bg-bg-elevated/70 px-3 py-1.5 text-xs text-fg-muted hover:text-fg hover:border-accent/40 transition-colors max-w-[340px]"
    >
      <CalendarDays size={13} className="text-accent shrink-0" />
      <span className="truncate">{summary}</span>
      <ChevronRight size={12} className="shrink-0 opacity-50 group-hover:opacity-100 transition-opacity" />
    </button>
  );
}
