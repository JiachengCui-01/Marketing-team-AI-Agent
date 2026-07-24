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
      setEvents(await listCalendar());
    } catch {
      /* silent — header widget must never surface errors */
    }
  }, []);

  useEffect(() => {
    load();
    // Refresh immediately when the calendar changes (AI or manual add/edit/delete),
    // so the summary never lags behind. A slow poll is only a safety net.
    const onChanged = () => load();
    const onFocus = () => load();
    window.addEventListener("oa-calendar-changed", onChanged);
    window.addEventListener("focus", onFocus);
    const id = window.setInterval(load, 120_000);
    return () => {
      window.removeEventListener("oa-calendar-changed", onChanged);
      window.removeEventListener("focus", onFocus);
      window.clearInterval(id);
    };
  }, [load]);

  const zh = locale === "zh";
  const nowSec = Date.now() / 1000;
  const activeEvents = events.filter((e) => e.status !== "done");
  const todayCount = activeEvents.filter((e) => isToday(e.start_at)).length;
  // The nearest task that has not started yet.
  const next = activeEvents.filter((e) => e.start_at > nowSec).sort((a, b) => a.start_at - b.start_at)[0];

  const countText = zh ? `今日 ${todayCount} 项` : `${todayCount} today`;
  let summary: string;
  if (!next) {
    summary = zh ? `${countText} · 暂无待开始` : `${countText} · none upcoming`;
  } else {
    const time = new Date(next.start_at * 1000).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
    const title = next.title.length > 10 ? next.title.slice(0, 10) + "…" : next.title;
    summary = `${countText} · ${time} ${title}`;
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
