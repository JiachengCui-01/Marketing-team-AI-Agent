"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, FileCheck2, Loader2, RefreshCw, Plus, X, Pencil, Undo2 } from "lucide-react";
import {
  actApproval,
  createApproval,
  listApprovals,
  updateApproval,
  withdrawApproval,
  type ApprovalRecord,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

type Tab = "mine" | "pending" | "acted";
const TAB_LABEL: Record<Tab, string> = { mine: "我发起的", pending: "待我审批", acted: "已处理" };
const STATUS_LABEL: Record<string, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  withdrawn: "已撤回",
};
const TYPE_LABEL: Record<string, string> = { leave: "请假", expense: "报销", purchase: "采购", general: "通用审批" };

type FormState = { id: string | null; type: string; title: string; detail: string };
const EMPTY_FORM: FormState = { id: null, type: "leave", title: "", detail: "" };

export function ApprovalsPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [tab, setTab] = useState<Tab>("pending");
  const [rows, setRows] = useState<ApprovalRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const load = useCallback(
    async (which: Tab) => {
      setLoading(true);
      setError(null);
      try {
        setRows(await listApprovals(which));
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

  const act = useCallback(
    async (id: string, action: "approved" | "rejected") => {
      setActingId(id);
      try {
        await actApproval(id, action);
        await load(tab);
      } catch (e) {
        setError(localizeError(e, locale));
      } finally {
        setActingId(null);
      }
    },
    [tab, load, locale],
  );

  const openNew = () => {
    setForm(EMPTY_FORM);
    setFormOpen(true);
  };
  const openEdit = (a: ApprovalRecord) => {
    const detail = String((a.form?.["事由"] ?? a.form?.["reason"] ?? Object.values(a.form ?? {})[0]) ?? "");
    setForm({ id: a.id, type: a.type, title: a.title, detail });
    setFormOpen(true);
  };

  const submit = useCallback(async () => {
    if (!form.title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const fields = form.detail.trim() ? { 事由: form.detail.trim() } : {};
      if (form.id) await updateApproval(form.id, { title: form.title.trim(), fields });
      else await createApproval({ type: form.type, title: form.title.trim(), fields });
      setForm(EMPTY_FORM);
      setFormOpen(false);
      setTab("mine");
      await load("mine");
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
          <FileCheck2 size={15} className="text-feature-image" />
          <span>{t.approvals}</span>
        </div>
        <button onClick={openNew} className="btn-accent h-8 px-3 text-sm">
          <Plus size={14} />
          发起审批
        </button>
        <button onClick={() => load(tab)} className="btn-ghost w-8 h-8" aria-label="刷新">
          <RefreshCw size={14} />
        </button>
      </header>

      {formOpen ? (
        <div className="mx-3 mt-3 rounded-xl border border-border bg-bg-subtle p-3 space-y-2 animate-fade-in">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{form.id ? "修改申请" : "发起审批"}</span>
            <button onClick={() => setFormOpen(false)} className="btn-ghost w-7 h-7" aria-label="关闭">
              <X size={14} />
            </button>
          </div>
          <select
            value={form.type}
            onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
            disabled={!!form.id}
            className="h-9 px-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent disabled:opacity-60"
          >
            <option value="leave">请假</option>
            <option value="expense">报销</option>
            <option value="purchase">采购</option>
            <option value="general">通用审批</option>
          </select>
          <input
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="标题，例如：年假申请（3 天）"
            className="w-full h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
          />
          <textarea
            value={form.detail}
            onChange={(e) => setForm((f) => ({ ...f, detail: e.target.value }))}
            placeholder="事由 / 说明"
            rows={2}
            className="w-full px-3 py-2 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent resize-none"
          />
          <div className="flex justify-end">
            <button onClick={submit} disabled={saving || !form.title.trim()} className="btn-accent h-8 px-4 text-sm disabled:opacity-50">
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              {form.id ? "保存" : "提交"}
            </button>
          </div>
        </div>
      ) : null}

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

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {loading ? (
          <div className="flex justify-center py-10 text-fg-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : error ? (
          <p className="text-sm text-danger px-1">{error}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-fg-subtle text-center py-10">暂无审批记录</p>
        ) : (
          rows.map((a) => (
            <div key={a.id} className="border border-border rounded-xl p-4 bg-bg-subtle">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-medium">{a.title}</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg-elevated text-fg-muted">
                  {TYPE_LABEL[a.type] ?? a.type}
                </span>
                <span
                  className={`ml-auto text-[11px] px-2 py-0.5 rounded-full ${
                    a.status === "approved"
                      ? "bg-success/15 text-success"
                      : a.status === "rejected"
                        ? "bg-danger/15 text-danger"
                        : a.status === "withdrawn"
                          ? "bg-bg-elevated text-fg-subtle"
                          : "bg-feature-research/15 text-feature-research"
                  }`}
                >
                  {STATUS_LABEL[a.status] ?? a.status}
                </span>
              </div>
              <div className="text-[13px] text-fg-muted space-y-1">
                <div>发起人：{a.applicant_name ?? "—"}</div>
                {Object.entries(a.form || {}).map(([k, v]) => (
                  <div key={k}>
                    {k}：<span className="text-fg">{String(v)}</span>
                  </div>
                ))}
              </div>

              {tab === "pending" && a.status === "pending" ? (
                <div className="mt-3 pt-3 border-t border-border flex gap-2">
                  <button onClick={() => act(a.id, "approved")} disabled={actingId === a.id} className="btn-accent h-8 px-3 text-sm disabled:opacity-50">
                    {actingId === a.id ? <Loader2 size={14} className="animate-spin" /> : null}
                    通过
                  </button>
                  <button onClick={() => act(a.id, "rejected")} disabled={actingId === a.id} className="btn-ghost h-8 px-3 text-sm border border-border">
                    驳回
                  </button>
                </div>
              ) : null}

              {tab === "mine" && a.status === "pending" ? (
                <div className="mt-3 pt-3 border-t border-border flex gap-2">
                  <button onClick={() => openEdit(a)} className="btn-ghost h-8 px-3 text-sm border border-border">
                    <Pencil size={13} /> 修改
                  </button>
                  <button onClick={() => mutate(() => withdrawApproval(a.id))} className="btn-ghost h-8 px-3 text-sm border border-border text-fg-subtle hover:text-danger">
                    <Undo2 size={13} /> 撤回
                  </button>
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
