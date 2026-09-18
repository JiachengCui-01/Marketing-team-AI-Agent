"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowUpRight, CheckCircle, Eye, Info, ShieldWarning, WarningCircle }
  from "@phosphor-icons/react";

import {
  getMarketEvidence,
  type MarketAlert,
  type MarketCoverage,
  type MarketCurrent,
  type MarketEvidence,
  type MarketKpi,
  type MarketMonitor,
  type MarketPulseMetric,
  type MarketPulseRow,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { fmtMoney } from "@/components/market/charts";
import { CitationMarkdown } from "@/components/citation-markdown";

/** Remembers where a long report was left, per view, and puts it back.
 *
 * These reports are thousands of pixels tall and every way out of one used to
 * land the reader back at the top: switching tabs, flipping 月度/当下, a
 * re-render that briefly shortens the body so the browser clamps the offset to
 * zero. Scrolling for the row you just clicked is not navigation.
 *
 * `key` names the view whose offset is being tracked (a category, a period);
 * `active` is false while the panel is hidden, so a hidden container's zero
 * never overwrites a real offset; `content` is whatever object identifies the
 * body currently rendered — the offset is restored again after it changes,
 * which is what survives a reload that swaps the whole body out.
 */
export function useScrollMemory({
  key,
  active = true,
  content,
}: {
  key: string;
  active?: boolean;
  content?: unknown;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const offsets = useRef(new Map<string, number>());
  const live = useRef(key);

  const onScroll = useCallback(() => {
    if (!ref.current) return;
    offsets.current.set(live.current, ref.current.scrollTop);
  }, []);

  useLayoutEffect(() => {
    if (!active) return;
    live.current = key;
    const el = ref.current;
    if (!el) return;
    const want = offsets.current.get(key) ?? 0;
    if (el.scrollTop !== want) el.scrollTop = want;
  }, [key, active, content]);

  /** Forget every view under a prefix — a category opened fresh from the board
   *  should start at the top, not wherever it was read down to last time. */
  const forget = useCallback((prefix: string) => {
    for (const k of Array.from(offsets.current.keys())) {
      if (k === prefix || k.startsWith(`${prefix}|`)) offsets.current.delete(k);
    }
    if (ref.current) ref.current.scrollTop = 0;
  }, []);

  return { ref, onScroll, forget };
}

/** True when a section has nothing to show: no rows, no values, all nulls. */
function isEmpty(data: unknown): boolean {
  if (data === null || data === undefined || data === false) return true;
  if (Array.isArray(data)) return data.every((item) => isEmpty(item));
  if (typeof data === "object") {
    const values = Object.values(data as Record<string, unknown>);
    return values.length === 0 || values.every((v) => v === null || v === undefined);
  }
  return data === "" || data === "—";
}

export function Section({
  title,
  hint,
  right,
  data,
  children,
}: {
  title: string;
  hint?: string;
  right?: React.ReactNode;
  /** The section's own data. When it is empty the section is not rendered at
   *  all — a heading over a blank chart says nothing except that something
   *  broke. What is missing is still reported once, by the coverage strip and
   *  the gap list, instead of twelve times as a row of em-dashes. */
  data?: unknown;
  children: React.ReactNode;
}) {
  if (data !== undefined && isEmpty(data)) return null;
  return (
    <section className="bi-section">
      <div className="bi-section-title">
        <span>{title}</span>
        {hint ? <span className="text-[10px] font-normal text-fg-subtle">{hint}</span> : null}
        {right ? <span className="ml-auto">{right}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** A labelled block inside a composite section, dropped when its data is
 *  missing. Without this a section survives because one of its three charts has
 *  data, and the other two leave a heading over nothing. */
export function Block({
  label,
  data,
  children,
}: {
  label: string;
  data: unknown;
  children: React.ReactNode;
}) {
  if (isEmpty(data)) return null;
  return (
    <div className="mt-3 first:mt-0">
      <div className="mb-1 text-[11px] text-fg-muted">{label}</div>
      {children}
    </div>
  );
}

export function KpiRow({ kpis, columns = 5 }: { kpis: MarketKpi[]; columns?: 4 | 5 }) {
  const { t } = useI18n();
  const shown = kpis.filter((kpi) => kpi.value && kpi.value !== "—");
  if (!shown.length) return null;
  // Four across for the department headline, which is eight tiles and reads as
  // two deliberate rows; five for the narrower per-category rows, where the tiles
  // carry short values and a fifth column costs nothing.
  return (
    <div className={`grid grid-cols-2 gap-2 sm:grid-cols-3 ${
      columns === 4 ? "lg:grid-cols-4" : "lg:grid-cols-5"}`}>
      {shown.map((kpi) => (
        <div key={kpi.label} className="bi-tile">
          <div className="flex items-center gap-1">
            <span className="bi-tile-label">{kpi.label}</span>
            {/* Both sides are marked. An unmarked tile used to mean either "this
                is measured" or "nobody labelled it", and on a board with one
                modelled figure among seven measured ones that ambiguity made the
                single chip read as a page-wide hedge. */}
            {kpi.estimated ? (
              <span className="bi-chip bi-chip-estimated" title={t.kpiModelledWhy}>
                {t.kpiModelled}
              </span>
            ) : kpi.observed ? (
              <span className="bi-chip bi-chip-observed">{t.evObserved}</span>
            ) : kpi.computed ? (
              <span className="bi-chip" title={t.kpiComputedWhy}>{t.kpiComputed}</span>
            ) : null}
          </div>
          <div className="bi-tile-value">{kpi.value}</div>
          {kpi.hint ? <div className="mt-0.5 text-[10px] text-fg-subtle">{kpi.hint}</div> : null}
        </div>
      ))}
    </div>
  );
}

export function VerdictChip({ verdict }: { verdict?: string }) {
  const { t } = useI18n();
  if (!verdict) return null;
  const label: Record<string, string> = {
    enter: t.scVerdictEnter,
    validate: t.scVerdictValidate,
    watch: t.scVerdictWatch,
    avoid: t.scVerdictAvoid,
  };
  return <span className={`bi-chip bi-verdict-${verdict}`}>{label[verdict] ?? verdict}</span>;
}

export function GapList({ gaps }: { gaps?: string[] }) {
  const { t } = useI18n();
  if (!gaps || gaps.length === 0) return null;
  return (
    <Section title={t.gmGaps}>
      <ul className="space-y-1 text-xs text-fg-muted">
        {gaps.map((gap, i) => (
          <li key={i} className="flex gap-1.5">
            <WarningCircle size={13} className="mt-0.5 shrink-0 text-warn" weight="duotone" />
            <span>{gap}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function DataGapCard({ summary, onRetry }: { summary: string; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm">
      <div className="mb-1.5 flex items-center gap-1.5 font-medium">
        <WarningCircle size={15} weight="duotone" className="text-warn" />
        {t.gmGaps}
      </div>
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-fg-muted">{summary}</p>
      {onRetry ? (
        <button onClick={onRetry} className="btn-ghost mt-2 h-7 px-2 text-xs">
          {t.gmRefresh}
        </button>
      ) : null}
    </div>
  );
}

/** An inline `[ev_…](evidence:ev_…)` citation, rendered as a chip that opens the
 * drawer. The whole inline-citation UI is this plus six lines in CitationMarkdown. */
export function EvidenceChip({ ids, label }: { ids: string[]; label?: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  if (!ids.length) return null;
  return (
    <>
      <button
        type="button"
        className="bi-evidence-chip"
        title={t.evOpen}
        onClick={(event) => {
          event.preventDefault();
          setOpen(true);
        }}
      >
        <Eye size={10} weight="duotone" />
        {label ?? ids.length}
      </button>
      {open ? <EvidenceDrawer ids={ids} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

/** Any number on screen leads here: the vendor tool, the arguments, the field path
 * inside the payload, the period, and whether it was observed or modelled. */
export function EvidenceDrawer({ ids, onClose }: { ids: string[]; onClose: () => void }) {
  const { t, locale } = useI18n();
  const [rows, setRows] = useState<MarketEvidence[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getMarketEvidence(ids)
      .then((found) => alive && setRows(found))
      .catch((e) => alive && setError(String(e instanceof Error ? e.message : e)));
    return () => {
      alive = false;
    };
  }, [ids]);

  return (
    <Modal title={t.evTitle} onClose={onClose}>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {rows === null && !error ? <p className="text-sm text-fg-muted">…</p> : null}
      {rows && rows.length === 0 ? <p className="text-sm text-fg-muted">{t.evUnknown}</p> : null}
      <div className="space-y-3">
        {(rows ?? []).map((row) => (
          <div key={row.id} className="bi-evidence">
            <div className="flex flex-wrap items-center gap-1.5">
              <code className="text-[11px] text-fg-muted">{row.id}</code>
              <span className={`bi-chip ${row.observed ? "bi-chip-observed" : "bi-chip-estimated"}`}>
                {row.observed ? t.evObserved : t.evEstimated}
              </span>
              {row.quality && row.quality !== "ok" ? (
                <span className="bi-chip bi-chip-high">{row.quality}</span>
              ) : null}
            </div>
            <div className="mt-1 text-sm font-medium">
              {row.label || row.metric}:{" "}
              {row.value_num !== null ? row.value_num.toLocaleString() : row.value_text}{" "}
              <span className="text-xs font-normal text-fg-subtle">{row.unit}</span>
            </div>
            <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px] text-fg-muted">
              <dt>{t.evTool}</dt>
              <dd><code>{row.tool}</code></dd>
              <dt>{t.evField}</dt>
              <dd><code className="break-all">{row.field_path}</code></dd>
              <dt>{t.evPeriod}</dt>
              <dd>{row.period || "—"}</dd>
              {row.sample_size ? (
                <>
                  <dt>{t.evSample}</dt>
                  <dd>{row.sample_size}</dd>
                </>
              ) : null}
              <dt>{t.evRetrieved}</dt>
              <dd>
                {row.retrieved_at
                  ? new Date(row.retrieved_at * 1000).toLocaleString(
                      locale === "zh" ? "zh-CN" : "en-US")
                  : "—"}
              </dd>
            </dl>
          </div>
        ))}
      </div>
    </Modal>
  );
}

/** A plain table with tabular numerals and an em-dash for missing values — the
 * same shape the selection panel used, generalised over its columns. */
export function BiTable<T extends Record<string, any>>({
  columns,
  rows,
  onPick,
}: {
  columns: { key: string; label: string; render?: (row: T) => React.ReactNode; numeric?: boolean }[];
  rows: T[];
  onPick?: (row: T) => void;
}) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="bi-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={index}
              onClick={() => onPick?.(row)}
              className={onPick ? "cursor-pointer" : undefined}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  style={column.numeric ? { fontVariantNumeric: "tabular-nums" } : undefined}
                >
                  {column.render ? column.render(row) : (row[column.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function useScoreLabels(): Record<string, string> {
  const { t } = useI18n();
  return {
    demand_scale: t.scDemandScale,
    demand_growth: t.scDemandGrowth,
    aov_fit: t.scAovFit,
    concentration: t.scConcentration,
    entrenchment: t.scEntrenchment,
    new_product_viability: t.scNewViability,
    keyword_sdr: t.scKeywordSdr,
    demand: t.scDemand,
    growth: t.scGrowth,
    competition: t.scCompetition,
    quality_fit: t.scQualityFit,
    pain_headroom: t.scPainHeadroom,
    keyword_headroom: t.scKeywordHeadroom,
    return_risk: t.scReturnRisk,
  };
}

export function useLocalizedError() {
  const { locale } = useI18n();
  return useCallback(
    (error: unknown) => {
      const raw = error instanceof Error ? error.message : String(error);
      return locale === "zh" ? raw : raw;
    },
    [locale],
  );
}

export function ConfidenceNote({ value }: { value: number | undefined }) {
  const { t } = useI18n();
  if (value === undefined || value === null) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-fg-subtle">
      {value >= 0.85 ? (
        <CheckCircle size={11} weight="duotone" className="text-ok" />
      ) : (
        <Info size={11} weight="duotone" className="text-warn" />
      )}
      {t.scConfidence} {value.toFixed(2)}
    </span>
  );
}

/** Risk and opportunity monitoring, side by side.
 *
 * Two columns rather than one merged feed: the question "what could go wrong
 * here" and the question "what is worth doing here" get answered at different
 * moments, and interleaving them means neither list can be read straight
 * through. Every card carries the number it fired on, so an alert can be
 * disagreed with rather than only believed.
 */
export function MonitorBoard({
  monitor,
  summary,
  onDrill,
  showNode = true,
}: {
  monitor?: MarketMonitor;
  summary?: string;
  onDrill?: (node: { nodeKey: string; label: string }) => void;
  showNode?: boolean;
}) {
  const { t } = useI18n();
  const risks = monitor?.risks ?? [];
  const opportunities = monitor?.opportunities ?? [];
  if (!risks.length && !opportunities.length) return null;

  const column = (
    alerts: MarketAlert[],
    title: string,
    icon: React.ReactNode,
    empty: string,
  ) => (
    <div className="min-w-0 flex-1">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-fg-muted">
        {icon}
        {title}
        <span className="text-fg-subtle">({alerts.length})</span>
      </div>
      {alerts.length === 0 ? (
        <p className="text-[11px] text-fg-subtle">{empty}</p>
      ) : (
        <div className="space-y-1.5">
          {alerts.map((alert) => (
            <AlertCard key={alert.key} alert={alert} onDrill={onDrill} showNode={showNode} />
          ))}
        </div>
      )}
    </div>
  );

  return (
    <Section
      title={t.mnTitle}
      hint={t.mnHint}
      right={
        <span className="flex items-center gap-1.5 text-[10px]">
          <span className="bi-chip bi-chip-high">
            {t.mnRiskHigh} {monitor?.counts?.risk_high ?? 0}
          </span>
          <span className="bi-chip bi-chip-low">
            {t.mnOppHigh} {monitor?.counts?.opportunity_high ?? 0}
          </span>
        </span>
      }
    >
      {summary ? (
        <div className="mb-3 text-sm leading-relaxed">
          <CitationMarkdown content={summary} />
        </div>
      ) : null}
      <div className="flex flex-col gap-4 sm:flex-row">
        {column(
          risks,
          t.mnRisks,
          <ShieldWarning size={13} weight="duotone" className="text-danger" />,
          t.mnNoRisks,
        )}
        {column(
          opportunities,
          t.mnOpportunities,
          <ArrowUpRight size={13} weight="duotone" className="text-ok" />,
          t.mnNoOpportunities,
        )}
      </div>
    </Section>
  );
}

function AlertCard({
  alert,
  onDrill,
  showNode,
}: {
  alert: MarketAlert;
  onDrill?: (node: { nodeKey: string; label: string }) => void;
  showNode: boolean;
}) {
  const { t } = useI18n();
  const severity: Record<string, string> = {
    high: t.mnHigh,
    medium: t.mnMedium,
    low: t.mnLow,
  };
  return (
    <div className={`bi-alert bi-alert-${alert.kind}-${alert.severity}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={`bi-chip bi-chip-${
            alert.severity === "high" ? "high" : alert.severity === "medium" ? "medium" : "low"
          }`}
        >
          {severity[alert.severity] ?? alert.severity}
        </span>
        {showNode && alert.label ? (
          onDrill ? (
            <button
              className="text-[11px] font-medium hover:underline"
              onClick={() => onDrill({ nodeKey: alert.node_key, label: alert.label })}
            >
              {alert.label}
            </button>
          ) : (
            <span className="text-[11px] font-medium">{alert.label}</span>
          )
        ) : null}
        {alert.evidence_ids?.length ? <EvidenceChip ids={alert.evidence_ids} /> : null}
      </div>
      <div className="mt-1 text-xs font-medium">{alert.title}</div>
      {alert.detail ? (
        <div className="mt-0.5 text-[11px] leading-relaxed text-fg-muted">{alert.detail}</div>
      ) : null}
      <div className="bi-alert-metric mt-1">{alert.metric}</div>
    </div>
  );
}

/** Which of the vendor's data families reached the warehouse this period.
 *
 * Worth a permanent strip rather than a debug page: an analysis is only as wide
 * as the data behind it, and a family that quietly stopped arriving is
 * otherwise indistinguishable from one the market has nothing to say about.
 */
export function CoverageStrip({ coverage }: { coverage?: MarketCoverage }) {
  const { t } = useI18n();
  if (!coverage?.families?.length) return null;
  return (
    <Section
      title={t.cvTitle}
      hint={t.cvHint}
      right={
        <span className="text-[10px] text-fg-subtle">
          {coverage.present}/{coverage.total}
        </span>
      }
    >
      <div className="flex flex-wrap gap-1.5">
        {coverage.families.map((family) => (
          <span
            key={family.key}
            className={family.present ? "bi-cov" : "bi-cov bi-cov-missing"}
            title={`${family.tool} · ${family.rows} ${t.cvRows}`}
          >
            {family.label}
            <span className="tabular-nums opacity-70">{family.present ? family.rows : "—"}</span>
          </span>
        ))}
      </div>
    </Section>
  );
}

/** The two halves of every market surface.
 *
 * Not a view switch over one dataset — that is what the persona toggle was, and
 * it was removed for hiding facts. These are two genuinely different statements:
 * a closed month the vendor has settled, and a live reading of the month in
 * flight. They cannot be merged, because the current month has no revenue, no
 * return rate and no concentration at all until it ends.
 */
export function SplitTabs({
  value,
  onChange,
}: {
  value: "monthly" | "current";
  onChange: (next: "monthly" | "current") => void;
}) {
  const { t } = useI18n();
  const options: { id: "monthly" | "current"; label: string; hint: string }[] = [
    { id: "monthly", label: t.splitMonthly, hint: t.splitMonthlyHint },
    { id: "current", label: t.splitCurrent, hint: t.splitCurrentHint },
  ];
  return (
    <div className="seg" role="tablist" aria-label="period">
      {options.map((option) => (
        <button
          key={option.id}
          role="tab"
          aria-selected={option.id === value}
          title={option.hint}
          onClick={() => onChange(option.id)}
          className={`seg-item ${option.id === value ? "seg-item-active" : ""}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function PaceChip({ pace }: { pace: MarketPulseRow["implied_pace"] }) {
  const { t } = useI18n();
  if (!pace) return null;
  const up = pace.ratio >= 1;
  return (
    <span className={`bi-chip ${up ? "bi-chip-low" : "bi-chip-high"}`} title={t.pcPaceHint}>
      {t.pcPace} {pace.ratio.toFixed(2)}×
      <span className="bi-chip bi-chip-estimated ml-1">{t.evEstimated}</span>
    </span>
  );
}

function DeltaText({ value }: { value: number | null }) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return <span className="text-fg-subtle">—</span>;
  }
  const up = value >= 0;
  return (
    <span className={up ? "text-ok" : "text-danger"} style={{ fontVariantNumeric: "tabular-nums" }}>
      {up ? "+" : ""}
      {value.toFixed(1)}%
    </span>
  );
}

function metricText(metric: MarketPulseMetric, which: "now" | "baseline"): string {
  const value = metric[which];
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (metric.unit === "$") return fmtMoney(value);
  if (metric.unit === "%") return `${value.toFixed(1)}%`;
  if (metric.unit === "★") return `${value.toFixed(2)}★`;
  // Counts and per-listing rates. The vendor sends these with more precision
  // than they carry — a seller count of 57.9996 is 58 sellers, and printing the
  // decimals makes a real number look like a bug.
  return Math.abs(value) >= 100
    ? Math.round(value).toLocaleString()
    : value.toFixed(1).replace(/\.0$/, "");
}

/** The month in flight: what the live shelf says, against last month, plus the
 * early warnings that come out of the comparison. */
export function CurrentPanel({
  current,
  onDrill,
  showNode = true,
}: {
  current?: MarketCurrent;
  onDrill?: (node: { nodeKey: string; label: string }) => void;
  showNode?: boolean;
}) {
  const { t, locale } = useI18n();
  if (!current || !current.available) {
    return (
      <div className="rounded-xl border border-border p-5 text-center">
        <p className="text-sm font-medium">{t.pcEmpty}</p>
        <p className="mt-1 text-xs text-fg-muted">{t.pcEmptyHint}</p>
      </div>
    );
  }
  const observed = current.observed_at
    ? new Date(current.observed_at * 1000).toLocaleString(locale === "zh" ? "zh-CN" : "en-US")
    : null;

  return (
    <>
      <Section
        title={t.pcTitle}
        hint={t.pcHint}
        right={
          <span className="text-[10px] text-fg-subtle">
            {observed ? `${t.pcObserved} ${observed}` : null}
            {current.baseline_period ? ` · ${t.pcBaseline} ${current.baseline_period}` : null}
          </span>
        }
      >
        <p className="rounded-lg border border-border bg-bg-subtle px-3 py-2 text-[11px] leading-relaxed text-fg-muted">
          {t.pcNoAggregate}
        </p>
      </Section>

      <MonitorBoard monitor={current.monitor} onDrill={onDrill} showNode={showNode} />

      {(current.rows ?? []).map((row) => (
        <Section
          key={row.node_key}
          title={showNode ? row.label : t.pcTitle}
          right={<PaceChip pace={row.implied_pace} />}
        >
          <BiTable
            rows={row.metrics}
            onPick={
              showNode && onDrill
                ? () => onDrill({ nodeKey: row.node_key, label: row.label })
                : undefined
            }
            columns={[
              { key: "label", label: "" },
              {
                key: "now",
                label: t.pcNow,
                numeric: true,
                render: (m: MarketPulseMetric) => metricText(m, "now"),
              },
              {
                key: "baseline",
                label: t.pcLast,
                numeric: true,
                render: (m: MarketPulseMetric) => metricText(m, "baseline"),
              },
              {
                key: "delta_pct",
                label: t.pcDelta,
                numeric: true,
                render: (m: MarketPulseMetric) => <DeltaText value={m.delta_pct} />,
              },
            ]}
          />
        </Section>
      ))}
    </>
  );
}
