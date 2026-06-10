"use client";

import {
  Activity,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  Cpu,
  PenLine,
  BarChart3,
  Search,
  type LucideIcon,
} from "lucide-react";
import type { StreamEvent } from "@/lib/sse";

export type TraceEvent = StreamEvent & { ts: number };

const SPECIALIST_META: Record<
  string,
  { label: string; icon: LucideIcon }
> = {
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

export function TracePanel({
  events,
  totals,
}: {
  events: TraceEvent[];
  totals: { input: number; output: number };
}) {
  return (
    <aside className="hidden lg:flex flex-col w-80 shrink-0 border-l border-border bg-bg-subtle/40">
      <header className="px-4 py-3 border-b border-border flex items-center gap-2">
        <Activity size={16} className="text-accent" />
        <h2 className="text-sm font-semibold tracking-tight">Agent trace</h2>
        <span className="ml-auto text-[11px] text-fg-subtle">live</span>
      </header>

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
    </aside>
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
          <p className="mt-1.5 text-[11px] text-fg-muted line-clamp-3">
            {task}
          </p>
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
          <span>
            {specialistLabel(payload.specialist as string)} failed
          </span>
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
            orchestrator {String(payload.stop_reason)} · in={" "}
            {usage?.input_tokens ?? 0} out={usage?.output_tokens ?? 0}
          </span>
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
