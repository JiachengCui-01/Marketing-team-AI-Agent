"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowSquareOut, ArrowsClockwise, Compass, Database, WarningCircle }
  from "@phosphor-icons/react";

import {
  getMarketBudget,
  getMarketConfig,
  getMarketOverview,
  marketOverviewStreamUrl,
  type MarketBoardRead,
  type MarketBoardRow,
  type MarketConfigResponse,
  type MarketCurrent,
  type MarketReport,
} from "@/lib/api";
import { CitationMarkdown } from "@/components/citation-markdown";
import { LoadingCard } from "@/components/ui/spinner";
import { useI18n } from "@/lib/i18n";
import { runTracedStream, type StreamEvent } from "@/lib/sse";
import {
  BandHistogram,
  Bullet,
  DeltaBullet,
  ElementComboChart,
  PriceFitCurve,
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
  SelectionBrief,
  SplitTabs,
  VerdictChip,
  useScoreLabels,
  useScrollMemory,
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
  active = true,
  onTrace,
  onTraceReset,
}: {
  onDrill: (node: { nodeKey: string; label: string }) => void;
  /** False while the shell is showing another tab. */
  active?: boolean;
  /** Report this run's phases into the shared trace panel. */
  onTrace?: (event: StreamEvent) => void;
  /** Clear it when a new run starts, so two runs never interleave. */
  onTraceReset?: () => void;
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
  const scroll = useScrollMemory({ key: half, active, content: report });

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
    onTraceReset?.();
    try {
      // The report still arrives as one value to await; the difference is that
      // the minute before it is no longer a spinner.
      const payload = await runTracedStream(
        marketOverviewStreamUrl({ collect, language: locale }),
        (e) => onTrace?.(e),
      );
      const next = payload.report as MarketReport;
      setReport(next);
      setCurrent(next?.dashboard?.current);
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

      <div ref={scroll.ref} onScroll={scroll.onScroll}
           className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
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
            {/* A report with no narrative has to say so. Every model-written
                block hides itself when empty, which is right for one missing
                section and wrong for all of them at once: the reader is left
                looking at a board that silently lost its conclusions with no
                way to tell a model outage from a market nobody had anything to
                say about. */}
            <NarrativeNotice source={dashboard?.narrative_source} />

            {/* First, above the tiles. The conclusion outranks the scale of the
                market it was drawn from: a reader who stops after one screen
                should have the answer to the question they opened the report
                with, and the tiles, the board, the quadrant and the price bands
                are what they read when they want to disagree with it. */}
            <SelectionBrief selection={dashboard?.selection}
                            labels={Object.fromEntries(
                              (dashboard?.board ?? []).map((row) => [row.node_key, row.label]))}
                            onDrill={onDrill} />

            {/* The period stays on the tiles rather than riding up with the
                brief: the brief is dropped whole when no pick survived its
                citations, and the date has to be on screen either way. */}
            <Section title={t.gmTitle}
                     right={<span className="text-[10px] text-fg-subtle">
                       {t.gmPeriod} {report.period}
                     </span>}>
              <KpiRow kpis={dashboard?.headline?.kpis ?? []} columns={4} />
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

            {/* One chart of whole specs, in place of the nine attribute rows.
                The per-attribute read is still in the element table below; what
                a design review opens with is the combination. */}
            <Section title={t.gmCombos} hint={t.gmCombosHint}
                     data={dashboard?.element_combos?.points ?? null}
                     right={<span className="text-[10px] text-fg-subtle">
                       {t.gmElementGrowth} ↑ · {t.gmElementShelf} →
                     </span>}>
              <ElementComboChart
                points={dashboard?.element_combos?.points ?? []}
                bounds={dashboard?.element_combos?.bounds ?? undefined}
                scale={dashboard?.element_combos?.scale ?? undefined}
                total={dashboard?.element_combos?.total}
                quadrants={(dashboard?.element_combos?.quadrants ?? [
                  "", "", "", ""]) as [string, string, string, string]}
                xLabel={t.gmElementShelf}
                yLabel={t.gmElementGrowth}
                medianLabel={t.gmElementMedian}
                countLabel={t.gmComboCount}
                moreLabel={t.gmComboMore}
                notes={[
                  t.gmCombosRating,
                  t.gmCombosWhyRating,
                  t.gmCombosOrigin,
                  t.gmElementSize,
                  t.gmElementHover,
                  t.gmElementRailNote,
                ]}
                tipLabels={{ rating: t.gmElementTipRating,
                             reviews: t.gmElementTipReviews,
                             asins: t.gmElementTipAsins,
                             price: t.gmElementTipPrice,
                             unmeasured: t.gmElementTipUnmeasured }}
                railLabels={{ noRating: t.gmElementRailNoRating,
                              noShelf: t.gmElementRailNoShelf }}
              />
            </Section>

            <Direction dashboard={dashboard} />

            {/* One chart per row. Side by side, the treemap's smaller tiles lost
                their labels and the trend line was too short to read a shape
                off — half a column is not enough width for either. */}
            <Section title={t.gmTreemap} hint={t.gmTreemapHint} data={dashboard?.treemap}>
              <Treemap items={dashboard?.treemap ?? []} onPick={pick}
                       labels={{ falling: t.gmFalling, rising: t.gmRising,
                                 unknown: t.gmNoTrend, unknownHint: t.gmNoTrendHint,
                                 window: t.gmTrendWindow }} />
            </Section>
            <Section title={t.gmTrend}
                     data={[(dashboard?.trend ?? []).length > 1 ? dashboard?.trend : null,
                            dashboard?.movers?.rising, dashboard?.movers?.declining]}>
              <Block label={t.gmTrend}
                     data={(dashboard?.trend ?? []).length > 1 ? dashboard?.trend : null}>
                <Sparkline points={(dashboard?.trend ?? []).map((p) => ({
                  period: p.period, value: p.value,
                }))} height={200} valueLabel={fmtMoney} />
              </Block>
              <div className="mt-3">
                <Movers dashboard={dashboard} onDrill={onDrill} inline />
              </div>
            </Section>

            {/* 机会象限 is off the board. It came back from a re-render with
                every one of its ninety-six specs on the rail — no node had a
                stored comparison month, so no spec had a y at all — and a
                quadrant drawn with an empty field is a caption and a tint
                claiming to be a reading.

                The payload behind it is still computed and still handed to the
                model: `spec_map` is where the PRODUCT LINES sheet comes from,
                and the 选品建议 at the top of this board is written off those
                rows. What is gone is the drawing of it, not the reading. */}

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
                             leadLabel={t.gmBandLead}
                             readingLabel={t.gmPriceReading} />
              {/* The curve the price factor was scored against, shown because a
                  score nobody can inspect is a score nobody should trust. It is
                  absent while the shipped fallback is in use, on purpose. The
                  tracked categories' own average prices ride on its baseline:
                  the shape of the curve is not the question, where we sit on it
                  is. */}
              <Block label={t.gmPriceFit} data={dashboard?.price_fit}>
                <p className="mb-1 text-[10px] text-fg-subtle">{t.gmPriceFitHint}</p>
                <PriceFitCurve
                  points={(dashboard?.price_fit ?? []).map((row: any) => ({
                    price: row.price, fit: row.fit,
                  }))}
                  peakLabel={t.gmPriceFitPeak}
                  markers={(dashboard?.physical ?? [])
                    .filter((row: any) => row.avg_price != null)
                    .map((row: any) => ({ label: row.label, price: row.avg_price }))}
                  markerLabel={t.gmPriceFitMarks}
                  moneyLabel={fmtMoney}
                />
              </Block>
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

/** Why this report has no prose in it, when it has none.
 *
 * The render never fails on a model problem — the board is server-computed and
 * losing the narrative loses prose only, which is the right trade. What was
 * wrong is that it lost it silently: every model-written block hides itself
 * when empty, so a whole missing narrative looked exactly like a market with
 * nothing to say. The reason has always been recorded in the payload; this puts
 * it on screen, next to the button that fixes it.
 */
function NarrativeNotice({ source }: { source?: string }) {
  const { t } = useI18n();
  if (!source || source === "llm") return null;
  const why = (t.gmNarrativeWhy as Record<string, string>)[source] ?? source;
  return (
    <div className="mb-6 rounded-xl border border-warn/40 bg-warn/10 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-xs font-medium">
        <WarningCircle size={14} weight="duotone" className="text-warn" />
        {t.gmNarrativeMissing}
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-fg-muted">
        {why}。{t.gmNarrativeRetry}
      </p>
    </div>
  );
}

/** 跟进 / 规避: the two lists the board exists to produce.
 *
 * A category says where to build; an element says what it should look like. Both
 * are server-computed from stored columns, and each carries the number that put
 * it on the list — a recommendation you cannot argue with is one nobody acts on.
 */
function Direction({ dashboard }: { dashboard: any }) {
  const { t } = useI18n();
  const follow = dashboard?.follow ?? [];
  const avoid = dashboard?.avoid ?? [];
  if (!follow.length && !avoid.length) return null;

  const column = (rows: any[], title: string, hint: string, good: boolean) => (
    <div className="min-w-0 flex-1">
      <div className="mb-1.5 flex items-baseline gap-1.5">
        <span className="text-[11px] font-medium text-fg">{title}</span>
        <span className="text-[10px] text-fg-subtle">{hint}</span>
      </div>
      {rows.length === 0 ? (
        <p className="text-[11px] text-fg-subtle">{t.gmDirectionNone}</p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((item) => (
            <li key={`${item.kind}-${item.key}`} className="bi-card py-1.5">
              <div className="flex flex-wrap items-baseline gap-1.5">
                <span className={`bi-chip ${good ? "bi-chip-low" : "bi-chip-high"}`}>
                  {item.kind === "element"
                    ? item.kind_label ?? t.gmDirectionElement
                    : t.gmDirectionCategory}
                </span>
                <span className="text-sm font-medium">{item.label}</span>
                {item.score != null ? (
                  <span className="text-[10px] tabular-nums text-fg-subtle">
                    {item.score}
                  </span>
                ) : null}
              </div>
              <p className="mt-0.5 text-[11px] text-fg-muted">{item.why}</p>
              {item.keywords?.length ? (
                <p className="mt-0.5 text-[10px] text-fg-subtle">
                  {item.keywords.join(" · ")}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <Section title={t.gmDirection} hint={t.gmDirectionHint}>
      {dashboard?.direction_reading ? (
        <div className="mb-3 text-sm leading-relaxed">
          <CitationMarkdown content={dashboard.direction_reading} />
        </div>
      ) : null}
      <div className="flex flex-col gap-4 sm:flex-row">
        {column(follow, t.gmFollow, t.gmFollowHint, true)}
        {column(avoid, t.gmAvoid, t.gmAvoidHint, false)}
      </div>
    </Section>
  );
}

/** The server's written read of one board row.
 *
 * Four kinds, in the order a decision is made: why it ranks there, the physical
 * and commercial constraints a brief would be written against, the strongest
 * signal each way, and what was not collected. The last one matters most on the
 * thin rows — a score with no data behind it is not a small finding, it is a
 * different claim.
 */
function BoardRead({ lines }: { lines?: MarketBoardRead[] }) {
  const { t } = useI18n();
  if (!lines?.length) return null;
  const prose = lines.filter((l) => l.kind === "read" || l.kind === "facts");
  const signals = lines.filter((l) => l.kind === "opportunity" || l.kind === "risk");
  const gap = lines.find((l) => l.kind === "gap");
  return (
    <div className="mt-1.5 space-y-1">
      {prose.map((line, i) => (
        <p key={i} className={`text-[11px] leading-relaxed ${
          line.kind === "read" ? "text-fg-muted" : "text-fg-subtle"}`}>
          {line.text}
        </p>
      ))}
      {signals.length ? (
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {signals.map((line, i) => (
            <span key={i} title={line.detail}
                  className={`bi-chip ${line.kind === "risk" ? "bi-chip-high" : "bi-chip-low"}`}>
              {line.kind === "risk" ? t.gmReadRisk : t.gmReadOpportunity} · {line.text}
            </span>
          ))}
        </div>
      ) : null}
      {gap ? (
        <p className="pt-0.5 text-[10px] leading-relaxed text-fg-subtle">{gap.text}</p>
      ) : null}
    </div>
  );
}

/** The board row's metrics: each one named, and absent when it has no value.
 *
 * `median_price` carries the vendor's ``avgPrice``, not a median — the field name
 * is wrong and predates this row. Labelled for what it actually holds rather than
 * for what it is called, because a mislabelled number is worse than a missing one.
 */
function BoardMetrics({ row }: { row: MarketBoardRow }) {
  const { t } = useI18n();
  const revenue = row.covered_revenue ?? row.revenue_est;
  const metrics = [
    revenue != null ? {
      key: "revenue",
      label: t.gmRowRevenue,
      value: fmtMoney(revenue),
      estimated: true,
      // How much of the category that sum actually covered; the number is a
      // roll-up of the ASINs we hold, never the whole shelf.
      suffix: row.covered_asins ? (
        <span className="ml-1 text-fg-subtle">
          {row.covered_asins}
          {row.product_pool ? `/${row.product_pool.toLocaleString()}` : ""} ASIN
        </span>
      ) : null,
      title: row.product_pool
        ? `${t.gmCoverage} ${row.covered_asins}/${row.product_pool}`
        : undefined,
    } : null,
    row.growth_pct != null ? {
      key: "growth",
      label: t.gmRowGrowth,
      value: fmtPct(row.growth_pct),
      title: t.gmRowGrowthHint,
    } : null,
    row.median_price != null ? {
      key: "price",
      label: t.gmRowPrice,
      value: fmtMoney(row.median_price),
    } : null,
    row.top5_brand_share_pct != null ? {
      key: "top5",
      label: t.gmRowTop5,
      value: fmtPct(row.top5_brand_share_pct),
    } : null,
  ].filter(Boolean) as {
    key: string; label: string; value: string; estimated?: boolean;
    suffix?: React.ReactNode; title?: string;
  }[];

  if (!metrics.length) {
    return <p className="mt-1.5 text-[11px] text-fg-subtle">{t.gmRowNoMetrics}</p>;
  }
  return (
    <div className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1.5">
      {metrics.map((metric) => (
        <div key={metric.key} title={metric.title}>
          <div className="flex items-center gap-1 text-[10px] leading-none text-fg-subtle">
            {metric.label}
            {metric.estimated ? (
              <span className="bi-chip bi-chip-estimated">{t.evEstimated}</span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[11px] tabular-nums text-fg-muted">
            {metric.value}
            {metric.suffix}
          </div>
        </div>
      ))}
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
          <BoardMetrics row={row} />
          <BoardRead lines={row.read} />
        </div>
        {/* Wider than it was: the card now carries every factor rather than
            three of them, and a truncated factor name is not a breakdown. */}
        <div className="w-52 shrink-0 text-right">
          <div className="text-lg font-semibold" style={{ fontVariantNumeric: "tabular-nums" }}>
            {row.category_score}
          </div>
          <ScoreBar score={row.category_score} breakdown={row.score_breakdown}
                    weights={weights} labels={labels}
                    missing={row.score_missing}
                    totalLabel={t.scTotal} unmeasuredLabel={t.scUnmeasured} />
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
