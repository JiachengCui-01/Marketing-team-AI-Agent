"use client";

import {
  Loader2,
  PenLine,
  BarChart3,
  Search,
  CheckCircle2,
  AlertCircle,
  Cpu,
  FileText,
  type LucideIcon,
} from "lucide-react";
import type { TraceEvent } from "./preview-panel";

const SPECIALIST_LABEL: Record<string, { label: string; icon: LucideIcon }> = {
  delegate_to_content_agent: { label: "Content agent", icon: PenLine },
  delegate_to_analytics_agent: { label: "Analytics agent", icon: BarChart3 },
  delegate_to_research_agent: { label: "Research agent", icon: Search },
};

export type StatusInfo = {
  label: string;
  icon: LucideIcon;
  tone: "working" | "ok" | "error";
};

export function deriveStatus(events: TraceEvent[]): StatusInfo {
  // Pick the most recent meaningful event for the status chip.
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    const t = e.event;
    if (t === "delegating") {
      const name = e.payload.specialist as string;
      const meta = SPECIALIST_LABEL[name];
      return {
        label: meta ? `Delegating to ${meta.label}…` : `Delegating to ${name}…`,
        icon: meta?.icon ?? Cpu,
        tone: "working",
      };
    }
    if (t === "specialist_done") {
      const name = e.payload.specialist as string;
      const meta = SPECIALIST_LABEL[name];
      return {
        label: meta ? `${meta.label} returned` : `${name} returned`,
        icon: CheckCircle2,
        tone: "ok",
      };
    }
    if (t === "specialist_error") {
      return {
        label: `${e.payload.specialist} failed`,
        icon: AlertCircle,
        tone: "error",
      };
    }
    if (t === "orchestrator_response") {
      return {
        label: "Synthesizing response…",
        icon: Cpu,
        tone: "working",
      };
    }
    if (t === "artifact_created") {
      return {
        label: `Generating ${String(e.payload.filename ?? "file")}…`,
        icon: FileText,
        tone: "working",
      };
    }
  }
  return { label: "Thinking…", icon: Loader2, tone: "working" };
}

export function StatusChip({ status }: { status: StatusInfo }) {
  const Icon = status.icon;
  const toneCls =
    status.tone === "error"
      ? "text-danger border-danger/30 bg-danger/10"
      : status.tone === "ok"
        ? "text-success border-success/30 bg-success/5"
        : "text-accent border-accent/30 bg-accent/5";
  const spin = status.tone === "working";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium ${toneCls}`}
    >
      <Icon size={12} className={spin ? "animate-spin" : ""} />
      <span>{status.label}</span>
    </span>
  );
}
