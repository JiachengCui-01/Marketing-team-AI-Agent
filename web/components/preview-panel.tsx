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
  return (
    <>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {events.length === 0 ? (
          <p className="text-xs text-fg-subtle px-2 py-6 text-center">{t.traceEmpty}</p>
        ) : (
          events.map((e, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setExpanded(e)}
              className="block w-full text-left cursor-pointer rounded-xl hover-lift"
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

function TraceDetailModal({ event, onClose }: { event: TraceEvent; onClose: () => void }) {
  const { t } = useI18n();
  const { event: type, payload } = event;

  let heading = String(type);
  let body = "";

  if (type === "started") {
    heading = t.connected;
  } else if (type === "delegating") {
    const input = payload.input as Record<string, unknown> | undefined;
    heading = `${t.delegating} ${specialistLabel(payload.specialist as string, t)}`;
    body = String(input?.task ?? "");
  } else if (type === "specialist_done") {
    heading = `${specialistLabel(payload.specialist as string, t)} ${t.specialistReturned}`;
    body = `${payload.chars} ${t.chars}`;
  } else if (type === "specialist_error") {
    heading = `${specialistLabel(payload.specialist as string, t)} ${t.specialistFailed}`;
    body = String(payload.error ?? "");
  } else if (type === "orchestrator_response") {
    const usage = payload.usage as { input_tokens?: number; output_tokens?: number } | undefined;
    heading = t.orchestrator;
    body = `${payload.stop_reason}\n${t.tokensShortIn}=${usage?.input_tokens ?? 0} ${t.tokensShortOut}=${usage?.output_tokens ?? 0}`;
  } else if (type === "artifact_created") {
    heading = t.artifactReady;
    body = String(payload.filename ?? "");
  } else if (type === "error") {
    heading = t.error;
    body = String(payload.message ?? "");
  } else if (type === "cancelled") {
    heading = t.streamCancelled;
    body = String(payload.message ?? "");
  }

  const raw = JSON.stringify(payload, null, 2);

  return (
    <Modal title={t.traceDetailTitle} onClose={onClose} wide>
      <p className="text-sm font-medium text-fg">{heading}</p>
      {body ? (
        <div className="mt-3 whitespace-pre-wrap break-words rounded-lg border border-border bg-bg p-3 text-xs text-fg-muted max-h-[50vh] overflow-y-auto">
          {body}
        </div>
      ) : null}
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-fg-subtle hover:text-fg">{t.traceRaw}</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg border border-border bg-bg p-3 text-[11px] text-fg-muted max-h-[40vh] overflow-y-auto">
          {raw}
        </pre>
      </details>
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
