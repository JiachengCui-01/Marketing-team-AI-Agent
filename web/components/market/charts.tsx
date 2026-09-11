"use client";

import { useId } from "react";

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

type TreeItem = {
  node_key: string;
  label: string;
  value: number;
  growth_pct?: number | null;
  score?: number;
};

type Tile = { item: TreeItem; x: number; y: number; w: number; h: number };

/** Squarified treemap layout (Bruls, Huizing & van Wijk).
 *
 * The obvious heuristic — fill a stripe until the tiles get thin — produces one
 * fat column and a comb of unreadable slivers. This is the real algorithm: keep
 * adding to the current row while doing so *improves* its worst aspect ratio,
 * then commit the row and recurse into what is left. Tiles come out close to
 * square, which is the only reason a treemap is legible at all.
 */
function squarify(items: TreeItem[], width: number, height: number): Tile[] {
  const total = items.reduce((sum, i) => sum + i.value, 0);
  if (total <= 0) return [];
  const scale = (width * height) / total;
  const queue = items.map((item) => ({ item, area: item.value * scale }));

  // Worst aspect ratio in a row laid along `side`.
  const worst = (areas: number[], side: number) => {
    const sum = areas.reduce((a, b) => a + b, 0);
    if (sum <= 0 || side <= 0) return Infinity;
    const depth = sum / side;
    const max = Math.max(...areas) / depth;
    const min = Math.min(...areas) / depth;
    return Math.max(depth / min, max / depth);
  };

  const tiles: Tile[] = [];
  let x = 0;
  let y = 0;
  let freeW = width;
  let freeH = height;
  let index = 0;
  while (index < queue.length) {
    const side = Math.min(freeW, freeH);
    const alongHeight = freeW >= freeH;
    const row: number[] = [];
    while (index + row.length < queue.length) {
      const next = queue[index + row.length].area;
      if (row.length && worst([...row, next], side) > worst(row, side)) break;
      row.push(next);
    }
    const sum = row.reduce((a, b) => a + b, 0);
    const depth = sum / side;
    let offset = 0;
    for (let i = 0; i < row.length; i += 1) {
      const extent = (row[i] / sum) * side;
      const { item } = queue[index + i];
      tiles.push(
        alongHeight
          ? { item, x, y: y + offset, w: depth, h: extent }
          : { item, x: x + offset, y, w: extent, h: depth },
      );
      offset += extent;
    }
    if (alongHeight) {
      x += depth;
      freeW -= depth;
    } else {
      y += depth;
      freeH -= depth;
    }
    index += row.length;
  }
  return tiles;
}

/** Revenue split across the tracked categories, as area.
 *
 * A treemap rather than a bar chart because the question it answers is "how is
 * the department's money divided", and division reads faster as area than as a
 * row of bars the eye has to add up.
 */
export function Treemap({
  items,
  onPick,
}: {
  items: TreeItem[];
  onPick?: (nodeKey: string) => void;
}) {
  // clipPath ids are document-global, so two treemaps on one page would collide.
  const clipId = useId().replace(/:/g, "");
  const rows = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  if (!rows.length) return null;
  const total = rows.reduce((sum, r) => sum + r.value, 0);
  const width = 100;
  const height = 62;
  const tiles = squarify(rows, width, height);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height: 210 }}
         preserveAspectRatio="none" role="img"
         aria-label={rows
           .map((r) => `${r.label} ${((r.value / total) * 100).toFixed(1)}%`)
           .join(", ")}>
      <defs>
        {/* Clip each label to its own tile. Estimating how many characters fit
            from the font size fails as soon as the viewBox is stretched or the
            label is CJK; clipping cannot be wrong. */}
        {tiles.map(({ item, x, y, w, h }, index) => (
          <clipPath key={item.node_key} id={`tree-${clipId}-${index}`}>
            <rect x={x + 0.5} y={y} width={Math.max(0, w - 1)} height={h} />
          </clipPath>
        ))}
      </defs>
      {tiles.map(({ item, x, y, w, h }, index) => {
        const share = (item.value / total) * 100;
        const growth = item.growth_pct ?? null;
        return (
          <g key={item.node_key} onClick={() => onPick?.(item.node_key)}
             style={{ cursor: onPick ? "pointer" : "default" }}>
            <rect
              className={growth !== null && growth < 0 ? "bi-tree-tile bi-tree-down" : "bi-tree-tile"}
              x={x + 0.25} y={y + 0.25}
              width={Math.max(0, w - 0.5)} height={Math.max(0, h - 0.5)}
              style={{ fillOpacity: 0.18 + Math.min(0.55, share / 45) }}>
              <title>{`${item.label} · ${share.toFixed(1)}% · ${fmtMoney(item.value)}`}</title>
            </rect>
            {w > 11 && h > 8 ? (
              <g clipPath={`url(#tree-${clipId}-${index})`}>
                <text className="bi-tree-label" x={x + 1.2} y={y + 4.2}>{item.label}</text>
                <text className="bi-tree-sub" x={x + 1.2} y={y + 7.8}>
                  {share.toFixed(0)}%
                </text>
              </g>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

/** One distribution as a single-series bar row.
 *
 * Separate from BandHistogram because the rotating distributions (rating,
 * review count, A+ coverage, seller country) only ever carry one share, and a
 * paired chart with one bar permanently empty reads as missing data rather than
 * as a different shape of data.
 */
export function DistributionBars({
  buckets,
  valueKey = "products_pct",
  label,
}: {
  buckets: { bucket_key: string; products_pct?: number | null; revenue_pct?: number | null;
             units_pct?: number | null; products?: number | null }[];
  valueKey?: "products_pct" | "revenue_pct" | "units_pct";
  label: string;
}) {
  const rows = buckets
    .map((b) => ({ key: b.bucket_key, value: b[valueKey] ?? b.products_pct ?? 0 }))
    .filter((r) => Number.isFinite(r.value));
  if (!rows.length) return null;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div role="img"
         aria-label={`${label}: ${rows.map((r) => `${r.key} ${r.value.toFixed(1)}%`).join(", ")}`}>
      <div className="flex items-end gap-1.5 overflow-x-auto pb-1" style={{ height: 96 }}>
        {rows.map((row) => (
          <div key={row.key}
               className="flex min-w-[38px] flex-1 flex-col items-center justify-end gap-1">
            <span className="text-[9px] text-fg-subtle">{row.value.toFixed(0)}%</span>
            <div className="flex h-[58px] w-full items-end justify-center">
              <div className="bi-band w-full max-w-[26px]"
                   style={{ height: `${(row.value / max) * 100}%` }}
                   title={`${row.key} ${row.value.toFixed(1)}%`} />
            </div>
            <span className="w-full truncate text-center text-[9px] text-fg-subtle"
                  title={row.key}>{row.key}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Several 100% bars stacked in a column — one row per category.
 *
 * Used for the fulfilment mix and the traffic mix. The comparison that matters
 * is between rows at the same position along the bar, which aligned 100% bars
 * give and a set of pie charts does not.
 */
export function StackedRows({
  rows,
  series,
  onPick,
}: {
  rows: (Record<string, any> & { node_key?: string; label: string })[];
  series: { key: string; label: string }[];
  onPick?: (nodeKey: string) => void;
}) {
  if (!rows.length) return null;
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-fg-subtle">
        {series.map((s, i) => (
          <span key={s.key} className="flex items-center gap-1">
            <i className="bi-swatch" style={{ opacity: 1 - i * 0.22 }} />
            {s.label}
          </span>
        ))}
      </div>
      {rows.map((row) => {
        const parts = series.map((s) => ({ ...s, value: Number(row[s.key] ?? 0) || 0 }));
        const used = parts.reduce((sum, part) => sum + part.value, 0);
        return (
          <button key={row.node_key ?? row.label} type="button"
                  onClick={() => row.node_key && onPick?.(row.node_key)}
                  className="flex w-full items-center gap-2 text-left">
            <span className="w-28 shrink-0 truncate text-[11px]">{row.label}</span>
            <span className="bi-share-bar flex-1" role="img"
                  aria-label={parts.map((p) => `${p.label} ${p.value.toFixed(1)}%`).join(", ")}>
              {parts.map((part, i) => (
                <span key={part.key} className="bi-share-seg"
                      style={{ width: `${Math.max(0, part.value)}%`, opacity: 1 - i * 0.22 }}
                      title={`${part.label} ${part.value.toFixed(1)}%`} />
              ))}
              {used < 100 ? (
                <span className="bi-share-rest" style={{ width: `${100 - used}%` }} />
              ) : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** This category against the department median on every axis at once.
 *
 * Outward is always better — the server inverts the axes where lower is better
 * (returns, concentration) before sending them, because a radar whose spokes
 * disagree about which direction is good cannot be read at a glance. The inner
 * dashed ring is parity with the median.
 */
export function Radar({
  axes,
  parityLabel,
}: {
  axes: { key: string; label: string; score: number; value: number; peer: number }[];
  parityLabel: string;
}) {
  if (axes.length < 3) return null;
  const size = 230;
  const c = size / 2;
  const r = size / 2 - 34;
  const point = (index: number, radius: number) => {
    const angle = (Math.PI * 2 * index) / axes.length - Math.PI / 2;
    return [c + Math.cos(angle) * radius, c + Math.sin(angle) * radius] as const;
  };
  const path = (radiusOf: (axis: (typeof axes)[number]) => number) =>
    `${axes
      .map((axis, i) => {
        const [px, py] = point(i, radiusOf(axis));
        return `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
      })
      .join(" ")} Z`;

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full" style={{ height: 230 }}
         role="img"
         aria-label={axes.map((a) => `${a.label} ${a.score.toFixed(0)} of 100`).join(", ")}>
      {[0.25, 0.5, 0.75, 1].map((ring) => (
        <circle key={ring} className="bi-axis" cx={c} cy={c} r={r * ring} fill="none" />
      ))}
      {axes.map((axis, i) => {
        const [px, py] = point(i, r);
        return <line key={axis.key} className="bi-axis" x1={c} y1={c} x2={px} y2={py} />;
      })}
      <path className="bi-radar-parity" d={path(() => r * 0.5)} />
      <path className="bi-radar-shape" vectorEffect="non-scaling-stroke"
            d={path((axis) => (Math.max(0, Math.min(100, axis.score)) / 100) * r)} />
      {axes.map((axis, i) => {
        const [px, py] = point(i, r + 15);
        return (
          <text key={axis.key} className="bi-quadrant-label" x={px} y={py}
                textAnchor={px > c + 4 ? "start" : px < c - 4 ? "end" : "middle"}>
            {axis.label}
            <title>{`${axis.label}: ${axis.value} · ${parityLabel} ${axis.peer}`}</title>
          </text>
        );
      })}
    </svg>
  );
}

/** Two series on one axis, each rebased to 100 at its first point.
 *
 * The only honest way to put Google Trends (an index) next to revenue
 * (dollars). Rebasing says "compare the shapes"; a twin axis would invite
 * reading the crossing point as meaningful when the two scales are arbitrary.
 */
export function IndexedCompare({
  series,
  height = 96,
}: {
  series: { key: string; label: string; points: Point[] }[];
  height?: number;
}) {
  const usable = series
    .map((s) => ({
      ...s,
      values: s.points.map((p) => Number(p.value)).filter((v) => Number.isFinite(v)),
    }))
    .filter((s) => s.values.length >= 2);
  if (!usable.length) return null;
  const width = 300;
  const pad = 8;
  const rebased = usable.map((s) => {
    const base = s.values.find((v) => v !== 0) ?? 1;
    return { ...s, values: s.values.map((v) => (v / base) * 100) };
  });
  const all = rebased.flatMap((s) => s.values);
  const lo = Math.min(90, ...all);
  const hi = Math.max(110, ...all);
  const span = hi - lo || 1;
  const longest = Math.max(...rebased.map((s) => s.values.length));
  const baseline = height - pad - ((100 - lo) / span) * (height - pad * 2);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}
           preserveAspectRatio="none" role="img"
           aria-label={rebased
             .map((s) => `${s.label} ${s.values[s.values.length - 1].toFixed(0)} indexed to 100`)
             .join(", ")}>
        <line className="bi-grid-line" x1={pad} x2={width - pad} y1={baseline} y2={baseline} />
        {rebased.map((s, index) => {
          const step = longest > 1 ? (width - pad * 2) / (longest - 1) : 0;
          const d = s.values
            .map((value, i) => {
              const px = pad + i * step;
              const py = height - pad - ((value - lo) / span) * (height - pad * 2);
              return `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
            })
            .join(" ");
          return (
            <path key={s.key}
                  className={index === 0 ? "bi-spark-line" : "bi-spark-line bi-spark-alt"}
                  d={d} vectorEffect="non-scaling-stroke" />
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-fg-subtle">
        {rebased.map((s, index) => (
          <span key={s.key} className="flex items-center gap-1">
            <i className="bi-swatch" style={{ opacity: index === 0 ? 0.85 : 0.4 }} />
            {s.label} {s.values[s.values.length - 1].toFixed(0)}
          </span>
        ))}
      </div>
    </div>
  );
}
