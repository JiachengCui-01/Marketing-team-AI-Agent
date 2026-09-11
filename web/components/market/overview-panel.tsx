"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowSquareOut, ArrowsClockwise, Compass, Database } from "@phosphor-icons/react";

import {
  getMarketBudget,
  getMarketConfig,
  getMarketOverview,
  refreshMarketOverview,
  type MarketBoardRow,
  type MarketConfigResponse,
  type MarketPersona,
  type MarketReport,
} from "@/lib/api";
import { CitationMarkdown } from "@/components/citation-markdown";
import { LoadingCard } from "@/components/ui/spinner";
import { useI18n } from "@/lib/i18n";
import {
  BandHistogram,
  Bullet,
  DeltaBullet,
  Quadrant,
  ScoreBar,
  fmtMoney,
  fmtPct,
} from "@/components/market/charts";
import {
  BiTable,
  ConfidenceNote,
  DataGapCard,
  EvidenceChip,
  GapList,
  KpiRow,
  PersonaToggle,
  Section,
  SectionGate,
  VerdictChip,
  usePersona,
  useScoreLabels,
} from "@/components/market/shared";

/** 全盘发现 — the furniture department, ranked.
 *
 * No category picking here: the system sweeps every tracked node itself and the
 * board is the answer to "where should we be looking". Every row drills into the
 * deep dive, which is the whole point of splitting the two surfaces.
 */
export function MarketOverviewPanel({
  onDrill,
}: {
  onDrill: (node: { nodeKey: string; label: string }) => void;
}) {
  const { t, locale } = useI18n();
  const labels = useScoreLabels();
  const [meta, setMeta] = useState<MarketConfigResponse | null>(null);
  const [persona, setPersona] = usePersona();
  const [report, setReport] = useState<MarketReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "render" | "collect">("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (who: MarketPersona) => {
      setLoading(true);
      setError(null);
      try {
        const [config, overview] = await Promise.all([
          getMarketConfig(who),
          getMarketOverview(who),
        ]);
        setMeta(config);
        setReport(overview.report);
        if (config.config?.persona && config.config.persona !== who) {
          setPersona(config.config.persona as MarketPersona);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(persona);
  }, [load, persona]);

  async function refresh(collect: boolean) {
    setBusy(collect ? "collect" : "render");
    setError(null);
    try {
      const next = await refreshMarketOverview({ persona, collect, language: locale });
      setReport(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  const dashboard = report?.dashboard;
  const sections = dashboard?.sections ?? meta?.sections.overview ?? [];
  const weights = dashboard?.score_model?.category_weights ?? meta?.score_model.category_weights ?? {};

  if (loading) return <LoadingCard label={t.gmTitle} variant="selection" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <Compass size={15} weight="duotone" className="text-feature-selection" />
        <span className="text-sm font-medium">{t.gmTitle}</span>
        <span className="text-[11px] text-fg-subtle">{t.gmSubtitle}</span>
        <div className="ml-auto flex items-center gap-2">
          {meta ? (
            <PersonaToggle personas={meta.personas} value={persona} onChange={setPersona} />
          ) : null}
          <button onClick={() => refresh(false)} disabled={busy !== ""}
                  className="btn-ghost h-8 px-2 text-xs">
            <ArrowsClockwise size={14} weight="duotone" />
            {busy === "render" ? t.gmRefreshing : t.gmRefresh}
          </button>
          <button onClick={() => refresh(true)} disabled={busy !== "" || !meta?.available}
                  title={t.gmCollectHint} className="btn-accent h-8 px-2.5 text-xs">
            <Database size={14} weight="duotone" />
            {busy === "collect" ? t.gmCollecting : t.gmCollect}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
        {meta && !meta.available ? (
          <p className="mb-3 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs">
            {t.gmUnavailable}
          </p>
        ) : null}

        {!report ? (
          <div className="rounded-xl border border-border p-5 text-center">
            <p className="text-sm font-medium">{t.gmEmpty}</p>
            <p className="mt-1 text-xs text-fg-muted">{t.gmEmptyHint}</p>
          </div>
        ) : report.status === "data_gap" ? (
          <DataGapCard summary={report.summary} onRetry={() => refresh(true)} />
        ) : (
          <>
            <SectionGate id="overview.headline" sections={sections}>
              {() => (
                <Section title={t.gmTitle}
                         right={<span className="text-[10px] text-fg-subtle">
                           {t.gmPeriod} {report.period}
                         </span>}>
                  <KpiRow kpis={dashboard?.headline?.kpis ?? []} />
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.thesis" sections={sections}>
              {() =>
                dashboard?.thesis ? (
                  <Section title={t.gmThesis}>
                    <div className="text-sm leading-relaxed">
                      <CitationMarkdown content={dashboard.thesis} />
                    </div>
                  </Section>
                ) : null
              }
            </SectionGate>

            <SectionGate id="overview.board" sections={sections}>
              {(detail) => (
                <Section title={t.gmBoard} hint={t.gmBoardHint}>
                  <div className="space-y-2">
                    {(dashboard?.board ?? [])
                      .slice(0, detail === "headline" ? 5 : undefined)
                      .map((row, index) => (
                        <BoardRow key={row.node_key} row={row} rank={index + 1}
                                  compact={detail === "headline"} weights={weights}
                                  labels={labels}
                                  verdict={dashboard?.verdicts?.[row.node_key]}
                                  onDrill={onDrill} />
                      ))}
                  </div>
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.movers" sections={sections}>
              {() => <Movers dashboard={dashboard} onDrill={onDrill} />}
            </SectionGate>

            <SectionGate id="overview.returnrisk" sections={sections}>
              {() => (
                <Section title={t.gmReturnRisk}>
                  <BiTable
                    rows={dashboard?.returnrisk ?? []}
                    columns={[
                      { key: "label", label: t.gmBoard },
                      { key: "rate", label: t.gmReturnRate, numeric: true,
                        render: (row: any) => fmtPct(row.return_ratio_pct, 2) },
                      { key: "bench", label: t.gmReturnBenchmark, numeric: true,
                        render: (row: any) => fmtPct(row.return_ratio_avg_pct, 2) },
                      { key: "bar", label: "", render: (row: any) => (
                        <Bullet value={row.return_ratio_pct ?? 0}
                                benchmark={row.return_ratio_avg_pct}
                                max={Math.max(4, row.return_ratio_avg_pct ?? 0)} />
                      ) },
                    ]}
                  />
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.map" sections={sections}>
              {() => (
                <Section title={t.gmMap}>
                  <Quadrant points={dashboard?.map ?? []} xLabel={t.gmMapX} yLabel={t.gmMapY}
                            onPick={(nodeKey) => {
                              const row = dashboard?.board?.find((b) => b.node_key === nodeKey);
                              if (row) onDrill({ nodeKey, label: row.label });
                            }} />
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.newproduct" sections={sections}>
              {() => (
                <Section title={t.gmNewProduct}>
                  <BiTable
                    rows={dashboard?.newproduct ?? []}
                    onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                    columns={[
                      { key: "label", label: t.gmBoard },
                      { key: "share", label: t.gmNewShare, numeric: true,
                        render: (row: any) => fmtPct(row.new_revenue_share_pct) },
                      { key: "completeness", label: t.cdCompleteness, numeric: true,
                        render: (row: any) => fmtPct((row.completeness ?? 0) * 100, 0) },
                    ]}
                  />
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.price" sections={sections}>
              {() => (
                <Section title={t.gmPrice}>
                  <BandHistogram bands={dashboard?.price ?? []}
                                 listingLabel={t.gmPriceListings}
                                 revenueLabel={t.gmPriceRevenue} />
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.concentration" sections={sections}>
              {() => (
                <Section title={t.gmConcentration}>
                  <BiTable
                    rows={dashboard?.concentration ?? []}
                    columns={[
                      { key: "label", label: t.gmBoard },
                      { key: "share", label: t.gmConcentration, numeric: true,
                        render: (row: any) => fmtPct(row.top5_brand_share_pct) },
                    ]}
                  />
                </Section>
              )}
            </SectionGate>

            <SectionGate id="overview.budget" sections={sections}>
              {() => <BudgetSection />}
            </SectionGate>

            <SectionGate id="overview.gaps" sections={sections}>
              {() => <GapList gaps={dashboard?.gaps} />}
            </SectionGate>

            <footer className="mt-4 border-t border-border pt-2 text-[10px] text-fg-subtle">
              {report.generated_at
                ? new Date(report.generated_at * 1000).toLocaleString(
                    locale === "zh" ? "zh-CN" : "en-US")
                : null}
              {report.vendor_tools?.length ? ` · ${report.vendor_tools.join(", ")}` : null}
              {dashboard?.hidden_sections
                ? ` · ${t.pvHidden} (${dashboard.hidden_sections})`
                : null}
            </footer>
          </>
        )}
      </div>
    </div>
  );
}

function BoardRow({
  row,
  rank,
  compact,
  weights,
  labels,
  verdict,
  onDrill,
}: {
  row: MarketBoardRow;
  rank: number;
  compact: boolean;
  weights: Record<string, number>;
  labels: Record<string, string>;
  verdict?: { verdict: string; rationale: string; evidence_ids: string[] };
  onDrill: (node: { nodeKey: string; label: string }) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="bi-card">
      <div className="flex items-start gap-3">
        <span className="bi-rank">{rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <button className="text-sm font-medium hover:underline"
                    onClick={() => onDrill({ nodeKey: row.node_key, label: row.label })}>
              {row.label}
            </button>
            <VerdictChip verdict={verdict?.verdict} />
            {verdict?.evidence_ids?.length ? (
              <EvidenceChip ids={verdict.evidence_ids} />
            ) : null}
            <button className="ml-auto text-[10px] text-fg-subtle hover:text-accent"
                    onClick={() => onDrill({ nodeKey: row.node_key, label: row.label })}>
              {t.gmDrill} <ArrowSquareOut size={10} className="inline" />
            </button>
          </div>
          {verdict?.rationale ? (
            <p className="mt-0.5 text-[11px] text-fg-muted">{verdict.rationale}</p>
          ) : null}
          {compact ? null : (
            <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-fg-muted sm:grid-cols-4">
              <span>{fmtMoney(row.revenue_est)}*</span>
              <span>{fmtPct(row.growth_pct)}</span>
              <span>{fmtMoney(row.median_price)}</span>
              <span>{fmtPct(row.top5_brand_share_pct)}</span>
            </div>
          )}
        </div>
        <div className="w-28 shrink-0 text-right">
          <div className="text-lg font-semibold" style={{ fontVariantNumeric: "tabular-nums" }}>
            {row.category_score}
          </div>
          <ScoreBar score={row.category_score} breakdown={row.score_breakdown}
                    weights={weights} labels={labels} compact={compact} />
          <ConfidenceNote value={row.score_confidence} />
        </div>
      </div>
    </div>
  );
}

function Movers({
  dashboard,
  onDrill,
}: {
  dashboard: any;
  onDrill: (node: { nodeKey: string; label: string }) => void;
}) {
  const { t } = useI18n();
  const rising = dashboard?.movers?.rising ?? [];
  const declining = dashboard?.movers?.declining ?? [];
  if (!rising.length && !declining.length) return null;
  const max = Math.max(
    1,
    ...[...rising, ...declining].map((r: any) => Math.abs(r.growth_pct ?? 0)),
  );
  const column = (rows: any[], title: string) => (
    <div className="min-w-0 flex-1">
      <div className="mb-1 text-[11px] font-medium text-fg-muted">{title}</div>
      <div className="space-y-1">
        {rows.map((row) => (
          <button key={row.node_key}
                  onClick={() => onDrill({ nodeKey: row.node_key, label: row.label })}
                  className="flex w-full items-center gap-2 text-left text-xs hover:text-accent">
            <span className="w-28 shrink-0 truncate">{row.label}</span>
            <DeltaBullet value={row.growth_pct ?? 0} max={max} />
            <span className="w-14 shrink-0 text-right"
                  style={{ fontVariantNumeric: "tabular-nums" }}>
              {fmtPct(row.growth_pct)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
  return (
    <Section title={t.gmMovers}>
      <div className="flex flex-col gap-4 sm:flex-row">
        {column(rising, t.gmMoversRising)}
        {column(declining, t.gmMoversDeclining)}
      </div>
    </Section>
  );
}

function BudgetSection() {
  const { t } = useI18n();
  const [data, setData] = useState<Awaited<ReturnType<typeof getMarketBudget>> | null>(null);
  useEffect(() => {
    let alive = true;
    getMarketBudget()
      .then((body) => alive && setData(body))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  if (!data) return null;
  return (
    <Section title={t.gmBudget}
             right={<span className="text-[10px] text-fg-subtle">
               {t.gmQueueDepth}: {data.queue_depth}
             </span>}>
      <BiTable
        rows={Object.entries(data.budget.wallets).map(([name, wallet]) => ({
          name, ...wallet,
        }))}
        columns={[
          { key: "name", label: "" },
          { key: "used", label: t.gmBudgetUsed, numeric: true },
          { key: "remaining", label: t.gmBudgetRemaining, numeric: true },
          { key: "limit", label: "", numeric: true },
        ]}
      />
    </Section>
  );
}
