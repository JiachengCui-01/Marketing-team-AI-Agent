"use client";

import {
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Cpu,
  FileText,
  Loader2,
  PenLine,
  Search,
  type LucideIcon,
} from "lucide-react";
import type { I18nText } from "@/lib/i18n";
import type { TraceEvent } from "./preview-panel";

const SPECIALIST_LABEL: Record<
  string,
  { key: "contentAgent" | "analyticsAgent" | "researchAgent"; icon: LucideIcon }
> = {
  delegate_to_content_agent: { key: "contentAgent", icon: PenLine },
  delegate_to_analytics_agent: { key: "analyticsAgent", icon: BarChart3 },
  delegate_to_research_agent: { key: "researchAgent", icon: Search },
};

export type StatusInfo = {
  label: string;
  icon: LucideIcon;
  tone: "working" | "ok" | "error";
};

export function deriveStatus(events: TraceEvent[], t: I18nText): StatusInfo {
  // Pick the most recent meaningful event for the status chip.
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    const type = event.event;
    if (type === "started") {
      return {
        label: `${t.connected} ${t.startingWork}`,
        icon: Loader2,
        tone: "working",
      };
    }
    if (type === "delegating") {
      const name = event.payload.specialist as string;
      const meta = SPECIALIST_LABEL[name];
      return {
        label: meta ? `${t.delegating} ${t[meta.key]}...` : `${t.delegating} ${name}...`,
        icon: meta?.icon ?? Cpu,
        tone: "working",
      };
    }
    if (type === "specialist_done") {
      const name = event.payload.specialist as string;
      const meta = SPECIALIST_LABEL[name];
      return {
        label: meta ? `${t[meta.key]} ${t.specialistReturned}` : `${name} ${t.specialistReturned}`,
        icon: CheckCircle2,
        tone: "ok",
      };
    }
    if (type === "specialist_error") {
      return {
        label: `${String(event.payload.specialist ?? t.specialist)} ${t.specialistFailed}`,
        icon: AlertCircle,
        tone: "error",
      };
    }
    if (type === "orchestrator_response") {
      return {
        label: t.synthesizing,
        icon: Cpu,
        tone: "working",
      };
    }
    if (type === "artifact_created") {
      return {
        label: `${t.generating} ${String(event.payload.filename ?? "file")}...`,
        icon: FileText,
        tone: "working",
      };
    }
  }
  return { label: t.thinking, icon: Loader2, tone: "working" };
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
