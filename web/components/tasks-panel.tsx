"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CheckSquare, Square, Loader2, RefreshCw } from "lucide-react";
import { listTasks, updateTask, type TaskRecord } from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

type Tab = "assigned" | "created";

const TAB_LABEL: Record<Tab, string> = { assigned: "指派给我", created: "我创建的" };
const PRIORITY_LABEL: Record<string, string> = { low: "低", normal: "中", high: "高" };

export function TasksPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [tab, setTab] = useState<Tab>("assigned");
  const [rows, setRows] = useState<TaskRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const toggle = useCallback(
    async (task: TaskRecord) => {
      const next = task.status === "done" ? "open" : "done";
      try {
        const updated = await updateTask(task.id, next);
        setRows((prev) => prev.map((r) => (r.id === task.id ? updated : r)));
      } catch (e) {
        setError(localizeError(e, locale));
      }
    },
    [locale],
  );

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 ml-1">
          <CheckSquare size={15} className="text-accent" />
          <span className="text-sm font-medium">{t.tasks}</span>
        </div>
        <button onClick={() => load(tab)} className="btn-ghost w-8 h-8 ml-auto" aria-label="刷新">
          <RefreshCw size={14} />
        </button>
      </header>

      <div className="flex gap-1 px-3 pt-3">
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
            <div
              key={task.id}
              className="border border-border rounded-xl p-3 bg-bg-subtle flex items-start gap-3"
            >
              <button
                onClick={() => toggle(task)}
                className="mt-0.5 shrink-0 text-accent"
                aria-label={task.status === "done" ? "标记未完成" : "标记完成"}
              >
                {task.status === "done" ? <CheckSquare size={18} /> : <Square size={18} />}
              </button>
              <div className="min-w-0 flex-1">
                <div
                  className={`text-sm ${task.status === "done" ? "line-through text-fg-subtle" : "text-fg"}`}
                >
                  {task.title}
                </div>
                {task.detail ? (
                  <div className="text-[13px] text-fg-muted mt-0.5 break-words">{task.detail}</div>
                ) : null}
                <div className="text-[11px] text-fg-subtle mt-1 flex gap-2">
                  <span>优先级：{PRIORITY_LABEL[task.priority] ?? task.priority}</span>
                  {tab === "assigned" ? (
                    <span>来自：{task.creator_name ?? "—"}</span>
                  ) : (
                    <span>指派给：{task.assignee_name ?? "我自己"}</span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
