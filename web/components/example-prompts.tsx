"use client";

import { PenLine, BarChart3, Search } from "lucide-react";

const EXAMPLES = [
  {
    icon: PenLine,
    label: "Draft content",
    prompt:
      "Write 3 confident LinkedIn posts announcing our new AI-powered campaign analytics feature.",
  },
  {
    icon: BarChart3,
    label: "Analyze campaign data",
    prompt:
      "Analyze last week's campaign performance and tell me which channels to scale.",
    requiresCsv: true,
  },
  {
    icon: Search,
    label: "Research competitors",
    prompt:
      "What did HubSpot and Marketo announce recently? Summarize their positioning shifts.",
  },
];

export function ExamplePrompts({
  onPick,
}: {
  onPick: (prompt: string, requiresCsv?: boolean) => void;
}) {
  return (
    <div className="grid sm:grid-cols-3 gap-3 max-w-3xl w-full">
      {EXAMPLES.map((ex) => {
        const Icon = ex.icon;
        return (
          <button
            key={ex.label}
            onClick={() => onPick(ex.prompt, ex.requiresCsv)}
            className="text-left rounded-xl border border-border bg-bg-elevated hover:border-accent/60 hover:bg-bg-subtle transition p-4 group"
          >
            <Icon size={18} className="text-accent mb-2" />
            <div className="text-sm font-medium mb-1">{ex.label}</div>
            <div className="text-xs text-fg-muted line-clamp-3">
              {ex.prompt}
            </div>
            {ex.requiresCsv ? (
              <div className="text-[10px] text-fg-subtle mt-2">
                needs an attached CSV
              </div>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
