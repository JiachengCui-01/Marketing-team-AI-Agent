"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Loader2,
  RotateCw,
  FlipHorizontal2,
  FlipVertical2,
  Download,
  Wand2,
  SlidersHorizontal,
  Palette,
  Crop,
  RefreshCw,
} from "lucide-react";
import { reeditImage, artifactPreviewUrl, type ImageGeneration } from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { LoadingCard } from "@/components/ui/spinner";

const ADJUST_DEFAULT = { brightness: 100, contrast: 100, saturation: 100 };
const TRANSFORM_DEFAULT = { rotate: 0, flipH: false, flipV: false };

// Filter presets contribute CSS filter fragments that compose on top of the
// brightness/contrast/saturation sliders (independent dimensions).
const FILTER_PRESETS: { key: string; fragment: string }[] = [
  { key: "none", fragment: "" },
  { key: "fresh", fragment: "saturate(118%) brightness(104%)" },
  { key: "warm", fragment: "sepia(30%) saturate(125%)" },
  { key: "mono", fragment: "grayscale(100%)" },
  { key: "vivid", fragment: "contrast(118%) saturate(135%)" },
];

type Category = "adjust" | "filter" | "transform";

/**
 * Post-generation refine view, laid out like a mobile photo editor (醒图-style):
 * a category switcher (icon + name); the selected category reveals its operations
 * below. Global Download + Reset-all live outside the categories; each category has
 * its own reset. AI re-edit is pinned at the bottom like a chat input.
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
  // The generation this view opened on — Reset-all reverts AI re-edits back to it.
  const baseGen = useRef(generation).current;

  const [adjust, setAdjust] = useState({ ...ADJUST_DEFAULT });
  const [preset, setPreset] = useState("none");
  const [transform, setTransform] = useState({ ...TRANSFORM_DEFAULT });
  const [category, setCategory] = useState<Category>("adjust");

  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const src = generation.artifact_id ? artifactPreviewUrl(generation.artifact_id) : "";
  const presetFragment = FILTER_PRESETS.find((p) => p.key === preset)?.fragment ?? "";
  const filter =
    `brightness(${adjust.brightness}%) contrast(${adjust.contrast}%) saturate(${adjust.saturation}%) ${presetFragment}`.trim();
  const cssTransform = `rotate(${transform.rotate}deg) scaleX(${transform.flipH ? -1 : 1}) scaleY(${transform.flipV ? -1 : 1})`;

  // A new underlying image (e.g. AI re-edit result) starts from clean edits.
  useEffect(() => {
    setAdjust({ ...ADJUST_DEFAULT });
    setPreset("none");
    setTransform({ ...TRANSFORM_DEFAULT });
  }, [generation.artifact_id]);

  function resetAll() {
    setAdjust({ ...ADJUST_DEFAULT });
    setPreset("none");
    setTransform({ ...TRANSFORM_DEFAULT });
    // Also undo any AI re-edits by returning to the generation we opened on.
    if (generation.artifact_id !== baseGen.artifact_id) onReplace(baseGen);
  }

  async function download() {
    if (!src) return;
    try {
      // Fetch as a blob (token in query) → object URL: same-origin, untainted canvas.
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
        const rotated = transform.rotate % 180 !== 0;
        const w = image.naturalWidth;
        const h = image.naturalHeight;
        canvas.width = rotated ? h : w;
        canvas.height = rotated ? w : h;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.filter = filter;
        ctx.translate(canvas.width / 2, canvas.height / 2);
        ctx.rotate((transform.rotate * Math.PI) / 180);
        ctx.scale(transform.flipH ? -1 : 1, transform.flipV ? -1 : 1);
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
      const gen = await reeditImage({ history_id: generation.history_id, prompt: instruction.trim() });
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

  const CATEGORIES: { key: Category; icon: typeof SlidersHorizontal; label: string }[] = [
    { key: "adjust", icon: SlidersHorizontal, label: t.imageCatAdjust },
    { key: "filter", icon: Palette, label: t.imageCatFilter },
    { key: "transform", icon: Crop, label: t.imageCatTransform },
  ];

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onExit} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.imageBackToPanel}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <Wand2 size={15} className="text-feature-image" />
          <span>{t.imageEditTitle}</span>
        </div>
        <div className="w-16" />
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
          {/* image frame */}
          <div className="relative flex justify-center rounded-xl border border-border bg-bg-subtle p-4">
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt={generation.prompt || "generated"}
                decoding="async"
                style={{ filter, transform: cssTransform }}
                className="max-h-[44vh] w-auto rounded"
              />
            ) : null}
            {busy ? (
              <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-bg/60 backdrop-blur-sm animate-fade-in">
                <LoadingCard label={t.imageReedecting} variant="image" />
              </div>
            ) : null}
          </div>

          {/* global actions (outside the categories) */}
          <div className="flex items-center justify-end gap-2">
            <button onClick={resetAll} className="btn-ghost border border-border px-3 py-2 text-sm">
              <RefreshCw size={14} />
              {t.imageResetAll}
            </button>
            <button onClick={download} className="btn-accent px-3 py-2 text-sm">
              <Download size={14} />
              {t.imageSaveVersion}
            </button>
          </div>

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          {/* category switcher + operations panel */}
          <div className="rounded-xl border border-border">
            <div className="grid grid-cols-3 border-b border-border">
              {CATEGORIES.map(({ key, icon: Icon, label }) => {
                const active = category === key;
                return (
                  <button
                    key={key}
                    onClick={() => setCategory(key)}
                    className={`flex flex-col items-center gap-1 py-2.5 text-[11px] transition ${
                      active
                        ? "text-accent bg-accent/10"
                        : "text-fg-muted hover:text-fg hover:bg-bg-elevated"
                    }`}
                  >
                    <Icon size={18} />
                    <span>{label}</span>
                  </button>
                );
              })}
            </div>

            <div className="p-3">
              {category === "adjust" ? (
                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Slider label={t.imageBrightness} value={adjust.brightness} onChange={(v) => setAdjust((a) => ({ ...a, brightness: v }))} />
                    <Slider label={t.imageContrast} value={adjust.contrast} onChange={(v) => setAdjust((a) => ({ ...a, contrast: v }))} />
                    <Slider label={t.imageSaturation} value={adjust.saturation} onChange={(v) => setAdjust((a) => ({ ...a, saturation: v }))} />
                  </div>
                  <CategoryReset onReset={() => setAdjust({ ...ADJUST_DEFAULT })} label={t.imageReset} />
                </div>
              ) : null}

              {category === "filter" ? (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {FILTER_PRESETS.map((p) => {
                      const active = preset === p.key;
                      return (
                        <button
                          key={p.key}
                          onClick={() => setPreset(p.key)}
                          className={`rounded-lg border px-3 py-1.5 text-xs transition ${
                            active ? "border-accent bg-accent/10 text-accent" : "border-border text-fg-muted hover:bg-bg-elevated"
                          }`}
                        >
                          {t[`imageFilter_${p.key}` as keyof typeof t] as string}
                        </button>
                      );
                    })}
                  </div>
                  <CategoryReset onReset={() => setPreset("none")} label={t.imageReset} />
                </div>
              ) : null}

              {category === "transform" ? (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => setTransform((tf) => ({ ...tf, rotate: (tf.rotate + 90) % 360 }))}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-fg-muted hover:bg-bg-elevated"
                    >
                      <RotateCw size={14} />
                      {t.imageRotate}
                    </button>
                    <button
                      onClick={() => setTransform((tf) => ({ ...tf, flipH: !tf.flipH }))}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition ${
                        transform.flipH ? "border-accent bg-accent/10 text-accent" : "border-border text-fg-muted hover:bg-bg-elevated"
                      }`}
                    >
                      <FlipHorizontal2 size={14} />
                      {t.imageFlipH}
                    </button>
                    <button
                      onClick={() => setTransform((tf) => ({ ...tf, flipV: !tf.flipV }))}
                      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition ${
                        transform.flipV ? "border-accent bg-accent/10 text-accent" : "border-border text-fg-muted hover:bg-bg-elevated"
                      }`}
                    >
                      <FlipVertical2 size={14} />
                      {t.imageFlipV}
                    </button>
                  </div>
                  <CategoryReset onReset={() => setTransform({ ...TRANSFORM_DEFAULT })} label={t.imageReset} />
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* AI re-edit — pinned at the bottom like the chat input */}
      <div className="border-t border-border bg-bg-elevated/60 backdrop-blur">
        <div className="max-w-3xl mx-auto px-4 py-3">
          <div className="flex items-end gap-2 rounded-xl border border-border bg-bg-elevated focus-within:border-accent transition shadow-sm">
            <div className="flex items-center gap-1.5 pl-3 text-xs text-fg-subtle">
              <Wand2 size={14} className="text-accent" />
            </div>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              rows={1}
              placeholder={t.imageAiReeditPlaceholder}
              disabled={busy}
              className="flex-1 resize-none bg-transparent px-1 py-3 text-sm placeholder:text-fg-subtle focus:outline-none disabled:opacity-50 max-h-40"
              style={{ minHeight: 48 }}
            />
            <button
              onClick={aiReedit}
              disabled={busy || !instruction.trim()}
              className="m-1.5 inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3.5 h-9 text-accent-fg text-sm font-medium hover:opacity-90 transition disabled:opacity-40"
            >
              {busy ? <Loader2 size={15} className="animate-spin text-feature-image" /> : <Wand2 size={15} />}
              <span>{busy ? t.imageReedecting : t.imageApply}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CategoryReset({ onReset, label }: { onReset: () => void; label: string }) {
  return (
    <div className="flex justify-end">
      <button
        onClick={onReset}
        className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-fg-muted hover:bg-bg-elevated"
      >
        <RefreshCw size={12} />
        {label}
      </button>
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
