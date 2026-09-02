"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
// Utility marks (settings, refresh, spinner, plus, close) stay on lucide; identity
// icons use Phosphor duotone — the same split the rest of the workspace uses.
import { Settings, RefreshCw, Loader2, Plus, X, AlertTriangle } from "lucide-react";
import { ChartLineUp, TrendUp, TrendDown, Info } from "@phosphor-icons/react";
import {
  getSelectionConfig,
  getSelectionReport,
  refreshSelection,
  saveSelectionConfig,
  cancelSelection,
  type SelectionConfig,
  type SelectionConfigResponse,
  type SelectionKpi,
  type SelectionMarketRow,
  type SelectionRecommendation,
  type SelectionReport,
  type SelectionScope,
  type SelectionTrend,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { Skeleton } from "@/components/ui/skeleton";
import { LoadingCard, Spinner } from "@/components/ui/spinner";
import { CitationMarkdown } from "@/components/citation-markdown";

/** Automated product-selection analysis, rendered as a BI dashboard.
 *
 * Every figure shown here came from SellerSprite via the server-side analysis job —
 * the panel does no arithmetic of its own, so it cannot introduce a number the
 * vendor did not supply. */
export function SelectionPanel() {
  const { locale, t } = useI18n();
  const [meta, setMeta] = useState<SelectionConfigResponse | null>(null);
  const [report, setReport] = useState<SelectionReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const config = meta?.config ?? null;
  const cancelled = !!config && config.enabled === false && config.cancelled_at != null;
  const refreshingEmpty = refreshing && !report;
  const refreshingExisting = refreshing && !!report;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, rep] = await Promise.all([getSelectionConfig(), getSelectionReport()]);
      setMeta(cfg);
      setReport(rep);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      setReport(await refreshSelection(locale));
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setRefreshing(false);
    }
  }

  const scopeLabel = config
    ? config.scope === "all"
      ? t.selScopeAll
      : config.categories.join(" · ")
    : t.selNoConfig;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-4 py-6">
          {meta && !meta.available ? (
            <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-warn/40 bg-warn/10 px-3.5 py-3 text-sm text-warn">
              <Info size={16} weight="duotone" className="mt-0.5 shrink-0" />
              <p>{t.selUnavailable}</p>
            </div>
          ) : null}
          {cancelled ? (
            <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-warn/40 bg-warn/10 px-3.5 py-3 text-sm text-warn">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <p>{t.selCancelledNotice}</p>
            </div>
          ) : null}

          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1 truncate text-xs text-fg-subtle">
              {config
                ? `${config.marketplace} · ${scopeLabel} · ${config.refresh_time} (${config.timezone})`
                : t.selNoConfig}
            </div>
            {refreshingExisting ? (
              <Spinner size={14} label={t.selAnalyzing} variant="selection" className="text-xs" />
            ) : null}
            <button
              onClick={() => setSettingsOpen(true)}
              className="btn-ghost px-2.5 py-1.5 text-xs"
              title={t.selSettings}
            >
              <Settings size={13} />
              <span>{t.selSettings}</span>
            </button>
            <button
              onClick={handleRefresh}
              disabled={refreshing || !config || cancelled || !meta?.available}
              className="btn-accent px-3 py-1.5 text-xs"
            >
              {refreshing ? (
                <Loader2 size={13} className="animate-spin text-feature-selection" />
              ) : (
                <RefreshCw size={13} />
              )}
              <span>{refreshing ? t.selRefreshing : t.selRefreshNow}</span>
            </button>
          </div>

          {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

          {loading ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} variant="selection" className="h-[68px]" />
                ))}
              </div>
              <Skeleton variant="selection" className="h-5 w-1/3" />
              <Skeleton variant="selection" className="h-24 w-full" />
              <Skeleton variant="selection" className="h-24 w-full" />
            </div>
          ) : !config ? (
            <EmptyState
              hint={t.selSetupHint}
              action={t.selSettings}
              onAction={() => setSettingsOpen(true)}
            />
          ) : report ? (
            <Dashboard report={report} />
          ) : refreshingEmpty ? (
            <div className="flex min-h-[360px] items-center justify-center">
              <LoadingCard label={t.selAnalyzing} variant="selection" />
            </div>
          ) : (
            <div className="py-16 text-center">
              <p className="text-sm text-fg-muted">{t.selEmpty}</p>
            </div>
          )}
        </div>
      </div>

      {settingsOpen ? (
        <SelectionSettingsDialog
          meta={meta}
          onClose={() => setSettingsOpen(false)}
          onSaved={(cfg) => {
            setMeta((m) => (m ? { ...m, config: cfg } : m));
            setSettingsOpen(false);
          }}
          onCleared={(cfg) => {
            setMeta((m) => (m ? { ...m, config: cfg } : m));
            setSettingsOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function EmptyState({
  hint,
  action,
  onAction,
}: {
  hint: string;
  action: string;
  onAction: () => void;
}) {
  return (
    <div className="py-16 text-center">
      <ChartLineUp size={28} weight="duotone" className="mx-auto mb-3 text-fg-subtle" />
      <p className="mx-auto max-w-md text-sm text-fg-muted">{hint}</p>
      <button
        onClick={onAction}
        className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg"
      >
        {action}
      </button>
    </div>
  );
}

function Dashboard({ report }: { report: SelectionReport }) {
  const { t } = useI18n();
  const { kpis = [], recommendations = [], trends = [], market = [], notes = [] } =
    report.dashboard ?? {};

  return (
    <div>
      {kpis.length ? (
        <section className="bi-section">
          <h3 className="bi-section-title">
            <ChartLineUp size={15} weight="duotone" className="text-feature-selection" />
            <span>{t.selKpis}</span>
          </h3>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            {kpis.slice(0, 8).map((kpi, i) => (
              <KpiTile key={`${kpi.label}-${i}`} kpi={kpi} />
            ))}
          </div>
        </section>
      ) : null}

      {recommendations.length ? (
        <section className="bi-section">
          <h3 className="bi-section-title">
            <TrendUp size={15} weight="duotone" className="text-feature-selection" />
            <span>{t.selRecommendations}</span>
          </h3>
          <div className="space-y-2.5">
            {recommendations.map((rec, i) => (
              <RecommendationCard key={`${rec.title}-${i}`} rec={rec} rank={i + 1} />
            ))}
          </div>
        </section>
      ) : null}

      {trends.length ? (
        <section className="bi-section">
          <h3 className="bi-section-title">
            <TrendUp size={15} weight="duotone" className="text-feature-selection" />
            <span>{t.selTrends}</span>
          </h3>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {trends.map((trend, i) => (
              <TrendCard key={`${trend.category}-${i}`} trend={trend} />
            ))}
          </div>
        </section>
      ) : null}

      {market.length ? (
        <section className="bi-section">
          <h3 className="bi-section-title">
            <ChartLineUp size={15} weight="duotone" className="text-feature-selection" />
            <span>{t.selMarket}</span>
          </h3>
          <MarketTable rows={market} />
        </section>
      ) : null}

      {report.summary ? (
        <section className="bi-section">
          <h3 className="bi-section-title">
            <Info size={15} weight="duotone" className="text-feature-selection" />
            <span>{t.selSummary}</span>
          </h3>
          <CitationMarkdown content={report.summary} />
        </section>
      ) : null}

      {notes.length ? (
        <section className="bi-section">
          <h3 className="bi-section-title">
            <Info size={15} weight="duotone" className="text-warn" />
            <span>{t.selNotes}</span>
          </h3>
          <ul className="space-y-1 text-xs leading-relaxed text-fg-muted">
            {notes.map((note, i) => (
              <li key={i}>· {note}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="mt-6 space-y-1 border-t border-border pt-3 text-[11px] text-fg-subtle">
        <p>
          {t.selGeneratedAt}: {new Date(report.generated_at * 1000).toLocaleString()}
        </p>
        {report.vendor_tools?.length ? (
          <p className="truncate">
            {t.selVendorTools}: {report.vendor_tools.join(", ")}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function KpiTile({ kpi }: { kpi: SelectionKpi }) {
  const { t } = useI18n();
  return (
    <div className="bi-tile">
      <div className="mb-1 flex items-start justify-between gap-1.5">
        <span className="bi-tile-label truncate">{kpi.label}</span>
        <span className={kpi.estimated ? "bi-chip bi-chip-estimated" : "bi-chip bi-chip-observed"}>
          {kpi.estimated ? t.selEstimated : t.selObserved}
        </span>
      </div>
      <div className="bi-tile-value truncate" title={kpi.value}>
        {kpi.value}
      </div>
      {kpi.hint ? <p className="mt-0.5 truncate text-[10px] text-fg-subtle">{kpi.hint}</p> : null}
    </div>
  );
}

function RecommendationCard({ rec, rank }: { rec: SelectionRecommendation; rank: number }) {
  const { t } = useI18n();
  const score = Math.max(0, Math.min(100, Number(rec.score) || 0));
  const competitionLabel =
    rec.competition === "low"
      ? t.selCompetitionLow
      : rec.competition === "high"
        ? t.selCompetitionHigh
        : rec.competition === "medium"
          ? t.selCompetitionMedium
          : null;

  // Sales and revenue are vendor estimates; price/BSR/rating/reviews are observed.
  const metrics: [string, string | undefined, boolean][] = [
    [t.selPrice, rec.price, false],
    [t.selMonthlySales, rec.monthly_sales, true],
    [t.selMonthlyRevenue, rec.monthly_revenue, true],
    ["BSR", rec.bsr, false],
    [t.selRating, rec.rating, false],
    [t.selReviews, rec.reviews, false],
  ];
  const shown = metrics.filter(([, value]) => value != null && String(value).trim() !== "");

  return (
    <article className="bi-card">
      <div className="mb-2 flex items-start gap-2.5">
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-bg-subtle text-[10px] font-semibold text-fg-muted">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <h4 className="truncate text-sm font-medium text-fg" title={rec.title}>
            {rec.title}
          </h4>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-fg-subtle">
            <span className="truncate">{rec.category}</span>
            {rec.asin ? <span className="bi-chip">{rec.asin}</span> : null}
            {competitionLabel ? (
              <span className={`bi-chip bi-chip-${rec.competition}`}>
                {t.selCompetition} {competitionLabel}
              </span>
            ) : null}
          </div>
        </div>
        <div className="w-[92px] shrink-0 text-right">
          <div className="text-[10px] text-fg-subtle">{t.selScore}</div>
          <div
            className="text-sm font-semibold text-fg"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {score}
          </div>
          <div className="bi-score-track mt-1">
            <div className="bi-score-fill" style={{ width: `${score}%` }} />
          </div>
        </div>
      </div>

      {rec.score_breakdown ? (
        <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 rounded-lg bg-bg-subtle/60 px-2.5 py-1.5 text-[10px] text-fg-subtle">
          <span>{t.selScoreDemand} {rec.score_breakdown.demand}/30</span>
          <span>{t.selScoreGrowth} {rec.score_breakdown.growth}/20</span>
          <span>{t.selScoreAov} {rec.score_breakdown.aov_fit}/20</span>
          <span>{t.selScoreCompetition} {rec.score_breakdown.competition}/20</span>
          <span>{t.selScoreQuality} {rec.score_breakdown.quality_fit}/10</span>
        </div>
      ) : null}

      {shown.length ? (
        <dl className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
          {shown.map(([label, value, estimated]) => (
            <div key={label} className="min-w-0">
              <dt className="flex items-center gap-1 text-[10px] text-fg-subtle">
                <span className="truncate">{label}</span>
                {estimated ? <span className="text-warn">*</span> : null}
              </dt>
              <dd
                className="truncate text-xs text-fg"
                style={{ fontVariantNumeric: "tabular-nums" }}
              >
                {value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <p className="text-xs leading-relaxed text-fg-muted">{rec.reason}</p>
    </article>
  );
}

function TrendCard({ trend }: { trend: SelectionTrend }) {
  const { t } = useI18n();
  const points = (trend.points ?? []).filter((p) => Number.isFinite(Number(p.value)));
  const change = Number(trend.change_pct);
  const hasChange = Number.isFinite(change);

  return (
    <article className="bi-card">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="truncate text-sm font-medium text-fg">{trend.category}</h4>
          <p className="truncate text-[10px] text-fg-subtle">
            {trend.label}
            {trend.unit ? ` (${trend.unit})` : ""}
          </p>
        </div>
        {hasChange ? (
          <span
            className={`flex shrink-0 items-center gap-1 text-xs font-medium ${
              change >= 0 ? "bi-delta-up" : "bi-delta-down"
            }`}
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {change >= 0 ? (
              <TrendUp size={13} weight="bold" />
            ) : (
              <TrendDown size={13} weight="bold" />
            )}
            {change >= 0 ? "+" : ""}
            {change.toFixed(1)}%
          </span>
        ) : null}
      </div>
      {points.length >= 2 ? (
        <Sparkline points={points} />
      ) : (
        <p className="py-4 text-center text-[11px] text-fg-subtle">{t.selNoTrend}</p>
      )}
    </article>
  );
}

/** A line, not bars. These series move inside a narrow band (a 20% swing on a
 * five-figure base), and bars anchored at zero flatten that to invisibility —
 * while bars on a truncated axis would overstate it, because a bar's area reads
 * as magnitude. A line carries no area claim, so a padded non-zero domain is
 * both honest and readable. The signed percentage above the chart states the
 * exact change, so the line only has to show the shape. */
function Sparkline({ points }: { points: { period: string; value: number }[] }) {
  const width = 260;
  const height = 72;
  const pad = 6;
  const values = points.map((p) => Number(p.value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  // 12% headroom top and bottom so a flat series does not sit on the frame.
  const room = (max - min || Math.abs(max) || 1) * 0.12;
  const lo = min - room;
  const span = max + room - lo || 1;

  const coords = values.map((value, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - ((value - lo) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${height - pad} L${coords[0][0].toFixed(1)},${height - pad} Z`;

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-[72px] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={points.map((p) => `${p.period}: ${p.value}`).join(", ")}
      >
        <line
          className="bi-grid-line"
          x1={pad}
          x2={width - pad}
          y1={height - pad}
          y2={height - pad}
        />
        <path className="bi-spark-area" d={area} />
        <path className="bi-spark-line" d={line} vectorEffect="non-scaling-stroke" />
        {coords.map(([x, y], i) => (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={i === coords.length - 1 ? 3 : 2}
            fill="rgb(var(--feature-selection))"
            opacity={i === coords.length - 1 ? 1 : 0.45}
          />
        ))}
      </svg>
      <div className="mt-1 flex items-center justify-between text-[9px] text-fg-subtle">
        <span className="truncate">
          {points[0]?.period} · {points[0]?.value}
        </span>
        <span className="truncate">
          {points[points.length - 1]?.period} · {points[points.length - 1]?.value}
        </span>
      </div>
    </div>
  );
}

function MarketTable({ rows }: { rows: SelectionMarketRow[] }) {
  const { t } = useI18n();
  return (
    <div className="overflow-x-auto">
      <table className="bi-table">
        <thead>
          <tr>
            <th>{t.selCategories}</th>
            <th>{t.selAvgPrice}</th>
            <th>{t.selAvgRevenue}</th>
            <th>{t.selAvgRating}</th>
            <th>{t.selBrandConcentration}</th>
            <th>{t.selVerdict}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row.category}-${i}`}>
              <td className="font-medium">{row.category}</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.avg_price ?? "—"}</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.avg_revenue ?? "—"}</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.avg_rating ?? "—"}</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>
                {row.brand_concentration ?? "—"}
              </td>
              <td className="text-fg-muted">{row.verdict}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SelectionSettingsDialog({
  meta,
  onClose,
  onSaved,
  onCleared,
}: {
  meta: SelectionConfigResponse | null;
  onClose: () => void;
  onSaved: (cfg: SelectionConfig) => void;
  onCleared: (cfg: SelectionConfig) => void;
}) {
  const { locale, t } = useI18n();
  const config = meta?.config ?? null;
  const isCancelled = !!config && config.enabled === false && config.cancelled_at != null;
  const canCancel = !!config && config.enabled !== false;
  const suggestions = useMemo(() => meta?.default_categories ?? [], [meta]);
  const marketplaces = useMemo(() => meta?.marketplaces ?? ["US"], [meta]);

  const [scope, setScope] = useState<SelectionScope>(isCancelled ? "all" : config?.scope ?? "all");
  const [categories, setCategories] = useState<string[]>(isCancelled ? [] : config?.categories ?? []);
  const [marketplace, setMarketplace] = useState(isCancelled ? "US" : config?.marketplace ?? "US");
  const [refreshTime, setRefreshTime] = useState(isCancelled ? "09:00" : config?.refresh_time ?? "09:00");
  const [custom, setCustom] = useState("");
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleCategory(name: string) {
    setCategories((current) =>
      current.includes(name) ? current.filter((c) => c !== name) : [...current, name],
    );
  }

  function addCustom() {
    const name = custom.trim();
    if (!name) return;
    setCategories((current) => (current.includes(name) ? current : [...current, name]));
    setCustom("");
  }

  async function handleSave() {
    if (scope === "categories" && categories.length === 0) {
      setError(t.selCategoriesRequired);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      onSaved(
        await saveSelectionConfig({
          scope,
          categories,
          marketplace,
          refresh_time: refreshTime,
          timezone,
          language: locale,
        }),
      );
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    setError(null);
    try {
      onCleared(await cancelSelection());
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setClearing(false);
    }
  }

  return (
    <Modal title={t.selSettings} onClose={onClose}>
      <div className="space-y-4">
        <fieldset>
          <legend className="mb-1.5 text-xs font-medium text-fg-muted">{t.selScope}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            <ScopeOption
              active={scope === "all"}
              title={t.selScopeAll}
              hint={t.selScopeAllHint}
              onClick={() => setScope("all")}
            />
            <ScopeOption
              active={scope === "categories"}
              title={t.selScopeCategories}
              hint={t.selScopeCategoriesHint}
              onClick={() => setScope("categories")}
            />
          </div>
        </fieldset>

        {scope === "categories" ? (
          <div>
            <p className="mb-1.5 text-xs font-medium text-fg-muted">{t.selCategories}</p>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {suggestions.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => toggleCategory(name)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] transition-all duration-200 ${
                    categories.includes(name)
                      ? "border-feature-selection/40 bg-feature-selection/10 text-feature-selection"
                      : "border-border text-fg-muted hover:bg-bg-subtle"
                  }`}
                >
                  {name}
                </button>
              ))}
            </div>
            {categories.filter((c) => !suggestions.includes(c)).length ? (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {categories
                  .filter((c) => !suggestions.includes(c))
                  .map((name) => (
                    <span
                      key={name}
                      className="inline-flex items-center gap-1 rounded-full border border-feature-selection/40 bg-feature-selection/10 px-2.5 py-1 text-[11px] text-feature-selection"
                    >
                      {name}
                      <button
                        type="button"
                        onClick={() => toggleCategory(name)}
                        aria-label={`remove ${name}`}
                      >
                        <X size={10} />
                      </button>
                    </span>
                  ))}
              </div>
            ) : null}
            <div className="flex gap-2">
              <input
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCustom();
                  }
                }}
                placeholder={t.selCategoriesHint}
                className="field w-full rounded-lg px-3 py-2 text-sm text-fg placeholder:text-fg-subtle"
              />
              <button
                type="button"
                onClick={addCustom}
                className="btn-ghost shrink-0 px-2.5 py-2 text-xs"
                title={t.selCategoryAdd}
              >
                <Plus size={13} />
              </button>
            </div>
          </div>
        ) : null}

        <label className="block text-xs font-medium text-fg-muted">
          {t.selMarketplace}
          <select
            value={marketplace}
            onChange={(e) => setMarketplace(e.target.value)}
            className="field mt-1 w-full rounded-lg px-3 py-2 text-sm text-fg"
          >
            {marketplaces.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-xs font-medium text-fg-muted">
          {t.selTime}
          <input
            type="time"
            value={refreshTime}
            onChange={(e) => setRefreshTime(e.target.value)}
            className="field mt-1 w-full rounded-lg px-3 py-2 text-sm text-fg"
          />
          <span className="mt-1 block text-[11px] text-fg-subtle">{t.selTimeHint}</span>
        </label>

        {error ? <p className="text-[11px] text-danger">{error}</p> : null}

        <div className="flex items-center gap-2 pt-1">
          {canCancel ? (
            <button
              type="button"
              onClick={handleClear}
              disabled={clearing || saving}
              className="inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-4 py-2 text-sm text-danger transition-colors duration-200 hover:bg-danger/10 disabled:opacity-40"
            >
              {clearing ? <Loader2 size={14} className="animate-spin text-danger" /> : null}
              {t.selCancelTask}
            </button>
          ) : null}
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted transition-colors duration-200 hover:bg-bg-subtle"
            >
              {t.cancel}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || clearing}
              className="btn-accent px-4 py-2 text-sm"
            >
              {saving ? (
                <Loader2 size={14} className="animate-spin text-feature-selection" />
              ) : null}
              {saving ? t.saving : t.save}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function ScopeOption({
  active,
  title,
  hint,
  onClick,
}: {
  active: boolean;
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-xl border px-3 py-2.5 text-left transition-all duration-200 ${
        active
          ? "border-feature-selection/45 bg-feature-selection/8"
          : "border-border hover:bg-bg-subtle"
      }`}
    >
      <span
        className={`block text-sm font-medium ${active ? "text-feature-selection" : "text-fg"}`}
      >
        {title}
      </span>
      <span className="mt-0.5 block text-[11px] leading-snug text-fg-subtle">{hint}</span>
    </button>
  );
}
