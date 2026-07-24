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
  ChevronDown,
  ChevronRight,
  AlignLeft,
} from "lucide-react";
import { createEvent, deleteEvent, listCalendar, updateEvent, type CalendarEvent } from "@/lib/api";
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
  if (dayKey(ts) === `${t.getFullYear()}-${t.getMonth()}-${t.getDate()}`) return zh ? "今天" : "Today";
  const tm = new Date(t);
  tm.setDate(tm.getDate() + 1);
  if (dayKey(ts) === `${tm.getFullYear()}-${tm.getMonth()}-${tm.getDate()}`) return zh ? "明天" : "Tomorrow";
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
function toLocal(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
function addMinutes(iso: string, mins: number): string {
  const d = new Date(iso);
  d.setMinutes(d.getMinutes() + mins);
  return toLocal(d);
}

type FormState = { id: string | null; title: string; start: string; end: string; location: string; description: string };
const EMPTY_FORM: FormState = { id: null, title: "", start: "", end: "", location: "", description: "" };

export function CalendarPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const zh = locale === "zh";
  const [rows, setRows] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [manual, setManual] = useState(false);
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

  // Quiet refresh (no full-panel spinner) for per-row actions.
  const refresh = useCallback(async () => {
    try {
      setRows(await listCalendar());
    } catch {
      /* keep current rows */
    }
  }, []);

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
    for (const e of active) (map.get(dayKey(e.start_at)) ?? map.set(dayKey(e.start_at), []).get(dayKey(e.start_at))!).push(e);
    return [...map.entries()];
  }, [active]);

  const openNew = () => {
    setForm(EMPTY_FORM);
    setManual(false);
    setFormError(null);
    setFormOpen(true);
  };
  const openEdit = (e: CalendarEvent) => {
    setForm({
      id: e.id,
      title: e.title,
      start: toLocal(new Date(e.start_at * 1000)),
      end: e.end_at ? toLocal(new Date(e.end_at * 1000)) : addMinutes(toLocal(new Date(e.start_at * 1000)), 5),
      location: e.location ?? "",
      description: e.description ?? "",
    });
    setManual(false);
    setFormError(null);
    setFormOpen(true);
  };

  // Keep end ≥ start+5min whenever start changes.
  const setStart = (iso: string) =>
    setForm((f) => {
      const minEnd = addMinutes(iso, 5);
      const end = f.end && new Date(f.end).getTime() > new Date(iso).getTime() ? f.end : minEnd;
      return { ...f, start: iso, end };
    });

  const submit = useCallback(async () => {
    const startIso = form.start;
    if (!startIso || isNaN(new Date(startIso).getTime()))
      return setFormError(zh ? "开始时间格式不正确。" : "Invalid start time.");
    if (new Date(startIso).getTime() < Date.now() - 60_000)
      return setFormError(zh ? "不能选择早于当前时间的时间。" : "Cannot pick a past time.");
    if (!form.title.trim()) return setFormError(zh ? "请填写标题。" : "Title is required.");
    let endIso = form.end;
    if (!endIso || new Date(endIso).getTime() <= new Date(startIso).getTime()) endIso = addMinutes(startIso, 5);
    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        title: form.title.trim(),
        start: startIso,
        end: endIso,
        location: form.location.trim() || undefined,
        description: form.description.trim() || undefined,
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
  }, [form, zh, load, locale]);

  const timeField = (label: string, value: string, onChange: (iso: string) => void, min?: string) => (
    <div className="flex-1 flex justify-center">
      {/* Fixed-width column so the label sits directly above the (centered) picker box. */}
      <div className="w-[268px] max-w-full">
        <div className="text-[11px] text-fg-muted mb-1">{label}</div>
        {manual ? (
          <input
            value={value.replace("T", " ")}
            onChange={(e) => onChange(e.target.value.trim().replace(" ", "T"))}
            placeholder="2026-07-26 14:30"
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
        ) : (
          <DateTimeWheel value={value || null} onChange={onChange} zh={zh} min={min} />
        )}
      </div>
    </div>
  );

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <Calendar size={15} className="text-feature-news" />
          <span>{t.calendar}</span>
        </div>
        <button onClick={openNew} className="btn-accent h-8 px-3 text-sm">
          <Plus size={14} />
          {zh ? "新建" : "New"}
        </button>
        <button onClick={load} className="btn-ghost w-8 h-8" aria-label={zh ? "刷新" : "Refresh"}>
          <RefreshCw size={14} />
        </button>
      </header>

      {formOpen ? (
        <div className="cal-form mx-3 mt-3 rounded-xl border border-border bg-bg-subtle p-3 space-y-3 animate-fade-in">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {form.id ? (zh ? "修改日程" : "Edit event") : zh ? "新建日程" : "New event"}
            </span>
            <div className="flex items-center gap-2">
              <div className="inline-flex rounded-lg border border-border bg-bg-elevated p-0.5 text-[11px]">
                <button onClick={() => setManual(false)} className={`px-2 py-0.5 rounded-md ${!manual ? "bg-accent text-accent-fg" : "text-fg-muted"}`}>
                  {zh ? "滚轮" : "Wheel"}
                </button>
                <button onClick={() => setManual(true)} className={`px-2 py-0.5 rounded-md ${manual ? "bg-accent text-accent-fg" : "text-fg-muted"}`}>
                  {zh ? "手动" : "Manual"}
                </button>
              </div>
              <button onClick={() => setFormOpen(false)} className="btn-ghost w-7 h-7" aria-label={zh ? "关闭" : "Close"}>
                <X size={14} />
              </button>
            </div>
          </div>

          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder={zh ? "标题，例如：团队周会" : "Title, e.g. Team sync"}
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />

          <div className="flex flex-wrap gap-3">
            {timeField(zh ? "开始时间" : "Start", form.start, setStart)}
            {timeField(zh ? "结束时间" : "End", form.end, (iso) => setForm((f) => ({ ...f, end: iso })), form.start ? addMinutes(form.start, 5) : undefined)}
          </div>

          <input
            value={form.location}
            onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
            placeholder={zh ? "地点（可选）" : "Location (optional)"}
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
          <textarea
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            placeholder={zh ? "备注 / 议程 / 详情（可选）" : "Notes / agenda / details (optional)"}
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent resize-none"
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
                    expanded={!!expanded[ev.id]}
                    onToggle={() => setExpanded((e) => ({ ...e, [ev.id]: !e[ev.id] }))}
                    onComplete={async () => {
                      await updateEvent(ev.id, { status: "done" });
                      notifyCalendarChanged();
                      await refresh();
                    }}
                    onEdit={() => openEdit(ev)}
                    onDelete={async () => {
                      await deleteEvent(ev.id);
                      notifyCalendarChanged();
                      await refresh();
                    }}
                  />
                ))}
              </div>
            ))}

            {done.length > 0 ? (
              <div className="space-y-2">
                <button onClick={() => setShowDone((v) => !v)} className="text-xs font-medium text-fg-muted px-1 hover:text-fg">
                  {zh ? `已完成（${done.length}）` : `Completed (${done.length})`} {showDone ? "▾" : "▸"}
                </button>
                {showDone
                  ? done.map((ev) => (
                      <EventRow
                        key={ev.id}
                        ev={ev}
                        zh={zh}
                        completed
                        expanded={!!expanded[ev.id]}
                        onToggle={() => setExpanded((e) => ({ ...e, [ev.id]: !e[ev.id] }))}
                        onRestore={async () => {
                          await updateEvent(ev.id, { status: "active" });
                          notifyCalendarChanged();
                          await refresh();
                        }}
                        onDelete={async () => {
                          await deleteEvent(ev.id);
                          notifyCalendarChanged();
                          await refresh();
                        }}
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
  expanded,
  onToggle,
  onComplete,
  onEdit,
  onDelete,
  onRestore,
}: {
  ev: CalendarEvent;
  zh: boolean;
  completed?: boolean;
  expanded: boolean;
  onToggle: () => void;
  onComplete?: () => Promise<void>;
  onEdit?: () => void;
  onDelete?: () => Promise<void>;
  onRestore?: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<"complete" | "delete" | "restore" | null>(null);
  const run = (kind: "complete" | "delete" | "restore", fn?: () => Promise<void>) => async () => {
    if (!fn || busy) return;
    setBusy(kind);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };
  const hasDetails = !!(ev.description || ev.location || ev.attendees.length);

  return (
    <div className="border border-border rounded-xl bg-bg-subtle">
      <div className="flex items-start gap-2 p-3">
        <button onClick={onToggle} className="min-w-0 flex-1 text-left">
          <div className={`text-sm font-medium flex items-center gap-1.5 ${completed ? "line-through text-fg-subtle" : "text-fg"}`}>
            {hasDetails ? (
              expanded ? <ChevronDown size={13} className="shrink-0 text-fg-subtle" /> : <ChevronRight size={13} className="shrink-0 text-fg-subtle" />
            ) : (
              <span className="w-[13px] shrink-0" />
            )}
            <span className="truncate">{ev.title}</span>
          </div>
          <div className="text-[13px] text-fg-muted mt-1 flex items-center gap-1.5 pl-[18px]">
            <Clock size={13} /> {timeRange(ev.start_at, ev.end_at)}
          </div>
        </button>
        <div className="flex items-center gap-1 shrink-0">
          {completed ? (
            <button onClick={run("restore", onRestore)} className="btn-ghost w-7 h-7" aria-label={zh ? "恢复" : "Restore"} title={zh ? "恢复" : "Restore"}>
              {busy === "restore" ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
            </button>
          ) : (
            <>
              <button onClick={run("complete", onComplete)} className="btn-ghost w-7 h-7 text-success" aria-label={zh ? "完成" : "Complete"} title={zh ? "完成" : "Complete"}>
                {busy === "complete" ? <Loader2 size={14} className="animate-spin" /> : <Check size={15} />}
              </button>
              <button onClick={onEdit} className="btn-ghost w-7 h-7" aria-label={zh ? "修改" : "Edit"} title={zh ? "修改" : "Edit"}>
                <Pencil size={13} />
              </button>
            </>
          )}
          <button onClick={run("delete", onDelete)} className="btn-ghost w-7 h-7 text-fg-subtle hover:text-danger" aria-label={zh ? "删除" : "Delete"} title={zh ? "删除" : "Delete"}>
            {busy === "delete" ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
          </button>
        </div>
      </div>
      {expanded && hasDetails ? (
        <div className="px-3 pb-3 pl-[42px] text-[13px] text-fg-muted space-y-1">
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
          {ev.description ? (
            <div className="flex items-start gap-1.5">
              <AlignLeft size={13} className="mt-0.5 shrink-0" /> <span className="whitespace-pre-wrap">{ev.description}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
