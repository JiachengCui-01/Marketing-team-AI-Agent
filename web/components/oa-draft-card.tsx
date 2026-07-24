"use client";

import { useState } from "react";
import { FileCheck2, Loader2, CheckCircle2, XCircle } from "lucide-react";
import {
  createApproval,
  createEvent,
  createTask,
  type OaDraft,
} from "@/lib/api";
import { getDraftStatus, setDraftStatus } from "@/lib/oa-drafts";
import { localizeError, useI18n } from "@/lib/i18n";

const KIND_LABEL: Record<string, string> = {
  approval: "审批草稿",
  task: "任务草稿",
  calendar: "日程草稿",
};

const APPROVAL_TYPE_LABEL: Record<string, string> = {
  leave: "请假",
  expense: "报销",
  purchase: "采购",
  general: "通用审批",
};

function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join("、") : "—";
  return String(v);
}

type CardState = { status: "submitted" | "error" | "cancelled"; note: string };

function draftRows(draft: OaDraft): [string, string][] {
  if (draft.kind === "task") {
    return [
      ["详情", fmt(draft.detail)],
      ["优先级", fmt(draft.priority)],
      ["指派给", fmt(draft.assignee_name) === "—" ? "我自己" : fmt(draft.assignee_name)],
      ["截止", fmt(draft.due)],
    ];
  }
  if (draft.kind === "calendar") {
    const start = draft.start ? new Date(String(draft.start)).toLocaleString() : "—";
    const end = draft.end ? new Date(String(draft.end)).toLocaleString() : "—";
    return [
      ["开始", start],
      ["结束", end],
      ["地点", fmt(draft.location)],
      ["参与人", fmt(draft.attendees)],
    ];
  }
  return Object.entries((draft.fields as Record<string, unknown>) ?? {}).map(
    ([k, v]) => [k, fmt(v)] as [string, string],
  );
}

/** A self-contained draft card rendered inline in the AI workspace chat. It manages its
 * own submit state and commits via the matching API on confirm (human-in-the-loop). */
export function OaDraftCard({ draft }: { draft: OaDraft }) {
  const { locale } = useI18n();
  const cardKey = String(draft._id ?? `${draft.kind}:${draft.title}`);
  const persisted = getDraftStatus(cardKey);
  const [status, setStatus] = useState<"pending" | "submitting" | "submitted" | "error" | "cancelled">(
    persisted?.status ?? "pending",
  );
  const [note, setNote] = useState(persisted?.note ?? "");

  const commit = (s: CardState) => {
    setDraftStatus(cardKey, s);
    setStatus(s.status);
    setNote(s.note);
  };

  const kindLabel = KIND_LABEL[draft.kind] ?? "草稿";
  const badge =
    draft.kind === "approval" ? APPROVAL_TYPE_LABEL[String(draft.type)] ?? String(draft.type) : null;
  const confirmLabel = draft.kind === "approval" ? "确认提交" : "确认创建";
  const rows = draftRows(draft);

  async function confirm() {
    setStatus("submitting");
    try {
      let note = "已提交";
      if (draft.kind === "task") {
        const task = await createTask({
          title: String(draft.title),
          detail: draft.detail ? String(draft.detail) : undefined,
          priority: draft.priority ? String(draft.priority) : undefined,
          assignee_name: draft.assignee_name ? String(draft.assignee_name) : undefined,
        });
        note = task.assignee_name && task.assignee_id !== task.creator_id
          ? `已创建，指派给 ${task.assignee_name}`
          : "已创建任务";
      } else if (draft.kind === "calendar") {
        const ev = await createEvent({
          title: String(draft.title),
          start: String(draft.start ?? ""),
          end: draft.end ? String(draft.end) : undefined,
          location: draft.location ? String(draft.location) : undefined,
          attendees: Array.isArray(draft.attendees) ? (draft.attendees as string[]) : undefined,
        });
        if (typeof window !== "undefined") window.dispatchEvent(new Event("oa-calendar-changed"));
        note = `已创建日程：${new Date(ev.start_at * 1000).toLocaleString()}`;
      } else {
        const appr = await createApproval({
          type: String(draft.type ?? "general"),
          title: String(draft.title),
          fields: (draft.fields as Record<string, unknown>) ?? {},
        });
        const approver = appr.steps[0]?.approver_name ?? "";
        note = approver ? `已提交，待 ${approver} 审批` : "已提交";
      }
      commit({ status: "submitted", note });
    } catch (e) {
      commit({ status: "error", note: localizeError(e, locale) });
    }
  }

  if (status === "cancelled") return null;

  return (
    <div className="mt-3 max-w-md rounded-xl border border-border bg-bg-subtle p-3.5">
      <div className="flex items-center gap-2 mb-2.5">
        <FileCheck2 size={15} className="text-accent" />
        <span className="text-[13px] font-medium">
          {kindLabel} · {draft.title}
        </span>
        {badge ? (
          <span className="ml-auto text-[11px] px-2 py-0.5 rounded-full bg-feature-research/15 text-feature-research">
            {badge}
          </span>
        ) : null}
      </div>
      <dl className="text-[12px] space-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <dt className="text-fg-muted w-20 shrink-0">{k}</dt>
            <dd className="text-fg break-words">{v}</dd>
          </div>
        ))}
      </dl>

      {status === "submitted" ? (
        <div className="mt-2.5 pt-2.5 border-t border-border flex items-center gap-2 text-[13px] text-success">
          <CheckCircle2 size={14} />
          <span>{note}</span>
        </div>
      ) : status === "error" ? (
        <div className="mt-2.5 pt-2.5 border-t border-border flex items-center gap-2 text-[13px] text-danger">
          <XCircle size={14} />
          <span>{note}</span>
        </div>
      ) : (
        <div className="mt-2.5 pt-2.5 border-t border-border flex gap-2">
          <button
            onClick={confirm}
            disabled={status === "submitting"}
            className="btn-accent h-8 px-3 text-sm disabled:opacity-50"
          >
            {status === "submitting" ? <Loader2 size={14} className="animate-spin" /> : null}
            {confirmLabel}
          </button>
          <button
            onClick={() => commit({ status: "cancelled", note: "" })}
            className="btn-ghost h-8 px-3 text-sm border border-border"
          >
            取消
          </button>
        </div>
      )}
    </div>
  );
}
