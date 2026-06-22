"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
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
  PanelRight,
  PanelRightClose,
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
}: {
  events: TraceEvent[];
  totals: { input: number; output: number };
  preview: PreviewItem | null;
  defaultTab?: "preview" | "trace";
  collapsed: boolean;
  width?: number;
  onToggle: () => void;
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
      <aside className="hidden lg:flex flex-col items-center w-12 shrink-0 border-l border-border bg-bg-subtle/40 py-2">
        <button
          onClick={onToggle}
          className="w-9 h-9 inline-flex items-center justify-center rounded-md hover:bg-bg-elevated text-fg-muted"
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
      className="hidden lg:flex flex-col shrink-0 border-l border-border bg-bg-subtle/40"
      style={{ width: width ?? 384 }}
    >
      <header className="px-2 py-2 border-b border-border flex items-center gap-1">
        <TabButton active={tab === "preview"} onClick={() => setTab("preview")} icon={Eye} label={t.preview} />
        <TabButton active={tab === "trace"} onClick={() => setTab("trace")} icon={Activity} label={t.trace} />
        <span className="ml-auto text-[10px] text-fg-subtle pr-2">
          {tab === "trace" ? t.live : preview ? preview.filename : t.noPreview}
        </span>
        <button
          onClick={onToggle}
          className="w-8 h-8 inline-flex items-center justify-center rounded-md hover:bg-bg-elevated text-fg-muted"
          aria-label={t.collapsePreview}
          title={t.collapsePreview}
        >
          <PanelRightClose size={14} />
        </button>
      </header>

      {tab === "preview" ? (
        <PreviewBody item={preview} />
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

function PreviewBody({ item }: { item: PreviewItem | null }) {
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
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-accent text-accent-fg text-xs font-medium hover:opacity-90 transition"
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
          <div className="w-full h-full flex items-center justify-center overflow-auto p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={previewUrl} alt={item.filename} className="max-w-full max-h-full object-contain" />
          </div>
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
  if (!rows) return <p className="p-4 text-xs text-fg-subtle">{t.csvLoading}</p>;

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
  return (
    <>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {events.length === 0 ? (
          <p className="text-xs text-fg-subtle px-2 py-6 text-center">{t.traceEmpty}</p>
        ) : (
          events.map((e, i) => <TraceItem key={i} event={e} />)
        )}
      </div>
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

function TraceItem({ event }: { event: TraceEvent }) {
  const { t } = useI18n();
  const { event: type, payload } = event;

  if (type === "started") {
    return (
      <div className="rounded-lg border border-border/60 bg-bg-elevated/60 px-3 py-2 animate-fade-in">
        <div className="flex items-center gap-2 text-[11px] text-fg-muted">
          <Cpu size={12} />
          <span>{t.connected}</span>
        </div>
      </div>
    );
  }

  if (type === "delegating") {
    const name = payload.specialist as string;
    const Icon = specialistIcon(name);
    const input = payload.input as Record<string, unknown> | undefined;
    const task = input?.task as string | undefined;
    return (
      <div className="rounded-lg border border-border bg-bg-elevated p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-accent">
          <ChevronRight size={14} />
          <Icon size={14} />
          <span>{t.delegating} {specialistLabel(name, t)}</span>
        </div>
        {task ? <p className="mt-1.5 text-[11px] text-fg-muted line-clamp-3">{task}</p> : null}
      </div>
    );
  }

  if (type === "specialist_done") {
    const name = payload.specialist as string;
    const chars = payload.chars as number;
    return (
      <div className="rounded-lg border border-border bg-bg-elevated p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-success">
          <CheckCircle2 size={14} />
          <span>{specialistLabel(name, t)} {t.specialistReturned}</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-subtle">{chars} {t.chars}</p>
      </div>
    );
  }

  if (type === "specialist_error") {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-danger">
          <AlertCircle size={14} />
          <span>{specialistLabel(payload.specialist as string, t)} {t.specialistFailed}</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-muted">{String(payload.error ?? "")}</p>
      </div>
    );
  }

  if (type === "orchestrator_response") {
    const usage = payload.usage as { input_tokens?: number; output_tokens?: number } | undefined;
    return (
      <div className="rounded-lg border border-border/60 bg-bg-elevated/60 px-3 py-2 animate-fade-in">
        <div className="flex items-center gap-2 text-[11px] text-fg-muted">
          <Cpu size={12} />
          <span>
            {t.orchestrator} {String(payload.stop_reason)} · {t.tokensShortIn}={usage?.input_tokens ?? 0} {t.tokensShortOut}={usage?.output_tokens ?? 0}
          </span>
        </div>
      </div>
    );
  }

  if (type === "artifact_created") {
    return (
      <div className="rounded-lg border border-accent/40 bg-accent/10 p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-accent">
          <FileText size={14} />
          <span>{t.artifactReady}: {String(payload.filename)}</span>
        </div>
      </div>
    );
  }

  if (type === "error") {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-danger">
          <AlertCircle size={14} />
          <span>{t.error}</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-muted">{String(payload.message ?? "")}</p>
      </div>
    );
  }

  if (type === "cancelled") {
    return (
      <div className="rounded-lg border border-border bg-bg-elevated p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-fg-muted">
          <AlertCircle size={14} />
          <span>{t.streamCancelled}</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-muted">{String(payload.message ?? "")}</p>
      </div>
    );
  }

  return null;
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
