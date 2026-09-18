"use client";

import { useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { ChartLineUp, Compass, Newspaper, Robot } from "@phosphor-icons/react";
import { NewsPanel } from "@/components/news-panel";
import { MarketOverviewPanel } from "@/components/market/overview-panel";
import { MarketCategoryPanel } from "@/components/market/category-panel";
import { useI18n } from "@/lib/i18n";

type Tab = "news" | "discovery" | "category";
type Drill = { nodeKey: string; label: string } | null;

/** The Automation entry: scheduled analysis that runs on its own timer.
 *
 * Owns the column header and the tab switch; each sub-panel renders body-only so
 * every tab shares one header, one toolbar rhythm, and one set of transitions
 * across every theme.
 *
 * The `drill` state is the whole 全盘 → 品类 path: the discovery board hands a node
 * up, this shell switches tabs, and the deep dive opens on it. Lifting one value
 * here is cheaper than a router or a shared store for a two-surface hop.
 *
 * A tab is mounted on first visit and then kept mounted, hidden. Switching used
 * to unmount the panel, so the return leg of that hop threw away everything the
 * reader had built up on the discovery board — scroll position, the 月度/当下
 * switch, the report itself — and re-fetched it, dropping them back at the top
 * of a long report to scroll for the row they had just clicked.
 */
export function AutomationPanel({ onBack }: { onBack: () => void }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("news");
  const [drill, setDrill] = useState<Drill>(null);
  // Which tabs exist in the DOM. Written during render on purpose: the tab being
  // rendered is by definition visited, and nothing re-renders off this.
  const mounted = useRef<Set<Tab>>(new Set<Tab>([tab]));
  mounted.current.add(tab);

  const tabs: { id: Tab; label: string; icon: typeof Newspaper; tone: string }[] = [
    { id: "news", label: t.automationTabNews, icon: Newspaper, tone: "text-feature-news" },
    {
      id: "discovery",
      label: t.automationTabDiscovery,
      icon: Compass,
      tone: "text-feature-selection",
    },
    {
      id: "category",
      label: t.automationTabCategory,
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

      {/* One wrapper per tab, all of them alive once visited. `display: none`
          keeps the scroll offsets of what is inside, and replays the enter
          animation when the wrapper comes back — which is what the `key` used
          to buy, minus the remount. */}
      {tabs.map(({ id }) =>
        mounted.current.has(id) ? (
          <div
            key={id}
            className={
              tab === id
                ? "flex min-h-0 flex-1 animate-automation-switch flex-col"
                : "hidden"
            }
            role="tabpanel"
            aria-hidden={tab !== id}
          >
            {id === "news" ? (
              <NewsPanel />
            ) : id === "discovery" ? (
              <MarketOverviewPanel
                onDrill={(node) => {
                  setDrill(node);
                  setTab("category");
                }}
              />
            ) : (
              <MarketCategoryPanel initialNode={drill} />
            )}
          </div>
        ) : null,
      )}
    </div>
  );
}
