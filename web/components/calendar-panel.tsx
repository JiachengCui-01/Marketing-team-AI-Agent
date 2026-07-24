"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Calendar,
  Clock,
  MapPin,
  Users,
  Loader2,
  RefreshCw,
  Plus,
  X,
  Check,
  Pencil,
  Trash2,
  RotateCcw,
} from "lucide-react";
import {
  createEvent,
  deleteEvent,
  listCalendar,
  updateEvent,
  type CalendarEvent,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { DateTimeWheel } from "./datetime-wheel";

function notifyCalendarChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("oa-calendar-changed"));
}

function dayKey(ts: number): string {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dayLabel(ts: number, zh: boolean): string {
  const d = new Date(ts * 1000);
  const t = new Date();
  const key = dayKey(ts);
  if (key === `${t.getFullYear()}-${t.getMonth()}-${t.getDate()}`) return zh ? "今天" : "Today";
  const tm = new Date(t);
  tm.setDate(tm.getDate() + 1);
  if (key === `${tm.getFullYear()}-${tm.getMonth()}-${tm.getDate()}`) return zh ? "明天" : "Tomorrow";
  return zh
    ? `${d.getMonth() + 1}月${d.getDate()}日 周${"日一二三四五六"[d.getDay()]}`
    : d.toLocaleDateString(undefined, { month: "long", day: "numeric", weekday: "short" });
}

function timeRange(start: number, end: number | null): string {
  const s = new Date(start * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (!end) return s;
  const e = new Date(end * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `${s} – ${e}`;
}

type FormState = { id: string | null; title: string; start: string; end: string; location: string };
const EMPTY_FORM: FormState = { id: null, title: "", start: "", end: "", location: "" };

export function CalendarPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const zh = locale === "zh";
  const [rows, setRows] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [endEnabled, setEndEnabled] = useState(false);
  const [manual, setManual] = useState(false);
  const [manualText, setManualText] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await listCalendar());
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  const active = useMemo(
    () => rows.filter((r) => r.status !== "done").sort((a, b) => a.start_at - b.start_at),
    [rows],
  );
  const done = useMemo(
    () => rows.filter((r) => r.status === "done").sort((a, b) => b.start_at - a.start_at),
    [rows],
  );
  const groups = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const e of active) {
      const k = dayKey(e.start_at);
      (map.get(k) ?? map.set(k, []).get(k)!).push(e);
    }
    return [...map.entries()];
  }, [active]);

  const openNew = () => {
    setForm(EMPTY_FORM);
    setEndEnabled(false);
    setManual(false);
    setManualText("");
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (e: CalendarEvent) => {
    const toLocal = (ts: number) => {
      const d = new Date(ts * 1000);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    };
    setForm({
      id: e.id,
      title: e.title,
      start: toLocal(e.start_at),
      end: e.end_at ? toLocal(e.end_at) : "",
      location: e.location ?? "",
    });
    setEndEnabled(!!e.end_at);
    setManual(false);
    setManualText("");
    setFormError(null);
    setFormOpen(true);
  };

  const validateStart = (iso: string): string | null => {
    if (!iso) return zh ? "请选择开始时间。" : "Pick a start time.";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return zh ? "时间格式不正确，请用 YYYY-MM-DD HH:MM。" : "Invalid format, use YYYY-MM-DD HH:MM.";
    if (d.getTime() < Date.now() - 60_000) return zh ? "不能选择早于当前时间的时间。" : "Cannot pick a time in the past.";
    return null;
  };

  const submit = useCallback(async () => {
    const startIso = manual ? manualText.trim().replace(" ", "T") : form.start;
    const err = validateStart(startIso);
    if (err) {
      setFormError(err);
      return;
    }
    if (!form.title.trim()) {
      setFormError(zh ? "请填写标题。" : "Title is required.");
      return;
    }
    if (endEnabled && form.end && new Date(form.end).getTime() < new Date(startIso).getTime()) {
      setFormError(zh ? "结束时间不能早于开始时间。" : "End cannot be before start.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        title: form.title.trim(),
        start: startIso,
        end: endEnabled && form.end ? form.end : undefined,
        location: form.location.trim() || undefined,
      };
      if (form.id) await updateEvent(form.id, payload);
      else await createEvent(payload);
      setFormOpen(false);
      notifyCalendarChanged();
      await load();
    } catch (e) {
      setFormError(localizeError(e, locale));
    } finally {
      setSaving(false);
    }
  }, [manual, manualText, form, endEnabled, zh, load, locale]);

  const mutate = useCallback(
    async (fn: () => Promise<unknown>) => {
      try {
        await fn();
        notifyCalendarChanged();
        await load();
      } catch (e) {
        setError(localizeError(e, locale));
      }
    },
    [load, locale],
  );

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
        <button onClick={openNew} className="btn-accent h-8 px-3 text-sm ml-auto">
          <Plus size={14} />
          {zh ? "新建" : "New"}
        </button>
        <button onClick={load} className="btn-ghost w-8 h-8" aria-label={zh ? "刷新" : "Refresh"}>
          <RefreshCw size={14} />
        </button>
      </header>

      {formOpen ? (
        <div className="mx-3 mt-3 rounded-xl border border-border bg-bg-subtle p-3 space-y-3 animate-fade-in">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {form.id ? (zh ? "修改日程" : "Edit event") : zh ? "新建日程" : "New event"}
            </span>
            <button onClick={() => setFormOpen(false)} className="btn-ghost w-7 h-7" aria-label={zh ? "关闭" : "Close"}>
              <X size={14} />
            </button>
          </div>

          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder={zh ? "标题，例如：团队周会" : "Title, e.g. Team sync"}
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-fg-muted">{zh ? "开始时间" : "Start"}</span>
              <div className="inline-flex rounded-lg border border-border bg-bg-elevated p-0.5 text-[11px]">
                <button
                  onClick={() => setManual(false)}
                  className={`px-2 py-0.5 rounded-md ${!manual ? "bg-accent text-accent-fg" : "text-fg-muted"}`}
                >
                  {zh ? "滚轮" : "Wheel"}
                </button>
                <button
                  onClick={() => setManual(true)}
                  className={`px-2 py-0.5 rounded-md ${manual ? "bg-accent text-accent-fg" : "text-fg-muted"}`}
                >
                  {zh ? "手动" : "Manual"}
                </button>
              </div>
            </div>
            {manual ? (
              <input
                value={manualText}
                onChange={(e) => setManualText(e.target.value)}
                placeholder="2026-07-26 14:30"
                className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
              />
            ) : (
              <DateTimeWheel value={form.start} onChange={(iso) => setForm((f) => ({ ...f, start: iso }))} zh={zh} />
            )}
          </div>

          <label className="flex items-center gap-2 text-xs text-fg-muted">
            <input type="checkbox" checked={endEnabled} onChange={(e) => setEndEnabled(e.target.checked)} />
            {zh ? "设置结束时间" : "Set end time"}
          </label>
          {endEnabled ? (
            <DateTimeWheel value={form.end} onChange={(iso) => setForm((f) => ({ ...f, end: iso }))} zh={zh} />
          ) : null}

          <input
            value={form.location}
            onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
            placeholder={zh ? "地点（可选）" : "Location (optional)"}
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />

          {formError ? <p className="text-xs text-danger">{formError}</p> : null}
          <div className="flex justify-end">
            <button onClick={submit} disabled={saving} className="btn-accent h-8 px-4 text-sm disabled:opacity-50">
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              {form.id ? (zh ? "保存" : "Save") : zh ? "创建" : "Create"}
            </button>
          </div>
        </div>
      ) : null}

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {loading ? (
          <div className="flex justify-center py-10 text-fg-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : error ? (
          <p className="text-sm text-danger px-1">{error}</p>
        ) : active.length === 0 && done.length === 0 ? (
          <p className="text-sm text-fg-subtle text-center py-10">
            {zh ? "还没有日程，点“新建”或用 AI 工作台添加。" : "No events yet. Add one or ask the AI workspace."}
          </p>
        ) : (
          <>
            {groups.map(([key, evs]) => (
              <div key={key} className="space-y-2">
                <div className="text-xs font-medium text-fg-muted px-1">{dayLabel(evs[0].start_at, zh)}</div>
                {evs.map((ev) => (
                  <EventRow
                    key={ev.id}
                    ev={ev}
                    zh={zh}
                    onComplete={() => mutate(() => updateEvent(ev.id, { status: "done" }))}
                    onEdit={() => openEdit(ev)}
                    onDelete={() => mutate(() => deleteEvent(ev.id))}
                  />
                ))}
              </div>
            ))}

            {done.length > 0 ? (
              <div className="space-y-2">
                <button
                  onClick={() => setShowDone((v) => !v)}
                  className="text-xs font-medium text-fg-muted px-1 hover:text-fg"
                >
                  {zh ? `已完成（${done.length}）` : `Completed (${done.length})`} {showDone ? "▾" : "▸"}
                </button>
                {showDone
                  ? done.map((ev) => (
                      <EventRow
                        key={ev.id}
                        ev={ev}
                        zh={zh}
                        completed
                        onRestore={() => mutate(() => updateEvent(ev.id, { status: "active" }))}
                        onDelete={() => mutate(() => deleteEvent(ev.id))}
                      />
                    ))
                  : null}
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function EventRow({
  ev,
  zh,
  completed,
  onComplete,
  onEdit,
  onDelete,
  onRestore,
}: {
  ev: CalendarEvent;
  zh: boolean;
  completed?: boolean;
  onComplete?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onRestore?: () => void;
}) {
  return (
    <div className="border border-border rounded-xl p-3 bg-bg-subtle group">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className={`text-sm font-medium ${completed ? "line-through text-fg-subtle" : "text-fg"}`}>
            {ev.title}
          </div>
          <div className="text-[13px] text-fg-muted mt-1 space-y-0.5">
            <div className="flex items-center gap-1.5">
              <Clock size={13} /> {timeRange(ev.start_at, ev.end_at)}
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
        <div className="flex items-center gap-1 shrink-0">
          {completed ? (
            <button onClick={onRestore} className="btn-ghost w-7 h-7" aria-label={zh ? "恢复" : "Restore"} title={zh ? "恢复" : "Restore"}>
              <RotateCcw size={14} />
            </button>
          ) : (
            <>
              <button onClick={onComplete} className="btn-ghost w-7 h-7 text-green-600" aria-label={zh ? "完成" : "Complete"} title={zh ? "完成" : "Complete"}>
                <Check size={15} />
              </button>
              <button onClick={onEdit} className="btn-ghost w-7 h-7" aria-label={zh ? "修改" : "Edit"} title={zh ? "修改" : "Edit"}>
                <Pencil size={13} />
              </button>
            </>
          )}
          <button onClick={onDelete} className="btn-ghost w-7 h-7 text-fg-subtle hover:text-danger" aria-label={zh ? "删除" : "Delete"} title={zh ? "删除" : "Delete"}>
            <Trash2 size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
