"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowsClockwise, Database, FileText, MagnifyingGlass } from "@phosphor-icons/react";

import {
  createMarketPrd,
  getMarketCategories,
  getMarketCategory,
  getMarketConfig,
  refreshMarketCategory,
  type MarketCategoryRow,
  type MarketConfigResponse,
  type MarketOpportunity,
  type MarketPrd,
  type MarketReport,
} from "@/lib/api";
import { CitationMarkdown } from "@/components/citation-markdown";
import { LoadingCard } from "@/components/ui/spinner";
import { useI18n } from "@/lib/i18n";
import {
  BandHistogram,
  DistributionBars,
  IndexedCompare,
  Radar,
  ScoreBar,
  ShareBar,
  Sparkline,
  StackedRows,
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
  MonitorBoard,
  Section,
  VerdictChip,
  useScoreLabels,
} from "@/components/market/shared";
import { PrdView } from "@/components/market/prd-view";

/** 品类深度 — one node, in depth.
 *
 * The category is still chosen by hand, exactly as before; what changed is what
 * arrives once it is chosen. The expensive per-ASIN work (keywords, traffic,
 * reviews, history) runs only here, against its own wallet — and now all of it
 * reaches the screen, including the rotating distributions and the 14-month
 * ASIN series that were being collected and then dropped at render time.
 */
export function MarketCategoryPanel({
  initialNode,
}: {
  initialNode?: { nodeKey: string; label: string } | null;
}) {
  const { t, locale } = useI18n();
  const labels = useScoreLabels();
  const [meta, setMeta] = useState<MarketConfigResponse | null>(null);
  const [categories, setCategories] = useState<MarketCategoryRow[]>([]);
  const [node, setNode] = useState<string>(initialNode?.nodeKey ?? "");
  const [report, setReport] = useState<MarketReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "render" | "collect" | "prd">("");
  const [error, setError] = useState<string | null>(null);
  const [prd, setPrd] = useState<MarketPrd | null>(null);

  useEffect(() => {
    if (initialNode?.nodeKey) setNode(initialNode.nodeKey);
  }, [initialNode?.nodeKey]);

  const boot = useCallback(async () => {
    setLoading(true);
    try {
      const [config, rows] = await Promise.all([getMarketConfig(), getMarketCategories()]);
      setMeta(config);
      setCategories(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void boot();
  }, [boot]);

  const loadReport = useCallback(async (nodeKey: string) => {
    if (!nodeKey) {
      setReport(null);
      return;
    }
    setError(null);
    try {
      const body = await getMarketCategory(nodeKey);
      setReport(body.report);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void loadReport(node);
    setPrd(null);
  }, [loadReport, node]);

  async function refresh(collect: boolean) {
    if (!node) return;
    setBusy(collect ? "collect" : "render");
    setError(null);
    try {
      setReport(await refreshMarketCategory({ node, collect, language: locale }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  async function generatePrd(opportunity: MarketOpportunity) {
    setBusy("prd");
    setError(null);
    try {
      setPrd(await createMarketPrd({
        node, opportunity_id: opportunity.id, period: report?.period, language: locale,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  const dashboard = report?.dashboard;
  const weights =
    dashboard?.score_model?.category_weights ?? meta?.score_model.category_weights ?? {};
  const productWeights =
    dashboard?.score_model?.product_weights ?? meta?.score_model.product_weights ?? {};

  if (loading) return <LoadingCard label={t.cdTitle} variant="selection" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <MagnifyingGlass size={15} weight="duotone" className="text-feature-selection" />
        <span className="text-sm font-medium">{t.cdTitle}</span>
        <select value={node} onChange={(event) => setNode(event.target.value)}
                className="input-inline h-8 max-w-[240px] text-xs">
          <option value="">{t.cdPick}</option>
          {categories.map((row) => (
            <option key={row.node_key} value={row.node_key}>
              {row.label}
              {row.score !== null ? ` · ${row.score}` : ""}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => refresh(false)} disabled={!node || busy !== ""}
                  className="btn-ghost h-8 px-2 text-xs">
            <ArrowsClockwise size={14} weight="duotone" />
            {busy === "render" ? t.gmRefreshing : t.cdRerender}
          </button>
          <button onClick={() => refresh(true)} disabled={!node || busy !== "" || !meta?.available}
                  title={t.cdRunHint} className="btn-accent h-8 px-2.5 text-xs">
            <Database size={14} weight="duotone" />
            {busy === "collect" ? t.cdRunning : t.cdRun}
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
        {!node ? (
          <div className="rounded-xl border border-border p-5 text-center">
            <p className="text-sm font-medium">{t.cdPick}</p>
            <p className="mt-1 text-xs text-fg-muted">{t.cdPickHint}</p>
          </div>
        ) : !report ? (
          <div className="rounded-xl border border-border p-5 text-center">
            <p className="text-sm font-medium">{t.cdEmpty}</p>
            <p className="mt-1 text-xs text-fg-muted">{t.cdRunHint}</p>
          </div>
        ) : report.status === "data_gap" ? (
          <DataGapCard summary={report.summary} onRetry={() => refresh(true)} />
        ) : (
          <>
            <Section
              title={dashboard?.header?.label ?? ""}
              hint={dashboard?.header?.node_label_path}
              right={
                <span className="flex items-center gap-2">
                  <VerdictChip verdict={dashboard?.verdict} />
                  <span className="text-lg font-semibold"
                        style={{ fontVariantNumeric: "tabular-nums" }}>
                    {dashboard?.header?.category_score}
                  </span>
                </span>
              }
            >
              <div className="mb-2">
                <ScoreBar score={dashboard?.header?.category_score ?? 0}
                          breakdown={dashboard?.header?.score_breakdown ?? {}}
                          weights={weights} labels={labels} />
                <div className="mt-1 flex flex-wrap items-center gap-3">
                  <ConfidenceNote value={dashboard?.header?.score_confidence} />
                  <span className="text-[10px] text-fg-subtle">
                    {t.cdCompleteness} {fmtPct((dashboard?.header?.completeness ?? 0) * 100, 0)}
                  </span>
                </div>
              </div>
              <KpiRow kpis={dashboard?.header?.kpis ?? []} />
              {dashboard?.verdict_rationale ? (
                <p className="mt-2 text-xs text-fg-muted">{dashboard.verdict_rationale}</p>
              ) : null}
            </Section>

            {dashboard?.narrative ? (
              <Section title={t.cdNarrative}>
                <div className="text-sm leading-relaxed">
                  <CitationMarkdown content={dashboard.narrative} />
                </div>
              </Section>
            ) : null}

            <MonitorBoard monitor={dashboard?.monitor}
                          summary={dashboard?.monitor_summary}
                          showNode={false} />

            <Section title={t.cdOpportunities}>
              <div className="space-y-2">
                {(dashboard?.opportunities ?? []).map((opportunity, index) => (
                  <OpportunityCard key={opportunity.id} rank={index + 1}
                                   opportunity={opportunity} weights={productWeights}
                                   labels={labels} busy={busy === "prd"}
                                   onPrd={() => generatePrd(opportunity)} />
                ))}
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-2">
              <Section title={t.cdBenchmark} hint={t.cdBenchmarkHint}>
                <Radar axes={dashboard?.benchmark ?? []} parityLabel={t.cdBenchmarkParity} />
              </Section>
              <Section title={t.cdStructure}>
                <div className="mb-1 text-[11px] text-fg-muted">{t.cdPriceBands}</div>
                <BandHistogram bands={dashboard?.structure?.price_bands ?? []}
                               listingLabel={t.gmPriceListings}
                               revenueLabel={t.gmPriceRevenue} />
                <div className="mt-3 text-[11px] text-fg-muted">{t.cdBrands}</div>
                <ShareBar
                  rows={(dashboard?.structure?.brands ?? []).slice(0, 6).map((b) => ({
                    label: b.entity, share: (b.revenue_ratio ?? 0) * 100,
                  }))}
                  restLabel="other"
                />
                <div className="mt-3 text-[11px] text-fg-muted">{t.cdTrend}</div>
                <Sparkline points={(dashboard?.structure?.trend ?? []).map((p) => ({
                  period: p.period, value: p.value,
                }))} />
              </Section>
            </div>

            {(dashboard?.distributions ?? []).length ? (
              <Section title={t.cdDistributions}>
                <div className="grid gap-4 lg:grid-cols-2">
                  {(dashboard?.distributions ?? []).map((panel) => (
                    <div key={panel.kind}>
                      <div className="mb-1 text-[11px] text-fg-muted">{panel.label}</div>
                      <DistributionBars buckets={panel.buckets} label={panel.label} />
                    </div>
                  ))}
                </div>
              </Section>
            ) : null}

            {(dashboard?.concentration ?? []).length ? (
              <Section title={t.cdConcentration}>
                <div className="grid gap-4 lg:grid-cols-2">
                  {(dashboard?.concentration ?? []).map((panel: any) => (
                    <div key={panel.kind}>
                      <div className="mb-1 text-[11px] text-fg-muted">{panel.label}</div>
                      <ShareBar
                        rows={(panel.entities ?? []).slice(0, 6).map((e: any) => ({
                          label: e.entity, share: e.revenue_pct ?? 0,
                        }))}
                        restLabel="other"
                      />
                    </div>
                  ))}
                </div>
              </Section>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <Section title={t.cdSupply}>
                <BiTable
                  rows={[
                    { k: t.gmSupplyProducts, v: dashboard?.supply?.products },
                    { k: t.gmSupplySellers, v: dashboard?.supply?.sellers },
                    { k: t.gmSupplyBrands, v: dashboard?.supply?.brands },
                    { k: t.cdAvgVolume, v: dashboard?.supply?.avg_volume },
                    { k: t.cdAvgWeight, v: dashboard?.supply?.avg_weight },
                  ].filter((row) => row.v !== null && row.v !== undefined)}
                  columns={[
                    { key: "k", label: "" },
                    { key: "v", label: "", numeric: true,
                      render: (row: any) => typeof row.v === "number"
                        ? row.v.toLocaleString(undefined, { maximumFractionDigits: 2 })
                        : "—" },
                  ]}
                />
                <div className="mt-3">
                  <StackedRows
                    rows={[{ label: t.gmFulfilment, ...(dashboard?.fulfilment ?? {}) }]}
                    series={[
                      { key: "fba_pct", label: t.gmFulfilmentFba },
                      { key: "fbm_pct", label: t.gmFulfilmentFbm },
                      { key: "amazon_self_pct", label: t.gmFulfilmentAmazon },
                    ]}
                  />
                </div>
              </Section>
              <Section title={t.cdOffAmazon} hint={t.cdOffAmazonHint}>
                <IndexedCompare
                  series={[
                    { key: "trend", label: t.cdOffAmazon,
                      points: (dashboard?.offamazon ?? []).map((p) => ({
                        period: p.period, value: p.value,
                      })) },
                    { key: "amazon", label: t.cdAmazonRevenue,
                      points: (dashboard?.structure?.trend ?? []).map((p) => ({
                        period: p.period, value: p.value,
                      })) },
                  ]}
                />
                {(dashboard?.structure?.glance_views ?? []).length ? (
                  <>
                    <div className="mt-3 text-[11px] text-fg-muted">{t.cdGlanceViews}</div>
                    <Sparkline points={(dashboard?.structure?.glance_views ?? []).map((p) => ({
                      period: p.period, value: p.value,
                    }))} height={60} />
                  </>
                ) : null}
              </Section>
            </div>

            <Section title={t.cdPain}>
              <div className="grid gap-2 sm:grid-cols-2">
                {(dashboard?.pain ?? []).map((theme) => (
                  <div key={theme.theme} className="bi-card">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-medium">{theme.theme_label}</span>
                      <span className={`bi-chip bi-chip-${
                        theme.severity === "blocking" ? "high"
                        : theme.severity === "major" ? "medium" : "low"}`}>
                        {theme.severity}
                      </span>
                      {theme.fixable_in_design ? (
                        <span className="bi-chip bi-chip-low">{t.cdPainFixable}</span>
                      ) : null}
                      {theme.return_driving ? (
                        <span className="bi-chip bi-chip-high">{t.cdPainReturn}</span>
                      ) : null}
                    </div>
                    <div className="mt-1 text-[11px] text-fg-muted">
                      {t.cdPainShare} {fmtPct((theme.share_of_negative ?? 0) * 100)} ·{" "}
                      {t.cdPainSample} {theme.mention_count}/{theme.sample_size}
                    </div>
                    {theme.summary ? (
                      <p className="mt-1 text-xs text-fg-muted">{theme.summary}</p>
                    ) : null}
                    {theme.quotes?.length ? (
                      <ul className="mt-1 space-y-0.5">
                        {theme.quotes.map((quote, i) => (
                          <li key={i} className="text-[11px] italic text-fg-subtle">
                            “{quote}”
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
              </div>
            </Section>

            <Section title={t.cdCompetitors}>
              <BiTable
                rows={dashboard?.competitors ?? []}
                columns={[
                  { key: "asin", label: "ASIN" },
                  { key: "brand", label: "Brand" },
                  { key: "price", label: "$", numeric: true,
                    render: (row: any) => fmtMoney(row.price) },
                  { key: "revenue", label: "Revenue*", numeric: true,
                    render: (row: any) => fmtMoney(row.revenue) },
                  { key: "rating", label: "★", numeric: true },
                  { key: "ratings", label: "#", numeric: true },
                  { key: "available_date", label: "Listed" },
                ]}
              />
            </Section>

            {(dashboard?.history ?? []).length ? (
              <Section title={t.cdHistory}>
                <div className="grid gap-4 lg:grid-cols-2">
                  {(dashboard?.history ?? []).map((row) => (
                    <div key={row.asin}>
                      <div className="mb-1 truncate text-[11px] text-fg-muted"
                           title={row.title}>
                        {row.asin} {row.title}
                      </div>
                      <IndexedCompare
                        height={72}
                        series={[
                          { key: "units", label: t.cdHistoryUnits, points: row.units },
                          { key: "revenue", label: t.cdHistoryRevenue, points: row.revenue },
                        ]}
                      />
                    </div>
                  ))}
                </div>
              </Section>
            ) : null}

            <Section title={t.cdKeywords}>
              <BiTable
                rows={(dashboard?.keywords ?? []).slice(0, 20)}
                columns={[
                  { key: "keyword", label: t.cdKeyword },
                  { key: "searches", label: t.cdSearches, numeric: true },
                  { key: "purchase_rate", label: t.cdPurchaseRate, numeric: true,
                    render: (row: any) => fmtPct((row.purchase_rate ?? 0) * 100, 2) },
                  { key: "supply_demand_ratio", label: t.cdSdr, numeric: true },
                  { key: "bid", label: t.cdBid, numeric: true,
                    render: (row: any) => fmtMoney(row.bid) },
                ]}
              />
            </Section>

            {(dashboard?.keyword_edges ?? []).length ? (
              <Section title={t.cdKeywordEdges} hint={t.cdKeywordEdgesHint}>
                <div className="space-y-3">
                  {(dashboard?.keyword_edges ?? []).map((row) => (
                    <div key={row.asin}>
                      <div className="mb-1 truncate text-[11px] text-fg-muted" title={row.title}>
                        {row.asin} {row.title}
                      </div>
                      <BiTable
                        rows={row.edges}
                        columns={[
                          { key: "keyword", label: t.cdKeyword },
                          { key: "traffic_pct", label: t.cdEdgeTraffic, numeric: true,
                            render: (e: any) => fmtPct(e.traffic_pct, 2) },
                          { key: "searches", label: t.cdSearches, numeric: true },
                          { key: "natural_rank", label: t.cdEdgeRank, numeric: true },
                        ]}
                      />
                    </div>
                  ))}
                </div>
              </Section>
            ) : null}

            <Section title={t.cdTraffic}>
              <div className="space-y-2">
                {(dashboard?.traffic ?? []).map((row) => (
                  <div key={row.asin}>
                    <div className="mb-0.5 flex justify-between text-[11px] text-fg-muted">
                      <span className="truncate">{row.asin} {row.title}</span>
                      <span>
                        {t.cdTrafficNatural} {fmtPct((row.natural ?? 0) * 100, 0)} ·{" "}
                        {t.cdTrafficAd} {fmtPct((row.ad ?? 0) * 100, 0)}
                      </span>
                    </div>
                    <ShareBar
                      rows={[
                        { label: t.cdTrafficNatural, share: (row.natural ?? 0) * 100 },
                        { label: t.cdTrafficAd, share: (row.ad ?? 0) * 100 },
                        { label: t.cdTrafficRecommend, share: (row.recommendation ?? 0) * 100 },
                      ]}
                      restLabel="—"
                    />
                  </div>
                ))}
              </div>
            </Section>

            <Section title={t.evTitle}>
              <BiTable
                rows={(report.evidence ?? []).slice(0, 40)}
                columns={[
                  { key: "id", label: "id" },
                  { key: "label", label: "", render: (row: any) => row.label || row.metric },
                  { key: "value", label: "", numeric: true,
                    render: (row: any) => row.value_num ?? row.value_text ?? "—" },
                  { key: "basis", label: t.evBasis,
                    render: (row: any) => (row.observed ? t.evObserved : t.evEstimated) },
                  { key: "tool", label: t.evTool },
                ]}
              />
            </Section>

            <GapList gaps={dashboard?.gaps} />
          </>
        )}
      </div>

      {prd ? <PrdView prd={prd} onClose={() => setPrd(null)} /> : null}
    </div>
  );
}

function OpportunityCard({
  rank,
  opportunity,
  weights,
  labels,
  busy,
  onPrd,
}: {
  rank: number;
  opportunity: MarketOpportunity;
  weights: Record<string, number>;
  labels: Record<string, string>;
  busy: boolean;
  onPrd: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="bi-card">
      <div className="flex items-start gap-3">
        <span className="bi-rank">{rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium">{opportunity.title}</span>
            <span className="bi-chip">{opportunity.anchor_asin}</span>
            {opportunity.target_price_band ? (
              <span className="bi-chip bi-chip-observed">{opportunity.target_price_band}</span>
            ) : null}
            {opportunity.evidence_ids?.length ? (
              <EvidenceChip ids={opportunity.evidence_ids} />
            ) : null}
          </div>
          {opportunity.thesis ? (
            <p className="mt-1 text-xs text-fg-muted">{opportunity.thesis}</p>
          ) : null}
          {opportunity.differentiation_hypotheses?.length ? (
            <ul className="mt-1.5 space-y-0.5">
              {opportunity.differentiation_hypotheses.map((item, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1 text-xs">
                  <span>{item.claim}</span>
                  <span className={`bi-chip ${
                    item.backing === "to_validate" ? "bi-chip-estimated" : "bi-chip-observed"}`}>
                    {item.backing === "to_validate" ? t.cdToValidate : t.cdBackedBy}
                  </span>
                  {item.evidence_ids?.length ? <EvidenceChip ids={item.evidence_ids} /> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {opportunity.risks?.length ? (
            <ul className="mt-1 space-y-0.5">
              {opportunity.risks.map((risk, i) => (
                <li key={i} className="flex items-center gap-1 text-[11px] text-warn">
                  {risk.risk}
                  {risk.evidence_ids?.length ? <EvidenceChip ids={risk.evidence_ids} /> : null}
                </li>
              ))}
            </ul>
          ) : null}
          <button onClick={onPrd} disabled={busy} className="btn-accent mt-2 h-7 px-2 text-xs">
            <FileText size={13} weight="duotone" />
            {busy ? t.prdGenerating : t.prdGenerate}
          </button>
        </div>
        <div className="w-28 shrink-0 text-right">
          <div className="text-lg font-semibold" style={{ fontVariantNumeric: "tabular-nums" }}>
            {opportunity.product_score}
          </div>
          <ScoreBar score={opportunity.product_score} breakdown={opportunity.score_breakdown}
                    weights={weights} labels={labels} />
          <ConfidenceNote value={opportunity.score_confidence} />
        </div>
      </div>
    </div>
  );
}
