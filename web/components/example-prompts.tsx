"use client";

import { PenLine, BarChart3, Search } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function ExamplePrompts({
  onPick,
}: {
  onPick: (prompt: string, requiresCsv?: boolean) => void;
}) {
  const { t } = useI18n();
  const examples = [
    { icon: PenLine, label: t.draftContent, prompt: t.draftContentPrompt },
    { icon: BarChart3, label: t.analyzeData, prompt: t.analyzeDataPrompt, requiresCsv: true },
    { icon: Search, label: t.researchCompetitors, prompt: t.researchCompetitorsPrompt },
  ];
  return (
    <div className="grid sm:grid-cols-3 gap-3 max-w-3xl w-full">
      {examples.map((ex) => {
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
                {t.needsCsv}
              </div>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
