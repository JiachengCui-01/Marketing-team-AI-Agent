"use client";

import { useId, useRef, useState, type CSSProperties } from "react";

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

/** Hold a value inside a fitted axis, so a reading outside the frame is drawn
 *  pinned to its edge rather than off the drawing. */
function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

/** Which wall of a fitted frame a reading fell outside of. */
type Wall = "top" | "bottom" | "left" | "right";

/** The mark on a dot pinned to that wall: a triangle standing on the frame
 *  edge, apex pointing at the reading the chart stops short of. `cx`/`cy` are
 *  the clamped position, so the arrow sits on the edge while the disc rests
 *  just inside it. Shared by both quadrants — the same claim in both, and two
 *  copies of it drifted apart the moment one frame gained a rail. */
function pinArrow(wall: Wall, cx: number, cy: number,
                  frame: { left: number; right: number;
                           top: number; bottom: number }): string {
  const [back, half] = [6.5, 4.5];
  if (wall === "bottom") {
    return `M${cx - half},${frame.bottom - back} L${cx + half},`
           + `${frame.bottom - back} L${cx},${frame.bottom} Z`;
  }
  if (wall === "top") {
    return `M${cx - half},${frame.top + back} L${cx + half},${frame.top + back} `
           + `L${cx},${frame.top} Z`;
  }
  if (wall === "right") {
    return `M${frame.right - back},${cy - half} L${frame.right - back},`
           + `${cy + half} L${frame.right},${cy} Z`;
  }
  return `M${frame.left + back},${cy - half} L${frame.left + back},${cy + half} `
         + `L${frame.left},${cy} Z`;
}

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

/** The score, and every factor that made it — the whole sum, not a highlight.
 *
 * This was a strip of anonymous segments whose only labels were `title`
 * tooltips, then a shortlist: the top two earners and the single biggest
 * shortfall. The shortlist was readable and it could not be checked. Two cards
 * showing different factor names read as two different models, the four or five
 * factors it left out were invisible whatever they scored, and nothing on the
 * card added up to the number the board ranks on.
 *
 * So every factor is listed, in the model's own order so two cards line up row
 * for row, each with what it earned out of what it is worth, and the total is
 * printed underneath. A factor that was never measured says so rather than
 * showing a 0 that looks like a reading — it is scored as zero, which is a
 * different sentence from "the market scored zero here".
 */
export function ScoreBar({
  score,
  breakdown,
  weights,
  riskKey = "return_risk",
  labels = {},
  compact = false,
  missing = [],
  totalLabel,
  unmeasuredLabel,
}: {
  score: number;
  breakdown: Record<string, number>;
  weights: Record<string, number>;
  riskKey?: string;
  labels?: Record<string, string>;
  compact?: boolean;
  /** Factor keys with no reading this period. They score zero and say so. */
  missing?: string[];
  /** e.g. 总分 / Total — names the line the rows add up to. */
  totalLabel?: string;
  /** e.g. 未测到 / not measured. */
  unmeasuredLabel?: string;
}) {
  const risk = Math.abs(breakdown[riskKey] ?? 0);
  const gaps = new Set(missing);
  // Weight order, which is the model's own order: two cards then line up row for
  // row and the eye can compare them without reading the labels again.
  const factors = Object.entries(weights).map(([key, weight]) => ({
    key,
    label: labels[key] ?? key,
    earned: breakdown[key] ?? 0,
    weight,
    unmeasured: gaps.has(key),
  }));

  return (
    <div>
      <div className="bi-score-track" role="img"
           aria-label={`score ${score} of 100; ${factors
             .map((f) => `${f.label} ${f.earned.toFixed(1)} of ${f.weight}`)
             .join(", ")}${risk ? `; risk -${risk.toFixed(1)}` : ""}`}>
        <div className="bi-score-fill" style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
      </div>
      {compact ? null : (
        <ul className="mt-1 space-y-[3px] text-[10px] leading-tight">
          {factors.map((factor) => (
            <li key={factor.key} className="flex items-baseline gap-1.5">
              <span className={`w-16 shrink-0 truncate text-left ${
                factor.unmeasured ? "text-fg-subtle" : "text-fg-muted"}`}
                    title={factor.label}>{factor.label}</span>
              {/* The share of its own weight this factor earned. A number
                  already says it; the rail is what makes eleven of them
                  scannable without being read one at a time. */}
              <span className="bi-factor-track">
                <span className="bi-factor-fill"
                      style={{ width: `${Math.max(0, Math.min(100,
                        (factor.earned / (factor.weight || 1)) * 100))}%` }} />
              </span>
              <span className={`ml-auto shrink-0 tabular-nums ${
                factor.unmeasured ? "text-fg-subtle" : "text-fg"}`}>
                {factor.unmeasured
                  ? `${unmeasuredLabel ?? "—"} 0/${factor.weight}`
                  : `${trim(factor.earned)}/${factor.weight}`}
              </span>
            </li>
          ))}
          <li className="flex items-baseline gap-1.5 text-danger">
            <span className="w-16 shrink-0 truncate text-left"
                  title={labels[riskKey] ?? riskKey}>{labels[riskKey] ?? riskKey}</span>
            <span className="bi-factor-track">
              <span className="bi-factor-fill bi-factor-fill-risk"
                    style={{ width: `${Math.min(100, (risk / 15) * 100)}%` }} />
            </span>
            <span className="ml-auto shrink-0 tabular-nums">−{trim(risk)}</span>
          </li>
          {/* The line the rows add up to. Without it the breakdown is a set of
              numbers beside a score rather than the score taken apart. */}
          <li className="mt-1 flex items-baseline gap-1.5 border-t border-border
                         pt-1 font-medium">
            <span className="w-16 shrink-0 truncate text-left">
              {totalLabel ?? "="}
            </span>
            <span className="ml-auto shrink-0 tabular-nums">{score}</span>
          </li>
        </ul>
      )}
    </div>
  );
}

/** One decimal, and none when it is a whole number: `18.4` and `20`, never
 *  `20.0`. The factors are rounded to a tenth server-side, so printing them as
 *  integers is what stopped the column from adding up to the score. */
function trim(value: number): string {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

/** A band leads when its revenue share runs this far ahead of its listings. */
const BAND_LEAD_PP = 3;

/** The next round percentage above a reading, so the axis tick is a number a
 *  reader recognises rather than whatever the tallest bar happened to be. */
function niceCeilPct(value: number): number {
  const step = value >= 10 ? 5 : value >= 4 ? 2 : 1;
  return Math.max(step, Math.ceil(value / step) * step);
}

/** Where the money is against where the listings are.
 *
 * This was two bars per band in two tints of one green, unlabelled except for a
 * bare "20%" floating over the top right corner. Both series were the same hue
 * and the same shape, so telling them apart was a colour-matching exercise
 * against a legend, and the thing the chart exists to show — the gap between
 * them — had to be eyeballed across a 2px trough with no scale behind it.
 *
 * One bar per band now, and it is the money: the column is the band's share of
 * revenue. Its listing share is the rule drawn across it, which is the share
 * the band would take if price made no difference to what sells. So the reading
 * is a position, not a comparison of two lengths — a column standing above its
 * own rule is a band that pays up, and those columns are painted a step
 * stronger. Two marks of different *shape* also means the legend is not the
 * only thing holding the two series apart.
 *
 * The axis is labelled and gridded at a round percentage, the columns are wide
 * with only a few pixels between them because the x is a continuous price axis,
 * and only the leading band carries a number.
 */
export function BandHistogram({
  bands,
  listingLabel,
  revenueLabel,
  leadLabel,
  readingLabel,
}: {
  bands: { bucket_key: string; listing_share_pct?: number; revenue_share_pct?: number;
           units_ratio?: number | null }[];
  listingLabel: string;
  revenueLabel: string;
  /** e.g. "这个价格带愿意付钱" — names what the marked gap means. */
  leadLabel?: string;
  /** One line naming what the column and the rule are, above the plot. */
  readingLabel?: string;
}) {
  const rows = bands.map((b) => ({
    key: b.bucket_key,
    listing: b.listing_share_pct ?? (b.units_ratio ?? 0) * 100,
    revenue: b.revenue_share_pct ?? 0,
  }));
  if (!rows.length) return null;
  const axisMax = niceCeilPct(Math.max(1, ...rows.flatMap((r) => [r.listing, r.revenue])));
  const leader = rows.reduce((best, r) =>
    r.revenue - r.listing > best.revenue - best.listing ? r : best, rows[0]);
  const leads = leader.revenue - leader.listing;
  const plot = 108;
  // Room above the plot for the one direct label, so a tall leading column puts
  // its number in the margin instead of over the top gridline.
  const cap = 16;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-fg-subtle">
        <span className="flex items-center gap-1"><i className="bi-swatch" />{revenueLabel}</span>
        <span className="flex items-center gap-1"><i className="bi-band-rule" />{listingLabel}</span>
      </div>
      {readingLabel ? (
        <p className="mt-0.5 text-[10px] text-fg-subtle">{readingLabel}</p>
      ) : null}
      <div className="mt-1.5 flex gap-1.5">
        {/* The scale, so a column's height is a quantity rather than a mood. */}
        <div className="flex shrink-0 flex-col justify-between text-[9px] tabular-nums
                        text-fg-subtle"
             style={{ height: plot + cap, paddingTop: cap }}>
          <span>{axisMax}%</span>
          <span>0</span>
        </div>
        <div className="min-w-0 flex-1 overflow-x-auto pb-0.5">
          <div role="img"
               aria-label={rows
                 .map((r) => `${r.key}: ${revenueLabel} ${r.revenue.toFixed(1)}%, `
                   + `${listingLabel} ${r.listing.toFixed(1)}%`)
                 .join("; ")}>
            <div className="relative" style={{ height: plot, marginTop: cap }}>
              <div className="bi-band-grid" style={{ top: 0 }} />
              <div className="bi-band-grid" style={{ bottom: 0 }} />
              <div className="flex h-full items-end gap-[3px]">
                {rows.map((row) => {
                  const ahead = row.revenue - row.listing >= BAND_LEAD_PP;
                  const top = `${(row.revenue / axisMax) * 100}%`;
                  return (
                    <div key={row.key} className="relative h-full min-w-[42px] flex-1"
                         title={`${row.key} · ${revenueLabel} ${row.revenue.toFixed(1)}% · `
                                + `${listingLabel} ${row.listing.toFixed(1)}%`}>
                      <div className={`bi-band-money${ahead ? " bi-band-money-lead" : ""}`}
                           style={{ height: top }} />
                      <div className="bi-band-bench"
                           style={{ bottom: `${(row.listing / axisMax) * 100}%` }} />
                      {row === leader && leads >= BAND_LEAD_PP ? (
                        <span className="bi-band-cap" style={{ bottom: `calc(${top} + 3px)` }}>
                          +{leads.toFixed(0)}pp
                        </span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
            <div className="mt-1 flex gap-[3px]">
              {rows.map((row) => (
                <span key={row.key}
                      className="min-w-[42px] flex-1 truncate text-center text-[9px]
                                 tabular-nums text-fg-subtle"
                      title={row.key}>{row.key}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
      {leadLabel && leads >= BAND_LEAD_PP ? (
        <p className="mt-1.5 text-[10px] text-fg-muted">
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

/** One element on the chart.
 *
 * Both axes are nullable, and that is the type's whole job: `null` is the
 * difference between "zero" and "we never took this reading". An element with
 * both readings gets a position in the field; one with a single reading gets a
 * rail mark against the axis it has. Making the nullable form the general one —
 * rather than a separate rail type narrowed off it — is what lets one predicate
 * decide which, on both sides of the wire.
 */
export type ElementPoint = {
  key: string;
  label: string;
  kind: string;
  kind_label: string;
  /** Share of head revenue whose listing title mentions this element. */
  shelf_pct: number | null;
  /** Stars against the board median — the y axis. Negative is the interesting
   *  direction: the market is taking money for something it does badly. */
  rating_gap: number | null;
  /** The rating itself, so the gap can be read as a number and not only as a
   *  position. */
  rating: number | null;
  /** Median review count across the spec's listings: what it costs to be
   *  believed here. */
  reviews: number | null;
  /** Head revenue, which is what the dot area encodes. */
  revenue: number;
  asins: number;
  avg_price: number | null;
  /** Set when the point is a spec rather than a single element: the combination
   *  broken out attribute by attribute, for the hover card. A glued label reads
   *  as one long word; "材质 实木 · 颜色 黑色" reads as a decision. */
  spec?: { kind: string; kind_label: string; label: string }[];
};

/** An element measured on both axes, so it has a position to be drawn at. */
export type ElementFieldPoint = ElementPoint & {
  shelf_pct: number;
  rating_gap: number;
};

export function inField(point: ElementPoint): point is ElementFieldPoint {
  // Loose equality on purpose: a dashboard stored before this axis existed has
  // no `rating_gap` key at all, and `undefined !== null` would send it to be
  // drawn at NaN.
  return point.shelf_pct != null && point.rating_gap != null;
}

/** The chart's axis bounds, computed server-side from the points on show.
 *
 *  `x_mid` is the department's median shelf share — a claim about the department
 *  rather than about the points drawn, which is why the server computes it over
 *  every measured element rather than over the ones that fit on the chart. */
export type ElementChartBounds = {
  /** Where the x axis starts. Usually 0 — a share of nothing is a real reading
   *  — but a board whose specs all sit well clear of zero is drawn where the
   *  specs are. Absent on a dashboard stored before the frame was fitted. */
  x_min?: number;
  x_max: number;
  x_mid: number;
  y_min: number;
  y_max: number;
  /** The rating the zero line stands for: the board median, in stars. */
  y_mid: number;
};

/** What genuinely has to be global: the dot area encodes head revenue, so it is
 *  measured against one maximum across every row. */
export type ElementScale = {
  max_revenue: number;
};

/** Row names for the hover card. The two axis names come in separately because
 *  they are the same two strings the axes themselves are labelled with. */
export type ElementTipLabels = {
  rating: string;
  reviews: string;
  asins: string;
  price: string;
  /** Stands in for a number that was never measured, e.g. 未测到 / not measured. */
  unmeasured: string;
};

/** One attribute, full width: the elements that are alternatives to each other.
 *
 * The board says which category to work in. This says what the product should
 * look like, which is the question a design review actually opens with. Both
 * axes are measured, from calls the sweep already makes: x from the titles of
 * the listings that hold the revenue, y from the search phrases that carry the
 * element.
 *
 * A row rather than a tile. Sizes, materials, finishes and surface treatments
 * each get the full width, because the comparison that matters is between the
 * dots inside one row — and a three-across grid was spending most of its pixels
 * making nine of those comparisons possible at once, which is a thing nobody
 * does.
 *
 * The cell that matters is top-left: demand rising, shelf thin. It is tinted in
 * every row; the four corner names are printed once, by the panel set, rather
 * than redrawn over the dots they are meant to explain.
 */
export function ElementMatrix({
  points,
  xLabel,
  yLabel,
  bounds,
  scale,
  medianLabel,
  tipLabels,
  railLabels,
  aspect = "row",
}: {
  /** Field dots and rail marks in one list; `inField` decides which is which. */
  points: ElementPoint[];
  xLabel: string;
  yLabel: string;
  /** This row's own axis bounds. */
  bounds: ElementChartBounds;
  /** The one globally shared quantity: what the largest dot area means. */
  scale: ElementScale;
  /** Names the dashed vertical reference for what it is, e.g. 中位 / median. */
  medianLabel: string;
  /** Row names for the hover card's lower half. */
  tipLabels: ElementTipLabels;
  /** Names the two rails, e.g. 评分未测到 / 货架未测到. */
  railLabels: { noRating: string; noShelf: string };
  /** `row` is one attribute in a stack of rows; `solo` is the single spec chart,
   *  which carries an order of magnitude more points and needs the height. */
  aspect?: "row" | "solo";
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] =
    useState<{ point: ElementPoint; style: CSSProperties } | null>(null);
  // One list in, three groups out, by the same predicate the server used to
  // decide the caps. A rail element missing its own axis too has nowhere to go
  // and is not drawn.
  const field = points.filter(inField);
  const rails = {
    shelf: points.filter((p) => !inField(p) && p.shelf_pct != null),
    rating: points.filter((p) => !inField(p) && p.rating_gap != null),
  };
  if (!points.length) return null;
  // Wide and short. The aspect ratio is the row's height control: the drawing
  // scales to the column it is in, so 5:1 is what keeps a full-width row about
  // 190px tall instead of 280 — seven rows of which is a scroll, not a chart.
  // The absolute numbers are chosen so that scaling lands near 1:1 on a desktop
  // panel and the 9px type stays the size it was designed at.
  const width = 1000;
  const height = aspect === "solo" ? 440 : 200;
  // Left pad carries the y tick values only; both axis names are on one line
  // under the plot. The two axes are different units — a share of revenue on x,
  // stars against the median on y — so a row that prints only numbers makes the
  // reader guess which is which. They are named for that reason, not for
  // decoration.
  const padL = 42;
  const padR = 20;
  const padT = 22;
  const padB = 34;

  // Bounds from this row's own elements; the dot area from the whole set, so a
  // big element in a quiet row cannot out-draw a bigger one in a busy row.
  const { x_max: xMax, x_mid: xMid, y_min: yMin, y_max: yMax } = bounds;
  // Older payloads have no x_min: the axis started at zero by construction.
  const xMin = bounds.x_min ?? 0;
  const maxRevenue = Math.max(1, scale.max_revenue);

  // The rails are inside the padding, not extra chrome outside it: each takes a
  // strip off the field and keeps its own axis, so a rail mark lines up with the
  // field marks it shares that axis with.
  const railW = rails.rating.length ? 26 : 0;
  const railH = rails.shelf.length ? 22 : 0;
  const fieldL = padL + railW;
  const fieldB = padB + railH;

  const px = (v: number) =>
    fieldL + ((clamp(v, xMin, xMax) - xMin) / (xMax - xMin || 1))
             * (width - fieldL - padR);
  const py = (v: number) =>
    height - fieldB
    - ((clamp(v, yMin, yMax) - yMin) / (yMax - yMin || 1)) * (height - padT - fieldB);

  // The frame is fitted to where the points are, so a reading far enough clear
  // of the rest of them can fall outside it — see the server's `_fitted`. It is
  // pinned to the frame rather than dropped, and drawn with an arrow against
  // the wall it is pressed to, so nobody reads the pinned position as the
  // measurement. Which wall, if any:
  const pinnedAt = (point: ElementFieldPoint): Wall | null =>
    point.rating_gap < yMin ? "bottom" : point.rating_gap > yMax ? "top"
    : point.shelf_pct > xMax ? "right" : point.shelf_pct < xMin ? "left" : null;
  const frame = { left: fieldL, right: width - padR,
                  top: padT, bottom: height - fieldB };
  // And whether either end of either axis has one, which is what the tick value
  // there has to admit to: "-0.3" and "at most -0.3" are different claims.
  const cut = {
    xMax: field.some((p) => p.shelf_pct > xMax),
    xMin: field.some((p) => p.shelf_pct < xMin),
    yMax: field.some((p) => p.rating_gap > yMax),
    yMin: field.some((p) => p.rating_gap < yMin),
  };
  // Tick values follow the span rather than a fixed precision: a fitted axis
  // can be a tenth of a point wide, and "0% … 0%" is what a hard toFixed(0)
  // prints for it.
  const xTick = (v: number) => `${v.toFixed(xMax - xMin < 10 ? 1 : 0)}%`;
  const yTick = (v: number) => v.toFixed(yMax - yMin < 0.5 ? 2 : 1);

  // Biggest first, so a small dot is never hidden under a large one, and so the
  // labels that get dropped on collision are the least important ones.
  const ordered = [...field].sort((a, b) => b.revenue - a.revenue);
  const placed: { x: number; y: number }[] = [];

  // Seats are claimed here rather than during the draw, because the draw order
  // is the opposite of the priority order: rail marks paint first so a field dot
  // is never hidden under one, but a measured position deserves its name more
  // than a rail mark does. Biggest first within the field, as before.
  //
  // Capped as well as collision-checked. Collision alone is not enough on the
  // spec chart: forty-five points leave a dense middle where a dozen labels
  // technically fit and collectively read as noise. Past the cap the name lives
  // in the hover card, which is where the reader looks for a specific point
  // anyway.
  const labelCap = aspect === "solo" ? 16 : ordered.length;
  // A seat the size of the name that sits in it. An attribute row holds one
  // word — "walnut", "60 inch" — and 56 units is generous for it; a spec is a
  // four-part phrase around 120 units long, and at the row's seat size two of
  // them clear each other by the numbers and still print as one smudge. The
  // dots that lose a seat keep their name in the hover card.
  const [seatW, seatH] = aspect === "solo" ? [130, 18] : [56, 13];
  const labelled = new Set<string>();
  for (const point of ordered) {
    if (labelled.size >= labelCap) break;
    const cx = px(point.shelf_pct);
    const cy = py(point.rating_gap);
    if (placed.some((seat) => Math.abs(seat.x - cx) < seatW
                              && Math.abs(seat.y - cy) < seatH)) continue;
    placed.push({ x: cx, y: cy });
    labelled.add(point.key);
  }

  /** Anchor the card to the dot, not to the cursor.
   *
   * The drawing is a scaled viewBox, so a user-space coordinate becomes a pixel
   * one by the same ratio the browser used to fit it — read off the element
   * rather than assumed, because the row's width changes with the window.
   */
  function show(point: ElementPoint, cx: number, cy: number) {
    const box = svgRef.current?.getBoundingClientRect();
    const k = box ? box.width / width : 1;
    const top = cy * k;
    // Below the dot when the dot sits high in the row: a card anchored above it
    // would hang over the row before this one.
    const below = top < 76;
    setHover({
      point,
      style: {
        // Clamped, or a dot at either end pushes half the card out of the row.
        left: Math.round(Math.min(Math.max(cx * k, 96),
                                  Math.max(96, (box?.width ?? width) - 96))),
        top: Math.round(below ? top + 16 : top - 14),
        transform: `translate(-50%, ${below ? "0" : "-100%"})`,
      },
    });
  }

  const hide = () => setHover(null);

  return (
    <div className="relative">
      {/* No fixed pixel height: with a viewBox and a full-width box the drawing
          scales to the column it sits in, which is what makes the row big on a
          wide screen instead of a 900px island floating in the middle of one. */}
      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="w-full"
           role="img"
           aria-label={points.map((p) => describe(p, xLabel, yLabel, tipLabels))
             .join("; ")}>
        {/* The two corners that carry a decision, tinted instead of captioned.
            Bottom right is the opening — head revenue is already there and the
            listings taking it are rated below the board; top right is the same
            money with the job already done well, which is the corner to leave
            alone. */}
        <rect className="bi-quadrant-open" x={px(xMid)} y={py(0)}
              width={Math.max(0, width - padR - px(xMid))}
              height={Math.max(0, height - fieldB - py(0))} />
        <rect className="bi-quadrant-risk" x={px(xMid)} y={padT}
              width={Math.max(0, width - padR - px(xMid))}
              height={Math.max(0, py(0) - padT)} />

        {/* Both lines are medians of what we track, and both are dashed for it:
            the horizontal one is the board's median rating, the vertical one its
            median share of head revenue. */}
        <line className="bi-axis-dashed" x1={fieldL} x2={width - padR}
              y1={py(0)} y2={py(0)} />
        <line className="bi-axis-dashed" x1={px(xMid)} x2={px(xMid)}
              y1={padT} y2={height - fieldB} />

        {/* The rails, and the boundary that says a mark inside one is missing a
            reading rather than sitting at zero. Left rail: demand measured, too
            few head listings to state a share. Bottom rail: on the shelf, no
            rated search signal. */}
        {rails.rating.length ? (
          <>
            <line className="bi-rail-edge" x1={fieldL - 6} x2={fieldL - 6}
                  y1={padT} y2={height - fieldB} />
            <text className="bi-rail-name" x={padL + railW / 2 - 3} y={padT - 8}
                  textAnchor="middle">{railLabels.noShelf}</text>
          </>
        ) : null}
        {rails.shelf.length ? (
          <>
            <line className="bi-rail-edge" x1={fieldL} x2={width - padR}
                  y1={height - fieldB + 6} y2={height - fieldB + 6} />
            <text className="bi-rail-name" x={width - padR}
                  y={height - padB - railH / 2 + 3} textAnchor="end">
              {railLabels.noRating}
            </text>
          </>
        ) : null}

        {/* Signed stars, and the zero line carries the rating it stands for: a
            bare 0 would leave the reader to guess what "average" was. */}
        <text className="bi-axis-tick" x={padL - 6} y={py(0) - 3} textAnchor="end">
          {medianLabel}
        </text>
        <text className="bi-axis-tick" x={padL - 6} y={py(0) + 9} textAnchor="end">
          {(bounds.y_mid ?? 0).toFixed(1)}★
        </text>
        {/* A fitted frame can stop short of a reading, and the tick is where it
            says so: ≥ / ≤ rather than a bare number that a pinned dot would
            turn into a lie. */}
        <text className="bi-axis-tick" x={padL - 6} y={padT + 4} textAnchor="end">
          {cut.yMax ? "≥" : "+"}{yTick(yMax)}
        </text>
        <text className="bi-axis-tick" x={padL - 6} y={height - fieldB} textAnchor="end">
          {cut.yMin ? "≤" : ""}{yTick(yMin)}
        </text>
        {/* The dashed line's value is meaningless without the word: nothing tells
            a reader that 13% is the median of the elements we track. */}
        <text className="bi-axis-tick" x={px(xMid)} y={height - padB + 13} textAnchor="middle">
          {medianLabel} {xTick(xMid)}
        </text>
        <text className="bi-axis-tick" x={fieldL} y={height - padB + 13}
              textAnchor="start">{cut.xMin ? "≤" : ""}{xTick(xMin)}</text>
        <text className="bi-axis-tick" x={width - padR} y={height - padB + 13} textAnchor="end">
          {cut.xMax ? "≥" : ""}{xTick(xMax)}
        </text>

        {/* Axis names, on every row. The one-line note in the section heading was
            doing this job for a single chart and stopped working the moment there
            were seven of them and the eye had left the heading.
            Both names sit horizontally on one line under the plot — y on the
            left with its arrow, x on the right with its own. The y name used to
            be rotated up the left edge, which reads badly for Chinese: rotating
            a run of CJK glyphs turns each one on its side rather than stacking
            them, so the reader tilts their head to parse a two-word label. The
            arrow is what ties the name to its axis, so the name does not have to
            sit against it. Unrotating it also freed 22px of left padding, which
            went straight into the plot. */}
        <text className="bi-axis-title" x={2} y={height - padB + 26}
              textAnchor="start">{yLabel} ↑</text>
        <text className="bi-axis-title" x={width - padR} y={height - padB + 26}
              textAnchor="end">{xLabel} →</text>

        {/* Rail marks first, so a field dot is never hidden under one. Both
            rails are the same mark pinned to the one axis its element has, so
            they are one list of (point, x, y) rather than two near-identical
            blocks that have to be kept in step. */}
        {[
          ...rails.rating.map((point) => ({
            point, cx: padL + railW / 2, cy: py(point.rating_gap as number) })),
          ...rails.shelf.map((point) => ({
            point, cx: px(point.shelf_pct as number),
            cy: height - padB - railH / 2 })),
        ].map(({ point, cx, cy }) => {
          // Named like any other element. Leaving the rails unlabelled made a
          // real element look like a decoration: "there is something here" and
          // no way to find out what without hunting for it with a mouse.
          const clash = placed.some(
            (seat) => Math.abs(seat.x - cx) < seatW - 4
                      && Math.abs(seat.y - cy) < seatH - 1);
          if (!clash) placed.push({ x: cx, y: cy });
          return (
            <g key={point.key} className="bi-dot-group" tabIndex={0} role="button"
               aria-label={describe(point, xLabel, yLabel, tipLabels)}
               onMouseEnter={() => show(point, cx, cy)} onMouseLeave={hide}
               onFocus={() => show(point, cx, cy)} onBlur={hide}>
              {/* Open square, not a disc: a different shape for a different
                  claim, so nobody reads a rail mark as a measured position. */}
              <rect x={cx - 9} y={cy - 7} width={18} height={14} fill="transparent" />
              <rect className="bi-rail-mark" x={cx - 4} y={cy - 4}
                    width={8} height={8} rx={1.5} />
              {!clash ? (
                <text className="bi-point-label" x={cx} y={cy - 9} textAnchor="middle">
                  {truncate(point.label, 10)}
                </text>
              ) : null}
            </g>
          );
        })}

        {ordered.map((point) => {
          const r = 4 + Math.sqrt(point.revenue / maxRevenue) * 11;
          // A pinned dot rests just inside the wall it is pressed to: half a
          // disc hanging over the axis would land in the rail strip and read as
          // a rail mark, which is a different claim again.
          const wall = pinnedAt(point);
          const edgeX = px(point.shelf_pct);
          const edgeY = py(point.rating_gap);
          const cx = edgeX + (wall === "left" ? r : wall === "right" ? -r : 0);
          const cy = edgeY + (wall === "top" ? r : wall === "bottom" ? -r : 0);
          // Colour says which corner, not which sign: below the median rating is
          // only an opening where there is money to take, and above it is only
          // a warning for the same reason. A well-rated spec nobody buys is
          // neither, and gets the plain mark.
          const heavy = point.shelf_pct >= xMid;
          const opening = heavy && point.rating_gap < 0;
          const crowded = heavy && point.rating_gap >= 0;
          // Drop a label rather than stack it: two names on top of each other is
          // worse than one name and a dot whose name the hover card gives back.
          const clash = !labelled.has(point.key);
          const hot = hover?.point.key === point.key;
          return (
            <g key={point.key} className="bi-dot-group"
               tabIndex={0} role="button"
               aria-label={describe(point, xLabel, yLabel, tipLabels)}
               onMouseEnter={() => show(point, cx, cy)}
               onMouseLeave={hide}
               onFocus={() => show(point, cx, cy)}
               onBlur={hide}>
              {/* The hit target is bigger than the mark; an 8px dot is not a
                  button, and this is now the thing that opens the hover card. */}
              <circle cx={cx} cy={cy} r={Math.max(15, r + 8)} fill="transparent" />
              {/* Disc for the volume, core for the position. Overlapping discs stay
                  countable because their cores do not merge. */}
              <circle className={`bi-dot-disc${opening ? "" : crowded
                                   ? " bi-dot-disc-risk" : " bi-dot-disc-flat"}`
                                 + (hot ? " bi-dot-hot" : "")}
                      cx={cx} cy={cy} r={r} />
              <circle className={`bi-dot-core${opening ? "" : crowded
                                   ? " bi-dot-core-risk" : " bi-dot-core-flat"}`}
                      cx={cx} cy={cy} r={Math.min(3, r / 3)} />
              {/* Off the fitted frame: the arrow, and the reading itself in the
                  hover card. Dropping the point would be a claim about the
                  market; drawing it at the edge unmarked would be a claim about
                  its position. */}
              {wall ? (
                <path className={`bi-dot-pin${opening ? "" : crowded
                                   ? " bi-dot-pin-risk" : " bi-dot-pin-flat"}`}
                      d={pinArrow(wall, edgeX, edgeY, frame)} />
              ) : null}
              {!clash ? (
                <text className="bi-point-label" x={cx} y={cy - r - 5} textAnchor="middle">
                  {truncate(point.label, aspect === "solo" ? 16 : 12)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>

      {/* An HTML card rather than SVG <title>. The native tooltip waits about a
          second, cannot be styled, and — the reason it had to go — was attached
          to the 3px core while the hit target is 15px, so on most dots it never
          appeared at all. Half the dots carry no printed label because their
          names would collide, and this is where those names live. */}
      {hover ? (
        <div className="bi-dot-tip" style={hover.style}>
          <div className="bi-dot-tip-head">
            <span className="bi-dot-tip-name">{hover.point.label}</span>
            <span className="bi-chip bi-chip-observed">{hover.point.kind_label}</span>
          </div>
          {/* A spec's own rows, above the measurements: which attribute took
              which value is the thing the reader came for. */}
          {hover.point.spec?.length ? (
            <div className="mb-1.5 border-b border-border pb-1.5">
              {hover.point.spec.map((part) => (
                <TipRow key={part.kind} label={part.kind_label} value={part.label} />
              ))}
            </div>
          ) : null}
          {/* An unmeasured half says so, in the row where its number would have
              been. Leaving the row out would read as "nothing to say about the
              rating"; a dash reads as "we did not measure it", which is the
              fact. */}
          <TipRow label={yLabel} value={stars(hover.point.rating_gap, tipLabels.unmeasured)} />
          <TipRow label={xLabel}
                  value={pct(hover.point.shelf_pct, tipLabels.unmeasured, false)} />
          <TipRow label={tipLabels.rating}
                  value={hover.point.rating == null ? tipLabels.unmeasured
                         : `${hover.point.rating.toFixed(2)}★`} />
          {hover.point.reviews != null ? (
            <TipRow label={tipLabels.reviews}
                    value={hover.point.reviews.toLocaleString()} />
          ) : null}
          <TipRow label={tipLabels.asins} value={`${hover.point.asins}`} />
          {hover.point.avg_price != null ? (
            <TipRow label={tipLabels.price} value={fmtMoney(hover.point.avg_price)} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TipRow({ label, value, tone }: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="bi-dot-tip-row">
      <span className="bi-dot-tip-key">{label}</span>
      <span className={"bi-dot-tip-val"
                       + (tone === "up" ? " text-success"
                          : tone === "down" ? " text-danger" : "")}>
        {value}
      </span>
    </div>
  );
}

/** A signed gap in stars, or the word for a reading that was never taken. */
function stars(value: number | null, unmeasured: string): string {
  if (value == null || !Number.isFinite(value)) return unmeasured;
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}★`;
}

/** A percentage, or the word for a reading that was never taken. */
function pct(value: number | null, unmeasured: string, signed = true): string {
  if (value == null || !Number.isFinite(value)) return unmeasured;
  return `${signed && value >= 0 ? "+" : ""}${fmtPct(value)}`;
}

/** The card's contents as one string, for the screen reader that cannot hover. */
function describe(point: ElementPoint, xLabel: string, yLabel: string,
                  tipLabels: ElementTipLabels): string {
  return `${point.label}（${point.kind_label}） · `
    + `${yLabel} ${stars(point.rating_gap, tipLabels.unmeasured)} · `
    + `${xLabel} ${pct(point.shelf_pct, tipLabels.unmeasured, false)} · `
    + `${tipLabels.rating} ${point.rating ?? tipLabels.unmeasured} · `
    + `${tipLabels.asins} ${point.asins}`
    + (point.avg_price != null ? ` · ${fmtMoney(point.avg_price)}` : "");
}

/** Every spec the market has built, on one chart.
 *
 * The attribute rows answer "of the finishes we track, which one is cooling".
 * This answers the question a brief is actually written from: which whole
 * product — a scene, a size, a material, a colour, a look, a surface treatment —
 * is taking the money, and whether the listings taking it are any good. A spec
 * spans the attributes by construction, so there is no attribute to file it
 * under and no row to put it in; it is one chart or it is nothing.
 *
 * Every point came off real listings. Enumerating the combinations of the mined
 * vocabulary would produce thousands of products nobody has made, and a chart of
 * hypothetical specs with a measured axis invites the reader to treat noise as
 * an opening.
 */
export function ElementComboChart({
  points,
  bounds,
  scale,
  quadrants,
  xLabel,
  yLabel,
  medianLabel,
  tipLabels,
  railLabels,
  notes,
  total,
  countLabel,
  moreLabel,
}: {
  points: ElementPoint[];
  bounds?: ElementChartBounds | null;
  scale?: ElementScale | null;
  quadrants: [string, string, string, string];
  xLabel: string;
  yLabel: string;
  medianLabel: string;
  tipLabels: ElementTipLabels;
  railLabels: { noRating: string; noShelf: string };
  notes: string[];
  /** Specs measured, before the plot cap — so a truncated tail is visible. */
  total?: number;
  countLabel: string;
  moreLabel: string;
}) {
  if (!points.length || !bounds || !scale) return null;
  const hidden = Math.max(0, (total ?? points.length) - points.length);
  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2 text-[11px]">
        <span className="text-fg-subtle tabular-nums">
          {total ?? points.length} {countLabel}
        </span>
        {hidden > 0 ? (
          <span className="text-fg-subtle tabular-nums">
            ·&nbsp;{hidden} {moreLabel}
          </span>
        ) : null}
      </div>
      <ElementMatrix points={points} bounds={bounds} scale={scale} aspect="solo"
                     xLabel={xLabel} yLabel={yLabel} medianLabel={medianLabel}
                     tipLabels={tipLabels} railLabels={railLabels} />
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]
                      text-fg-subtle">
        <span>↖&nbsp;{quadrants[0]}</span>
        <span className="flex items-center gap-1">
          ↗<i className="bi-swatch shrink-0 bi-legend-risk" />{quadrants[1]}
        </span>
        <span className="flex items-center gap-1">
          ↘<i className="bi-swatch shrink-0 bi-legend-open" />{quadrants[2]}
        </span>
        <span>↙&nbsp;{quadrants[3]}</span>
      </div>
      {notes.map((note) => (
        <div key={note} className="mt-0.5 text-[10px] text-fg-subtle">{note}</div>
      ))}
    </div>
  );
}

/** One spec on one shelf: the unit the opportunity quadrant is drawn in.
 *
 * A point is the sentence a brief is written from — room, shelf, colour, look —
 * rather than a category. "Sideboards are up 12%" cannot be drawn; "walnut
 * fluted sideboards hold 9% of that shelf, up 2 points, and no brand owns them"
 * can.
 */
export type SpecPoint = {
  key: string;
  node_key: string;
  /** The room-level category: Bedroom Furniture, Home Office, Patio. */
  area: string;
  node_label: string;
  label: string;
  /** The spec broken out row by row for the hover card, the two category rows
   *  first — a look is only open or crowded somewhere. */
  spec: { kind: string; kind_label: string; label: string }[];
  color: string | null;
  look: string | null;
  /** 0–100: what the three largest brands inside the spec have *not* taken. */
  entry: number;
  /** Percentage points of its own shelf, against last month. Null when that
   *  shelf has no comparison month: a rail mark, never a zero. */
  share_shift_pp: number | null;
  /** The same movement, signed against the median spec on the chart — the
   *  position on y. Absent on a dashboard stored before the axis was
   *  re-centred, whose frame was drawn against zero. */
  shift_gap_pp?: number | null;
  share_pct: number;
  share_before_pct: number | null;
  revenue: number;
  asins: number;
  brands: number;
  avg_price: number | null;
  rating: number | null;
  reviews: number | null;
  /** The shelf's own return risk, carried for the card. It belongs to the
   *  category rather than to the look, so it is never a position here. */
  return_risk: number;
};

export type SpecBounds = {
  x_min: number;
  x_max: number;
  /** The median 可进入度 of the specs drawn — a claim about this board rather
   *  than an absolute. Three brands inside one colour of one shelf are not
   *  comparable to five brands across a whole category, so a fixed 50 would be
   *  a number pretending to be a threshold. */
  x_mid: number;
  y_min: number;
  y_max: number;
  /** The movement the y zero line stands for: the median spec's own share
   *  shift, in percentage points. Absent on an older payload, where the line
   *  was an absolute zero and this is therefore 0. */
  y_mid?: number;
};

export type SpecTipLabels = {
  share: string;
  was: string;
  revenue: string;
  asins: string;
  brands: string;
  rating: string;
  reviews: string;
  price: string;
  returnRisk: string;
  /** Names the raw movement in the hover card, e.g. 份额变化, as opposed to the
   *  axis, which carries the same number signed against the median. */
  shift: string;
  /** Stands in for a number that was never measured, e.g. 未测到. */
  unmeasured: string;
};

/** The opportunity quadrant, over specs rather than over categories.
 *
 * The old one plotted a dot per tracked category: the same rows the board
 * above it already lists, minus the ones whose growth happened to be
 * unmeasurable — a duplicate, and an incomplete duplicate. This plots what a
 * design programme actually chooses between.
 *
 * x is 可进入度: what is left of a spec once its three largest brands have taken
 * theirs. y is how much of its own shelf the spec has won since last month, in
 * percentage points — a share rather than a growth rate, because the number of
 * listings we hold for a node moves with whatever the monthly walk collected
 * and a share does not. Right and up is the opening: nobody owns it, and it is
 * taking the shelf.
 *
 * The room chips are a filter, not decoration: ninety specs across five rooms
 * is a chart nobody reads all at once. The axes stay fixed while it is
 * filtered, so a dot does not move when the reader narrows to its room.
 */
export function SpecQuadrant({
  points,
  bounds,
  scale,
  areas = [],
  total,
  onPick,
  xLabel,
  yLabel,
  medianLabel,
  quadrants,
  railLabel,
  allLabel,
  countLabel,
  moreLabel,
  tipLabels,
  notes = [],
  width = 1000,
  height = 470,
}: {
  points: SpecPoint[];
  bounds?: SpecBounds | null;
  scale?: { max_revenue: number } | null;
  /** The rooms present, biggest first, for the filter chips. */
  areas?: { area: string; count: number; revenue: number }[];
  /** Specs measured, before the plot cap — so a truncated tail stays visible. */
  total?: number;
  onPick?: (nodeKey: string) => void;
  xLabel: string;
  yLabel: string;
  medianLabel: string;
  /** Clockwise from top-right: open+rising, crowded+rising, crowded+falling,
   *  open+falling. Named so a dot's position is a recommendation, not a mood. */
  quadrants: [string, string, string, string];
  railLabel: string;
  allLabel: string;
  countLabel: string;
  moreLabel: string;
  tipLabels: SpecTipLabels;
  notes?: string[];
  /** Canvas in user units; the svg scales to the width of the row it sits in. */
  width?: number;
  height?: number;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hover, setHover] =
    useState<{ point: SpecPoint; style: CSSProperties } | null>(null);
  const [room, setRoom] = useState("");
  if (!points.length || !bounds || !scale) return null;

  const shown = room ? points.filter((p) => p.area === room) : points;
  const field = shown.filter((p) => gapOf(p) != null);
  const rail = shown.filter((p) => gapOf(p) == null);
  const hidden = Math.max(0, (total ?? points.length) - points.length);

  const padL = 46;
  const padR = 22;
  const padT = 26;
  const padB = 40;
  // The rail is a strip taken off the field rather than chrome outside it, so a
  // rail mark lines up with the field dots it shares an x with. Its height
  // comes from the whole chart and not from the filtered subset: otherwise
  // picking a room whose shelves all have a comparison month would give the
  // field 24 more pixels and move every remaining dot, which is exactly what a
  // filter must not do.
  const railed = points.some((p) => gapOf(p) == null);
  const railH = railed ? 24 : 0;
  const fieldB = padB + railH;
  const { x_min: xMin, x_max: xMax, x_mid: xMid, y_min: yMin, y_max: yMax } = bounds;
  // What y = 0 stands for: the median spec's own movement. Zero on an older
  // payload, which is exactly what it meant there.
  const shiftMid = bounds.y_mid ?? 0;
  const maxRevenue = Math.max(1, scale.max_revenue);
  const px = (v: number) =>
    padL + ((clamp(v, xMin, xMax) - xMin) / (xMax - xMin || 1))
           * (width - padL - padR);
  const py = (v: number) =>
    height - fieldB
    - ((clamp(v, yMin, yMax) - yMin) / (yMax - yMin || 1)) * (height - padT - fieldB);

  // The frame is fitted to the points, so a reading far enough clear of the
  // rest can fall outside it. Pinned to the wall it is pressed to and drawn
  // with an arrow, never dropped and never drawn as if it were measured there.
  const pinnedAt = (point: SpecPoint): Wall | null => {
    const gap = gapOf(point);
    if (gap == null) return null;
    return gap < yMin ? "bottom" : gap > yMax ? "top"
      : point.entry > xMax ? "right" : point.entry < xMin ? "left" : null;
  };
  const frame = { left: padL, right: width - padR,
                  top: padT, bottom: height - fieldB };
  // Which ends of which axis stop short of a reading, so the tick there can say
  // so rather than print a number a pinned dot would make into a lie.
  const cut = {
    xMax: field.some((p) => p.entry > xMax),
    xMin: field.some((p) => p.entry < xMin),
    yMax: field.some((p) => (gapOf(p) as number) > yMax),
    yMin: field.some((p) => (gapOf(p) as number) < yMin),
  };
  const yTick = (v: number) => v.toFixed(yMax - yMin < 5 ? 1 : 0);
  // Where "held exactly its share" lands once y is a gap: a real line, drawn
  // only while the fitted frame reaches it.
  const zero = -shiftMid;
  const zeroInFrame = Math.abs(shiftMid) > 0.005 && zero > yMin && zero < yMax;

  /** Which corner a spec is in, which is also what colours it.
   *
   * Only two of the four carry a decision. Open and winning share is the
   * opening; crowded and losing it is the one to walk away from. The other two
   * are readings rather than verdicts, and a third hue would say there was a
   * third thing to do. */
  const verdict = (point: SpecPoint) => {
    const gap = gapOf(point) ?? 0;
    if (point.entry >= xMid && gap > 0) return "open";
    if (point.entry < xMid && gap < 0) return "trap";
    return "flat";
  };

  // Biggest first: a small dot is never drawn under a large one, and the names
  // dropped on collision are the least important ones. Past the cap a name
  // lives in the hover card — two dozen labels in a dense middle technically
  // fit and collectively read as noise.
  const labelCap = 14;
  const ordered = [...field].sort((a, b) => b.revenue - a.revenue);
  const placed: { x: number; y: number }[] = [];
  const labelled = new Set<string>();
  for (const point of ordered) {
    if (labelled.size >= labelCap) break;
    const cx = px(point.entry);
    const cy = py(gapOf(point) as number);
    // A seat the size of the name it holds: two lines, each of them a phrase
    // rather than a word. A seat cut to one short term's width lets two names
    // clear each other by the numbers and still read as one smudge.
    if (placed.some((seat) => Math.abs(seat.x - cx) < 100
                              && Math.abs(seat.y - cy) < 26)) continue;
    placed.push({ x: cx, y: cy });
    labelled.add(point.key);
  }

  /** Keep a name inside the frame: a dot near either edge has half its label
   *  outside the drawing, and an SVG does not wrap or clip it — it simply hangs
   *  off the chart and lands on whatever sits beside it. */
  const nameAt = (cx: number) => (
    cx > width - padR - 56 ? { x: width - padR, anchor: "end" as const }
    : cx < padL + 56 ? { x: padL, anchor: "start" as const }
    : { x: cx, anchor: "middle" as const });

  /** Anchor the card to the dot, not to the cursor: the drawing is a scaled
   *  viewBox, so a user-space coordinate becomes a pixel one by the ratio the
   *  browser used to fit it — read off the element, because the width changes
   *  with the window. */
  function show(point: SpecPoint, cx: number, cy: number) {
    const box = svgRef.current?.getBoundingClientRect();
    const k = box ? box.width / width : 1;
    const top = cy * k;
    // Below the dot when the dot sits high: a card anchored above it would hang
    // over the section before this one.
    const below = top < 150;
    setHover({
      point,
      style: {
        // Clamped, or a dot at either end pushes half the card out of the row.
        left: Math.round(Math.min(Math.max(cx * k, 104),
                                  Math.max(104, (box?.width ?? width) - 104))),
        top: Math.round(below ? top + 16 : top - 14),
        transform: `translate(-50%, ${below ? "0" : "-100%"})`,
      },
    });
  }

  const hide = () => setHover(null);

  return (
    <div className="relative">
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] text-fg-subtle tabular-nums">
          {total ?? points.length} {countLabel}
          {hidden > 0 ? ` · ${hidden} ${moreLabel}` : ""}
        </span>
        <button type="button" onClick={() => setRoom("")}
                className={`bi-chip ${room ? "" : "bi-chip-observed"}`}>
          {allLabel} {points.length}
        </button>
        {areas.map((entry) => (
          <button key={entry.area} type="button"
                  onClick={() => setRoom(room === entry.area ? "" : entry.area)}
                  className={`bi-chip ${room === entry.area ? "bi-chip-observed" : ""}`}>
            {entry.area} {entry.count}
          </button>
        ))}
      </div>

      <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} className="w-full"
           role="img"
           aria-label={shown.map((p) => describeSpec(p, xLabel, yLabel, tipLabels))
             .join("; ")}>
        {/* The two corners that carry a decision, tinted instead of captioned,
            so nobody has to hold "right of the dashed line and above zero" in
            their head while reading dots. */}
        <rect className="bi-quadrant-open" x={px(xMid)} y={padT}
              width={Math.max(0, width - padR - px(xMid))}
              height={Math.max(0, py(0) - padT)} />
        <rect className="bi-quadrant-risk" x={padL} y={py(0)}
              width={Math.max(0, px(xMid) - padL)}
              height={Math.max(0, height - fieldB - py(0))} />

        {/* Both medians are properties of this board rather than of the market,
            and both are dashed for it: the vertical one at the median 可进入度,
            the horizontal one at the median spec's own share movement. */}
        <line className="bi-axis-dashed" x1={padL} x2={width - padR}
              y1={py(0)} y2={py(0)} />
        <line className="bi-axis-dashed" x1={px(xMid)} x2={px(xMid)}
              y1={padT} y2={height - fieldB} />
        {/* And where holding exactly its share lands, which is a real line —
            solid, quiet, and only while the frame reaches it. A department that
            diluted this month shows it as a line above the median, which is the
            fact the median alone would hide. */}
        {zeroInFrame ? (
          <>
            <line className="bi-axis-solid" x1={padL} x2={width - padR}
                  y1={py(zero)} y2={py(zero)} />
            <text className="bi-axis-tick" x={padL - 6} y={py(zero) + 3}
                  textAnchor="end">0</text>
          </>
        ) : null}

        {railed ? (
          <>
            <line className="bi-rail-edge" x1={padL} x2={width - padR}
                  y1={height - fieldB + 7} y2={height - fieldB + 7} />
            <text className="bi-rail-name" x={width - padR}
                  y={height - padB - railH / 2 + 3} textAnchor="end">{railLabel}</text>
          </>
        ) : null}

        {/* The median line carries the movement it stands for: a bare 0 would
            leave the reader to guess whether the board grew or diluted. */}
        <text className="bi-axis-tick" x={padL - 6} y={py(0) - 3} textAnchor="end">
          {medianLabel}
        </text>
        <text className="bi-axis-tick" x={padL - 6} y={py(0) + 9} textAnchor="end">
          {shiftMid >= 0 ? "+" : ""}{shiftMid.toFixed(1)}
        </text>
        <text className="bi-axis-tick" x={padL - 6} y={padT + 4} textAnchor="end">
          {cut.yMax ? "≥" : "+"}{yTick(yMax)}
        </text>
        <text className="bi-axis-tick" x={padL - 6} y={height - fieldB} textAnchor="end">
          {cut.yMin ? "≤" : ""}{yTick(yMin)}
        </text>
        <text className="bi-axis-tick" x={px(xMid)} y={height - padB + 13}
              textAnchor="middle">{medianLabel} {xMid.toFixed(0)}</text>
        <text className="bi-axis-tick" x={padL} y={height - padB + 13}
              textAnchor="start">{cut.xMin ? "≤" : ""}{xMin.toFixed(0)}</text>
        <text className="bi-axis-tick" x={width - padR} y={height - padB + 13}
              textAnchor="end">{cut.xMax ? "≥" : ""}{xMax.toFixed(0)}</text>
        {/* Both axis names on one line under the plot. A rotated y title reads
            badly for Chinese — rotating CJK turns each glyph on its side rather
            than stacking them — and the arrow is what ties a name to its axis. */}
        <text className="bi-axis-title" x={2} y={height - padB + 26}
              textAnchor="start">{yLabel} ↑</text>
        <text className="bi-axis-title" x={width - padR} y={height - padB + 26}
              textAnchor="end">{xLabel} →</text>

        <text className="bi-quadrant-name" x={width - padR - 2} y={padT - 6}
              textAnchor="end">{quadrants[0]}</text>
        <text className="bi-quadrant-name" x={padL + 2} y={padT - 6}
              textAnchor="start">{quadrants[1]}</text>
        <text className="bi-quadrant-name" x={padL + 2} y={height - fieldB - 9}
              textAnchor="start">{quadrants[2]}</text>
        <text className="bi-quadrant-name" x={width - padR - 2} y={height - fieldB - 9}
              textAnchor="end">{quadrants[3]}</text>

        {/* Rail marks first, so a field dot is never drawn under one. */}
        {rail.map((point) => {
          const cx = px(point.entry);
          const cy = height - padB - railH / 2;
          // Under the mark rather than over it. Above, the name lands on the
          // rail's own edge and on the corner caption that sits there, which is
          // two claims stacked on one another.
          const seat = { x: cx, y: cy + 12 };
          const clash = placed.some((other) => Math.abs(other.x - seat.x) < 110
                                               && Math.abs(other.y - seat.y) < 14);
          if (!clash) placed.push(seat);
          const name = nameAt(cx);
          return (
            <g key={point.key} className="bi-dot-group" tabIndex={0} role="button"
               aria-label={describeSpec(point, xLabel, yLabel, tipLabels)}
               onClick={() => onPick?.(point.node_key)}
               onMouseEnter={() => show(point, cx, cy)} onMouseLeave={hide}
               onFocus={() => show(point, cx, cy)} onBlur={hide}>
              <rect x={cx - 9} y={cy - 7} width={18} height={14} fill="transparent" />
              {/* An open square, not a disc: a different shape for a different
                  claim, so nobody reads a rail mark as a measured position. */}
              <rect className="bi-rail-mark" x={cx - 4} y={cy - 4}
                    width={8} height={8} rx={1.5} />
              {!clash ? (
                <text className="bi-point-label" x={name.x} y={cy + 12}
                      textAnchor={name.anchor}>
                  {truncate(point.label, 18)}
                </text>
              ) : null}
            </g>
          );
        })}

        {ordered.map((point) => {
          const corner = verdict(point);
          const r = 4 + Math.sqrt(point.revenue / maxRevenue) * 13;
          // A pinned dot rests just inside the wall it is pressed to; half a
          // disc hanging over the axis would land in the rail strip and read as
          // a rail mark, which is a different claim again.
          const wall = pinnedAt(point);
          const edgeX = px(point.entry);
          const edgeY = py(gapOf(point) as number);
          const cx = edgeX + (wall === "left" ? r : wall === "right" ? -r : 0);
          const cy = edgeY + (wall === "top" ? r : wall === "bottom" ? -r : 0);
          const name = nameAt(cx);
          const hot = hover?.point.key === point.key;
          return (
            <g key={point.key} className="bi-dot-group" tabIndex={0} role="button"
               aria-label={describeSpec(point, xLabel, yLabel, tipLabels)}
               onClick={() => onPick?.(point.node_key)}
               onMouseEnter={() => show(point, cx, cy)} onMouseLeave={hide}
               onFocus={() => show(point, cx, cy)} onBlur={hide}>
              {/* The hit target is bigger than the mark; an 8px dot is not a
                  button, and this is what opens the card. */}
              <circle cx={cx} cy={cy} r={Math.max(15, r + 8)} fill="transparent" />
              {/* Disc for the money, core for the position: overlapping discs
                  stay countable because their cores do not merge. */}
              <circle className={`bi-dot-disc${corner === "open" ? "" : corner === "trap"
                                   ? " bi-dot-disc-risk" : " bi-dot-disc-flat"}`
                                 + (hot ? " bi-dot-hot" : "")}
                      cx={cx} cy={cy} r={r} />
              <circle className={`bi-dot-core${corner === "open" ? "" : corner === "trap"
                                   ? " bi-dot-core-risk" : " bi-dot-core-flat"}`}
                      cx={cx} cy={cy} r={Math.min(3, r / 3)} />
              {/* Off the fitted frame: the arrow, and the reading itself in the
                  card. Dropping it would be a claim about the shelf; drawing it
                  at the edge unmarked would be a claim about its position. */}
              {wall ? (
                <path className={`bi-dot-pin${corner === "open" ? "" : corner === "trap"
                                   ? " bi-dot-pin-risk" : " bi-dot-pin-flat"}`}
                      d={pinArrow(wall, edgeX, edgeY, frame)} />
              ) : null}
              {labelled.has(point.key) ? (
                /* Two lines: the shelf, then the two decisions. One line of the
                   three joined by dots is 160 units wide — six of those is the
                   whole chart, and the seventh lands on top of one of them. */
                <text className="bi-point-label" x={name.x} y={cy - r - 16}
                      textAnchor={name.anchor}>
                  <tspan x={name.x}>{truncate(point.node_label, 16)}</tspan>
                  <tspan x={name.x} dy="10.5">
                    {truncate([point.color, point.look].filter(Boolean).join(" · "), 14)}
                  </tspan>
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>

      {hover ? (
        <div className="bi-dot-tip" style={hover.style}>
          <div className="bi-dot-tip-head">
            <span className="bi-dot-tip-name">{hover.point.label}</span>
          </div>
          {/* The spec's own rows first: which decision took which value is what
              the reader came for, and the measurements are the argument for it. */}
          <div className="mb-1.5 border-b border-border pb-1.5">
            {hover.point.spec.map((part) => (
              <TipRow key={part.kind} label={part.kind_label} value={part.label} />
            ))}
          </div>
          {/* The position first, then the movement it was signed against: the
              axis says "ahead of the board", the row under it says by how much
              the spec itself actually moved. */}
          <TipRow label={yLabel}
                  value={shiftText(gapOf(hover.point), tipLabels.unmeasured)}
                  tone={!gapOf(hover.point) ? undefined
                        : (gapOf(hover.point) as number) > 0 ? "up" : "down"} />
          <TipRow label={tipLabels.shift}
                  value={shiftText(hover.point.share_shift_pp, tipLabels.unmeasured)} />
          <TipRow label={xLabel} value={hover.point.entry.toFixed(0)} />
          <TipRow label={tipLabels.share}
                  value={hover.point.share_before_pct == null
                    ? fmtPct(hover.point.share_pct)
                    : `${fmtPct(hover.point.share_pct)}（${tipLabels.was} `
                      + `${fmtPct(hover.point.share_before_pct)}）`} />
          <TipRow label={tipLabels.revenue} value={fmtMoney(hover.point.revenue)} />
          <TipRow label={tipLabels.asins} value={`${hover.point.asins}`} />
          <TipRow label={tipLabels.brands} value={`${hover.point.brands}`} />
          <TipRow label={tipLabels.rating}
                  value={hover.point.rating == null ? tipLabels.unmeasured
                         : `${hover.point.rating.toFixed(2)}★`} />
          {hover.point.reviews != null ? (
            <TipRow label={tipLabels.reviews}
                    value={hover.point.reviews.toLocaleString()} />
          ) : null}
          {hover.point.avg_price != null ? (
            <TipRow label={tipLabels.price} value={fmtMoney(hover.point.avg_price)} />
          ) : null}
          {hover.point.return_risk > 0 ? (
            <TipRow label={tipLabels.returnRisk}
                    value={hover.point.return_risk.toFixed(1)}
                    tone={hover.point.return_risk > 8 ? "down" : undefined} />
          ) : null}
        </div>
      ) : null}

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]
                      text-fg-subtle">
        <span className="flex items-center gap-1">
          ↗<i className="bi-swatch shrink-0 bi-legend-open" />{quadrants[0]}
        </span>
        <span>↖&nbsp;{quadrants[1]}</span>
        <span className="flex items-center gap-1">
          ↙<i className="bi-swatch shrink-0 bi-legend-risk" />{quadrants[2]}
        </span>
        <span>↘&nbsp;{quadrants[3]}</span>
      </div>
      {notes.map((note) => (
        <div key={note} className="mt-0.5 text-[10px] text-fg-subtle">{note}</div>
      ))}
    </div>
  );
}

/** A signed movement in percentage points, or the word for a reading nobody took. */
/** Where a spec sits on y: its share movement signed against the median spec
 *  on the chart. A dashboard stored before the axis was re-centred carries no
 *  gap, and there the raw movement *is* the gap — that frame was drawn against
 *  zero, so reading it this way draws the old payload exactly as it was. */
function gapOf(point: SpecPoint): number | null {
  return point.shift_gap_pp ?? point.share_shift_pp;
}

function shiftText(value: number | null, unmeasured: string): string {
  if (value == null || !Number.isFinite(value)) return unmeasured;
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}pp`;
}

/** The card's contents as one string, for the reader who cannot hover. */
function describeSpec(point: SpecPoint, xLabel: string, yLabel: string,
                      tipLabels: SpecTipLabels): string {
  return `${point.label} · ${yLabel} ${shiftText(gapOf(point), tipLabels.unmeasured)}`
    + ` · ${tipLabels.shift} ${shiftText(point.share_shift_pp, tipLabels.unmeasured)}`
    + ` · ${xLabel} ${point.entry.toFixed(0)}`
    + ` · ${tipLabels.share} ${fmtPct(point.share_pct)}`
    + ` · ${tipLabels.revenue} ${fmtMoney(point.revenue)}`
    + ` · ${tipLabels.asins} ${point.asins}`;
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
  // Three states, not two. With no benchmark there is no comparison to pass or
  // fail, and the old code called that `good` — so a category whose peers were
  // never measured rendered in the same green as one that genuinely beats them.
  const verdict = benchmark === null ? "unknown"
    : (goodBelow ? value <= benchmark : value >= benchmark) ? "good" : "bad";
  return (
    <div className="bi-bullet" role="img"
         aria-label={`${value.toFixed(2)} against benchmark ${benchmark?.toFixed(2) ?? "—"}`}>
      <div className={`bi-bullet-fill${
             verdict === "bad" ? " bi-bullet-bad"
             : verdict === "unknown" ? " bi-bullet-unknown" : ""}`}
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
  width = 1000,
  height = 320,
  labels,
}: {
  items: TreeItem[];
  onPick?: (nodeKey: string) => void;
  /** Canvas in user units. The aspect ratio is what decides the rendered
   *  height — the svg scales to the width it is given. */
  width?: number;
  height?: number;
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
      {/* Height follows the width the row gives it. A fixed pixel height would
          letterbox the tiles into a narrow block in the middle of a full-width
          row and waste the space that makes the small tiles legible. */}
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full"
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

/** The price-to-revenue curve the price-fit factor was scored against.
 *
 * This was eight disconnected bars with a percentage printed over every one of
 * them — the one shape that cannot show what the panel underneath it claims the
 * chart shows. The caption says "peak", and a row of bars has no peak; it says
 * the score falls off with distance from that peak, and equally-spaced bars
 * put $54 and $130 as far apart as $1.0K and $1.6K, so there is no distance to
 * read either.
 *
 * So it is drawn as the curve it is called: price along x, the fit index up y,
 * the peak marked and named. X is logarithmic because that is how price is
 * read — a move from $50 to $100 is the same decision as $500 to $1,000 — and
 * because on a linear axis the bins below $300, which is where this department
 * mostly sells, collapse into the left eighth of the frame.
 *
 * `markers` puts the tracked categories' own average prices along the baseline,
 * which is the question the curve is there to answer: not "what is the shape"
 * but "where do we sit on it".
 */
export function PriceFitCurve({
  points,
  peakLabel,
  markers = [],
  markerLabel,
  moneyLabel,
}: {
  points: { price: number; fit: number }[];
  /** e.g. "峰值" — names the one labelled point. */
  peakLabel: string;
  /** Average price per tracked category, drawn as a rug on the baseline. */
  markers?: { label: string; price: number }[];
  markerLabel?: string;
  moneyLabel: (value: number | null | undefined) => string;
}) {
  const rows = points
    .filter((p) => Number.isFinite(p.price) && p.price > 0 && Number.isFinite(p.fit))
    .sort((a, b) => a.price - b.price);
  if (rows.length < 2) return null;

  // A 0-100 viewBox with `preserveAspectRatio="none"`: the path stretches to the
  // column, and every label and dot rides on top in HTML at the same
  // percentages, so none of them is stretched with it.
  const padX = 2;
  const padTop = 14;
  const padBottom = 4;
  const lo = Math.log10(rows[0].price);
  const span = Math.log10(rows[rows.length - 1].price) - lo || 1;
  // Rounded, and not for tidiness: `Math.log10` is implementation-defined in
  // its last digits, so Node and the browser disagree from about the fourteenth
  // decimal — enough for React to call every position a hydration mismatch.
  const round = (value: number) => Math.round(value * 1000) / 1000;
  const atX = (price: number) =>
    round(padX + ((Math.log10(price) - lo) / span) * (100 - padX * 2));
  const atY = (fit: number) =>
    round(padTop + (1 - clamp(fit, 0, 100) / 100) * (100 - padTop - padBottom));

  const coords = rows.map((r) => [atX(r.price), atY(r.fit)] as const);
  const line = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
  const floor = 100 - padBottom;
  const area = `${line} L${coords[coords.length - 1][0].toFixed(2)},${floor} `
    + `L${coords[0][0].toFixed(2)},${floor} Z`;
  const peak = rows.reduce((best, r) => (r.fit > best.fit ? r : best), rows[0]);

  // Ticks: the ends and the peak always, then whatever else clears them. A price
  // on every point is what made the bar version unreadable.
  const ticks: typeof rows = [];
  for (const row of [rows[0], rows[rows.length - 1], peak, ...rows]) {
    if (!ticks.includes(row)
        && ticks.every((t) => Math.abs(atX(t.price) - atX(row.price)) > 13)) {
      ticks.push(row);
    }
  }
  // A category priced outside the department's own bins has no place on this
  // axis; pinning it to an end would state a fit the curve never computed.
  const rug = markers.filter((m) => Number.isFinite(m.price)
    && m.price >= rows[0].price && m.price <= rows[rows.length - 1].price);
  const height = 104;
  const peakX = atX(peak.price);
  const peakY = atY(peak.fit);
  // Beside the peak, not above it. Above needs a quarter of the frame reserved
  // as headroom for one label, and the peak is by definition at the top of the
  // curve — the side it goes on is whichever has the room.
  // Sat on the dot's own line, the label was crossed by the curve falling away
  // from the peak; a fifth of its height below centre clears it and still reads
  // as attached to the dot.
  const peakSide = peakX > 55 ? "translate(calc(-100% - 9px), 20%)" : "translate(9px, 20%)";

  return (
    <div>
      <div className="flex items-start gap-1.5">
        {/* Percentages of a height have to be placement, not padding: padding-%
            resolves against the container's *width*, which put these two labels
            a hundred pixels below the chart they scale. */}
        <div className="relative w-[26px] shrink-0" style={{ height }}>
          <span className="bi-fit-y" style={{ top: `${padTop}%` }}>100</span>
          <span className="bi-fit-y" style={{ top: `${100 - padBottom}%` }}>0</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative" style={{ height }} role="img"
               aria-label={rows
                 .map((r) => `${moneyLabel(r.price)}: ${r.fit.toFixed(0)}`).join(", ")}>
            <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full"
                 preserveAspectRatio="none" aria-hidden="true">
              <line className="bi-grid-line" x1={padX} x2={100 - padX} y1={floor} y2={floor} />
              <path className="bi-spark-area" d={area} />
              {/* Drops the peak onto the axis, so "where the money is" is a
                  price a reader can point at and not just a bump. */}
              <line className="bi-fit-peak-drop" x1={peakX} x2={peakX} y1={peakY} y2={floor}
                    vectorEffect="non-scaling-stroke" />
              <path className="bi-spark-line" d={line} vectorEffect="non-scaling-stroke" />
            </svg>
            <span className="bi-fit-peak"
                  style={{ left: `${peakX}%`, bottom: `${100 - peakY}%` }} />
            <span className="bi-fit-peak-label"
                  style={{ left: `${peakX}%`, bottom: `${100 - peakY}%`,
                           transform: peakSide }}>
              {peakLabel} {moneyLabel(peak.price)}
            </span>
            {rug.map((m) => (
              <span key={`${m.label}-${m.price}`} className="bi-fit-rug"
                    style={{ left: `${atX(m.price)}%`, bottom: `${padBottom}%` }}
                    title={`${m.label} · ${moneyLabel(m.price)}`} />
            ))}
          </div>
          <div className="relative mt-1 h-3">
            {ticks.map((t) => (
              <span key={t.price} className="bi-fit-tick" style={{ left: `${atX(t.price)}%` }}>
                {moneyLabel(t.price)}
              </span>
            ))}
          </div>
        </div>
      </div>
      {markerLabel && rug.length ? (
        <p className="ml-[30px] mt-1 flex items-center gap-1 text-[10px] text-fg-subtle">
          <i className="bi-fit-rug-key" />{markerLabel} · {rug.length}
        </p>
      ) : null}
    </div>
  );
}

/** Several 100% bars stacked in a column — one row per category.
 *
 * Used for the fulfilment mix and the traffic mix. The comparison that matters
 * is between rows at the same position along the bar, which aligned 100% bars
 * give and a set of pie charts does not.
 *
 * Each series is an identity — FBA is not "more" than FBM — so they take hues
 * in a fixed order rather than steps of one hue. The steps were three opacities
 * of the panel green, which left FBM and 亚马逊自营 close enough in lightness
 * that the legend was the only way to tell which was which. Slot 1 stays that
 * green, so the chart still belongs to this board.
 */
// Spelled out, not built from an index: Tailwind scans source text for class
// names and drops the ones in `@layer components` it never sees, so a template
// literal would leave every segment painted the base green.
const SEG_HUE = ["bi-share-seg-1", "bi-share-seg-2", "bi-share-seg-3"];
const SWATCH_HUE = ["bi-swatch-series-1", "bi-swatch-series-2", "bi-swatch-series-3"];

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
            <i className={`bi-swatch ${SWATCH_HUE[i % SWATCH_HUE.length]}`} />
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
                <span key={part.key}
                      className={`bi-share-seg ${SEG_HUE[i % SEG_HUE.length]}`}
                      style={{ width: `${Math.max(0, part.value)}%` }}
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
