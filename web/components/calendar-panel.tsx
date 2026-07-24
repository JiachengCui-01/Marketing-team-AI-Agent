"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Calendar, Clock, MapPin, Users, Loader2, RefreshCw } from "lucide-react";
import { listCalendar, type CalendarEvent } from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

function fmtRange(start: number, end: number | null): string {
  const s = new Date(start * 1000);
  const day = s.toLocaleDateString(undefined, { month: "long", day: "numeric", weekday: "short" });
  const st = s.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (!end) return `${day} ${st}`;
  const et = new Date(end * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `${day} ${st} – ${et}`;
}

export function CalendarPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [rows, setRows] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await listCalendar(true));
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 ml-1">
          <Calendar size={15} className="text-accent" />
          <span className="text-sm font-medium">{t.calendar}</span>
        </div>
        <button onClick={load} className="btn-ghost w-8 h-8 ml-auto" aria-label="刷新">
          <RefreshCw size={14} />
        </button>
      </header>

      <div className="px-3 pt-3 text-xs text-fg-subtle">即将到来的日程</div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading ? (
          <div className="flex justify-center py-10 text-fg-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : error ? (
          <p className="text-sm text-danger px-1">{error}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-fg-subtle text-center py-10">近期没有日程，试试用 Copilot 说“约个明天下午的会”。</p>
        ) : (
          rows.map((ev) => (
            <div key={ev.id} className="border border-border rounded-xl p-3 bg-bg-subtle">
              <div className="text-sm font-medium text-fg">{ev.title}</div>
              <div className="text-[13px] text-fg-muted mt-1.5 space-y-1">
                <div className="flex items-center gap-1.5">
                  <Clock size={13} /> {fmtRange(ev.start_at, ev.end_at)}
                </div>
                {ev.location ? (
                  <div className="flex items-center gap-1.5">
                    <MapPin size={13} /> {ev.location}
                  </div>
                ) : null}
                {ev.attendees.length ? (
                  <div className="flex items-center gap-1.5">
                    <Users size={13} /> {ev.attendees.join("、")}
                  </div>
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
