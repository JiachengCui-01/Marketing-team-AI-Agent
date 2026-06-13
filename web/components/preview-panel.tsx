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
  type LucideIcon,
} from "lucide-react";
import type { StreamEvent } from "@/lib/sse";
import {
  artifactDownloadUrl,
  artifactPreviewUrl,
  uploadDownloadUrl,
  uploadPreviewUrl,
} from "@/lib/api";

export type TraceEvent = StreamEvent & { ts: number };

export type PreviewItem =
  | {
      source: "artifact";
      id: string;
      filename: string;
      mime: string;
    }
  | {
      source: "upload";
      id: string;
      filename: string;
      mime: string;
    };

const SPECIALIST_META: Record<string, { label: string; icon: LucideIcon }> = {
  delegate_to_content_agent: { label: "Content agent", icon: PenLine },
  delegate_to_analytics_agent: { label: "Analytics agent", icon: BarChart3 },
  delegate_to_research_agent: { label: "Research agent", icon: Search },
};

function specialistLabel(name?: string) {
  if (!name) return "specialist";
  return SPECIALIST_META[name]?.label ?? name;
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
}: {
  events: TraceEvent[];
  totals: { input: number; output: number };
  preview: PreviewItem | null;
  defaultTab?: "preview" | "trace";
}) {
  const [tab, setTab] = useState<"preview" | "trace">(
    defaultTab ?? (preview ? "preview" : "trace"),
  );

  // Auto-switch to Preview whenever a new item is selected (artifact created or
  // user clicks a file chip). Keyed on the item id so re-selecting the same item
  // after manually switching to Trace won't yank the user back.
  const lastIdRef = useRef<string | null>(null);
  useEffect(() => {
    const id = preview ? `${preview.source}:${preview.id}` : null;
    if (id && id !== lastIdRef.current) {
      setTab("preview");
    }
    lastIdRef.current = id;
  }, [preview]);

  return (
    <aside className="hidden lg:flex flex-col w-96 shrink-0 border-l border-border bg-bg-subtle/40">
      <header className="px-2 py-2 border-b border-border flex items-center gap-1">
        <TabButton
          active={tab === "preview"}
          onClick={() => setTab("preview")}
          icon={Eye}
          label="Preview"
        />
        <TabButton
          active={tab === "trace"}
          onClick={() => setTab("trace")}
          icon={Activity}
          label="Trace"
        />
        <span className="ml-auto text-[10px] text-fg-subtle pr-2">
          {tab === "trace" ? "live" : preview ? preview.filename : "no preview"}
        </span>
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
  if (mime.includes("csv") || mime.includes("excel") || mime.includes("spreadsheet"))
    return FileSpreadsheet;
  return FileIcon;
}

function PreviewBody({ item }: { item: PreviewItem | null }) {
  if (!item) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center max-w-xs">
          <Eye size={28} className="mx-auto text-fg-subtle mb-3" />
          <p className="text-sm text-fg-muted">
            Generated PDFs and uploaded files appear here.
          </p>
          <p className="mt-2 text-xs text-fg-subtle">
            Ask for a PDF deliverable and the result will be previewable
            with a download button — your save location is chosen at
            download time.
          </p>
        </div>
      </div>
    );
  }

  const previewUrl =
    item.source === "artifact"
      ? artifactPreviewUrl(item.id)
      : uploadPreviewUrl(item.id);
  const downloadUrl =
    item.source === "artifact"
      ? artifactDownloadUrl(item.id)
      : uploadDownloadUrl(item.id);
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
          title="Choose a location and download"
        >
          <Download size={12} />
          <span>Download</span>
        </a>
      </div>
      <div className="flex-1 overflow-hidden bg-bg">
        {item.mime === "application/pdf" ? (
          <iframe
            src={previewUrl}
            title={item.filename}
            className="w-full h-full border-0"
          />
        ) : item.mime.startsWith("image/") ? (
          <div className="w-full h-full flex items-center justify-center overflow-auto p-4">
            {/* Dynamic API file previews are intentionally served directly. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewUrl}
              alt={item.filename}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        ) : item.mime === "text/csv" ? (
          <CsvPreview url={previewUrl} />
        ) : (
          <div className="p-6 text-center">
            <Icon size={32} className="mx-auto text-fg-subtle mb-3" />
            <p className="text-sm text-fg-muted">
              {item.filename}
            </p>
            <p className="mt-1 text-xs text-fg-subtle">
              No inline preview for this file type — use Download.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function CsvPreview({ url }: { url: string }) {
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
  if (!rows) return <p className="p-4 text-xs text-fg-subtle">Loading…</p>;

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
      {body.length >= 49 ? (
        <p className="text-fg-subtle mt-2">Preview truncated to first 50 rows.</p>
      ) : null}
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
  return (
    <>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {events.length === 0 ? (
          <p className="text-xs text-fg-subtle px-2 py-6 text-center">
            Specialist activity will appear here in real time.
          </p>
        ) : (
          events.map((e, i) => <TraceItem key={i} event={e} />)
        )}
      </div>
      <footer className="px-4 py-3 border-t border-border text-[11px] text-fg-muted flex justify-between">
        <span>
          tokens in: <strong className="text-fg">{totals.input}</strong>
        </span>
        <span>
          tokens out: <strong className="text-fg">{totals.output}</strong>
        </span>
      </footer>
    </>
  );
}

function TraceItem({ event }: { event: TraceEvent }) {
  const { event: type, payload } = event;

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
          <span>Delegating → {specialistLabel(name)}</span>
        </div>
        {task ? (
          <p className="mt-1.5 text-[11px] text-fg-muted line-clamp-3">{task}</p>
        ) : null}
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
          <span>{specialistLabel(name)} returned</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-subtle">{chars} chars</p>
      </div>
    );
  }

  if (type === "specialist_error") {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-danger">
          <AlertCircle size={14} />
          <span>{specialistLabel(payload.specialist as string)} failed</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-muted">
          {String(payload.error ?? "")}
        </p>
      </div>
    );
  }

  if (type === "orchestrator_response") {
    const usage = payload.usage as
      | { input_tokens?: number; output_tokens?: number }
      | undefined;
    return (
      <div className="rounded-lg border border-border/60 bg-bg-elevated/60 px-3 py-2 animate-fade-in">
        <div className="flex items-center gap-2 text-[11px] text-fg-muted">
          <Cpu size={12} />
          <span>
            orchestrator {String(payload.stop_reason)} · in= {usage?.input_tokens ?? 0}
            {" "}out={usage?.output_tokens ?? 0}
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
          <span>Artifact ready: {String(payload.filename)}</span>
        </div>
      </div>
    );
  }

  if (type === "error") {
    return (
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-danger">
          <AlertCircle size={14} />
          <span>Error</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-muted">
          {String(payload.message ?? "")}
        </p>
      </div>
    );
  }

  if (type === "cancelled") {
    return (
      <div className="rounded-lg border border-border bg-bg-elevated p-3 animate-fade-in">
        <div className="flex items-center gap-2 text-xs font-medium text-fg-muted">
          <AlertCircle size={14} />
          <span>Stream cancelled</span>
        </div>
        <p className="mt-1 text-[11px] text-fg-muted">
          {String(payload.message ?? "The connection was closed.")}
        </p>
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
      const usage = e.payload.usage as
        | { input_tokens?: number; output_tokens?: number }
        | undefined;
      input += usage?.input_tokens ?? 0;
      output += usage?.output_tokens ?? 0;
    }
  }
  return { input, output };
}
