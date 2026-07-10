"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Loader2, RotateCw, Download, Wand2 } from "lucide-react";
import {
  reeditImage,
  artifactPreviewUrl,
  type ImageGeneration,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

const DEFAULTS = { brightness: 100, contrast: 100, saturation: 100, rotate: 0 };

/**
 * Post-generation refine view: live client-side adjustments (brightness/contrast/
 * saturation/rotate) as a CSS-filter preview, a baked PNG download, and AI re-edit
 * (a real backend round-trip that produces a new version). Pixel brush cutout and a
 * full layer editor are intentionally out of scope for now.
 */
export function ImageEditView({
  generation,
  onReplace,
  onExit,
  onBack,
}: {
  generation: ImageGeneration;
  onReplace: (g: ImageGeneration) => void;
  onExit: () => void;
  onBack: () => void;
}) {
  const { locale, t } = useI18n();
  const [adj, setAdj] = useState({ ...DEFAULTS });
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const src = generation.artifact_id ? artifactPreviewUrl(generation.artifact_id) : "";
  const filter = `brightness(${adj.brightness}%) contrast(${adj.contrast}%) saturate(${adj.saturation}%)`;

  useEffect(() => {
    setAdj({ ...DEFAULTS });
  }, [generation.artifact_id]);

  async function download() {
    if (!src) return;
    try {
      // Fetch the artifact as a blob (auth token is in the query) and draw from an
      // object URL — a same-origin source, so the canvas stays untainted and we avoid
      // the crossOrigin cache pitfall that breaks the <img> display.
      const res = await fetch(src);
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      try {
        const image = await new Promise<HTMLImageElement>((resolve, reject) => {
          const im = new Image();
          im.onload = () => resolve(im);
          im.onerror = reject;
          im.src = objectUrl;
        });
        const canvas = document.createElement("canvas");
        const rotated = adj.rotate % 180 !== 0;
        const w = image.naturalWidth;
        const h = image.naturalHeight;
        canvas.width = rotated ? h : w;
        canvas.height = rotated ? w : h;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.filter = filter;
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate((adj.rotate * Math.PI) / 180);
        ctx.drawImage(image, -w / 2, -h / 2);
        const url = canvas.toDataURL("image/png");
        const a = document.createElement("a");
        a.href = url;
        a.download = generation.filename || "marketing.png";
        a.click();
      } finally {
        URL.revokeObjectURL(objectUrl);
      }
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  async function aiReedit() {
    if (!instruction.trim() || !generation.history_id) return;
    setBusy(true);
    setError(null);
    try {
      const gen = await reeditImage({
        history_id: generation.history_id,
        prompt: instruction.trim(),
      });
      if (!gen.ok) {
        setError(gen.message || t.imageGenFailed);
        return;
      }
      setInstruction("");
      onReplace(gen);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <header className="border-b border-border bg-bg-elevated/60 backdrop-blur flex items-center gap-2 px-4 py-2.5">
        <button
          onClick={onExit}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm text-fg-muted hover:text-fg hover:bg-bg-elevated transition"
        >
          <ArrowLeft size={15} />
          <span>{t.imageBackToPanel}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <Wand2 size={15} className="text-accent" />
          <span>{t.imageEditTitle}</span>
        </div>
        <div className="w-16" />
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
          <div className="flex justify-center rounded-xl border border-border bg-bg-subtle p-4">
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt={generation.prompt || "generated"}
                decoding="async"
                style={{ filter, transform: `rotate(${adj.rotate}deg)` }}
                className="max-h-[46vh] w-auto rounded"
              />
            ) : null}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Slider label={t.imageBrightness} value={adj.brightness} onChange={(v) => setAdj((a) => ({ ...a, brightness: v }))} />
            <Slider label={t.imageContrast} value={adj.contrast} onChange={(v) => setAdj((a) => ({ ...a, contrast: v }))} />
            <Slider label={t.imageSaturation} value={adj.saturation} onChange={(v) => setAdj((a) => ({ ...a, saturation: v }))} />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setAdj((a) => ({ ...a, rotate: (a.rotate + 90) % 360 }))}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-fg-muted hover:bg-bg-elevated"
            >
              <RotateCw size={14} />
              {t.imageRotate}
            </button>
            <button
              onClick={() => setAdj({ ...DEFAULTS })}
              className="rounded-lg border border-border px-3 py-2 text-sm text-fg-muted hover:bg-bg-elevated"
            >
              {t.imageReset}
            </button>
            <button
              onClick={download}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-fg-muted hover:bg-bg-elevated"
            >
              <Download size={14} />
              {t.imageSaveVersion}
            </button>
          </div>

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          <div className="rounded-xl border border-border p-3">
            <p className="mb-2 flex items-center gap-1.5 text-sm font-medium">
              <Wand2 size={14} className="text-accent" />
              {t.imageAiReedit}
            </p>
            <div className="flex items-end gap-2">
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={1}
                placeholder={t.imageAiReeditPlaceholder}
                disabled={busy}
                className="flex-1 resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-50"
              />
              <button
                onClick={aiReedit}
                disabled={busy || !instruction.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <Wand2 size={15} />}
                {busy ? t.imageReedecting : t.imageApply}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Slider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block text-xs text-fg-muted">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="text-fg-subtle">{value}%</span>
      </span>
      <input
        type="range"
        min={0}
        max={200}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-accent"
      />
    </label>
  );
}
