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
  type MarketCurrent,
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
  Sparkline,
  StackedRows,
  Treemap,
  fmtMoney,
  fmtPct,
} from "@/components/market/charts";
import {
  BiTable,
  ConfidenceNote,
  CoverageStrip,
  Block,
  CurrentPanel,
  DataGapCard,
  EvidenceChip,
  GapList,
  KpiRow,
  MonitorBoard,
  Section,
  SplitTabs,
  VerdictChip,
  useScoreLabels,
} from "@/components/market/shared";

/** 全盘发现 — the furniture department, ranked.
 *
 * No category picking here: the system sweeps every tracked node itself and the
 * board is the answer to "where should we be looking". Every row drills into
 * the deep dive, which is the whole point of splitting the two surfaces.
 *
 * One view, everything on it. The three-role switch this panel used to carry
 * was hiding sections from people who then could not tell whether a number was
 * missing or merely withheld — and the sections it hid (concentration, supply,
 * the vendor spend) are exactly the ones that explain the headline.
 */
export function MarketOverviewPanel({
  onDrill,
}: {
  onDrill: (node: { nodeKey: string; label: string }) => void;
}) {
  const { t, locale } = useI18n();
  const labels = useScoreLabels();
  const [meta, setMeta] = useState<MarketConfigResponse | null>(null);
  const [report, setReport] = useState<MarketReport | null>(null);
  const [current, setCurrent] = useState<MarketCurrent | undefined>(undefined);
  const [half, setHalf] = useState<"monthly" | "current">("monthly");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "render" | "collect">("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [config, overview] = await Promise.all([getMarketConfig(), getMarketOverview()]);
      setMeta(config);
      setReport(overview.report);
      setCurrent(overview.report?.dashboard?.current ?? overview.current);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function refresh(collect: boolean) {
    setBusy(collect ? "collect" : "render");
    setError(null);
    try {
      const next = await refreshMarketOverview({ collect, language: locale });
      setReport(next);
      setCurrent(next.dashboard?.current);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  const dashboard = report?.dashboard;
  const weights =
    dashboard?.score_model?.category_weights ?? meta?.score_model.category_weights ?? {};
  const pick = (nodeKey: string) => {
    const row = dashboard?.board?.find((b) => b.node_key === nodeKey);
    if (row) onDrill({ nodeKey, label: row.label });
  };

  if (loading) return <LoadingCard label={t.gmTitle} variant="selection" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <Compass size={15} weight="duotone" className="text-feature-selection" />
        <span className="text-sm font-medium">{t.gmTitle}</span>
        <span className="text-[11px] text-fg-subtle">{t.gmSubtitle}</span>
        <SplitTabs value={half} onChange={setHalf} />
        <div className="ml-auto flex items-center gap-2">
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

        {half === "current" ? (
          <CurrentPanel current={current} onDrill={onDrill} />
        ) : !report ? (
          <div className="rounded-xl border border-border p-5 text-center">
            <p className="text-sm font-medium">{t.gmEmpty}</p>
            <p className="mt-1 text-xs text-fg-muted">{t.gmEmptyHint}</p>
          </div>
        ) : report.status === "data_gap" ? (
          <DataGapCard summary={report.summary} onRetry={() => refresh(true)} />
        ) : (
          <>
            <Section title={t.gmTitle}
                     right={<span className="text-[10px] text-fg-subtle">
                       {t.gmPeriod} {report.period}
                     </span>}>
              <KpiRow kpis={dashboard?.headline?.kpis ?? []} />
            </Section>

            {dashboard?.thesis ? (
              <Section title={t.gmThesis}>
                <div className="text-sm leading-relaxed">
                  <CitationMarkdown content={dashboard.thesis} />
                </div>
              </Section>
            ) : null}

            <MonitorBoard monitor={dashboard?.monitor}
                          summary={dashboard?.monitor_summary}
                          onDrill={onDrill} />

            <Section title={t.gmBoard} hint={t.gmBoardHint}>
              <div className="space-y-2">
                {(dashboard?.board ?? []).map((row, index) => (
                  <BoardRow key={row.node_key} row={row} rank={index + 1} weights={weights}
                            labels={labels} verdict={dashboard?.verdicts?.[row.node_key]}
                            onDrill={onDrill} />
                ))}
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-2 empty:hidden">
              <Section title={t.gmTreemap} hint={t.gmTreemapHint} data={dashboard?.treemap}>
                <Treemap items={dashboard?.treemap ?? []} onPick={pick} fallingLabel={t.gmFalling} />
              </Section>
              <Section title={t.gmTrend}
                       data={[(dashboard?.trend ?? []).length > 1 ? dashboard?.trend : null,
                              dashboard?.movers?.rising, dashboard?.movers?.declining]}>
                <Block label={t.gmTrend}
                       data={(dashboard?.trend ?? []).length > 1 ? dashboard?.trend : null}>
                  <Sparkline points={(dashboard?.trend ?? []).map((p) => ({
                    period: p.period, value: p.value,
                  }))} height={96} valueLabel={fmtMoney} />
                </Block>
                <div className="mt-3">
                  <Movers dashboard={dashboard} onDrill={onDrill} inline />
                </div>
              </Section>
            </div>

            <Section title={t.gmMap} data={(dashboard?.map ?? []).filter((p) => p.growth_pct !== null)}>
              <Quadrant points={dashboard?.map ?? []} xLabel={t.gmMapX} yLabel={t.gmMapY}
                        quadrants={[t.gmQuadEnter, t.gmQuadCrowdedUp,
                                    t.gmQuadCrowdedDown, t.gmQuadOpenDown]}
                        onPick={pick} />
            </Section>

            <Section title={t.gmPhysical} hint={t.gmPhysicalHint}
                     data={dashboard?.physical}>
              <BiTable
                rows={dashboard?.physical ?? []}
                onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                columns={[
                  { key: "label", label: t.gmBoard },
                  { key: "avg_weight", label: t.gmPhysicalWeight, numeric: true,
                    render: (row: any) => row.avg_weight == null
                      ? "\u2014" : `${row.avg_weight} lb` },
                  { key: "avg_volume", label: t.gmPhysicalVolume, numeric: true,
                    render: (row: any) => row.avg_volume == null
                      ? "\u2014" : `${Math.round(row.avg_volume).toLocaleString()} in\u00b3` },
                  { key: "avg_price", label: t.gmPhysicalPrice, numeric: true,
                    render: (row: any) => fmtMoney(row.avg_price) },
                  { key: "price_per_lb", label: t.gmPhysicalDensity, numeric: true,
                    render: (row: any) => row.price_per_lb == null
                      ? "\u2014" : `${fmtMoney(row.price_per_lb)}/lb` },
                  { key: "bar", label: "", render: (row: any) => (
                    <Bullet value={row.price_per_lb ?? 0}
                            benchmark={null}
                            max={Math.max(
                              ...(dashboard?.physical ?? [])
                                .map((r: any) => r.price_per_lb ?? 0), 1)}
                            goodBelow={false} />
                  ) },
                ]}
              />
            </Section>

            <Section title={t.gmReturnRisk} data={dashboard?.returnrisk}>
              <BiTable
                rows={dashboard?.returnrisk ?? []}
                onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
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

            <Section title={t.gmPrice} data={dashboard?.price}>
              <BandHistogram bands={dashboard?.price ?? []}
                             listingLabel={t.gmPriceListings}
                             revenueLabel={t.gmPriceRevenue}
                             leadLabel={t.gmBandLead} />
            </Section>

            <Section title={t.gmNewProduct} data={dashboard?.newproduct}>
              <BiTable
                rows={dashboard?.newproduct ?? []}
                onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                columns={[
                  { key: "label", label: t.gmBoard },
                  { key: "share", label: t.gmNewShare, numeric: true,
                    render: (row: any) => fmtPct(row.new_revenue_share_pct) },
                  { key: "count", label: t.gmNewCount, numeric: true,
                    render: (row: any) => row.new_count_l12 ?? "—" },
                  { key: "reviews", label: t.gmNewReviews, numeric: true,
                    render: (row: any) => row.new_avg_reviews_l12 != null
                      ? Math.round(row.new_avg_reviews_l12).toLocaleString() : "—" },
                  { key: "completeness", label: t.cdCompleteness, numeric: true,
                    render: (row: any) => fmtPct((row.completeness ?? 0) * 100, 0) },
                ]}
              />
            </Section>

            <div className="grid gap-4 lg:grid-cols-2 empty:hidden">
              <Section title={t.gmSupply} data={dashboard?.supply}>
                <BiTable
                  rows={dashboard?.supply ?? []}
                  onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                  columns={[
                    { key: "label", label: "" },
                    { key: "products", label: t.gmSupplyProducts, numeric: true },
                    { key: "sellers", label: t.gmSupplySellers, numeric: true },
                    { key: "brands", label: t.gmSupplyBrands, numeric: true },
                    { key: "per", label: t.gmSupplyPerListing, numeric: true,
                      render: (row: any) => fmtMoney(row.revenue_per_listing) },
                  ]}
                />
              </Section>
              <Section title={t.gmQuality} data={dashboard?.quality}>
                <BiTable
                  rows={dashboard?.quality ?? []}
                  onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                  columns={[
                    { key: "label", label: "" },
                    { key: "avg_rating", label: t.gmQualityRating, numeric: true },
                    { key: "avg_ratings", label: t.gmQualityRatings, numeric: true,
                      render: (row: any) => row.avg_ratings != null
                        ? Math.round(row.avg_ratings).toLocaleString() : "—" },
                    { key: "head", label: t.gmQualityHead, numeric: true,
                      render: (row: any) => row.head_avg_ratings != null
                        ? Math.round(row.head_avg_ratings).toLocaleString() : "—" },
                    { key: "headprice", label: t.gmQualityHeadPrice, numeric: true,
                      render: (row: any) => fmtMoney(row.head_avg_price) },
                  ]}
                />
              </Section>
            </div>

            <div className="grid gap-4 lg:grid-cols-2 empty:hidden">
              <Section title={t.gmFulfilment} data={dashboard?.fulfilment}>
                <StackedRows
                  rows={dashboard?.fulfilment ?? []}
                  onPick={pick}
                  series={[
                    { key: "fba_pct", label: t.gmFulfilmentFba },
                    { key: "fbm_pct", label: t.gmFulfilmentFbm },
                    { key: "amazon_self_pct", label: t.gmFulfilmentAmazon },
                  ]}
                />
              </Section>
              <Section title={t.gmConversion} data={dashboard?.conversion}>
                <BiTable
                  rows={dashboard?.conversion ?? []}
                  onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                  columns={[
                    { key: "label", label: "" },
                    { key: "rate", label: t.gmConversionRate, numeric: true,
                      render: (row: any) => row.search_purchase_ratio?.toFixed?.(2) ?? "—" },
                    { key: "peer", label: t.gmConversionPeer, numeric: true,
                      render: (row: any) => row.search_purchase_ratio_avg?.toFixed?.(2) ?? "—" },
                    { key: "views", label: t.gmConversionViews, numeric: true,
                      render: (row: any) => row.glance_views != null
                        ? Math.round(row.glance_views).toLocaleString() : "—" },
                  ]}
                />
              </Section>
            </div>

            <Section title={t.gmConcentration} data={dashboard?.concentration}>
              <BiTable
                rows={dashboard?.concentration ?? []}
                onPick={(row: any) => onDrill({ nodeKey: row.node_key, label: row.label })}
                columns={[
                  { key: "label", label: t.gmBoard },
                  { key: "b5", label: "Top5 brand", numeric: true,
                    render: (row: any) => fmtPct(row.top5_brand_share_pct) },
                  { key: "b10", label: "Top10 brand", numeric: true,
                    render: (row: any) => fmtPct(row.top10_brand_share_pct) },
                  { key: "s5", label: "Top5 seller", numeric: true,
                    render: (row: any) => fmtPct(row.top5_seller_share_pct) },
                  { key: "p5", label: "Top5 ASIN", numeric: true,
                    render: (row: any) => fmtPct(row.top5_product_share_pct) },
                ]}
              />
            </Section>

            <CoverageStrip coverage={dashboard?.coverage} />
            <BudgetSection />
            <GapList gaps={dashboard?.gaps} />

            <footer className="mt-4 border-t border-border pt-2 text-[10px] text-fg-subtle">
              {report.generated_at
                ? new Date(report.generated_at * 1000).toLocaleString(
                    locale === "zh" ? "zh-CN" : "en-US")
                : null}
              {report.vendor_tools?.length ? ` · ${report.vendor_tools.join(", ")}` : null}
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
  weights,
  labels,
  verdict,
  onDrill,
}: {
  row: MarketBoardRow;
  rank: number;
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
          <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-fg-muted sm:grid-cols-4">
            <span title={row.product_pool
              ? `${t.gmCoverage} ${row.covered_asins}/${row.product_pool}`
              : undefined}>
              {fmtMoney(row.covered_revenue ?? row.revenue_est)}*
              {row.covered_asins ? (
                <span className="ml-1 text-fg-subtle">
                  ({row.covered_asins}
                  {row.product_pool ? `/${row.product_pool.toLocaleString()}` : ""})
                </span>
              ) : null}
            </span>
            <span>{fmtPct(row.growth_pct)}</span>
            <span>{fmtMoney(row.median_price)}</span>
            <span>{fmtPct(row.top5_brand_share_pct)}</span>
          </div>
        </div>
        <div className="w-28 shrink-0 text-right">
          <div className="text-lg font-semibold" style={{ fontVariantNumeric: "tabular-nums" }}>
            {row.category_score}
          </div>
          <ScoreBar score={row.category_score} breakdown={row.score_breakdown}
                    weights={weights} labels={labels} />
          <ConfidenceNote value={row.score_confidence} />
        </div>
      </div>
    </div>
  );
}

function Movers({
  dashboard,
  onDrill,
  inline = false,
}: {
  dashboard: any;
  onDrill: (node: { nodeKey: string; label: string }) => void;
  inline?: boolean;
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
            <span className="w-24 shrink-0 truncate">{row.label}</span>
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
  const body = (
    <div className="flex flex-col gap-4 sm:flex-row">
      {column(rising, t.gmMoversRising)}
      {column(declining, t.gmMoversDeclining)}
    </div>
  );
  if (inline) {
    return (
      <>
        <div className="mb-1 text-[11px] text-fg-muted">{t.gmMovers}</div>
        {body}
      </>
    );
  }
  return <Section title={t.gmMovers}>{body}</Section>;
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
