"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Image as ImageIcon,
  Wand2,
  Loader2,
  History,
  LayoutTemplate,
  Upload,
  Trash2,
  Check,
  X,
} from "lucide-react";
import {
  getImageSkills,
  processImage,
  generateImage,
  listImageHistory,
  deleteImageGeneration,
  uploadFile,
  uploadPreviewUrl,
  artifactPreviewUrl,
  type ImageSkill,
  type ImageProcessResult,
  type ImageGeneration,
  type ImageHistoryItem,
  type ImageSource,
  type UploadResponse,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { ImageEditView } from "@/components/image-edit-view";
import { ImageTemplatesModal } from "@/components/image-templates-modal";
import { SourceChoice } from "@/components/image-source-choice";
import type { PreviewItem } from "@/components/preview-panel";

export function MarketingImagePanel({
  onBack,
  onPreview,
}: {
  onBack: () => void;
  onPreview: (item: PreviewItem) => void;
}) {
  const { locale, t } = useI18n();
  const [skills, setSkills] = useState<ImageSkill[]>([]);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const [activeStyle, setActiveStyle] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [upload, setUpload] = useState<UploadResponse | null>(null);
  const [processResult, setProcessResult] = useState<ImageProcessResult | null>(null);
  const [pendingSource, setPendingSource] = useState<ImageSource | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ImageGeneration | null>(null);

  useEffect(() => {
    getImageSkills()
      .then(setSkills)
      .catch((e) => setError(localizeError(e, locale)));
  }, [locale]);

  const showPreview = useCallback(
    (gen: ImageGeneration) => {
      if (gen.artifact_id && gen.mime && gen.filename) {
        onPreview({
          source: "artifact",
          id: gen.artifact_id,
          filename: gen.filename,
          mime: gen.mime,
        });
      }
    },
    [onPreview],
  );

  async function handleUpload(file: File) {
    setError(null);
    setPendingSource(null);
    setProcessResult(null);
    setProcessing(true);
    try {
      const resp = await uploadFile(file);
      setUpload(resp);
      const result = await processImage(resp.file_id);
      setProcessResult(result);
      setConfirmOpen(true);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setProcessing(false);
    }
  }

  async function runGenerate(source: ImageSource) {
    if (!prompt.trim()) {
      setError(t.imagePromptPlaceholder);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const gen = await generateImage({
        prompt: prompt.trim(),
        style_key: activeStyle,
        source,
      });
      if (!gen.ok) {
        setError(gen.message || t.imageGenFailed);
        return;
      }
      showPreview(gen);
      setEditing(gen);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  function handleGenerateClick() {
    if (pendingSource) {
      void runGenerate(pendingSource);
    } else if (processResult) {
      setConfirmOpen(true);
    } else {
      setError(t.imageUploadHint);
    }
  }

  if (editing) {
    return (
      <ImageEditView
        generation={editing}
        onReplace={(g) => {
          setEditing(g);
          showPreview(g);
        }}
        onExit={() => setEditing(null)}
        onBack={onBack}
      />
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <header className="border-b border-border bg-bg-elevated/60 backdrop-blur flex items-center gap-2 px-4 py-2.5">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm text-fg-muted hover:text-fg hover:bg-bg-elevated transition"
        >
          <ArrowLeft size={15} />
          <span>{t.imageBackToPanel}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <ImageIcon size={15} className="text-accent" />
          <span>{t.marketingImage}</span>
        </div>
        <div className="w-16" />
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
          {/* boards */}
          <div className="flex gap-2">
            <button
              onClick={() => setHistoryOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border text-sm text-fg-muted hover:text-fg hover:bg-bg-elevated transition"
            >
              <History size={15} className="text-accent" />
              {t.imageHistory}
            </button>
            <button
              onClick={() => setTemplatesOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border text-sm text-fg-muted hover:text-fg hover:bg-bg-elevated transition"
            >
              <LayoutTemplate size={15} className="text-accent" />
              {t.imageTemplates}
            </button>
          </div>

          {/* skills selector */}
          <div className="rounded-xl border border-border">
            <button
              onClick={() => setSkillsOpen((v) => !v)}
              className="w-full flex items-center justify-between px-3.5 py-2.5 text-sm"
            >
              <span className="flex items-center gap-2 font-medium">
                <Wand2 size={15} className="text-accent" />
                {t.imageStyles}
              </span>
              <span className="text-xs text-fg-subtle">
                {activeStyle
                  ? skills.find((s) => s.id === activeStyle)?.name ?? activeStyle
                  : t.imageStylesHint}
              </span>
            </button>
            {skillsOpen ? (
              <div className="grid gap-2 px-3.5 pb-3.5 sm:grid-cols-2">
                {skills.map((s) => {
                  const active = activeStyle === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => setActiveStyle(active ? null : s.id)}
                      className={`text-left rounded-lg border px-3 py-2 transition ${
                        active
                          ? "border-accent bg-accent/10"
                          : "border-border hover:bg-bg-elevated"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 text-sm font-medium">
                        {active ? <Check size={13} className="text-accent" /> : null}
                        {s.name}
                        <span className="ml-auto text-[10px] text-fg-subtle">{s.aspect_ratio}</span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-fg-subtle leading-snug">{s.description}</p>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          {/* uploaded thumbnail */}
          {upload ? (
            <div className="flex items-center gap-3 rounded-lg border border-border bg-bg-elevated px-3 py-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={uploadPreviewUrl(upload.file_id)}
                alt={upload.original_name}
                className="h-12 w-12 rounded object-cover"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{upload.original_name}</p>
                <p className="text-[11px] text-fg-subtle">
                  {processing
                    ? t.imageProcessing
                    : processResult?.classification === "object"
                      ? t.imageClassObject
                      : processResult
                        ? t.imageClassScreenshot
                        : ""}
                </p>
              </div>
              {processResult ? (
                <button
                  onClick={() => setConfirmOpen(true)}
                  className="text-xs text-accent hover:underline"
                >
                  {t.imageConfirmTitle}
                </button>
              ) : null}
              <button
                onClick={() => {
                  setUpload(null);
                  setProcessResult(null);
                  setPendingSource(null);
                }}
                className="text-fg-subtle hover:text-danger"
                aria-label={t.imageDelete}
              >
                <X size={15} />
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {/* bottom input bar */}
      <div className="border-t border-border bg-bg-elevated/60 backdrop-blur">
        <div className="max-w-3xl mx-auto px-4 py-3 space-y-2">
          <ImageUploadButton onFile={handleUpload} busy={processing} />
          <div className="flex items-end gap-2 rounded-xl border border-border bg-bg-elevated focus-within:border-accent transition shadow-sm">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={1}
              placeholder={t.imagePromptPlaceholder}
              disabled={busy}
              className="flex-1 resize-none bg-transparent px-4 py-3 text-sm placeholder:text-fg-subtle focus:outline-none disabled:opacity-50 max-h-48"
              style={{ minHeight: 48 }}
            />
            <button
              onClick={handleGenerateClick}
              disabled={busy || processing}
              className="m-1.5 inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 h-9 text-accent-fg text-sm hover:opacity-90 transition disabled:opacity-40"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Wand2 size={15} />}
              <span>{busy ? t.imageGenerating : t.imageGenerate}</span>
            </button>
          </div>
        </div>
      </div>

      {confirmOpen && processResult ? (
        <ConfirmProcessModal
          result={processResult}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={(source) => {
            setPendingSource(source);
            setConfirmOpen(false);
            void runGenerate(source);
          }}
        />
      ) : null}

      {historyOpen ? (
        <HistoryModal
          onClose={() => setHistoryOpen(false)}
          onOpen={(gen) => {
            setHistoryOpen(false);
            setEditing(gen);
            showPreview(gen);
          }}
        />
      ) : null}

      {templatesOpen ? (
        <ImageTemplatesModal
          activeStyle={activeStyle}
          onClose={() => setTemplatesOpen(false)}
          onGenerated={(gen) => {
            setTemplatesOpen(false);
            showPreview(gen);
            setEditing(gen);
          }}
        />
      ) : null}
    </div>
  );
}

function ImageUploadButton({ onFile, busy }: { onFile: (f: File) => void; busy: boolean }) {
  const { t } = useI18n();
  return (
    <label className="inline-flex items-center gap-2 text-xs text-fg-muted hover:text-fg transition cursor-pointer w-fit">
      {busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
      <span>{t.imageUploadHint}</span>
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        disabled={busy}
        onChange={(e) => {
          if (e.target.files && e.target.files[0]) onFile(e.target.files[0]);
          e.target.value = "";
        }}
      />
    </label>
  );
}

function ConfirmProcessModal({
  result,
  onCancel,
  onConfirm,
}: {
  result: ImageProcessResult;
  onCancel: () => void;
  onConfirm: (source: ImageSource) => void;
}) {
  const { t } = useI18n();
  const [choice, setChoice] = useState<"original" | "cutout">(result.cutout ? "cutout" : "original");

  return (
    <Modal title={t.imageConfirmTitle} onClose={onCancel} wide>
      <div className="space-y-4">
        <SourceChoice result={result} value={choice} onChange={setChoice} />
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            disabled
            title={t.imageComingSoon}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-fg-subtle opacity-60 cursor-not-allowed"
          >
            {t.imageManualRefine}
            <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-[10px]">{t.imageComingSoon}</span>
          </button>
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={onCancel}
              className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle"
            >
              {t.cancel}
            </button>
            <button
              type="button"
              onClick={() =>
                onConfirm(
                  choice === "cutout" && result.cutout
                    ? { type: "cutout", id: result.cutout.artifact_id }
                    : { type: "upload", id: result.original.file_id },
                )
              }
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg"
            >
              {t.imageConfirmGenerate}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function HistoryModal({
  onClose,
  onOpen,
}: {
  onClose: () => void;
  onOpen: (gen: ImageGeneration) => void;
}) {
  const { locale, t } = useI18n();
  const [items, setItems] = useState<ImageHistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listImageHistory()
      .then(setItems)
      .catch((e) => setError(localizeError(e, locale)));
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(id: string) {
    if (!window.confirm(t.imageDeleteConfirm)) return;
    try {
      await deleteImageGeneration(id);
      load();
    } catch (e) {
      setError(localizeError(e, locale));
    }
  }

  return (
    <Modal title={t.imageHistoryTitle} onClose={onClose} wide>
      {error ? <p className="mb-3 text-sm text-danger">{error}</p> : null}
      {items === null ? (
        <p className="text-sm text-fg-subtle">{t.csvLoading}</p>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-fg-muted">{t.imageHistoryEmpty}</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {items.map((it) => (
            <div key={it.id} className="group relative rounded-lg border border-border overflow-hidden">
              <button
                onClick={() =>
                  it.artifact_id &&
                  onOpen({
                    ok: true,
                    artifact_id: it.artifact_id,
                    history_id: it.id,
                    filename: `${it.style_key}.png`,
                    mime: "image/png",
                    prompt: it.prompt,
                    style_key: it.style_key,
                  })
                }
                className="block w-full"
                title={it.prompt}
              >
                {it.preview_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={it.artifact_id ? artifactPreviewUrl(it.artifact_id) : ""}
                    alt={it.prompt}
                    className="h-32 w-full object-cover"
                  />
                ) : (
                  <div className="h-32 w-full bg-bg-subtle" />
                )}
              </button>
              <button
                onClick={() => remove(it.id)}
                className="absolute right-1.5 top-1.5 rounded bg-black/40 p-1 text-white opacity-0 group-hover:opacity-100 transition"
                aria-label={t.imageDelete}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
