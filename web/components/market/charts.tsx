"use client";

/** Hand-rolled SVG chart primitives.
 *
 * There is no chart library in this repo and adding one for six shapes would cost
 * more than it saves. Every primitive here follows the conventions the existing
 * Sparkline established: a viewBox with `preserveAspectRatio` so the chart scales
 * with its column, `vectorEffect="non-scaling-stroke"` so lines stay hairline,
 * colour from CSS variables so themes work, and `role="img"` with an aria-label
 * that reads out the actual numbers — a chart nobody can read aloud is a chart
 * that excludes people.
 */

export type Point = { period: string; value: number };

const ACCENT = "rgb(var(--feature-selection))";

function niceNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(digits).replace(/\.0$/, "");
}

export function fmtMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `$${niceNumber(value)}`;
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

/** A line, not bars. These series move inside a narrow band and bars anchored at
 * zero flatten that to invisibility, while bars on a truncated axis overstate it
 * because a bar's area reads as magnitude. A line carries no area claim. */
export function Sparkline({ points, height = 72 }: { points: Point[]; height?: number }) {
  const values = points.map((p) => Number(p.value)).filter((v) => Number.isFinite(v));
  if (values.length < 2) return null;
  const width = 260;
  const pad = 6;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const room = (max - min || Math.abs(max) || 1) * 0.12;
  const lo = min - room;
  const span = max + room - lo || 1;

  const coords = values.map((value, i) => {
    const x = pad + (i / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - ((value - lo) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${height - pad} L${coords[0][0].toFixed(1)},${height - pad} Z`;

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        role="img"
        aria-label={points.map((p) => `${p.period}: ${p.value}`).join(", ")}
      >
        <line className="bi-grid-line" x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} />
        <path className="bi-spark-area" d={area} />
        <path className="bi-spark-line" d={line} vectorEffect="non-scaling-stroke" />
        {coords.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i === coords.length - 1 ? 3 : 2} fill={ACCENT}
                  opacity={i === coords.length - 1 ? 1 : 0.45} />
        ))}
      </svg>
      <div className="mt-1 flex items-center justify-between text-[9px] text-fg-subtle">
        <span className="truncate">{points[0]?.period} · {niceNumber(points[0]?.value)}</span>
        <span className="truncate">
          {points[points.length - 1]?.period} · {niceNumber(points[points.length - 1]?.value)}
        </span>
      </div>
    </div>
  );
}

/** A horizontal score bar plus the weighted breakdown, rendered from the weight
 * table the API ships. Nothing here hardcodes "/30", so changing a weight on the
 * server cannot desync the chart. */
export function ScoreBar({
  score,
  breakdown,
  weights,
  riskKey = "return_risk",
  labels = {},
  compact = false,
}: {
  score: number;
  breakdown: Record<string, number>;
  weights: Record<string, number>;
  riskKey?: string;
  labels?: Record<string, string>;
  compact?: boolean;
}) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 100;
  const risk = Math.abs(breakdown[riskKey] ?? 0);
  return (
    <div>
      <div className="bi-score-track" role="img" aria-label={`score ${score} of 100`}>
        <div className="bi-score-fill" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
      {compact ? null : (
        <div className="bi-seg-strip mt-1.5">
          {Object.entries(weights).map(([key, weight]) => {
            const earned = breakdown[key] ?? 0;
            const share = (weight / total) * 100;
            return (
              <div key={key} className="bi-seg" style={{ width: `${share}%` }}
                   title={`${labels[key] ?? key}: ${earned.toFixed(1)} / ${weight}`}>
                <div className="bi-seg-fill"
                     style={{ height: `${Math.max(0, Math.min(100, (earned / weight) * 100))}%` }} />
              </div>
            );
          })}
          {risk > 0 ? (
            <div className="bi-seg bi-seg-risk" style={{ width: "12%" }}
                 title={`${labels[riskKey] ?? riskKey}: -${risk.toFixed(1)}`}>
              <div className="bi-seg-fill-risk"
                   style={{ height: `${Math.min(100, (risk / 15) * 100)}%` }} />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** Paired columns: how listings and revenue sit differently across price bands.
 * The gap between the two is the point — a band holding more revenue than
 * listings is where the market pays up. */
export function BandHistogram({
  bands,
  listingLabel,
  revenueLabel,
}: {
  bands: { bucket_key: string; listing_share_pct?: number; revenue_share_pct?: number;
           units_ratio?: number | null }[];
  listingLabel: string;
  revenueLabel: string;
}) {
  const rows = bands.map((b) => ({
    key: b.bucket_key,
    listing: b.listing_share_pct ?? (b.units_ratio ?? 0) * 100,
    revenue: b.revenue_share_pct ?? 0,
  }));
  const max = Math.max(1, ...rows.flatMap((r) => [r.listing, r.revenue]));
  return (
    <div role="img"
         aria-label={rows.map((r) => `${r.key}: ${r.listing.toFixed(1)}% / ${r.revenue.toFixed(1)}%`).join(", ")}>
      <div className="flex items-end gap-2 overflow-x-auto pb-1" style={{ height: 118 }}>
        {rows.map((row) => (
          <div key={row.key} className="flex min-w-[46px] flex-1 flex-col items-center justify-end gap-1">
            <div className="flex h-[86px] w-full items-end justify-center gap-[3px]">
              <div className="bi-band" style={{ height: `${(row.listing / max) * 100}%` }}
                   title={`${listingLabel} ${row.listing.toFixed(1)}%`} />
              <div className="bi-band-alt" style={{ height: `${(row.revenue / max) * 100}%` }}
                   title={`${revenueLabel} ${row.revenue.toFixed(1)}%`} />
            </div>
            <span className="truncate text-[9px] text-fg-subtle">{row.key}</span>
          </div>
        ))}
      </div>
      <div className="mt-1 flex items-center gap-3 text-[10px] text-fg-subtle">
        <span className="flex items-center gap-1"><i className="bi-swatch" />{listingLabel}</span>
        <span className="flex items-center gap-1"><i className="bi-swatch bi-swatch-alt" />{revenueLabel}</span>
      </div>
    </div>
  );
}

/** One 100% bar: who holds the category. */
export function ShareBar({
  rows,
  restLabel,
}: {
  rows: { label: string; share: number }[];
  restLabel: string;
}) {
  const used = rows.reduce((sum, r) => sum + r.share, 0);
  const rest = Math.max(0, 100 - used);
  return (
    <div>
      <div className="bi-share-bar" role="img"
           aria-label={rows.map((r) => `${r.label} ${r.share.toFixed(1)}%`).join(", ")}>
        {rows.map((row, i) => (
          <div key={row.label} className="bi-share-seg"
               style={{ width: `${row.share}%`, opacity: 1 - i * 0.11 }}
               title={`${row.label} ${row.share.toFixed(1)}%`} />
        ))}
        {rest > 0 ? <div className="bi-share-rest" style={{ width: `${rest}%` }} title={restLabel} /> : null}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-fg-subtle">
        {rows.slice(0, 5).map((row) => (
          <span key={row.label}>{row.label} {row.share.toFixed(1)}%</span>
        ))}
      </div>
    </div>
  );
}

/** Demand growth against ease of entry, sized by revenue and tinted by return
 * risk. Upper-right is where a freight-shipped furniture brand wants to be. */
export function Quadrant({
  points,
  xLabel,
  yLabel,
  onPick,
}: {
  points: { node_key: string; label: string; competition: number; growth_pct: number | null;
            revenue_est: number | null; return_risk: number }[];
  xLabel: string;
  yLabel: string;
  onPick?: (nodeKey: string) => void;
}) {
  const width = 420;
  const height = 250;
  const pad = 26;
  const usable = points.filter((p) => p.growth_pct !== null);
  if (!usable.length) return null;
  const growths = usable.map((p) => p.growth_pct as number);
  const yMin = Math.min(-5, ...growths);
  const yMax = Math.max(5, ...growths);
  const maxRevenue = Math.max(1, ...usable.map((p) => p.revenue_est ?? 0));

  const px = (competition: number) => pad + (competition / 100) * (width - pad * 2);
  const py = (growth: number) =>
    height - pad - ((growth - yMin) / (yMax - yMin || 1)) * (height - pad * 2);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height: 250 }}
         role="img"
         aria-label={usable.map((p) => `${p.label}: ${xLabel} ${p.competition.toFixed(0)}, ${yLabel} ${(p.growth_pct as number).toFixed(1)}%`).join("; ")}>
      <line className="bi-axis" x1={pad} x2={width - pad} y1={py(0)} y2={py(0)} />
      <line className="bi-axis" x1={px(50)} x2={px(50)} y1={pad} y2={height - pad} />
      <text className="bi-quadrant-label" x={width - pad} y={pad - 8} textAnchor="end">
        {xLabel} ↑ / {yLabel} ↑
      </text>
      {usable.map((point) => {
        const r = 4 + Math.sqrt((point.revenue_est ?? 0) / maxRevenue) * 9;
        return (
          <g key={point.node_key} onClick={() => onPick?.(point.node_key)}
             style={{ cursor: onPick ? "pointer" : "default" }}>
            <circle className={point.return_risk > 8 ? "bi-dot bi-dot-risk" : "bi-dot"}
                    cx={px(point.competition)} cy={py(point.growth_pct as number)} r={r}>
              <title>{`${point.label} · ${xLabel} ${point.competition.toFixed(0)} · ${yLabel} ${(point.growth_pct as number).toFixed(1)}%`}</title>
            </circle>
            <text className="bi-quadrant-label" x={px(point.competition)}
                  y={py(point.growth_pct as number) - r - 3} textAnchor="middle">
              {point.label.length > 14 ? `${point.label.slice(0, 13)}…` : point.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** A zero-anchored diverging bar: risers and decliners on one scale. */
export function DeltaBullet({ value, max }: { value: number; max: number }) {
  const span = Math.max(1, max);
  const width = Math.min(50, (Math.abs(value) / span) * 50);
  const positive = value >= 0;
  return (
    <div className="bi-delta-track" role="img" aria-label={`${value.toFixed(1)} percent`}>
      <div className={positive ? "bi-delta-pos" : "bi-delta-neg"}
           style={{ width: `${width}%`, left: positive ? "50%" : `${50 - width}%` }} />
      <div className="bi-delta-zero" />
    </div>
  );
}

/** One measure against its benchmark — the only honest way to read a return rate. */
export function Bullet({
  value,
  benchmark,
  max,
  goodBelow = true,
}: {
  value: number;
  benchmark: number | null;
  max: number;
  goodBelow?: boolean;
}) {
  const scale = Math.max(max, value, benchmark ?? 0) || 1;
  const good = benchmark === null ? true : goodBelow ? value <= benchmark : value >= benchmark;
  return (
    <div className="bi-bullet" role="img"
         aria-label={`${value.toFixed(2)} against benchmark ${benchmark?.toFixed(2) ?? "—"}`}>
      <div className={good ? "bi-bullet-fill" : "bi-bullet-fill bi-bullet-bad"}
           style={{ width: `${Math.min(100, (value / scale) * 100)}%` }} />
      {benchmark !== null ? (
        <div className="bi-bullet-mark" style={{ left: `${Math.min(100, (benchmark / scale) * 100)}%` }} />
      ) : null}
    </div>
  );
}
