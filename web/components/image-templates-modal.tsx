"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Loader2,
  Upload,
  Check,
  Scissors,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import {
  cutoutImage,
  uploadFile,
  saveComposedImage,
  uploadPreviewUrl,
  artifactPreviewUrl,
  type ImageGeneration,
  type UploadResponse,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import {
  TEMPLATES,
  PLATFORM_ORDER,
  canvasSize,
  type TemplateDef,
  type TemplateText,
} from "@/lib/image-templates";
import { TemplateCanvas, TemplateThumb, drawTemplate, type ComposeOpts } from "@/components/template-canvas";

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = url;
  });
}

export function ImageTemplatesModal({
  onClose,
  onGenerated,
}: {
  onClose: () => void;
  onGenerated: (gen: ImageGeneration) => void;
}) {
  const { locale, t } = useI18n();

  // ----- left: filters + gallery -----
  const [platform, setPlatform] = useState("all");
  const [style, setStyle] = useState("all");
  const [appliedPlatform, setAppliedPlatform] = useState("all");
  const [appliedStyle, setAppliedStyle] = useState("all");
  const [selected, setSelected] = useState<TemplateDef | null>(null);

  // ----- right: upload + compose -----
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [originalImg, setOriginalImg] = useState<HTMLImageElement | null>(null);
  const [cutoutArtifactId, setCutoutArtifactId] = useState<string | null>(null);
  const [cutoutImg, setCutoutImg] = useState<HTMLImageElement | null>(null);
  const [bgRemoved, setBgRemoved] = useState(false);
  const [bgBusy, setBgBusy] = useState(false);
  const [bgWarning, setBgWarning] = useState<string | null>(null);

  const [texts, setTexts] = useState<TemplateText[]>([]);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [adjust, setAdjust] = useState({ brightness: 100, contrast: 100, saturation: 100 });

  const [toolPage, setToolPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const platformLabel = (p: string) =>
    (
      {
        taobao: t.imagePlatformTaobao,
        xiaohongshu: t.imagePlatformXiaohongshu,
        amazon: t.imagePlatformAmazon,
        instagram: t.imagePlatformInstagram,
        generic: t.imagePlatformGeneric,
      } as Record<string, string>
    )[p] ?? p;
  const styleLabel = (s: string) =>
    (
      {
        white: t.imageStyleWhite,
        scene: t.imageStyleScene,
        promo: t.imageStylePromo,
        lifestyle: t.imageStyleLifestyle,
        handheld: t.imageStyleHandheld,
        flatlay: t.imageStyleFlatlay,
        multiangle: t.imageStyleMultiangle,
        editorial: t.imageStyleEditorial,
        minimal: t.imageStyleMinimal,
        clean: t.imageStyleClean,
      } as Record<string, string>
    )[s] ?? s;

  const platformOptions = useMemo(
    () => ["all", ...PLATFORM_ORDER.filter((p) => TEMPLATES.some((tpl) => tpl.platform === p))],
    [],
  );
  const styleOptions = useMemo(
    () => ["all", ...Array.from(new Set(TEMPLATES.map((tpl) => tpl.style)))],
    [],
  );
  const filtered = useMemo(
    () =>
      TEMPLATES.filter(
        (tpl) =>
          (appliedPlatform === "all" || tpl.platform === appliedPlatform) &&
          (appliedStyle === "all" || tpl.style === appliedStyle),
      ),
    [appliedPlatform, appliedStyle],
  );
  const groups = useMemo(() => {
    const map = new Map<string, TemplateDef[]>();
    for (const tpl of filtered) {
      const arr = map.get(tpl.platform) ?? [];
      arr.push(tpl);
      map.set(tpl.platform, arr);
    }
    return PLATFORM_ORDER.filter((p) => map.has(p)).map((p) => [p, map.get(p)!] as const);
  }, [filtered]);

  // load original when uploaded
  useEffect(() => {
    if (!upload) {
      setOriginalImg(null);
      return;
    }
    let alive = true;
    loadImage(uploadPreviewUrl(upload.file_id))
      .then((img) => alive && setOriginalImg(img))
      .catch(() => alive && setError(t.imageGenFailed));
    return () => {
      alive = false;
    };
  }, [upload, t.imageGenFailed]);

  // load cutout once its artifact exists
  useEffect(() => {
    if (!cutoutArtifactId) {
      setCutoutImg(null);
      return;
    }
    let alive = true;
    loadImage(artifactPreviewUrl(cutoutArtifactId))
      .then((img) => alive && setCutoutImg(img))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [cutoutArtifactId]);

  function selectTemplate(tpl: TemplateDef) {
    setSelected(tpl);
    setTexts(tpl.texts.map((x) => ({ ...x })));
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setAdjust({ brightness: 100, contrast: 100, saturation: 100 });
    setToolPage(0);
  }

  function clearTemplate() {
    // Click an applied template again to un-apply it.
    setSelected(null);
    setTexts([]);
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }

  async function handleUpload(file: File) {
    setError(null);
    setBgRemoved(false);
    setCutoutArtifactId(null);
    setBgWarning(null);
    setUploading(true);
    try {
      const resp = await uploadFile(file);
      setUpload(resp);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setUploading(false);
    }
  }

  async function toggleBg() {
    if (bgRemoved) {
      setBgRemoved(false); // restore — keeps cached cutout
      return;
    }
    if (cutoutArtifactId) {
      setBgRemoved(true); // reuse first cutout, no re-run
      return;
    }
    if (!upload) return;
    setBgBusy(true);
    setBgWarning(null);
    try {
      const r = await cutoutImage(upload.file_id);
      if (r.artifact_id) {
        setCutoutArtifactId(r.artifact_id);
        setBgRemoved(true);
      } else {
        setBgWarning(r.warning || t.imageNoCutout);
      }
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBgBusy(false);
    }
  }

  const productImg = bgRemoved ? cutoutImg : originalImg;
  const opts: ComposeOpts = { productImg, productScale: scale, productOffset: offset, adjust, texts };

  async function confirmGenerate() {
    if (!selected || !upload) return;
    setBusy(true);
    setError(null);
    try {
      const size = canvasSize(selected.aspectRatio);
      const cv = document.createElement("canvas");
      cv.width = size.w;
      cv.height = size.h;
      const ctx = cv.getContext("2d");
      if (!ctx) throw new Error("canvas unavailable");
      drawTemplate(ctx, selected, size, opts);
      const blob: Blob | null = await new Promise((res) => cv.toBlob(res, "image/png"));
      if (!blob) throw new Error("export failed");
      const file = new File([blob], "composition.png", { type: "image/png" });
      const composed = await uploadFile(file);
      const gen = await saveComposedImage({
        file_id: composed.file_id,
        template_id: selected.id,
        style_key: selected.platform,
        prompt: texts.map((x) => x.text).join(" ").trim() || selected.label,
      });
      onGenerated(gen);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  const TOOL_PAGES = [t.imageToolText, t.imageToolBg, t.imageToolAdjust, t.imageToolSubject];

  return (
    <Modal title={t.imageTemplatesTitle} onClose={onClose} wide>
      <div className="grid gap-4 md:grid-cols-2">
        {/* LEFT: filters + gallery */}
        <div>
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <label className="text-xs text-fg-muted">
              {t.imageFilterPlatform}
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="mt-1 block rounded-lg border border-border bg-bg px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
              >
                {platformOptions.map((p) => (
                  <option key={p} value={p}>
                    {p === "all" ? t.imageAll : platformLabel(p)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-fg-muted">
              {t.imageFilterStyle}
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="mt-1 block rounded-lg border border-border bg-bg px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
              >
                {styleOptions.map((s) => (
                  <option key={s} value={s}>
                    {s === "all" ? t.imageAll : styleLabel(s)}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => {
                setAppliedPlatform(platform);
                setAppliedStyle(style);
              }}
              className="btn-accent px-3 py-1.5 text-sm"
            >
              {t.imageFilterApply}
            </button>
            <button
              onClick={() => {
                setPlatform("all");
                setStyle("all");
                setAppliedPlatform("all");
                setAppliedStyle("all");
              }}
              className="btn-ghost border border-border px-3 py-1.5 text-sm"
            >
              {t.imageFilterReset}
            </button>
          </div>

          {filtered.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-muted">{t.imageTemplatesEmpty}</p>
          ) : (
            <div className="max-h-[54vh] space-y-4 overflow-y-auto pr-1">
              {groups.map(([plat, items]) => (
                <div key={plat}>
                  <p className="mb-1.5 text-xs font-semibold text-fg-muted">{platformLabel(plat)}</p>
                  <div className="grid grid-cols-2 gap-2">
                    {items.map((tpl) => {
                      const active = selected?.id === tpl.id;
                      return (
                        <button
                          key={tpl.id}
                          onClick={() => (active ? clearTemplate() : selectTemplate(tpl))}
                          className={`overflow-hidden rounded-xl border text-left hover-lift ${
                            active ? "border-accent ring-1 ring-accent" : "border-border hover:bg-bg-elevated"
                          }`}
                        >
                          <TemplateThumb def={tpl} className="w-full bg-bg-subtle" />
                          <div className="px-2 py-1.5">
                            <div className="flex items-center gap-1 text-xs font-medium">
                              {active ? <Check size={12} className="text-accent" /> : null}
                              {tpl.label}
                            </div>
                            <p className="text-[10px] text-fg-subtle">
                              {styleLabel(tpl.style)} · {tpl.aspectRatio}
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* RIGHT: single image frame + 剪映-style tool tabs */}
        <div className="space-y-3">
          <label
            className={`inline-flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2.5 text-sm cursor-pointer transition ${
              upload
                ? "border-border text-fg-muted hover:bg-bg-elevated"
                : "border-accent/40 bg-accent/10 text-accent hover:bg-accent/15"
            }`}
          >
            {uploading ? <Loader2 size={15} className="animate-spin text-feature-analytics" /> : <Upload size={15} />}
            <span>{t.imageUploadButton}</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) handleUpload(e.target.files[0]);
                e.target.value = "";
              }}
            />
          </label>

          {/* the single main image frame — everything reflects here */}
          <div className="flex items-center justify-center rounded-lg border border-border bg-bg-subtle p-2">
            {upload && selected ? (
              <TemplateCanvas
                def={selected}
                opts={opts}
                className="max-h-[40vh] w-auto rounded"
                onPointerOffset={
                  toolPage === 3
                    ? (d) => setOffset((o) => ({ x: o.x + d.x, y: o.y + d.y }))
                    : undefined
                }
              />
            ) : upload ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={bgRemoved && cutoutArtifactId ? artifactPreviewUrl(cutoutArtifactId) : uploadPreviewUrl(upload.file_id)}
                alt="uploaded"
                crossOrigin="anonymous"
                decoding="async"
                className="max-h-[40vh] w-auto rounded object-contain"
              />
            ) : (
              <div className="flex h-40 w-full items-center justify-center text-xs text-fg-subtle">
                {t.imageUploadHint}
              </div>
            )}
          </div>

          {/* tool tabs with arrow navigation — always visible (剪映-style) */}
          <div className="rounded-lg border border-border">
              <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
                <button
                  onClick={() => setToolPage((p) => (p - 1 + TOOL_PAGES.length) % TOOL_PAGES.length)}
                  className="btn-ghost w-7 h-7"
                  aria-label="prev"
                >
                  <ChevronLeft size={16} />
                </button>
                <span className="text-sm font-medium">{TOOL_PAGES[toolPage]}</span>
                <button
                  onClick={() => setToolPage((p) => (p + 1) % TOOL_PAGES.length)}
                  className="btn-ghost w-7 h-7"
                  aria-label="next"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              <div className="p-3">
                {toolPage === 0 ? (
                  texts.length === 0 ? (
                    <p className="text-xs text-fg-subtle">{selected ? t.imageNoText : t.imageSelectTemplateFirst}</p>
                  ) : (
                    <div className="space-y-2">
                      {texts.map((layer, i) => (
                        <div key={layer.id} className="flex items-center gap-2">
                          <input
                            value={layer.text}
                            onChange={(e) =>
                              setTexts((arr) => arr.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))
                            }
                            className="flex-1 rounded-lg border border-border bg-bg px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
                          />
                          <input
                            type="color"
                            value={layer.color}
                            onChange={(e) =>
                              setTexts((arr) => arr.map((x, j) => (j === i ? { ...x, color: e.target.value } : x)))
                            }
                            className="h-8 w-8 shrink-0 rounded border border-border bg-bg"
                            aria-label="color"
                          />
                        </div>
                      ))}
                    </div>
                  )
                ) : null}

                {toolPage === 1 ? (
                  <div className="space-y-2">
                    {!upload ? (
                      <p className="text-xs text-fg-subtle">{t.imageUploadFirst}</p>
                    ) : null}
                    <button
                      onClick={toggleBg}
                      disabled={bgBusy || !upload}
                      className="btn-accent px-3 py-2 text-sm"
                    >
                      {bgBusy ? <Loader2 size={14} className="animate-spin text-feature-image" /> : bgRemoved ? <RotateCcw size={14} /> : <Scissors size={14} />}
                      {bgBusy ? t.imageRemovingBg : bgRemoved ? t.imageRestoreBg : t.imageRemoveBg}
                    </button>
                    {bgWarning ? <p className="text-[11px] text-danger">{bgWarning}</p> : null}
                  </div>
                ) : null}

                {toolPage === 2 ? (
                  <div className="space-y-2">
                    <div className="grid gap-2 sm:grid-cols-3">
                      <Slider label={t.imageBrightness} value={adjust.brightness} onChange={(v) => setAdjust((a) => ({ ...a, brightness: v }))} />
                      <Slider label={t.imageContrast} value={adjust.contrast} onChange={(v) => setAdjust((a) => ({ ...a, contrast: v }))} />
                      <Slider label={t.imageSaturation} value={adjust.saturation} onChange={(v) => setAdjust((a) => ({ ...a, saturation: v }))} />
                    </div>
                    <div className="flex justify-end">
                      <button
                        onClick={() => setAdjust({ brightness: 100, contrast: 100, saturation: 100 })}
                        className="rounded border border-border px-2 py-1 text-xs text-fg-muted hover:bg-bg-elevated"
                      >
                        {t.imageReset}
                      </button>
                    </div>
                  </div>
                ) : null}

                {toolPage === 3 ? (
                  <div className="space-y-2">
                    <Slider label={t.imageSubjectScale} value={Math.round(scale * 100)} min={40} max={200} onChange={(v) => setScale(v / 100)} />
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-fg-subtle">{t.imageDragHint}</span>
                      <button
                        onClick={() => {
                          setScale(1);
                          setOffset({ x: 0, y: 0 });
                        }}
                        className="rounded border border-border px-2 py-1 text-xs text-fg-muted hover:bg-bg-elevated"
                      >
                        {t.imageReset}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          <button
            onClick={confirmGenerate}
            disabled={busy || !selected || !upload}
            className="btn-accent w-full px-4 py-2 text-sm"
          >
            {busy ? <Loader2 size={15} className="animate-spin text-feature-image" /> : null}
            {t.imageConfirmGenerate}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function Slider({
  label,
  value,
  onChange,
  min = 0,
  max = 200,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <label className="block text-xs text-fg-muted">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="text-fg-subtle">{value}%</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-accent"
      />
    </label>
  );
}
