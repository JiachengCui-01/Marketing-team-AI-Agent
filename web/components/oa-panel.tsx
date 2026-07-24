"use client";

import { useCallback, useRef, useState } from "react";
import { ArrowLeft, Send, Sparkles, FileCheck2, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { createApproval, createEvent, createTask, oaStreamUrl } from "@/lib/api";
import { openEventStream, type StreamEvent } from "@/lib/sse";
import { localizeError, useI18n } from "@/lib/i18n";

type OaDraft = { kind: "approval" | "task" | "calendar"; title: string } & Record<string, unknown>;

type DraftItem = {
  kind: "draft";
  id: string;
  draft: OaDraft;
  status: "pending" | "submitting" | "submitted" | "error";
  note?: string;
};
type TextItem = { kind: "user" | "assistant"; id: string; text: string };
type ChatItem = TextItem | DraftItem;

const APPROVAL_TYPE_LABEL: Record<string, string> = {
  leave: "请假",
  expense: "报销",
  purchase: "采购",
  general: "通用审批",
};

const DRAFT_KIND_LABEL: Record<string, string> = {
  approval: "审批草稿",
  task: "任务草稿",
  calendar: "日程草稿",
};

const SUGGESTIONS = [
  "帮我提交一个 3 天年假申请，从下周一开始，事由写家庭事务",
  "给我自己建个任务：周五前完成季度总结",
  "约个明天下午 3 点的团队周会",
  "搜一下公司的报销制度",
];

let counter = 0;
const nextId = () => `oa-${Date.now()}-${counter++}`;

function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join("、") : "—";
  return String(v);
}

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

export function OaPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const closeRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, []);

  const send = useCallback(
    (text: string) => {
      const prompt = text.trim();
      if (!prompt || busy) return;
      setInput("");
      setBusy(true);
      const assistantId = nextId();
      let assistantOpen = false;
      setItems((prev) => [...prev, { kind: "user", id: nextId(), text: prompt }]);
      scrollToBottom();

      const ensureAssistant = () => {
        if (assistantOpen) return;
        assistantOpen = true;
        setItems((prev) => [...prev, { kind: "assistant", id: assistantId, text: "" }]);
      };

      const onEvent = (e: StreamEvent) => {
        if (e.event === "assistant_delta") {
          ensureAssistant();
          const delta = String((e.payload as { delta?: string }).delta ?? "");
          setItems((prev) =>
            prev.map((it) =>
              it.kind === "assistant" && it.id === assistantId
                ? { ...it, text: it.text + delta }
                : it,
            ),
          );
          scrollToBottom();
        } else if (e.event === "oa_draft") {
          const draft = e.payload as unknown as OaDraft;
          setItems((prev) => [
            ...prev,
            { kind: "draft", id: nextId(), draft, status: "pending" },
          ]);
          scrollToBottom();
        } else if (e.event === "error") {
          ensureAssistant();
          const msg = String((e.payload as { message?: string }).message ?? "出错了");
          setItems((prev) =>
            prev.map((it) =>
              it.kind === "assistant" && it.id === assistantId
                ? { ...it, text: it.text || `**出错：** ${msg}` }
                : it,
            ),
          );
        }
      };

      closeRef.current = openEventStream(
        oaStreamUrl(prompt),
        onEvent,
        () => {
          setBusy(false);
          closeRef.current = null;
        },
        () => {
          setBusy(false);
          closeRef.current = null;
        },
      );
    },
    [busy, scrollToBottom],
  );

  const confirmDraft = useCallback(
    async (id: string) => {
      const item = items.find((it) => it.kind === "draft" && it.id === id) as DraftItem | undefined;
      if (!item) return;
      setItems((prev) =>
        prev.map((it) => (it.kind === "draft" && it.id === id ? { ...it, status: "submitting" } : it)),
      );
      try {
        const d = item.draft;
        let note = "已提交";
        if (d.kind === "task") {
          const task = await createTask({
            title: String(d.title),
            detail: d.detail ? String(d.detail) : undefined,
            priority: d.priority ? String(d.priority) : undefined,
            assignee_name: d.assignee_name ? String(d.assignee_name) : undefined,
          });
          note = task.assignee_name ? `已创建，指派给 ${task.assignee_name}` : "已创建任务";
        } else if (d.kind === "calendar") {
          const ev = await createEvent({
            title: String(d.title),
            start: String(d.start ?? ""),
            end: d.end ? String(d.end) : undefined,
            location: d.location ? String(d.location) : undefined,
            attendees: Array.isArray(d.attendees) ? (d.attendees as string[]) : undefined,
          });
          note = `已创建日程：${new Date(ev.start_at * 1000).toLocaleString()}`;
        } else {
          const appr = await createApproval({
            type: String(d.type ?? "general"),
            title: String(d.title),
            fields: (d.fields as Record<string, unknown>) ?? {},
          });
          const approver = appr.steps[0]?.approver_name ?? "";
          note = approver ? `已提交，待 ${approver} 审批` : "已提交";
        }
        setItems((prev) =>
          prev.map((it) =>
            it.kind === "draft" && it.id === id ? { ...it, status: "submitted", note } : it,
          ),
        );
      } catch (e) {
        setItems((prev) =>
          prev.map((it) =>
            it.kind === "draft" && it.id === id
              ? { ...it, status: "error", note: localizeError(e, locale) }
              : it,
          ),
        );
      }
    },
    [items, locale],
  );

  const cancelDraft = useCallback((id: string) => {
    setItems((prev) => prev.filter((it) => !(it.kind === "draft" && it.id === id)));
  }, []);

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 ml-1">
          <Sparkles size={15} className="text-accent" />
          <span className="text-sm font-medium">{t.oaCopilot}</span>
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {items.length === 0 ? (
          <div className="max-w-md mx-auto mt-10 text-center space-y-4">
            <Sparkles size={28} className="text-accent mx-auto" />
            <p className="text-sm text-fg-muted">
              我是企业 OA 助手，可以帮你起草审批、查询待办，也保留了营销文案 / 数据 / 研究能力。
            </p>
            <div className="space-y-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="btn-ghost w-full justify-start text-left px-3 py-2 text-sm border border-border rounded-lg"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {items.map((it) =>
          it.kind === "draft" ? (
            <DraftCard
              key={it.id}
              item={it}
              onConfirm={() => confirmDraft(it.id)}
              onCancel={() => cancelDraft(it.id)}
            />
          ) : (
            <div
              key={it.id}
              className={it.kind === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[80%] px-3.5 py-2 rounded-2xl text-sm whitespace-pre-wrap leading-relaxed ${
                  it.kind === "user"
                    ? "bg-accent/15 text-fg"
                    : "bg-bg-elevated text-fg"
                }`}
              >
                {it.text || (busy ? "…" : "")}
              </div>
            </div>
          ),
        )}
      </div>

      <div className="border-t border-border p-3 flex items-center gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          placeholder="试试：帮我请 3 天年假 / 我还有哪些待审批"
          className="flex-1 h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
        />
        <button
          onClick={() => send(input)}
          disabled={busy || !input.trim()}
          className="btn-accent h-9 w-9 disabled:opacity-40"
          aria-label="发送"
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  );
}

function DraftCard({
  item,
  onConfirm,
  onCancel,
}: {
  item: DraftItem;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { draft, status, note } = item;
  const kindLabel = DRAFT_KIND_LABEL[draft.kind] ?? "草稿";
  const rows = draftRows(draft);
  const badge =
    draft.kind === "approval" ? APPROVAL_TYPE_LABEL[String(draft.type)] ?? String(draft.type) : null;
  const confirmLabel = draft.kind === "approval" ? "确认提交" : "确认创建";
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] w-full border border-border rounded-xl p-4 bg-bg-subtle">
        <div className="flex items-center gap-2 mb-3">
          <FileCheck2 size={16} className="text-accent" />
          <span className="text-sm font-medium">
            {kindLabel} · {draft.title}
          </span>
          {badge ? (
            <span className="ml-auto text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-600">
              {badge}
            </span>
          ) : null}
        </div>
        <dl className="text-[13px] space-y-1.5">
          {rows.map(([k, v]) => (
            <div key={k} className="flex gap-3">
              <dt className="text-fg-muted w-24 shrink-0">{k}</dt>
              <dd className="text-fg break-words">{v}</dd>
            </div>
          ))}
        </dl>

        {status === "submitted" ? (
          <div className="mt-3 pt-3 border-t border-border flex items-center gap-2 text-sm text-green-600">
            <CheckCircle2 size={15} />
            <span>{note}</span>
          </div>
        ) : status === "error" ? (
          <div className="mt-3 pt-3 border-t border-border flex items-center gap-2 text-sm text-danger">
            <XCircle size={15} />
            <span>{note}</span>
          </div>
        ) : (
          <div className="mt-3 pt-3 border-t border-border flex gap-2">
            <button
              onClick={onConfirm}
              disabled={status === "submitting"}
              className="btn-accent h-8 px-3 text-sm disabled:opacity-50"
            >
              {status === "submitting" ? <Loader2 size={14} className="animate-spin" /> : null}
              {confirmLabel}
            </button>
            <button onClick={onCancel} className="btn-ghost h-8 px-3 text-sm border border-border">
              取消
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
