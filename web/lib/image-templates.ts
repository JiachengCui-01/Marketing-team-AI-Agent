// Client-side product-image templates. Selecting a template composites the user's
// furniture photo + editable text onto a programmatic background on a <canvas> — no AI.
// Default text layers are English: they are baked into the exported PNG and the
// audience is the US shopper, not the internal team.
// The same definitions drive the gallery thumbnails, the live editor, and the export.

export type TemplateText = {
  id: string;
  text: string; // default, user-editable
  xPct: number; // 0..1 anchor (align-relative)
  yPct: number; // 0..1 baseline
  fontPct: number; // font size as fraction of canvas height
  color: string;
  align: "left" | "center" | "right";
  weight: number; // 400 | 600 | 800
};

export type TemplateDef = {
  id: string;
  platform: "amazon" | "wayfair" | "dtc_site" | "instagram" | "pinterest" | "generic";
  style: string;
  label: string;
  aspectRatio: "1:1" | "3:4" | "4:5" | "16:9";
  background: { kind: "gradient" | "solid"; colors: string[]; angle?: number };
  // Product placement — center-based, fractions of canvas.
  productBox: { xPct: number; yPct: number; wPct: number; hPct: number };
  texts: TemplateText[];
};

export function canvasSize(aspectRatio: string, base = 1024): { w: number; h: number } {
  const [aw, ah] = aspectRatio.split(":").map(Number);
  if (!aw || !ah) return { w: base, h: base };
  // Fit within a `base` box keeping the longer side = base.
  return aw >= ah
    ? { w: base, h: Math.round((base * ah) / aw) }
    : { w: Math.round((base * aw) / ah), h: base };
}

const t = (
  id: string,
  text: string,
  xPct: number,
  yPct: number,
  fontPct: number,
  color: string,
  align: "left" | "center" | "right",
  weight: number,
): TemplateText => ({ id, text, xPct, yPct, fontPct, color, align, weight });

export const TEMPLATES: TemplateDef[] = [
  // ---- Amazon: compliance first, then the gallery slots that answer objections.
  {
    id: "t_amazon_white",
    platform: "amazon",
    style: "white",
    label: "合规白底",
    aspectRatio: "1:1",
    background: { kind: "solid", colors: ["#ffffff"] },
    productBox: { xPct: 0.5, yPct: 0.5, wPct: 0.85, hPct: 0.85 },
    texts: [],
  },
  {
    id: "t_amazon_dimension",
    platform: "amazon",
    style: "dimension",
    label: "尺寸标注",
    aspectRatio: "1:1",
    background: { kind: "solid", colors: ["#ffffff"] },
    productBox: { xPct: 0.46, yPct: 0.52, wPct: 0.66, hPct: 0.7 },
    texts: [
      t("w", 'W 84"', 0.46, 0.94, 0.038, "#0f172a", "center", 600),
      t("d", 'D 38"', 0.86, 0.62, 0.038, "#0f172a", "center", 600),
      t("h", 'H 33"', 0.86, 0.5, 0.038, "#0f172a", "center", 600),
      t("seat", 'Seat height 18"', 0.86, 0.38, 0.03, "#475569", "center", 400),
    ],
  },
  {
    id: "t_amazon_feature",
    platform: "amazon",
    style: "multiangle",
    label: "卖点标注",
    aspectRatio: "1:1",
    background: { kind: "gradient", colors: ["#f8fafc", "#e2e8f0"], angle: 180 },
    productBox: { xPct: 0.42, yPct: 0.5, wPct: 0.62, hPct: 0.7 },
    texts: [
      t("f1", "• Kiln-dried solid wood", 0.74, 0.38, 0.032, "#0f172a", "center", 600),
      t("f2", "• Ships LTL, curbside", 0.74, 0.48, 0.032, "#0f172a", "center", 600),
      t("f3", "• Assembles in 30 min", 0.74, 0.58, 0.032, "#0f172a", "center", 600),
      t("f4", "• 5-year frame warranty", 0.74, 0.68, 0.032, "#0f172a", "center", 600),
    ],
  },
  // ---- Wayfair: browse-grid legibility.
  {
    id: "t_wayfair_roomset",
    platform: "wayfair",
    style: "roomset",
    label: "房间实景",
    aspectRatio: "1:1",
    background: { kind: "gradient", colors: ["#f7f5f2", "#e9e4dc"], angle: 160 },
    productBox: { xPct: 0.5, yPct: 0.54, wPct: 0.74, hPct: 0.66 },
    texts: [],
  },
  {
    id: "t_wayfair_white",
    platform: "wayfair",
    style: "white",
    label: "白底属性图",
    aspectRatio: "1:1",
    background: { kind: "solid", colors: ["#fbfbfb"] },
    productBox: { xPct: 0.5, yPct: 0.5, wPct: 0.8, hPct: 0.8 },
    texts: [],
  },
  // ---- Own store: wide hero with room for a headline.
  {
    id: "t_dtc_hero",
    platform: "dtc_site",
    style: "hero",
    label: "首页 Hero",
    aspectRatio: "16:9",
    background: { kind: "gradient", colors: ["#efe9e1", "#d9cfc2"], angle: 120 },
    productBox: { xPct: 0.68, yPct: 0.55, wPct: 0.5, hPct: 0.8 },
    texts: [
      t("title", "Built to last a decade", 0.06, 0.4, 0.075, "#2b2620", "left", 800),
      t("sub", "Solid oak. Free curbside delivery.", 0.06, 0.52, 0.033, "#5c534a", "left", 400),
      t("cta", "Shop the collection", 0.06, 0.66, 0.028, "#8a6a44", "left", 600),
    ],
  },
  {
    id: "t_dtc_scale",
    platform: "dtc_site",
    style: "scale",
    label: "尺度对比",
    aspectRatio: "16:9",
    background: { kind: "solid", colors: ["#f4f4f5"] },
    productBox: { xPct: 0.44, yPct: 0.55, wPct: 0.52, hPct: 0.78 },
    texts: [
      t("title", "Will it fit?", 0.8, 0.32, 0.055, "#27272a", "center", 800),
      t("sub", 'Shown beside a 5\'9" adult', 0.8, 0.44, 0.028, "#52525b", "center", 400),
    ],
  },
  // ---- Instagram: editorial feed.
  {
    id: "t_ins_editorial",
    platform: "instagram",
    style: "editorial",
    label: "杂志风",
    aspectRatio: "4:5",
    background: { kind: "gradient", colors: ["#1f2933", "#3e4c59"], angle: 160 },
    productBox: { xPct: 0.5, yPct: 0.52, wPct: 0.72, hPct: 0.6 },
    texts: [
      t("title", "NEW ARRIVAL", 0.5, 0.11, 0.048, "#ffffff", "center", 800),
      t("sub", "the dining collection", 0.5, 0.91, 0.032, "#cbd5e1", "center", 400),
    ],
  },
  {
    id: "t_ins_minimal",
    platform: "instagram",
    style: "minimal",
    label: "极简风",
    aspectRatio: "4:5",
    background: { kind: "solid", colors: ["#f4f4f5"] },
    productBox: { xPct: 0.5, yPct: 0.46, wPct: 0.62, hPct: 0.6 },
    texts: [t("title", "room for everyone", 0.5, 0.9, 0.042, "#27272a", "center", 400)],
  },
  // ---- Pinterest: tall, searchable room inspiration.
  {
    id: "t_pin_inspiration",
    platform: "pinterest",
    style: "inspiration",
    label: "房间灵感",
    aspectRatio: "3:4",
    background: { kind: "gradient", colors: ["#fdfaf5", "#efe3d3"], angle: 150 },
    productBox: { xPct: 0.5, yPct: 0.56, wPct: 0.76, hPct: 0.58 },
    texts: [
      t("title", "Small-space dining ideas", 0.5, 0.11, 0.052, "#4a3b2a", "center", 800),
      t("sub", "seats 4 in under 40 inches", 0.5, 0.19, 0.032, "#7a6852", "center", 400),
    ],
  },
  {
    id: "t_pin_roomset",
    platform: "pinterest",
    style: "roomset",
    label: "风格搭配",
    aspectRatio: "3:4",
    background: { kind: "gradient", colors: ["#f2f4f1", "#dde3dc"], angle: 140 },
    productBox: { xPct: 0.5, yPct: 0.55, wPct: 0.74, hPct: 0.6 },
    texts: [t("title", "How to style warm minimalism", 0.5, 0.12, 0.046, "#33403a", "center", 700)],
  },
  // ---- Fallback.
  {
    id: "t_generic_clean",
    platform: "generic",
    style: "clean",
    label: "干净背景",
    aspectRatio: "1:1",
    background: { kind: "gradient", colors: ["#eef2ff", "#e0e7ff"], angle: 145 },
    productBox: { xPct: 0.5, yPct: 0.5, wPct: 0.7, hPct: 0.7 },
    texts: [t("title", "Your brand here", 0.5, 0.9, 0.045, "#4f46e5", "center", 600)],
  },
];

export const PLATFORM_ORDER: TemplateDef["platform"][] = [
  "amazon",
  "wayfair",
  "dtc_site",
  "instagram",
  "pinterest",
  "generic",
];
