// Client-side marketing-image templates. Selecting a template composites the user's
// product image + editable text onto a programmatic background on a <canvas> — no AI.
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
  platform: "taobao" | "xiaohongshu" | "amazon" | "instagram" | "generic";
  style: string;
  label: string;
  aspectRatio: "1:1" | "3:4" | "4:5";
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
  // ---- Taobao / Tmall ----
  {
    id: "t_taobao_white",
    platform: "taobao",
    style: "white",
    label: "纯白主图",
    aspectRatio: "1:1",
    background: { kind: "solid", colors: ["#ffffff"] },
    productBox: { xPct: 0.5, yPct: 0.48, wPct: 0.72, hPct: 0.72 },
    texts: [
      t("title", "新品上市", 0.5, 0.12, 0.07, "#1f2937", "center", 800),
      t("sub", "品质之选", 0.5, 0.92, 0.04, "#6b7280", "center", 400),
    ],
  },
  {
    id: "t_taobao_promo",
    platform: "taobao",
    style: "promo",
    label: "促销大字",
    aspectRatio: "1:1",
    background: { kind: "gradient", colors: ["#ff5f6d", "#ffc371"], angle: 135 },
    productBox: { xPct: 0.5, yPct: 0.55, wPct: 0.6, hPct: 0.6 },
    texts: [
      t("title", "限时5折", 0.5, 0.16, 0.11, "#ffffff", "center", 800),
      t("sub", "抢完即止", 0.5, 0.27, 0.045, "#fff5f5", "center", 600),
    ],
  },
  {
    id: "t_taobao_scene",
    platform: "taobao",
    style: "scene",
    label: "场景氛围",
    aspectRatio: "1:1",
    background: { kind: "gradient", colors: ["#f5efe6", "#e8dccb"], angle: 160 },
    productBox: { xPct: 0.5, yPct: 0.5, wPct: 0.66, hPct: 0.66 },
    texts: [t("title", "质感生活", 0.5, 0.9, 0.05, "#5b4a36", "center", 600)],
  },
  // ---- Xiaohongshu ----
  {
    id: "t_xhs_lifestyle",
    platform: "xiaohongshu",
    style: "lifestyle",
    label: "生活种草",
    aspectRatio: "3:4",
    background: { kind: "gradient", colors: ["#ffe6ec", "#fff4e6"], angle: 150 },
    productBox: { xPct: 0.5, yPct: 0.55, wPct: 0.68, hPct: 0.55 },
    texts: [
      t("title", "本命好物分享", 0.5, 0.12, 0.06, "#e64980", "center", 800),
      t("sub", "真的好用到哭😭", 0.5, 0.2, 0.04, "#c2185b", "center", 400),
    ],
  },
  {
    id: "t_xhs_title",
    platform: "xiaohongshu",
    style: "handheld",
    label: "标题贴纸",
    aspectRatio: "3:4",
    background: { kind: "gradient", colors: ["#fff9db", "#ffec99"], angle: 120 },
    productBox: { xPct: 0.5, yPct: 0.58, wPct: 0.66, hPct: 0.55 },
    texts: [
      t("title", "谁懂啊！", 0.5, 0.13, 0.08, "#f08c00", "center", 800),
      t("sub", "打工人必入清单", 0.5, 0.23, 0.045, "#e67700", "center", 600),
    ],
  },
  // ---- Amazon ----
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
    id: "t_amazon_feature",
    platform: "amazon",
    style: "multiangle",
    label: "卖点标注",
    aspectRatio: "1:1",
    background: { kind: "gradient", colors: ["#f8fafc", "#e2e8f0"], angle: 180 },
    productBox: { xPct: 0.42, yPct: 0.5, wPct: 0.62, hPct: 0.7 },
    texts: [
      t("f1", "• Premium material", 0.72, 0.4, 0.035, "#0f172a", "center", 600),
      t("f2", "• 12-month warranty", 0.72, 0.5, 0.035, "#0f172a", "center", 600),
      t("f3", "• Ready to ship", 0.72, 0.6, 0.035, "#0f172a", "center", 600),
    ],
  },
  // ---- Instagram ----
  {
    id: "t_ins_editorial",
    platform: "instagram",
    style: "editorial",
    label: "杂志风",
    aspectRatio: "4:5",
    background: { kind: "gradient", colors: ["#1f2933", "#3e4c59"], angle: 160 },
    productBox: { xPct: 0.5, yPct: 0.5, wPct: 0.7, hPct: 0.6 },
    texts: [
      t("title", "NEW ARRIVAL", 0.5, 0.12, 0.05, "#ffffff", "center", 800),
      t("sub", "the essentials", 0.5, 0.9, 0.035, "#cbd5e1", "center", 400),
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
    texts: [t("title", "less is more", 0.5, 0.9, 0.045, "#27272a", "center", 400)],
  },
  // ---- Generic ----
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
  "taobao",
  "xiaohongshu",
  "amazon",
  "instagram",
  "generic",
];
