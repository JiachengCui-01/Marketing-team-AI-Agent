"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Upload, Check } from "lucide-react";
import {
  listImageTemplates,
  processImage,
  generateImage,
  uploadFile,
  type ImageTemplate,
  type ImageProcessResult,
  type ImageGeneration,
  type ImageSource,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { SourceChoice } from "@/components/image-source-choice";

const PLATFORMS = ["all", "taobao", "xiaohongshu", "amazon", "instagram", "generic"] as const;

/**
 * Templates modal: LEFT = template gallery + platform/style filter; RIGHT = image
 * upload with the SAME cutout flow inline (SourceChoice) + a prompt. Selecting a
 * template and confirming generates using that template + the uploaded image.
 */
export function ImageTemplatesModal({
  activeStyle,
  onClose,
  onGenerated,
}: {
  activeStyle: string | null;
  onClose: () => void;
  onGenerated: (gen: ImageGeneration) => void;
}) {
  const { locale, t } = useI18n();
  const [platform, setPlatform] = useState<string>("all");
  const [style, setStyle] = useState<string>("all");
  const [templates, setTemplates] = useState<ImageTemplate[] | null>(null);
  const [selected, setSelected] = useState<ImageTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);

  // right pane
  const [prompt, setPrompt] = useState("");
  const [processing, setProcessing] = useState(false);
  const [processResult, setProcessResult] = useState<ImageProcessResult | null>(null);
  const [choice, setChoice] = useState<"original" | "cutout">("original");
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    (p: string, s: string) => {
      setTemplates(null);
      listImageTemplates({ platform: p, style: s })
        .then(setTemplates)
        .catch((e) => setError(localizeError(e, locale)));
    },
    [locale],
  );

  useEffect(() => {
    load("all", "all");
  }, [load]);

  async function handleUpload(file: File) {
    setError(null);
    setProcessResult(null);
    setProcessing(true);
    try {
      const resp = await uploadFile(file);
      const result = await processImage(resp.file_id);
      setProcessResult(result);
      setChoice(result.cutout ? "cutout" : "original");
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setProcessing(false);
    }
  }

  async function confirmGenerate() {
    if (!selected || !processResult) return;
    const source: ImageSource =
      choice === "cutout" && processResult.cutout
        ? { type: "cutout", id: processResult.cutout.artifact_id }
        : { type: "upload", id: processResult.original.file_id };
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
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p === "all" ? t.imageAll : p}
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
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p === "all" ? t.imageAll : p}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={() => load(platform, style)}
              className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg"
            >
              {t.imageFilterApply}
            </button>
            <button
              onClick={() => {
                setPlatform("all");
                setStyle("all");
                load("all", "all");
              }}
              className="rounded-lg border border-border px-3 py-1.5 text-sm text-fg-muted hover:bg-bg-elevated"
            >
              {t.imageFilterReset}
            </button>
          </div>

          {templates === null ? (
            <p className="text-sm text-fg-subtle">{t.csvLoading}</p>
          ) : templates.length === 0 ? (
            <p className="py-8 text-center text-sm text-fg-muted">{t.imageTemplatesEmpty}</p>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {templates.map((tpl) => {
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
                      {tpl.platform} · {tpl.aspect_ratio}
                    </p>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* RIGHT: upload + inline process + generate */}
        <div className="space-y-3">
          <label className="inline-flex items-center gap-2 text-xs text-fg-muted hover:text-fg cursor-pointer">
            {processing ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            <span>{t.imageUploadHint}</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={processing}
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) handleUpload(e.target.files[0]);
                e.target.value = "";
              }}
            />
          </label>

          {processResult ? (
            <SourceChoice result={processResult} value={choice} onChange={setChoice} />
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
            disabled={busy || !selected || !processResult}
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
