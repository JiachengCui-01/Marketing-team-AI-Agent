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
  growth_pct: number | null;
  searches: number;
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
  growth_pct: number;
};

export function inField(point: ElementPoint): point is ElementFieldPoint {
  return point.shelf_pct !== null && point.growth_pct !== null;
}

/** The chart's axis bounds, computed server-side from the points on show.
 *
 *  `x_mid` is the department's median shelf share — a claim about the department
 *  rather than about the points drawn, which is why the server computes it over
 *  every measured element rather than over the ones that fit on the chart. */
export type ElementChartBounds = {
  x_max: number;
  x_mid: number;
  y_min: number;
  y_max: number;
};

/** What genuinely has to be global: the dot area encodes monthly searches, so
 *  it is measured against one maximum across every row. */
export type ElementScale = {
  max_searches: number;
};

/** Row names for the hover card. The two axis names come in separately because
 *  they are the same two strings the axes themselves are labelled with. */
export type ElementTipLabels = {
  searches: string;
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
  /** Names the two rails, e.g. 需求未测到 / 货架未测到. */
  railLabels: { noDemand: string; noShelf: string };
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
    shelf: points.filter((p) => !inField(p) && p.shelf_pct !== null),
    demand: points.filter((p) => !inField(p) && p.growth_pct !== null),
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
  // under the plot. Both axes are percentages of completely different things —
  // a share on x, a growth rate on y — so a row that prints only numbers makes
  // the reader guess which percent is which. They are named on every row for
  // that reason, not for decoration.
  const padL = 42;
  const padR = 20;
  const padT = 22;
  const padB = 34;

  // Bounds from this row's own elements; the dot area from the whole set, so a
  // big element in a quiet row cannot out-draw a bigger one in a busy row.
  const { x_max: xMax, x_mid: xMid, y_min: yMin, y_max: yMax } = bounds;
  const maxSearches = Math.max(1, scale.max_searches);

  // The rails are inside the padding, not extra chrome outside it: each takes a
  // strip off the field and keeps its own axis, so a rail mark lines up with the
  // field marks it shares that axis with.
  const railW = rails.demand.length ? 26 : 0;
  const railH = rails.shelf.length ? 22 : 0;
  const fieldL = padL + railW;
  const fieldB = padB + railH;

  const px = (v: number) => fieldL + (v / xMax) * (width - fieldL - padR);
  const py = (v: number) =>
    height - fieldB - ((v - yMin) / (yMax - yMin || 1)) * (height - padT - fieldB);

  // Biggest first, so a small dot is never hidden under a large one, and so the
  // labels that get dropped on collision are the least important ones.
  const ordered = [...field].sort((a, b) => b.searches - a.searches);
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
  const labelled = new Set<string>();
  for (const point of ordered) {
    if (labelled.size >= labelCap) break;
    const cx = px(point.shelf_pct);
    const cy = py(point.growth_pct);
    if (placed.some((seat) => Math.abs(seat.x - cx) < 56
                              && Math.abs(seat.y - cy) < 13)) continue;
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
        {/* The two corners that carry a decision, tinted instead of captioned. A
            tint survives being repeated down a column of rows; four captions a
            row do not. */}
        <rect className="bi-quadrant-open" x={fieldL} y={padT}
              width={Math.max(0, px(xMid) - fieldL)} height={Math.max(0, py(0) - padT)} />
        <rect className="bi-quadrant-risk" x={px(xMid)} y={py(0)}
              width={Math.max(0, width - padR - px(xMid))}
              height={Math.max(0, height - fieldB - py(0))} />

        {/* Zero growth is a fact about the market; the median is a fact about our
            own tracking list, so it is the dashed one. */}
        <line className="bi-axis-solid" x1={fieldL} x2={width - padR}
              y1={py(0)} y2={py(0)} />
        <line className="bi-axis-dashed" x1={px(xMid)} x2={px(xMid)}
              y1={padT} y2={height - fieldB} />

        {/* The rails, and the boundary that says a mark inside one is missing a
            reading rather than sitting at zero. Left rail: demand measured, too
            few head listings to state a share. Bottom rail: on the shelf, no
            rated search signal. */}
        {rails.demand.length ? (
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
              {railLabels.noDemand}
            </text>
          </>
        ) : null}

        {/* Signed, so "135%" cannot be read as a level rather than a change. */}
        <text className="bi-axis-tick" x={padL - 6} y={py(0) + 3} textAnchor="end">0%</text>
        <text className="bi-axis-tick" x={padL - 6} y={padT + 4} textAnchor="end">
          +{yMax.toFixed(0)}%
        </text>
        <text className="bi-axis-tick" x={padL - 6} y={height - fieldB} textAnchor="end">
          {yMin.toFixed(0)}%
        </text>
        {/* The dashed line's value is meaningless without the word: nothing tells
            a reader that 13% is the median of the elements we track. */}
        <text className="bi-axis-tick" x={px(xMid)} y={height - padB + 13} textAnchor="middle">
          {medianLabel} {xMid.toFixed(0)}%
        </text>
        <text className="bi-axis-tick" x={fieldL} y={height - padB + 13}
              textAnchor="start">0</text>
        <text className="bi-axis-tick" x={width - padR} y={height - padB + 13} textAnchor="end">
          {xMax.toFixed(0)}%
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
          ...rails.demand.map((point) => ({
            point, cx: padL + railW / 2, cy: py(point.growth_pct as number) })),
          ...rails.shelf.map((point) => ({
            point, cx: px(point.shelf_pct as number),
            cy: height - padB - railH / 2 })),
        ].map(({ point, cx, cy }) => {
          // Named like any other element. Leaving the rails unlabelled made a
          // real element look like a decoration: "there is something here" and
          // no way to find out what without hunting for it with a mouse.
          const clash = placed.some(
            (seat) => Math.abs(seat.x - cx) < 52 && Math.abs(seat.y - cy) < 12);
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
          const r = 4 + Math.sqrt(point.searches / maxSearches) * 11;
          const cx = px(point.shelf_pct);
          const cy = py(point.growth_pct);
          const rising = point.growth_pct >= 0;
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
              <circle className={`${rising ? "bi-dot-disc" : "bi-dot-disc bi-dot-disc-risk"}`
                                 + (hot ? " bi-dot-hot" : "")}
                      cx={cx} cy={cy} r={r} />
              <circle className={rising ? "bi-dot-core" : "bi-dot-core bi-dot-core-risk"}
                      cx={cx} cy={cy} r={Math.min(3, r / 3)} />
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
              been. Leaving the row out would read as "nothing to say about
              growth"; a dash reads as "we did not measure it", which is the
              fact. */}
          <TipRow label={yLabel} value={pct(hover.point.growth_pct, tipLabels.unmeasured)}
                  tone={hover.point.growth_pct == null ? undefined
                        : hover.point.growth_pct >= 0 ? "up" : "down"} />
          <TipRow label={xLabel}
                  value={pct(hover.point.shelf_pct, tipLabels.unmeasured, false)} />
          <TipRow label={tipLabels.searches}
                  value={hover.point.searches.toLocaleString()} />
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

/** A percentage, or the word for a reading that was never taken. */
function pct(value: number | null, unmeasured: string, signed = true): string {
  if (value == null || !Number.isFinite(value)) return unmeasured;
  return `${signed && value >= 0 ? "+" : ""}${fmtPct(value)}`;
}

/** The card's contents as one string, for the screen reader that cannot hover. */
function describe(point: ElementPoint, xLabel: string, yLabel: string,
                  tipLabels: ElementTipLabels): string {
  return `${point.label}（${point.kind_label}） · `
    + `${yLabel} ${pct(point.growth_pct, tipLabels.unmeasured)} · `
    + `${xLabel} ${pct(point.shelf_pct, tipLabels.unmeasured, false)} · `
    + `${tipLabels.searches} ${point.searches.toLocaleString()} · `
    + `${tipLabels.asins} ${point.asins}`
    + (point.avg_price != null ? ` · ${fmtMoney(point.avg_price)}` : "");
}

/** Every spec the market has built, on one chart.
 *
 * The attribute rows answer "of the finishes we track, which one is cooling".
 * This answers the question a brief is actually written from: which whole
 * product — a scene, a size, a material, a colour, a look, a surface treatment —
 * is selling and which way its demand is moving. A spec spans the attributes by
 * construction, so there is no attribute to file it under and no row to put it
 * in; it is one chart or it is nothing.
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
  railLabels: { noDemand: string; noShelf: string };
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
        <span className="flex items-center gap-1">
          ↖<i className="bi-swatch shrink-0 bi-legend-open" />{quadrants[0]}
        </span>
        <span>↗&nbsp;{quadrants[1]}</span>
        <span className="flex items-center gap-1">
          ↘<i className="bi-swatch shrink-0 bi-legend-risk" />{quadrants[2]}
        </span>
        <span>↙&nbsp;{quadrants[3]}</span>
      </div>
      {notes.map((note) => (
        <div key={note} className="mt-0.5 text-[10px] text-fg-subtle">{note}</div>
      ))}
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
  width = 1000,
  height = 420,
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
  /** Canvas in user units; the svg scales to the width of the row it sits in. */
  width?: number;
  height?: number;
}) {
  const pad = 40;
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
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full"
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
        const r = 6 + Math.sqrt((point.revenue_est ?? 0) / maxRevenue) * 12;
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
