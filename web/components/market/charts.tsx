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

/** Fit a label to a character budget, with an ellipsis rather than a hard cut. */
function truncate(text: string, budget: number): string {
  if (budget < 3) return "";
  return text.length > budget ? `${text.slice(0, budget - 1)}…` : text;
}

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

/** A line with a readable scale, not just a shape.
 *
 * The end labels said which period and what value; the axis said nothing, so
 * the height of the line meant nothing. Now the top and bottom of the plotted
 * band are labelled and the last point is called out, which is the one a reader
 * actually wants.
 */
export function Sparkline({
  points,
  height = 72,
  valueLabel,
}: {
  points: Point[];
  height?: number;
  valueLabel?: (value: number) => string;
}) {
  const values = points.map((p) => Number(p.value)).filter((v) => Number.isFinite(v));
  if (values.length < 2) return null;
  const fmt = valueLabel ?? ((v: number) => niceNumber(v));
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
  const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${height - pad} `
    + `L${coords[0][0].toFixed(1)},${height - pad} Z`;
  const last = coords[coords.length - 1];

  return (
    <div>
      <div className="flex items-start gap-1.5">
        {/* The scale, so the line's height is a quantity rather than a mood. */}
        <div className="flex shrink-0 flex-col justify-between text-[9px] tabular-nums
                        text-fg-subtle" style={{ height }}>
          <span>{fmt(max)}</span>
          <span>{fmt(min)}</span>
        </div>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full"
          style={{ height }}
          preserveAspectRatio="none"
          role="img"
          aria-label={points.map((p) => `${p.period}: ${fmt(Number(p.value))}`).join(", ")}
        >
          <line className="bi-grid-line" x1={pad} x2={width - pad}
                y1={height - pad} y2={height - pad} />
          <path className="bi-spark-area" d={area} />
          <path className="bi-spark-line" d={line} vectorEffect="non-scaling-stroke" />
          {/* One marker, at the end — the point a reader is looking for. */}
          <circle cx={last[0]} cy={last[1]} r={4} className="bi-spark-end" />
        </svg>
      </div>
      <div className="mt-1 flex items-center justify-between text-[9px] text-fg-subtle">
        <span className="truncate">{points[0]?.period}</span>
        <span className="truncate text-fg">
          {points[points.length - 1]?.period} · {fmt(Number(points[points.length - 1]?.value))}
        </span>
      </div>
    </div>
  );
}

/** The score, and the two or three things that actually made it.
 *
 * This was a strip of anonymous segments whose only labels were `title`
 * tooltips — so the number the whole board ranks on could not be explained
 * without hovering, one factor at a time. A tooltip may enhance a value; it may
 * never be the only way to read one.
 *
 * What a reader needs from a score is not all seven factors: it is *why this
 * one is higher than that one*. So the bar names its biggest contributors and
 * its biggest shortfall by name, with the points each is worth, and leaves the
 * full breakdown to the table view.
 */
export function ScoreBar({
  score,
  breakdown,
  weights,
  riskKey = "return_risk",
  labels = {},
  compact = false,
  topN = 2,
}: {
  score: number;
  breakdown: Record<string, number>;
  weights: Record<string, number>;
  riskKey?: string;
  labels?: Record<string, string>;
  compact?: boolean;
  topN?: number;
}) {
  const risk = Math.abs(breakdown[riskKey] ?? 0);
  const factors = Object.entries(weights).map(([key, weight]) => ({
    key,
    label: labels[key] ?? key,
    earned: breakdown[key] ?? 0,
    weight,
    // Points forgone is what separates two scores; a factor worth 20 that
    // earned 4 costs more than one worth 8 that earned 0.
    lost: weight - (breakdown[key] ?? 0),
  }));
  const best = [...factors].sort((a, b) => b.earned - a.earned).slice(0, topN)
    .filter((f) => f.earned > 0);
  const worst = [...factors].sort((a, b) => b.lost - a.lost)[0];

  return (
    <div>
      <div className="bi-score-track" role="img"
           aria-label={`score ${score} of 100; ${factors
             .map((f) => `${f.label} ${f.earned.toFixed(1)} of ${f.weight}`)
             .join(", ")}${risk ? `; risk -${risk.toFixed(1)}` : ""}`}>
        <div className="bi-score-fill" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
      {compact ? null : (
        <ul className="mt-1 space-y-0.5 text-[10px] leading-tight">
          {best.map((factor) => (
            <li key={factor.key} className="flex items-baseline gap-1 text-fg-muted">
              <i className="bi-swatch shrink-0" />
              <span className="truncate">{factor.label}</span>
              <span className="ml-auto shrink-0 tabular-nums text-fg">
                +{factor.earned.toFixed(0)}
              </span>
            </li>
          ))}
          {worst && worst.lost >= 3 ? (
            <li className="flex items-baseline gap-1 text-fg-subtle">
              <i className="bi-swatch bi-swatch-empty shrink-0" />
              <span className="truncate">{worst.label}</span>
              <span className="ml-auto shrink-0 tabular-nums">
                {worst.earned.toFixed(0)}/{worst.weight}
              </span>
            </li>
          ) : null}
          {risk > 0 ? (
            <li className="flex items-baseline gap-1 text-danger">
              <i className="bi-swatch bi-swatch-risk shrink-0" />
              <span className="truncate">{labels[riskKey] ?? riskKey}</span>
              <span className="ml-auto shrink-0 tabular-nums">−{risk.toFixed(0)}</span>
            </li>
          ) : null}
        </ul>
      )}
    </div>
  );
}

/** Where the listings are against where the money is.
 *
 * The gap between the two bars is the whole point of this chart — a band
 * holding more revenue than listings is the market saying it will pay up — so
 * the gap is now stated rather than left to be eyeballed: bands where revenue
 * leads are marked, and the leading band is called out underneath.
 */
export function BandHistogram({
  bands,
  listingLabel,
  revenueLabel,
  leadLabel,
}: {
  bands: { bucket_key: string; listing_share_pct?: number; revenue_share_pct?: number;
           units_ratio?: number | null }[];
  listingLabel: string;
  revenueLabel: string;
  /** e.g. "这个价格带愿意付钱" — names what the marked gap means. */
  leadLabel?: string;
}) {
  const rows = bands.map((b) => ({
    key: b.bucket_key,
    listing: b.listing_share_pct ?? (b.units_ratio ?? 0) * 100,
    revenue: b.revenue_share_pct ?? 0,
  }));
  if (!rows.length) return null;
  const max = Math.max(1, ...rows.flatMap((r) => [r.listing, r.revenue]));
  const leader = rows.reduce((best, r) =>
    r.revenue - r.listing > best.revenue - best.listing ? r : best, rows[0]);
  const leads = leader.revenue - leader.listing;

  return (
    <div>
      <div className="flex items-center gap-3 text-[10px] text-fg-subtle">
        <span className="flex items-center gap-1"><i className="bi-swatch" />{listingLabel}</span>
        <span className="flex items-center gap-1">
          <i className="bi-swatch bi-swatch-alt" />{revenueLabel}
        </span>
        <span className="ml-auto tabular-nums">{max.toFixed(0)}%</span>
      </div>
      <div role="img"
           aria-label={rows
             .map((r) => `${r.key}: ${listingLabel} ${r.listing.toFixed(1)}%, `
               + `${revenueLabel} ${r.revenue.toFixed(1)}%`)
             .join("; ")}>
        <div className="flex items-end gap-2 overflow-x-auto pb-1" style={{ height: 124 }}>
          {rows.map((row) => {
            const ahead = row.revenue - row.listing >= 3;
            return (
              <div key={row.key}
                   className="flex min-w-[52px] flex-1 flex-col items-center justify-end gap-1">
                <span className={`text-[9px] tabular-nums ${ahead ? "text-fg" : "text-fg-subtle"}`}>
                  {ahead ? `+${(row.revenue - row.listing).toFixed(0)}` : ""}
                </span>
                <div className="flex h-[80px] w-full items-end justify-center gap-[2px]">
                  <div className="bi-band" style={{ height: `${(row.listing / max) * 100}%` }}
                       title={`${listingLabel} ${row.listing.toFixed(1)}%`} />
                  <div className={ahead ? "bi-band-alt bi-band-lead" : "bi-band-alt"}
                       style={{ height: `${(row.revenue / max) * 100}%` }}
                       title={`${revenueLabel} ${row.revenue.toFixed(1)}%`} />
                </div>
                <span className="w-full truncate text-center text-[9px] text-fg-subtle"
                      title={row.key}>{row.key}</span>
              </div>
            );
          })}
        </div>
      </div>
      {leadLabel && leads >= 3 ? (
        <p className="mt-1 text-[10px] text-fg-muted">
          <span className="font-medium text-fg">{leader.key}</span> · {leadLabel}
          <span className="ml-1 tabular-nums">
            ({revenueLabel} {leader.revenue.toFixed(0)}% / {listingLabel}{" "}
            {leader.listing.toFixed(0)}%)
          </span>
        </p>
      ) : null}
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
        {rows.slice(0, 5).map((row, i) => (
          <span key={row.label} className="flex items-center gap-1">
            <i className="bi-swatch shrink-0" style={{ opacity: 1 - i * 0.11 }} />
            {row.label} <span className="tabular-nums text-fg-muted">{row.share.toFixed(1)}%</span>
          </span>
        ))}
        {rest > 0 ? (
          <span className="flex items-center gap-1">
            <i className="bi-swatch bi-swatch-empty shrink-0" />
            {restLabel} <span className="tabular-nums">{rest.toFixed(1)}%</span>
          </span>
        ) : null}
      </div>
    </div>
  );
}

export type ElementPoint = {
  key: string;
  label: string;
  kind: string;
  kind_label: string;
  /** Share of head revenue whose listing title mentions this element. */
  shelf_pct: number;
  growth_pct: number;
  searches: number;
  asins: number;
  avg_price: number | null;
};

export type ElementGroup = {
  kind: string;
  kind_label: string;
  points: ElementPoint[];
  /** How many elements of this kind were measured, before the plot cap. */
  total: number;
  dropped: number;
};

/** Axis bounds shared by every attribute panel, computed server-side over all
 *  plotted elements. Without it each panel would silently rescale and two dots
 *  in the same position would mean two different numbers. */
export type ElementScale = {
  x_max: number;
  x_mid: number;
  y_min: number;
  y_max: number;
  max_searches: number;
};

/** What to draw, and whether the shelf has already answered.
 *
 * The board says which category to work in. This says what the product should
 * look like, which is the question a design review actually opens with. Both
 * axes are measured, from calls the sweep already makes: x from the titles of
 * the listings that hold the revenue, y from the search phrases that carry the
 * element.
 *
 * The cell that matters is top-left — demand rising, shelf thin. Top-right is
 * real but crowded, bottom-right is what to stop proposing. Those are the
 * sentences, so they are printed on the chart rather than left to be inferred
 * from a dot's position.
 */
export function ElementMatrix({
  points,
  quadrants,
  xLabel,
  yLabel,
  windowNote,
  sizeNote,
  scale,
  compact = false,
}: {
  points: ElementPoint[];
  /** Clockwise from top-left: rising+thin, rising+proven, cooling+heavy, cooling+thin. */
  quadrants: [string, string, string, string];
  xLabel: string;
  yLabel: string;
  /** Names the window y was measured over — a month and a year are not the same claim. */
  windowNote: string;
  sizeNote: string;
  /** Bounds to draw against. Omitted, the panel scales to its own points —
   *  right for a lone chart, wrong for one panel of a set. */
  scale?: ElementScale;
  /** Small-multiple sizing: one attribute per panel, several panels a row. */
  compact?: boolean;
}) {
  if (points.length < (compact ? 1 : 2)) return null;
  const width = compact ? 330 : 680;
  const height = compact ? 210 : 300;
  const padL = compact ? 32 : 46;
  const padR = compact ? 10 : 16;
  const padT = compact ? 16 : 20;
  const padB = compact ? 28 : 40;

  const shelves = points.map((p) => p.shelf_pct);
  const growths = points.map((p) => p.growth_pct);
  const xMax = scale ? scale.x_max : Math.max(5, ...shelves) * 1.1;
  const yMin = scale ? scale.y_min : Math.min(-10, ...growths) * 1.1;
  const yMax = scale ? scale.y_max : Math.max(10, ...growths) * 1.1;
  // The x reference is the median, not an arbitrary round number: "more shelf
  // presence than half the elements we track" is a claim the data supports.
  // Across a set of panels it is the department's median, so the line sits in
  // the same place in every one of them and the panels can be read as a row.
  const sorted = [...shelves].sort((a, b) => a - b);
  const xMid = scale ? scale.x_mid : sorted[Math.floor(sorted.length / 2)];
  const maxSearches = scale
    ? Math.max(1, scale.max_searches)
    : Math.max(1, ...points.map((p) => p.searches));

  const px = (v: number) => padL + (v / xMax) * (width - padL - padR);
  const py = (v: number) =>
    height - padB - ((v - yMin) / (yMax - yMin || 1)) * (height - padT - padB);

  // Biggest first, so a small dot is never hidden under a large one, and so the
  // labels that get dropped on collision are the least important ones.
  const ordered = [...points].sort((a, b) => b.searches - a.searches);
  const placed: { x: number; y: number }[] = [];

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}
           role="img"
           aria-label={points.map((p) =>
             `${p.label}: ${xLabel} ${p.shelf_pct.toFixed(1)}%, `
             + `${yLabel} ${p.growth_pct.toFixed(1)}%`).join("; ")}>
        <line className="bi-axis-solid" x1={padL} x2={width - padR} y1={py(0)} y2={py(0)} />
        <line className="bi-axis-solid" x1={px(xMid)} x2={px(xMid)}
              y1={padT} y2={height - padB} />

        <text className="bi-axis-tick" x={padL - 5} y={py(0) + 3} textAnchor="end">0%</text>
        <text className="bi-axis-tick" x={padL - 5} y={padT + 8} textAnchor="end">
          {yMax.toFixed(0)}%
        </text>
        <text className="bi-axis-tick" x={padL - 5} y={height - padB} textAnchor="end">
          {yMin.toFixed(0)}%
        </text>
        <text className="bi-axis-tick" x={px(xMid)} y={height - padB + 13} textAnchor="middle">
          {xMid.toFixed(0)}%
        </text>
        <text className="bi-axis-tick" x={padL} y={height - padB + 13} textAnchor="start">0</text>
        <text className="bi-axis-tick" x={width - padR} y={height - padB + 13} textAnchor="end">
          {compact ? `${xMax.toFixed(0)}%` : `${xMax.toFixed(0)}% · ${xLabel}`}
        </text>
        {/* Named once per panel set rather than once per panel: the axes are
            shared, so repeating their names is noise the dots have to pay for. */}
        {!compact ? (
          <text className="bi-axis-tick" x={padL - 5} y={padT - 8} textAnchor="end">
            {yLabel}
          </text>
        ) : null}

        {/* Corner names belong on a lone chart. Repeated across nine small
            panels they say the same four things nine times and collide with the
            dots they are meant to explain, so the panel set prints them once in
            its legend instead. */}
        {!compact ? (
          <>
            <text className="bi-quadrant-name" x={padL + 3} y={padT + 10}
                  textAnchor="start">{quadrants[0]}</text>
            <text className="bi-quadrant-name" x={width - padR - 3} y={padT + 10}
                  textAnchor="end">{quadrants[1]}</text>
            <text className="bi-quadrant-name" x={width - padR - 3} y={height - padB - 5}
                  textAnchor="end">{quadrants[2]}</text>
            <text className="bi-quadrant-name" x={padL + 3} y={height - padB - 5}
                  textAnchor="start">{quadrants[3]}</text>
          </>
        ) : null}

        {ordered.map((point) => {
          const r = (compact ? 3.5 : 5)
            + Math.sqrt(point.searches / maxSearches) * (compact ? 7 : 10);
          const cx = px(point.shelf_pct);
          const cy = py(point.growth_pct);
          const rising = point.growth_pct >= 0;
          // Drop a label rather than stack it: two names on top of each other is
          // worse than one name and a dot you can hover.
          const clash = placed.some(
            (seat) => Math.abs(seat.x - cx) < (compact ? 44 : 58)
              && Math.abs(seat.y - cy) < 13);
          if (!clash) placed.push({ x: cx, y: cy });
          return (
            <g key={point.key}>
              {/* The hit target is bigger than the mark; an 8px dot is not a button. */}
              <circle cx={cx} cy={cy} r={Math.max(15, r + 8)} fill="transparent" />
              <circle className={rising ? "bi-dot" : "bi-dot bi-dot-risk"}
                      cx={cx} cy={cy} r={r}>
                <title>
                  {`${point.label}（${point.kind_label}） · ${yLabel} `
                    + `${point.growth_pct >= 0 ? "+" : ""}${point.growth_pct.toFixed(1)}% · `
                    + `${xLabel} ${point.shelf_pct.toFixed(1)}% · ${point.asins} ASIN · `
                    + `${point.searches.toLocaleString()} `
                    + (point.avg_price != null ? `· ${fmtMoney(point.avg_price)}` : "")}
                </title>
              </circle>
              {!clash ? (
                <text className="bi-quadrant-label" x={cx} y={cy - r - 5} textAnchor="middle">
                  {truncate(point.label, compact ? 9 : 10)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      {/* In a set of panels these two notes are true of every panel, so the
          wrapper prints them once instead of nine times. */}
      {!compact ? (
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]
                        text-fg-subtle">
          <span>{windowNote}</span>
          <span>{sizeNote}</span>
        </div>
      ) : null}
    </div>
  );
}

/** The same chart once per attribute — sizes beside sizes, finishes beside
 *  finishes, surface treatments beside surface treatments.
 *
 * One scatter for every element was the wrong unit of comparison. A designer
 * choosing a front profile is not weighing it against a colour, and putting the
 * two on shared axes implies they are alternatives. Within a column they really
 * are: the dots are the options for one decision, so their ranking is the
 * decision, and the top-left corner names the option nobody has built yet.
 *
 * The axes are shared across panels, which is what makes a row of small charts
 * legitimate rather than nine charts that happen to sit together.
 */
export function ElementMatrixGroups({
  groups,
  scale,
  quadrants,
  xLabel,
  yLabel,
  windowNote,
  sizeNote,
  splitNote,
  countLabel,
  moreLabel,
}: {
  groups: ElementGroup[];
  scale?: ElementScale;
  quadrants: [string, string, string, string];
  xLabel: string;
  yLabel: string;
  windowNote: string;
  sizeNote: string;
  /** Why the chart is split — without it a reader compares across panels. */
  splitNote: string;
  /** Suffix for "n elements", e.g. 个 / elements. */
  countLabel: string;
  /** Suffix for the elements a column measured but could not plot. */
  moreLabel: string;
}) {
  if (!groups.length) return null;
  return (
    <div>
      <div className="grid gap-x-4 gap-y-3 md:grid-cols-2 xl:grid-cols-3">
        {groups.map((group) => (
          <div key={group.kind} className="min-w-0">
            <div className="flex items-baseline gap-1.5 text-[11px]">
              <span className="font-medium">{group.kind_label}</span>
              <span className="text-fg-subtle tabular-nums">
                {group.total} {countLabel}
              </span>
              {group.dropped > 0 ? (
                <span className="text-fg-subtle tabular-nums">
                  ·&nbsp;{group.dropped} {moreLabel}
                </span>
              ) : null}
            </div>
            <ElementMatrix points={group.points} quadrants={quadrants} xLabel={xLabel}
                           yLabel={yLabel} windowNote={windowNote} sizeNote={sizeNote}
                           scale={scale} compact />
          </div>
        ))}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]
                      text-fg-subtle">
        {/* Said once for the whole set rather than drawn into every panel. */}
        <span>↖&nbsp;{quadrants[0]}</span>
        <span>↗&nbsp;{quadrants[1]}</span>
        <span>↘&nbsp;{quadrants[2]}</span>
        <span>↙&nbsp;{quadrants[3]}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]
                      text-fg-subtle">
        <span>{splitNote}</span>
        <span>{windowNote}</span>
        <span>{sizeNote}</span>
      </div>
    </div>
  );
}

/** Demand growth against ease of entry — and which corner you are in.
 *
 * A scatter only pays for itself if the reader can name the region a dot sits
 * in. So the two reference lines are labelled with their values, each quadrant
 * is named for the decision it implies, and only the notable points carry a
 * label: past four or five, labels collide and the chart becomes the thing you
 * squint at instead of the thing you read.
 */
export function Quadrant({
  points,
  xLabel,
  yLabel,
  quadrants,
  onPick,
  labelTop = 4,
}: {
  points: { node_key: string; label: string; competition: number; growth_pct: number | null;
            revenue_est: number | null; return_risk: number }[];
  xLabel: string;
  yLabel: string;
  /** Clockwise from top-right: open+growing, crowded+growing, crowded+shrinking,
   *  open+shrinking. Named so a dot's position is a recommendation, not a mood. */
  quadrants: [string, string, string, string];
  onPick?: (nodeKey: string) => void;
  labelTop?: number;
}) {
  const width = 420;
  const height = 270;
  const pad = 34;
  const usable = points.filter((p) => p.growth_pct !== null);
  if (!usable.length) return null;
  const growths = usable.map((p) => p.growth_pct as number);
  const yMin = Math.min(-5, ...growths);
  const yMax = Math.max(5, ...growths);
  const maxRevenue = Math.max(1, ...usable.map((p) => p.revenue_est ?? 0));

  const px = (competition: number) => pad + (competition / 100) * (width - pad * 2);
  const py = (growth: number) =>
    height - pad - ((growth - yMin) / (yMax - yMin || 1)) * (height - pad * 2);

  // Label the ones worth naming, biggest first — but never two labels on top of
  // each other. Categories routinely share a growth rate or a concentration, so
  // their dots coincide; stacked labels then read as a smudge and the chart
  // stops being readable exactly where it is densest. The unlabelled ones keep
  // their tooltip, and every row is in the board below.
  const named = new Set<string>();
  const placed: [number, number][] = [];
  for (const point of [...usable].sort((a, b) => (b.revenue_est ?? 0) - (a.revenue_est ?? 0))) {
    if (named.size >= labelTop) break;
    const cx = px(point.competition);
    const cy = py(point.growth_pct as number);
    if (placed.some(([ox, oy]) => Math.abs(ox - cx) < 70 && Math.abs(oy - cy) < 16)) continue;
    named.add(point.node_key);
    placed.push([cx, cy]);
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height: 270 }}
         role="img"
         aria-label={usable.map((p) =>
           `${p.label}: ${xLabel} ${p.competition.toFixed(0)}, ${yLabel} ${(p.growth_pct as number).toFixed(1)}%`).join("; ")}>
      {/* Reference lines carry their own values, so a position can be read. */}
      <line className="bi-axis-solid" x1={pad} x2={width - pad} y1={py(0)} y2={py(0)} />
      <line className="bi-axis-solid" x1={px(50)} x2={px(50)} y1={pad} y2={height - pad} />
      <text className="bi-axis-tick" x={pad - 4} y={py(0) + 3} textAnchor="end">0%</text>
      <text className="bi-axis-tick" x={pad - 4} y={pad + 3} textAnchor="end">
        {yMax.toFixed(0)}%
      </text>
      <text className="bi-axis-tick" x={pad - 4} y={height - pad + 3} textAnchor="end">
        {yMin.toFixed(0)}%
      </text>
      <text className="bi-axis-tick" x={px(50)} y={height - pad + 13} textAnchor="middle">50</text>
      <text className="bi-axis-tick" x={width - pad} y={height - pad + 13} textAnchor="end">
        100 · {xLabel}
      </text>
      <text className="bi-axis-tick" x={pad} y={height - pad + 13} textAnchor="start">0</text>
      {/* Horizontal and clear of the ticks. A rotated axis title that lands on
          top of "14%" costs more legibility than it buys. */}
      <text className="bi-axis-tick" x={pad - 4} y={14} textAnchor="start">{yLabel} ↑</text>

      <text className="bi-quadrant-name" x={width - pad - 2} y={pad + 9} textAnchor="end">
        {quadrants[0]}
      </text>
      <text className="bi-quadrant-name" x={pad + 2} y={pad + 9} textAnchor="start">
        {quadrants[1]}
      </text>
      <text className="bi-quadrant-name" x={pad + 2} y={height - pad - 4} textAnchor="start">
        {quadrants[2]}
      </text>
      <text className="bi-quadrant-name" x={width - pad - 2} y={height - pad - 4} textAnchor="end">
        {quadrants[3]}
      </text>

      {[...usable]
        .sort((a, b) => (b.revenue_est ?? 0) - (a.revenue_est ?? 0))
        .map((point) => {
        const r = 5 + Math.sqrt((point.revenue_est ?? 0) / maxRevenue) * 9;
        const cx = px(point.competition);
        const cy = py(point.growth_pct as number);
        return (
          <g key={point.node_key} onClick={() => onPick?.(point.node_key)}
             style={{ cursor: onPick ? "pointer" : "default" }}>
            {/* The hit target is bigger than the mark; an 8px dot is not a button. */}
            <circle cx={cx} cy={cy} r={Math.max(14, r + 8)} fill="transparent" />
            <circle className={point.return_risk > 8 ? "bi-dot bi-dot-risk" : "bi-dot"}
                    cx={cx} cy={cy} r={r}>
              <title>{`${point.label} · ${xLabel} ${point.competition.toFixed(0)} · `
                + `${yLabel} ${(point.growth_pct as number).toFixed(1)}% · `
                + fmtMoney(point.revenue_est)}</title>
            </circle>
            {named.has(point.node_key) ? (
              <text className="bi-quadrant-label" x={cx} y={cy - r - 4} textAnchor="middle">
                {point.label.length > 16 ? `${point.label.slice(0, 15)}…` : point.label}
              </text>
            ) : null}
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
  /** null means "not computable yet" — one stored month — not "flat". */
  growth_pct?: number | null;
  growth_from?: string;
  growth_to?: string;
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
 *
 * One flat fill, deliberately. Tinting each tile by its own share would encode
 * the same number twice — area already says it — so the free channel goes to
 * *change*, which area cannot show.
 *
 * Change has **three** states here, not two. A category we hold one month of has
 * no growth figure at all, and drawing it exactly like a category that grew
 * makes the chart quietly claim "nothing is declining" when the truth is "we
 * cannot tell yet". Declining is a red outline, unknown is a dashed grey one,
 * and the footer counts all three so the absence of red is readable as a fact
 * rather than as an assumption.
 */
export function Treemap({
  items,
  onPick,
  labels,
}: {
  items: TreeItem[];
  onPick?: (nodeKey: string) => void;
  labels: {
    falling: string;
    rising: string;
    unknown: string;
    /** e.g. "需要两个月才能算" — says why the unknown tiles are unknown. */
    unknownHint: string;
    /** e.g. "对比区间" — prefixes the window in the tooltip. */
    window: string;
  };
}) {
  const clipId = useId().replace(/:/g, "");
  const rows = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  if (!rows.length) return null;
  const total = rows.reduce((sum, r) => sum + r.value, 0);
  // Real pixel units and a uniform scale. A 100x62 viewBox stretched with
  // `preserveAspectRatio="none"` scales x and y by different factors, which
  // stretches the type — the labels came out twice as wide as they should be
  // and ran off their tiles.
  const width = 680;
  const height = 210;
  const tiles = squarify(rows, width, height);

  const state = (item: TreeItem) =>
    item.growth_pct === null || item.growth_pct === undefined
      ? "unknown" : item.growth_pct < 0 ? "down" : "up";
  const counts = {
    down: rows.filter((r) => state(r) === "down").length,
    up: rows.filter((r) => state(r) === "up").length,
    unknown: rows.filter((r) => state(r) === "unknown").length,
  };

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}
           preserveAspectRatio="xMidYMid meet" role="img"
           aria-label={rows
             .map((r) => `${r.label} ${fmtMoney(r.value)}, ${((r.value / total) * 100).toFixed(1)}%`
               + (r.growth_pct == null ? `, ${labels.unknown}`
                  : `, ${r.growth_pct >= 0 ? "+" : ""}${r.growth_pct.toFixed(1)}%`))
             .join("; ")}>
        <defs>
          {tiles.map(({ item }, index) => {
            const tile = tiles[index];
            return (
              <clipPath key={item.node_key} id={`tree-${clipId}-${index}`}>
                <rect x={tile.x + 4} y={tile.y} width={Math.max(0, tile.w - 8)}
                      height={tile.h} />
              </clipPath>
            );
          })}
        </defs>
        {tiles.map(({ item, x, y, w, h }, index) => {
          const share = (item.value / total) * 100;
          const growth = item.growth_pct ?? null;
          const kind = state(item);
          const span = item.growth_from && item.growth_to
            ? ` · ${labels.window} ${item.growth_from}–${item.growth_to}` : "";
          return (
            <g key={item.node_key} onClick={() => onPick?.(item.node_key)}
               style={{ cursor: onPick ? "pointer" : "default" }}>
              <rect className={`bi-tree-tile${kind === "down" ? " bi-tree-down"
                                : kind === "unknown" ? " bi-tree-unknown" : ""}`}
                    x={x + 1} y={y + 1} rx={3}
                    width={Math.max(0, w - 2)} height={Math.max(0, h - 2)}>
                <title>
                  {`${item.label} · ${fmtMoney(item.value)} · ${share.toFixed(1)}%`
                    + (growth !== null
                       ? ` · ${growth >= 0 ? "+" : ""}${growth.toFixed(1)}%${span}`
                       : ` · ${labels.unknown}`)}
                </title>
              </rect>
              {w > 74 && h > 34 ? (
                <g clipPath={`url(#tree-${clipId}-${index})`}>
                  {/* Measured, not clipped: a name cut mid-word reads as a bug.
                      ~6.2px per character at 11px in this face. */}
                  <text className="bi-tree-label" x={x + 6} y={y + 17}>
                    {truncate(item.label, Math.floor((w - 12) / 6.2))}
                  </text>
                  <text className="bi-tree-sub" x={x + 6} y={y + 30}>
                    {fmtMoney(item.value)} · {share.toFixed(0)}%
                  </text>
                  {/* The change, on every tile that has one. Thirteen tiles is few
                      enough to read, and it is what stops the outline from being
                      the only place the direction lives. */}
                  <text className={kind === "down" ? "bi-tree-delta bi-tree-delta-down"
                                   : kind === "unknown" ? "bi-tree-delta bi-tree-delta-unknown"
                                   : "bi-tree-delta"}
                        x={x + 6} y={y + 43}>
                    {kind === "unknown" ? labels.unknown
                      : `${growth! < 0 ? "▼" : "▲"}${Math.abs(growth!).toFixed(0)}%`}
                  </text>
                </g>
              ) : null}
            </g>
          );
        })}
      </svg>
      {/* Always rendered. The old footer appeared only when something was
          falling, so "no red anywhere" and "we did not draw the legend" looked
          identical — which is the question this chart kept being asked. */}
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]
                      text-fg-subtle">
        {counts.down ? (
          <span className="flex items-center gap-1">
            <i className="bi-swatch bi-swatch-down" />{labels.falling} · {counts.down}
          </span>
        ) : null}
        {counts.up ? (
          <span className="flex items-center gap-1">
            <i className="bi-swatch" />{labels.rising} · {counts.up}
          </span>
        ) : null}
        {counts.unknown ? (
          <span className="flex items-center gap-1">
            <i className="bi-swatch bi-swatch-unknown" />
            {labels.unknown} · {counts.unknown}
            <span className="opacity-70">— {labels.unknownHint}</span>
          </span>
        ) : null}
      </div>
    </div>
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
            <span className="w-24 shrink-0 truncate text-[11px]">{row.label}</span>
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
            {/* The leading share, stated. A stacked bar read by eye is a guess. */}
            <span className="w-20 shrink-0 text-right text-[10px] tabular-nums text-fg-muted">
              {parts[0]?.label} {parts[0]?.value.toFixed(0)}%
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
      {/* Without this the rings are decoration: 50 is parity with the median,
          and that is the only number on the chart that means anything. */}
      <text className="bi-axis-tick" x={c + 2} y={c - r * 0.5 - 2}>{parityLabel}</text>
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
