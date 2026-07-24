"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckSquare,
  Loader2,
  RefreshCw,
  Plus,
  X,
  Check,
  Circle,
  CheckCircle2,
  Clock3,
  Trash2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import {
  listTasks,
  createTask,
  updateTask,
  confirmTask,
  deleteTask,
  clearDoneTasks,
  type TaskRecord,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

type Tab = "assigned" | "created" | "done";
const TAB_LABEL: Record<Tab, string> = { assigned: "指派给我", created: "我创建的", done: "已完成" };
const PRIORITY_LABEL: Record<string, string> = { low: "低", normal: "中", high: "高" };

function dueLabel(ts: number | null): string | null {
  if (!ts) return null;
  const d = new Date(ts * 1000);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function TasksPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [tab, setTab] = useState<Tab>("assigned");
  const [rows, setRows] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ title: "", detail: "", priority: "normal", assignee_name: "", due: "" });

  const load = useCallback(
    async (which: Tab) => {
      setLoading(true);
      setError(null);
      try {
        setRows(await listTasks(which));
      } catch (e) {
        setError(localizeError(e, locale));
      } finally {
        setLoading(false);
      }
    },
    [locale],
  );

  useEffect(() => {
    load(tab);
  }, [tab, load]);

  const mutate = useCallback(
    async (fn: () => Promise<unknown>) => {
      try {
        await fn();
        await load(tab);
      } catch (e) {
        setError(localizeError(e, locale));
      }
    },
    [tab, load, locale],
  );

  const submit = useCallback(async () => {
    if (!form.title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createTask({
        title: form.title.trim(),
        detail: form.detail.trim() || undefined,
        priority: form.priority,
        assignee_name: form.assignee_name.trim() || undefined,
        due: form.due || undefined,
      });
      setForm({ title: "", detail: "", priority: "normal", assignee_name: "", due: "" });
      setFormOpen(false);
      // A newly created task shows under 我创建的.
      setTab("created");
      await load("created");
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setSaving(false);
    }
  }, [form, load, locale]);

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <CheckSquare size={15} className="text-feature-image" />
          <span>{t.tasks}</span>
        </div>
        <button onClick={() => setFormOpen((v) => !v)} className="btn-accent h-8 px-3 text-sm">
          <Plus size={14} />
          新建
        </button>
        <button onClick={() => load(tab)} className="btn-ghost w-8 h-8" aria-label="刷新">
          <RefreshCw size={14} />
        </button>
      </header>

      {formOpen ? (
        <div className="mx-3 mt-3 rounded-xl border border-border bg-bg-subtle p-3 space-y-2 animate-fade-in">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">新建任务</span>
            <button onClick={() => setFormOpen(false)} className="btn-ghost w-7 h-7" aria-label="关闭">
              <X size={14} />
            </button>
          </div>
          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="任务标题"
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
          <textarea
            value={form.detail}
            onChange={(e) => setForm((f) => ({ ...f, detail: e.target.value }))}
            placeholder="详情（可选）"
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent resize-none"
          />
          <div className="flex gap-2">
            <select
              value={form.priority}
              onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
              className="h-9 px-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
            >
              <option value="low">优先级：低</option>
              <option value="normal">优先级：中</option>
              <option value="high">优先级：高</option>
            </select>
            <input
              value={form.assignee_name}
              onChange={(e) => setForm((f) => ({ ...f, assignee_name: e.target.value }))}
              placeholder="指派给（留空=自己）"
              className="flex-1 h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
            />
          </div>
          <label className="block text-[11px] text-fg-muted">
            截止时间（可选）
            <input
              type="datetime-local"
              value={form.due}
              onChange={(e) => setForm((f) => ({ ...f, due: e.target.value }))}
              className="w-full h-9 px-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
            />
          </label>
          <div className="flex justify-end">
            <button onClick={submit} disabled={saving || !form.title.trim()} className="btn-accent h-8 px-4 text-sm disabled:opacity-50">
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              创建
            </button>
          </div>
        </div>
      ) : null}

      <div className="flex items-center gap-1 px-3 pt-3">
        {(Object.keys(TAB_LABEL) as Tab[]).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-3 py-1.5 rounded-lg text-sm ${
              tab === k ? "bg-accent/15 text-accent font-medium" : "text-fg-muted hover:bg-bg-elevated"
            }`}
          >
            {TAB_LABEL[k]}
          </button>
        ))}
        {tab === "done" && rows.length > 0 ? (
          <button
            onClick={() => mutate(() => clearDoneTasks())}
            className="ml-auto text-xs text-fg-subtle hover:text-danger inline-flex items-center gap-1"
          >
            <Trash2 size={12} /> 清空
          </button>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading ? (
          <div className="flex justify-center py-10 text-fg-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : error ? (
          <p className="text-sm text-danger px-1">{error}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-fg-subtle text-center py-10">暂无任务</p>
        ) : (
          rows.map((task) => (
            <TodoRow
              key={task.id}
              task={task}
              tab={tab}
              expanded={!!expanded[task.id]}
              onToggleExpand={() => setExpanded((e) => ({ ...e, [task.id]: !e[task.id] }))}
              onComplete={() => mutate(() => updateTask(task.id, "done"))}
              onReopen={() => mutate(() => updateTask(task.id, "open"))}
              onConfirm={() => mutate(() => confirmTask(task.id))}
              onDelete={() => mutate(() => deleteTask(task.id))}
            />
          ))
        )}
      </div>
    </div>
  );
}

function TodoRow({
  task,
  tab,
  expanded,
  onToggleExpand,
  onComplete,
  onReopen,
  onConfirm,
  onDelete,
}: {
  task: TaskRecord;
  tab: Tab;
  expanded: boolean;
  onToggleExpand: () => void;
  onComplete: () => void;
  onReopen: () => void;
  onConfirm: () => void;
  onDelete: () => void;
}) {
  const due = dueLabel(task.due_at);
  const awaiting = task.status === "awaiting_confirmation";
  const done = task.status === "done";
  // The assignee (assigned tab) or self-owner (created tab, self task) can tick to complete.
  const canTick = !done && !awaiting;

  const Checkbox = () => {
    if (done) return <CheckCircle2 size={20} className="text-success shrink-0" />;
    if (awaiting)
      return <Clock3 size={20} className="text-feature-research shrink-0" aria-label="待确认" />;
    return (
      <button
        onClick={canTick ? onComplete : undefined}
        className="shrink-0 text-fg-muted hover:text-accent"
        aria-label="标记完成"
        disabled={!canTick}
      >
        <Circle size={20} className={canTick ? "" : "opacity-40"} />
      </button>
    );
  };

  return (
    <div className="border border-border rounded-xl bg-bg-subtle">
      <div className="flex items-start gap-3 p-3">
        <div className="mt-0.5">
          <Checkbox />
        </div>
        <button onClick={onToggleExpand} className="min-w-0 flex-1 text-left">
          <div className={`text-sm flex items-center gap-1.5 ${done ? "line-through text-fg-subtle" : "text-fg"}`}>
            {expanded ? <ChevronDown size={13} className="shrink-0 text-fg-subtle" /> : <ChevronRight size={13} className="shrink-0 text-fg-subtle" />}
            <span className="truncate">{task.title}</span>
          </div>
          <div className="text-[11px] text-fg-subtle mt-1 flex flex-wrap gap-x-3 gap-y-0.5 pl-[18px]">
            {due ? <span>截至 {due}</span> : null}
            <span>优先级：{PRIORITY_LABEL[task.priority] ?? task.priority}</span>
            {tab === "assigned" ? <span>来自：{task.creator_name ?? "—"}</span> : null}
            {tab === "created" && task.assignee_name && task.assignee_id !== task.creator_id ? (
              <span>指派给：{task.assignee_name}</span>
            ) : null}
            {awaiting ? <span className="text-feature-research">待确认</span> : null}
          </div>
        </button>
        <div className="flex items-center gap-1 shrink-0">
          {tab === "created" && awaiting ? (
            <button onClick={onConfirm} className="btn-accent h-7 px-2 text-xs" title="确认完成">
              <Check size={12} /> 确认
            </button>
          ) : null}
          {done ? (
            <button onClick={onReopen} className="btn-ghost w-7 h-7 text-fg-subtle" title="恢复" aria-label="恢复">
              <RefreshCw size={13} />
            </button>
          ) : null}
          {tab !== "assigned" ? (
            <button onClick={onDelete} className="btn-ghost w-7 h-7 text-fg-subtle hover:text-danger" title="删除" aria-label="删除">
              <Trash2 size={13} />
            </button>
          ) : null}
        </div>
      </div>
      {expanded && task.detail ? (
        <div className="px-3 pb-3 pl-[42px] text-[13px] text-fg-muted whitespace-pre-wrap">{task.detail}</div>
      ) : null}
    </div>
  );
}
