"use client";

import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Newspaper, ChartLineUp, Robot } from "@phosphor-icons/react";
import { NewsPanel } from "@/components/news-panel";
import { SelectionPanel } from "@/components/selection-panel";
import { useI18n } from "@/lib/i18n";

type Tab = "news" | "selection";

/** The Automation entry: scheduled analysis jobs that run on their own timer.
 *
 * Owns the column header and the tab switch; each sub-panel renders body-only so
 * both tabs share one header, one toolbar rhythm, and one set of transitions
 * across every theme. */
export function AutomationPanel({ onBack }: { onBack: () => void }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("news");

  const tabs: { id: Tab; label: string; icon: typeof Newspaper; tone: string }[] = [
    { id: "news", label: t.automationTabNews, icon: Newspaper, tone: "text-feature-news" },
    {
      id: "selection",
      label: t.automationTabSelection,
      icon: ChartLineUp,
      tone: "text-feature-selection",
    },
  ];

  return (
    <div className="panel-card flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="col-header !grid grid-cols-[1fr_auto_1fr]">
        <button
          onClick={onBack}
          className="btn-ghost justify-self-start px-2.5 py-1.5 text-sm"
        >
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 justify-self-center text-sm font-medium">
          <Robot size={15} weight="duotone" className="text-feature-selection" />
          <span>{t.automation}</span>
        </div>
        <div className="seg justify-self-end" role="tablist" aria-label={t.automation}>
          {tabs.map(({ id, label, icon: Icon, tone }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(id)}
                className={`seg-item ${active ? "seg-item-active" : ""}`}
              >
                <Icon
                  size={13}
                  weight="duotone"
                  className={active ? tone : "text-fg-subtle"}
                />
                <span>{label}</span>
              </button>
            );
          })}
        </div>
      </header>

      {/* Keyed so switching tabs replays the same enter animation both ways. */}
      <div key={tab} className="flex min-h-0 flex-1 animate-automation-switch flex-col">
        {tab === "news" ? <NewsPanel /> : <SelectionPanel />}
      </div>
    </div>
  );
}
