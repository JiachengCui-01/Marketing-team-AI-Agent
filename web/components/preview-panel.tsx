"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  CircleDot,
  Cpu,
  PenLine,
  BarChart3,
  Search,
  Download,
  FileText,
  FileImage,
  FileSpreadsheet,
  File as FileIcon,
  Eye,
  Layers3,
  PanelRight,
  PanelRightClose,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import type { StreamEvent } from "@/lib/sse";
import {
  artifactDownloadUrl,
  artifactPreviewUrl,
  uploadDownloadUrl,
  uploadPreviewUrl,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Skeleton } from "@/components/ui/skeleton";
import { Modal } from "@/components/modal";

export type TraceEvent = StreamEvent & { ts: number };

export type PreviewItem =
  | { source: "artifact"; id: string; filename: string; mime: string }
  | { source: "upload"; id: string; filename: string; mime: string };

const SPECIALIST_META: Record<string, { key: "content" | "analytics" | "research"; icon: LucideIcon }> = {
  delegate_to_content_agent: { key: "content", icon: PenLine },
  delegate_to_analytics_agent: { key: "analytics", icon: BarChart3 },
  delegate_to_research_agent: { key: "research", icon: Search },
};

function specialistLabel(name: string | undefined, t: ReturnType<typeof useI18n>["t"]) {
  if (!name) return t.specialist;
  const meta = SPECIALIST_META[name];
  if (!meta) return name;
  if (meta.key === "content") return t.draftContent;
  if (meta.key === "analytics") return t.analyzeData;
  return t.researchCompetitors;
}

function specialistIcon(name?: string) {
  if (!name) return Cpu;
  return SPECIALIST_META[name]?.icon ?? Cpu;
}

export function PreviewPanel({
  events,
  totals,
  preview,
  defaultTab,
  collapsed,
  width,
  onToggle,
  onDownloadArtifact,
}: {
  events: TraceEvent[];
  totals: { input: number; output: number };
  preview: PreviewItem | null;
  defaultTab?: "preview" | "trace";
  collapsed: boolean;
  width?: number;
  onToggle: () => void;
  onDownloadArtifact?: (item: Extract<PreviewItem, { source: "artifact" }>) => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"preview" | "trace">(
    defaultTab ?? (preview ? "preview" : "trace"),
  );
  const lastIdRef = useRef<string | null>(null);

  useEffect(() => {
    const id = preview ? `${preview.source}:${preview.id}` : null;
    if (id && id !== lastIdRef.current) setTab("preview");
    lastIdRef.current = id;
  }, [preview]);

  if (collapsed) {
    return (
      <aside className="hidden lg:flex flex-col items-center w-12 shrink-0 py-2 panel-card">
        <button
          onClick={onToggle}
          className="btn-ghost w-9 h-9"
          aria-label={t.expandPreview}
          title={t.expandPreview}
        >
          <PanelRight size={16} />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className="hidden lg:flex flex-col shrink-0 panel-card"
      style={{ width: width ?? 384 }}
    >
      <header className="col-header !gap-1">
        <TabButton active={tab === "preview"} onClick={() => setTab("preview")} icon={Eye} label={t.preview} />
        <TabButton active={tab === "trace"} onClick={() => setTab("trace")} icon={Activity} label={t.trace} />
        <span className="ml-auto text-[10px] text-fg-subtle pr-2">
          {tab === "trace" ? t.live : preview ? preview.filename : t.noPreview}
        </span>
        <button
          onClick={onToggle}
          className="btn-ghost w-8 h-8"
          aria-label={t.collapsePreview}
          title={t.collapsePreview}
        >
          <PanelRightClose size={14} />
        </button>
      </header>

      {tab === "preview" ? (
        <PreviewBody item={preview} onDownloadArtifact={onDownloadArtifact} />
      ) : (
        <TraceBody events={events} totals={totals} />
      )}
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: LucideIcon;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
        active
          ? "bg-bg-elevated text-fg border border-border"
          : "text-fg-muted hover:text-fg hover:bg-bg-elevated/60"
      }`}
    >
      <Icon size={13} />
      <span>{label}</span>
    </button>
  );
}

function iconForMime(mime: string): LucideIcon {
  if (mime.startsWith("image/")) return FileImage;
  if (mime === "application/pdf") return FileText;
  if (mime.includes("csv") || mime.includes("excel") || mime.includes("spreadsheet")) return FileSpreadsheet;
  return FileIcon;
}

function PreviewBody({
  item,
  onDownloadArtifact,
}: {
  item: PreviewItem | null;
  onDownloadArtifact?: (item: Extract<PreviewItem, { source: "artifact" }>) => void;
}) {
  const { t } = useI18n();
  if (!item) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center max-w-xs">
          <Eye size={28} className="mx-auto text-fg-subtle mb-3" />
          <p className="text-sm text-fg-muted">{t.previewEmptyTitle}</p>
          <p className="mt-2 text-xs text-fg-subtle">{t.previewEmptyBody}</p>
        </div>
      </div>
    );
  }

  const previewUrl = item.source === "artifact" ? artifactPreviewUrl(item.id) : uploadPreviewUrl(item.id);
  const downloadUrl = item.source === "artifact" ? artifactDownloadUrl(item.id) : uploadDownloadUrl(item.id);
  const Icon = iconForMime(item.mime);

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-3 py-2 border-b border-border flex items-center gap-2">
        <Icon size={14} className="text-accent shrink-0" />
        <span className="text-xs font-medium truncate flex-1" title={item.filename}>
          {item.filename}
        </span>
        <a
          href={downloadUrl}
          download={item.filename}
          onClick={(event) => {
            if (item.source !== "artifact" || !onDownloadArtifact) return;
            event.preventDefault();
            onDownloadArtifact(item);
          }}
          className="btn-accent px-2.5 py-1 text-xs"
          title={t.download}
        >
          <Download size={12} />
          <span>{t.download}</span>
        </a>
      </div>
      <div className="flex-1 overflow-hidden bg-bg">
        {item.mime === "application/pdf" ? (
          <iframe src={previewUrl} title={item.filename} className="w-full h-full border-0" />
        ) : item.mime.startsWith("image/") ? (
          <PreviewImage src={previewUrl} alt={item.filename} />
        ) : item.mime === "text/csv" ? (
          <CsvPreview url={previewUrl} />
        ) : (
          <div className="p-6 text-center">
            <Icon size={32} className="mx-auto text-fg-subtle mb-3" />
            <p className="text-sm text-fg-muted">{item.filename}</p>
            <p className="mt-1 text-xs text-fg-subtle">{t.noInlinePreview}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function PreviewImage({ src, alt }: { src: string; alt: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="relative w-full h-full flex items-center justify-center overflow-auto p-4">
      {!loaded ? <Skeleton variant="preview" className="absolute inset-4 rounded-xl" /> : null}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        decoding="async"
        onLoad={() => setLoaded(true)}
        className={`max-w-full max-h-full object-contain rounded-lg transition-opacity duration-200 ${
          loaded ? "opacity-100" : "opacity-0"
        }`}
      />
    </div>
  );
}

function CsvPreview({ url }: { url: string }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<string[][] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setErr(null);
    fetch(url)
      .then((r) => r.text())
      .then((text) => {
        if (cancelled) return;
        const lines = text.split(/\r?\n/).slice(0, 50);
        setRows(lines.map((l) => l.split(",")));
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (err) return <p className="p-4 text-xs text-danger">{err}</p>;
  if (!rows)
    return (
      <div className="space-y-1.5 p-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} variant="preview" className="h-5 w-full" />
        ))}
      </div>
    );

  const [header, ...body] = rows;
  return (
    <div className="overflow-auto p-2 text-xs">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {header?.map((h, i) => (
              <th key={i} className="text-left border-b border-border px-2 py-1 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.slice(0, 49).map((row, i) => (
            <tr key={i} className="hover:bg-bg-elevated/50">
              {row.map((c, j) => (
                <td key={j} className="border-b border-border/40 px-2 py-1 text-fg-muted">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length >= 49 ? <p className="text-fg-subtle mt-2">{t.csvTruncated}</p> : null}
    </div>
  );
}

function TraceBody({
  events,
  totals,
}: {
  events: TraceEvent[];
  totals: { input: number; output: number };
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<TraceEvent | null>(null);
  const visibleEvents = events.filter(isVisibleTraceEvent);
  return (
    <>
      <div className="trace-flow flex-1 overflow-y-auto px-3 py-2">
        {visibleEvents.length === 0 ? (
          <p className="text-xs text-fg-subtle px-2 py-6 text-center">{t.traceEmpty}</p>
        ) : (
          visibleEvents.map((e, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setExpanded(e)}
              className="trace-node group block w-full text-left cursor-pointer"
              title={t.traceDetailHint}
            >
              <TraceItem event={e} />
            </button>
          ))
        )}
      </div>
      {expanded ? <TraceDetailModal event={expanded} onClose={() => setExpanded(null)} /> : null}
      <footer className="px-4 py-3 border-t border-border text-[11px] text-fg-muted flex justify-between">
        <span>
          {t.tokensIn}: <strong className="text-fg">{totals.input}</strong>
        </span>
        <span>
          {t.tokensOut}: <strong className="text-fg">{totals.output}</strong>
        </span>
      </footer>
    </>
  );
}

function isVisibleTraceEvent(event: TraceEvent) {
  return ![
    "assistant_delta",
    "result",
    "heartbeat",
    "orchestrator_response",
    "delegating",
    "oa_sources", // data event for source capsules, not a trace step
    "oa_draft", // data event for draft cards, not a trace step
  ].includes(event.event);
}

type TraceTone = "orchestrator" | "content" | "analytics" | "research" | "success" | "error" | "artifact" | "neutral";

type TraceView = {
  title: string;
  subtitle: string;
  detailTitle: string;
  detail: string;
  method: string;
  tone: TraceTone;
  icon: LucideIcon;
  active?: boolean;
};

function traceView(event: TraceEvent, t: ReturnType<typeof useI18n>["t"]): TraceView {
  const { event: type, payload } = event;
  if (type === "started") {
    return {
      title: t.connected,
      subtitle: t.startingWork,
      detailTitle: t.connected,
      detail: t.startingWork,
      method: "建立实时连接后，系统会开始接收编排器和专家执行过程中的事件。",
      tone: "neutral",
      icon: Cpu,
      active: true,
    };
  }
  if (type === "orchestrator_step") {
    const status = String(payload.status ?? "running");
    return {
      title: String(payload.title ?? t.orchestrator),
      subtitle: String(payload.detail ?? ""),
      detailTitle: String(payload.title ?? t.orchestrator),
      detail: String(payload.detail ?? ""),
      method: orchestratorMethod(String(payload.stage ?? "")),
      tone: status === "done" ? "success" : "orchestrator",
      icon: status === "done" ? CheckCircle2 : Layers3,
      active: status !== "done",
    };
  }
  if (type === "specialist_start") {
    const name = payload.specialist as string;
    const meta = SPECIALIST_META[name];
    return {
      title: `${t.delegating} ${specialistLabel(name, t)}`,
      subtitle: String(payload.task ?? ""),
      detailTitle: specialistLabel(name, t),
      detail: String(payload.task ?? ""),
      method: String(payload.method ?? ""),
      tone: meta?.key ?? "neutral",
      icon: specialistIcon(name),
      active: true,
    };
  }
  if (type === "specialist_done") {
    const name = payload.specialist as string;
    return {
      title: `${specialistLabel(name, t)} ${t.specialistReturned}`,
      subtitle: `${payload.chars ?? 0} ${t.chars}`,
      detailTitle: `${specialistLabel(name, t)} ${t.specialistReturned}`,
      detail: "专家已返回结果，正在交给 Orchestrator 继续判断和汇总。",
      method: "专家先完成各自范围内的分析，再把结论交回编排器统一整合。",
      tone: "success",
      icon: CheckCircle2,
    };
  }
  if (type === "specialist_error") {
    const name = payload.specialist as string;
    return {
      title: `${specialistLabel(name, t)} ${t.specialistFailed}`,
      subtitle: String(payload.error ?? ""),
      detailTitle: `${specialistLabel(name, t)} ${t.specialistFailed}`,
      detail: String(payload.error ?? ""),
      method: "专家执行失败后，Orchestrator 会保留错误信息，并尽量用已有上下文继续处理。",
      tone: "error",
      icon: AlertCircle,
    };
  }
  if (type === "artifact_created") {
    return {
      title: t.artifactReady,
      subtitle: String(payload.filename ?? ""),
      detailTitle: t.artifactReady,
      detail: String(payload.filename ?? ""),
      method: "系统已生成可下载交付物，并把它加入右侧预览与下载区域。",
      tone: "artifact",
      icon: FileText,
    };
  }
  if (type === "error") {
    return {
      title: t.error,
      subtitle: String(payload.message ?? ""),
      detailTitle: t.error,
      detail: String(payload.message ?? ""),
      method: "执行过程中出现错误，请根据错误信息调整输入或稍后重试。",
      tone: "error",
      icon: AlertCircle,
    };
  }
  if (type === "cancelled") {
    return {
      title: t.streamCancelled,
      subtitle: String(payload.message ?? ""),
      detailTitle: t.streamCancelled,
      detail: String(payload.message ?? ""),
      method: "任务已取消，当前请求不会继续消耗模型或工具资源。",
      tone: "neutral",
      icon: AlertCircle,
    };
  }
  return {
    title: String(type),
    subtitle: "",
    detailTitle: String(type),
    detail: "",
    method: "记录该事件用于追踪执行过程，便于理解系统当前状态。",
    tone: "neutral",
    icon: CircleDot,
  };
}

function orchestratorMethod(stage: string) {
  if (stage === "intake") return "读取用户请求、附件和已选 skill，判断任务需要哪些能力。";
  if (stage === "planning") return "规划下一步执行路径：继续分派专家、等待结果，或进入最终汇总。";
  if (stage === "dispatch") return "把任务拆给合适的专家代理，让不同能力并行或分步处理。";
  if (stage === "review") return "检查专家返回内容，判断信息是否足够生成最终答案。";
  if (stage === "synthesis") return "整合专家结论、引用和交付物说明，生成最终回复。";
  return "记录当前执行阶段，帮助用户理解系统正在做什么。";
}

function TraceItem({ event }: { event: TraceEvent }) {
  const { t } = useI18n();
  const view = traceView(event, t);
  const Icon = view.icon;

  return (
    <div className={`trace-card trace-card-${view.tone} ${view.active ? "trace-card-active" : ""}`}>
      <span className={`trace-dot trace-dot-${view.tone}`} aria-hidden>
        <Icon size={13} className={view.active ? "animate-pulse" : ""} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-xs font-semibold text-fg">{view.title}</p>
          {view.active ? <span className="trace-live-pill">{t.live}</span> : null}
        </div>
        {view.subtitle ? <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-fg-muted">{view.subtitle}</p> : null}
      </div>
      <ChevronRight size={13} className="shrink-0 text-fg-subtle transition group-hover:translate-x-0.5 group-hover:text-accent" />
    </div>
  );
}

function TraceDetailModal({ event, onClose }: { event: TraceEvent; onClose: () => void }) {
  const { t } = useI18n();
  const view = traceView(event, t);
  const Icon = view.icon;

  return (
    <Modal title={t.traceDetailTitle} onClose={onClose} wide>
      <div className="flex items-start gap-3">
        <span className={`trace-dot trace-dot-${view.tone} mt-0.5`} aria-hidden>
          <Icon size={14} />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-fg">{view.detailTitle}</p>
          {view.detail ? <p className="mt-1 text-xs leading-relaxed text-fg-muted">{view.detail}</p> : null}
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-border bg-bg p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">工作方法</p>
        <p className="mt-1.5 whitespace-pre-wrap break-words text-xs leading-relaxed text-fg-muted">
          {view.method || "记录该事件用于追踪执行过程，便于理解系统当前状态。"}
        </p>
      </div>
    </Modal>
  );
}
export function classifyTotals(events: TraceEvent[]): {
  input: number;
  output: number;
} {
  let input = 0;
  let output = 0;
  for (const e of events) {
    if (e.event === "orchestrator_response") {
      const usage = e.payload.usage as { input_tokens?: number; output_tokens?: number } | undefined;
      input += usage?.input_tokens ?? 0;
      output += usage?.output_tokens ?? 0;
    }
  }
  return { input, output };
}
