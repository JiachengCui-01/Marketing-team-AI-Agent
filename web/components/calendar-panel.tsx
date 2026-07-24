"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Calendar, Clock, MapPin, Users, Loader2, RefreshCw, Plus, X } from "lucide-react";
import { createEvent, listCalendar, type CalendarEvent } from "@/lib/api";
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
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ title: "", start: "", end: "", location: "" });

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

  const submit = useCallback(async () => {
    if (!form.title.trim() || !form.start) return;
    setSaving(true);
    setError(null);
    try {
      await createEvent({
        title: form.title.trim(),
        start: form.start,
        end: form.end || undefined,
        location: form.location.trim() || undefined,
      });
      setForm({ title: "", start: "", end: "", location: "" });
      setFormOpen(false);
      await load();
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setSaving(false);
    }
  }, [form, load, locale]);

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
        <button
          onClick={() => setFormOpen((v) => !v)}
          className="btn-accent h-8 px-3 text-sm ml-auto"
        >
          <Plus size={14} />
          新建
        </button>
        <button onClick={load} className="btn-ghost w-8 h-8" aria-label="刷新">
          <RefreshCw size={14} />
        </button>
      </header>

      {formOpen ? (
        <div className="mx-3 mt-3 rounded-xl border border-border bg-bg-subtle p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">新建日程</span>
            <button onClick={() => setFormOpen(false)} className="btn-ghost w-7 h-7" aria-label="关闭">
              <X size={14} />
            </button>
          </div>
          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="标题，例如：团队周会"
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
          <div className="flex gap-2">
            <label className="flex-1 text-[11px] text-fg-muted">
              开始
              <input
                type="datetime-local"
                value={form.start}
                onChange={(e) => setForm((f) => ({ ...f, start: e.target.value }))}
                className="w-full h-9 px-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
              />
            </label>
            <label className="flex-1 text-[11px] text-fg-muted">
              结束（可选）
              <input
                type="datetime-local"
                value={form.end}
                onChange={(e) => setForm((f) => ({ ...f, end: e.target.value }))}
                className="w-full h-9 px-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
              />
            </label>
          </div>
          <input
            value={form.location}
            onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
            placeholder="地点（可选）"
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
          <div className="flex justify-end">
            <button
              onClick={submit}
              disabled={saving || !form.title.trim() || !form.start}
              className="btn-accent h-8 px-4 text-sm disabled:opacity-50"
            >
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              创建
            </button>
          </div>
        </div>
      ) : null}

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
