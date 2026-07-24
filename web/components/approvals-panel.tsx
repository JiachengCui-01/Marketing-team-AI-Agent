"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, FileCheck2, Loader2, RefreshCw } from "lucide-react";
import { actApproval, listApprovals, type ApprovalRecord } from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

type Tab = "mine" | "pending" | "acted";

const TAB_LABEL: Record<Tab, string> = {
  mine: "我发起的",
  pending: "待我审批",
  acted: "已处理",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
};

const TYPE_LABEL: Record<string, string> = {
  leave: "请假",
  expense: "报销",
  purchase: "采购",
  general: "通用审批",
};

export function ApprovalsPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [tab, setTab] = useState<Tab>("pending");
  const [rows, setRows] = useState<ApprovalRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);

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

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 ml-1">
          <FileCheck2 size={15} className="text-accent" />
          <span className="text-sm font-medium">{t.approvals}</span>
        </div>
        <button
          onClick={() => load(tab)}
          className="btn-ghost w-8 h-8 ml-auto"
          aria-label="刷新"
          title="刷新"
        >
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
                      ? "bg-green-500/15 text-green-600"
                      : a.status === "rejected"
                        ? "bg-danger/15 text-danger"
                        : "bg-amber-500/15 text-amber-600"
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
                  <button
                    onClick={() => act(a.id, "approved")}
                    disabled={actingId === a.id}
                    className="btn-accent h-8 px-3 text-sm disabled:opacity-50"
                  >
                    {actingId === a.id ? <Loader2 size={14} className="animate-spin" /> : null}
                    通过
                  </button>
                  <button
                    onClick={() => act(a.id, "rejected")}
                    disabled={actingId === a.id}
                    className="btn-ghost h-8 px-3 text-sm border border-border"
                  >
                    驳回
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
