"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Upload, Check } from "lucide-react";
import {
  listImageTemplates,
  cutoutImage,
  generateImage,
  uploadFile,
  type ImageTemplate,
  type ImageGeneration,
  type ImageSource,
  type UploadResponse,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { ImageUploadWorkspace } from "@/components/image-source-choice";

/**
 * Templates modal: LEFT = platform/style filters + gallery grouped by platform;
 * RIGHT = image upload with the on-demand cutout workspace inline + a prompt.
 * Selecting a template and confirming generates using that template + the image.
 */
export function ImageTemplatesModal({
  onClose,
  onGenerated,
}: {
  onClose: () => void;
  onGenerated: (gen: ImageGeneration) => void;
}) {
  const { locale, t } = useI18n();
  const [all, setAll] = useState<ImageTemplate[] | null>(null);
  // pending (dropdown) vs applied (after clicking 筛选) filters
  const [platform, setPlatform] = useState("all");
  const [style, setStyle] = useState("all");
  const [appliedPlatform, setAppliedPlatform] = useState("all");
  const [appliedStyle, setAppliedStyle] = useState("all");
  const [selected, setSelected] = useState<ImageTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // right pane
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [cutoutArtifactId, setCutoutArtifactId] = useState<string | null>(null);
  const [choice, setChoice] = useState<"original" | "cutout">("original");
  const [bgBusy, setBgBusy] = useState(false);
  const [bgWarning, setBgWarning] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);

  const platformLabel = useCallback(
    (p: string) =>
      (
        {
          taobao: t.imagePlatformTaobao,
          xiaohongshu: t.imagePlatformXiaohongshu,
          amazon: t.imagePlatformAmazon,
          instagram: t.imagePlatformInstagram,
          generic: t.imagePlatformGeneric,
        } as Record<string, string>
      )[p] ?? p,
    [t],
  );

  const styleLabel = useCallback(
    (s: string | null) =>
      s
        ? ((
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
          )[s] ?? s)
        : "",
    [t],
  );

  useEffect(() => {
    listImageTemplates()
      .then(setAll)
      .catch((e) => setError(localizeError(e, locale)));
  }, [locale]);

  const platformOptions = useMemo(
    () => ["all", ...Array.from(new Set((all ?? []).map((tpl) => tpl.platform)))],
    [all],
  );
  const styleOptions = useMemo(
    () => ["all", ...Array.from(new Set((all ?? []).map((tpl) => tpl.style).filter(Boolean) as string[]))],
    [all],
  );

  const filtered = useMemo(() => {
    return (all ?? []).filter(
      (tpl) =>
        (appliedPlatform === "all" || tpl.platform === appliedPlatform) &&
        (appliedStyle === "all" || tpl.style === appliedStyle),
    );
  }, [all, appliedPlatform, appliedStyle]);

  // Group by platform for the "All" view; a single group when a platform is applied.
  const groups = useMemo(() => {
    const map = new Map<string, ImageTemplate[]>();
    for (const tpl of filtered) {
      const arr = map.get(tpl.platform) ?? [];
      arr.push(tpl);
      map.set(tpl.platform, arr);
    }
    return Array.from(map.entries());
  }, [filtered]);

  function applyFilter() {
    setAppliedPlatform(platform);
    setAppliedStyle(style);
  }

  function resetFilter() {
    setPlatform("all");
    setStyle("all");
    setAppliedPlatform("all");
    setAppliedStyle("all");
  }

  async function handleUpload(file: File) {
    setError(null);
    setCutoutArtifactId(null);
    setChoice("original");
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

  async function removeBackground() {
    if (!upload) return;
    setBgBusy(true);
    setBgWarning(null);
    try {
      const r = await cutoutImage(upload.file_id);
      if (r.artifact_id) {
        setCutoutArtifactId(r.artifact_id);
        setChoice("cutout");
      } else {
        setBgWarning(r.warning || t.imageNoCutout);
      }
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBgBusy(false);
    }
  }

  async function confirmGenerate() {
    if (!selected || !upload) return;
    const source: ImageSource =
      choice === "cutout" && cutoutArtifactId
        ? { type: "cutout", id: cutoutArtifactId }
        : { type: "upload", id: upload.file_id };
    setBusy(true);
    setError(null);
    try {
      const gen = await generateImage({
        prompt: prompt.trim() || selected.label,
        style_key: selected.style_key,
        template_id: selected.id,
        source,
      });
      if (!gen.ok) {
        setError(gen.message || t.imageGenFailed);
        return;
      }
      onGenerated(gen);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={t.imageTemplatesTitle} onClose={onClose} wide>
      <div className="grid gap-4 md:grid-cols-2">
        {/* LEFT: filters + gallery grouped by platform */}
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
              onClick={applyFilter}
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg"
            >
              {t.imageFilterApply}
            </button>
            <button
              onClick={resetFilter}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-fg-muted hover:bg-bg-elevated"
            >
              {t.imageFilterReset}
            </button>
          </div>

          {all === null ? (
            <p className="text-sm text-fg-subtle">{t.csvLoading}</p>
          ) : filtered.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-muted">{t.imageTemplatesEmpty}</p>
          ) : (
            <div className="max-h-[52vh] space-y-4 overflow-y-auto pr-1">
              {groups.map(([plat, items]) => (
                <div key={plat}>
                  <p className="mb-1.5 text-xs font-semibold text-fg-muted">{platformLabel(plat)}</p>
                  <div className="grid grid-cols-2 gap-2">
                    {items.map((tpl) => {
                      const active = selected?.id === tpl.id;
                      return (
                        <button
                          key={tpl.id}
                          onClick={() => setSelected(tpl)}
                          className={`text-left rounded-lg border p-2.5 transition ${
                            active ? "border-accent bg-accent/10" : "border-border hover:bg-bg-elevated"
                          }`}
                        >
                          <div className="flex items-center gap-1 text-sm font-medium">
                            {active ? <Check size={13} className="text-accent" /> : null}
                            {tpl.label}
                          </div>
                          <p className="mt-0.5 text-[10px] text-fg-subtle">
                            {styleLabel(tpl.style)} · {tpl.aspect_ratio}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* RIGHT: upload + inline on-demand cutout + generate */}
        <div className="space-y-3">
          <label
            className={`inline-flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2.5 text-sm cursor-pointer transition ${
              upload
                ? "border-border text-fg-muted hover:bg-bg-elevated"
                : "border-accent/40 bg-accent/10 text-accent hover:bg-accent/15"
            }`}
          >
            {uploading ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
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

          {upload ? (
            <ImageUploadWorkspace
              fileId={upload.file_id}
              cutoutArtifactId={cutoutArtifactId}
              choice={choice}
              onChoice={setChoice}
              onRemoveBg={removeBackground}
              bgBusy={bgBusy}
              warning={bgWarning}
            />
          ) : (
            <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-border text-xs text-fg-subtle">
              {t.imageUploadHint}
            </div>
          )}

          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={2}
            placeholder={t.imagePromptPlaceholder}
            className="w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 text-sm placeholder:text-fg-subtle focus:border-accent focus:outline-none"
          />

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          <button
            onClick={confirmGenerate}
            disabled={busy || !selected || !upload}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : null}
            {t.imageConfirmGenerate}
          </button>
        </div>
      </div>
    </Modal>
  );
}
