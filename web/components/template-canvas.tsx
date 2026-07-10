"use client";

import { useEffect, useMemo, useRef } from "react";
import { canvasSize, type TemplateDef, type TemplateText } from "@/lib/image-templates";

export type ComposeOpts = {
  productImg: HTMLImageElement | null;
  productScale: number; // multiplier on the template's productBox
  productOffset: { x: number; y: number }; // in base-canvas px
  adjust: { brightness: number; contrast: number; saturation: number }; // percentages
  texts: TemplateText[]; // edited overrides of def.texts
};

export function defaultOpts(): Omit<ComposeOpts, "productImg" | "texts"> {
  return { productScale: 1, productOffset: { x: 0, y: 0 }, adjust: { brightness: 100, contrast: 100, saturation: 100 } };
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Draw a full template composition into ``ctx`` at ``size`` (base-canvas pixels). */
export function drawTemplate(
  ctx: CanvasRenderingContext2D,
  def: TemplateDef,
  size: { w: number; h: number },
  opts: ComposeOpts,
) {
  const { w, h } = size;

  // background
  if (def.background.kind === "gradient") {
    const angle = ((def.background.angle ?? 135) * Math.PI) / 180;
    const dx = Math.cos(angle) * w;
    const dy = Math.sin(angle) * h;
    const g = ctx.createLinearGradient(w / 2 - dx / 2, h / 2 - dy / 2, w / 2 + dx / 2, h / 2 + dy / 2);
    const cols = def.background.colors;
    cols.forEach((c, i) => g.addColorStop(cols.length === 1 ? 0 : i / (cols.length - 1), c));
    ctx.fillStyle = g;
  } else {
    ctx.fillStyle = def.background.colors[0] ?? "#ffffff";
  }
  ctx.fillRect(0, 0, w, h);

  // product (or placeholder)
  const cx = def.productBox.xPct * w;
  const cy = def.productBox.yPct * h;
  const bw = def.productBox.wPct * w * opts.productScale;
  const bh = def.productBox.hPct * h * opts.productScale;
  if (opts.productImg && opts.productImg.naturalWidth > 0) {
    const img = opts.productImg;
    const s = Math.min(bw / img.naturalWidth, bh / img.naturalHeight);
    const dw = img.naturalWidth * s;
    const dh = img.naturalHeight * s;
    ctx.save();
    const { brightness, contrast, saturation } = opts.adjust;
    ctx.filter = `brightness(${brightness}%) contrast(${contrast}%) saturate(${saturation}%)`;
    ctx.drawImage(img, cx - dw / 2 + opts.productOffset.x, cy - dh / 2 + opts.productOffset.y, dw, dh);
    ctx.restore();
  } else if (!opts.productImg) {
    ctx.save();
    ctx.fillStyle = "rgba(100,100,120,0.10)";
    ctx.strokeStyle = "rgba(100,100,120,0.35)";
    ctx.lineWidth = Math.max(2, w * 0.004);
    roundRect(ctx, cx - bw / 2, cy - bh / 2, bw, bh, w * 0.03);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  // text layers
  for (const layer of opts.texts) {
    const fontPx = layer.fontPct * h;
    ctx.font = `${layer.weight} ${fontPx}px Inter, system-ui, sans-serif`;
    ctx.fillStyle = layer.color;
    ctx.textAlign = layer.align;
    ctx.textBaseline = "middle";
    ctx.fillText(layer.text, layer.xPct * w, layer.yPct * h);
  }
}

/** Live editor canvas. Redraws whenever inputs change; exposes the DOM canvas via ref. */
export function TemplateCanvas({
  def,
  opts,
  className,
  onPointerOffset,
  canvasRef,
}: {
  def: TemplateDef;
  opts: ComposeOpts;
  className?: string;
  onPointerOffset?: (delta: { x: number; y: number }) => void;
  canvasRef?: (el: HTMLCanvasElement | null) => void;
}) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const size = useMemo(() => canvasSize(def.aspectRatio), [def.aspectRatio]);
  const drag = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    cv.width = size.w;
    cv.height = size.h;
    const ctx = cv.getContext("2d");
    if (ctx) drawTemplate(ctx, def, size, opts);
  }, [def, opts, size]);

  function toBase(e: React.PointerEvent<HTMLCanvasElement>): { x: number; y: number } {
    const cv = ref.current!;
    const rect = cv.getBoundingClientRect();
    const scale = size.w / rect.width;
    return { x: (e.clientX - rect.left) * scale, y: (e.clientY - rect.top) * scale };
  }

  return (
    <canvas
      ref={(el) => {
        ref.current = el;
        canvasRef?.(el);
      }}
      className={className}
      style={{ touchAction: "none", aspectRatio: `${size.w} / ${size.h}` }}
      onPointerDown={(e) => {
        if (!onPointerOffset) return;
        (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
        drag.current = toBase(e);
      }}
      onPointerMove={(e) => {
        if (!onPointerOffset || !drag.current) return;
        const p = toBase(e);
        onPointerOffset({ x: p.x - drag.current.x, y: p.y - drag.current.y });
        drag.current = p;
      }}
      onPointerUp={(e) => {
        if (!onPointerOffset) return;
        drag.current = null;
        (e.target as HTMLCanvasElement).releasePointerCapture(e.pointerId);
      }}
    />
  );
}

/** Small static preview for the template gallery (product placeholder). */
export function TemplateThumb({ def, className }: { def: TemplateDef; className?: string }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const size = useMemo(() => canvasSize(def.aspectRatio, 320), [def.aspectRatio]);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    cv.width = size.w;
    cv.height = size.h;
    const ctx = cv.getContext("2d");
    if (ctx) {
      drawTemplate(ctx, def, size, {
        productImg: null,
        productScale: 1,
        productOffset: { x: 0, y: 0 },
        adjust: { brightness: 100, contrast: 100, saturation: 100 },
        texts: def.texts,
      });
    }
  }, [def, size]);

  return <canvas ref={ref} className={className} style={{ aspectRatio: `${size.w} / ${size.h}` }} />;
}
