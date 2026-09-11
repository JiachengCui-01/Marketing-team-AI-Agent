"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, Eye, Info, WarningCircle } from "@phosphor-icons/react";

import {
  getMarketEvidence,
  type MarketEvidence,
  type MarketKpi,
  type MarketPersona,
  type MarketPersonaMeta,
  type MarketSection,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";

/** Renders a section only when the active persona is entitled to it.
 *
 * The gating table lives on the server (server/market/personas.py) so the rule is
 * unit-testable in Python; this component is the entire frontend cost of it.
 */
export function SectionGate({
  id,
  sections,
  children,
}: {
  id: string;
  sections: MarketSection[];
  children: (detail: "full" | "headline") => React.ReactNode;
}) {
  const section = sections.find((s) => s.id === id);
  if (!section) return null;
  return <>{children(section.detail)}</>;
}

export function PersonaToggle({
  personas,
  value,
  onChange,
}: {
  personas: MarketPersonaMeta[];
  value: MarketPersona;
  onChange: (persona: MarketPersona) => void;
}) {
  const { locale } = useI18n();
  return (
    <div className="seg" role="tablist" aria-label="persona">
      {personas.map((persona) => {
        const active = persona.id === value;
        return (
          <button
            key={persona.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(persona.id)}
            title={locale === "zh" ? persona.hint_zh : persona.hint_en}
            className={`seg-item ${active ? "seg-item-active" : ""}`}
          >
            {locale === "zh" ? persona.label_zh : persona.label_en}
          </button>
        );
      })}
    </div>
  );
}

export function Section({
  title,
  hint,
  right,
  children,
}: {
  title: string;
  hint?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
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

export function KpiRow({ kpis }: { kpis: MarketKpi[] }) {
  const { t } = useI18n();
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {kpis.map((kpi) => (
        <div key={kpi.label} className="bi-tile">
          <div className="flex items-center gap-1">
            <span className="bi-tile-label">{kpi.label}</span>
            {kpi.estimated ? (
              <span className="bi-chip bi-chip-estimated">{t.evEstimated}</span>
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

const PERSONA_KEY = "marketing-agent-market-persona";

/** Remember the chosen view across reloads.
 *
 * Deliberately local, not server-side: switching persona is a view preference,
 * and writing it back would create a scheduled-task config row as a side effect
 * of clicking a tab.
 */
export function usePersona(): [MarketPersona, (next: MarketPersona) => void] {
  const [persona, setPersona] = useState<MarketPersona>("pm");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(PERSONA_KEY);
    if (stored === "boss" || stored === "pm" || stored === "analyst") setPersona(stored);
  }, []);

  const update = useCallback((next: MarketPersona) => {
    setPersona(next);
    if (typeof window !== "undefined") window.localStorage.setItem(PERSONA_KEY, next);
  }, []);

  return [persona, update];
}
