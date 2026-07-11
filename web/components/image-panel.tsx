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
  ChevronDown,
  Check,
  X,
} from "lucide-react";
import {
  getImageSkills,
  cutoutImage,
  generateImage,
  listImageHistory,
  deleteImageGeneration,
  uploadFile,
  artifactPreviewUrl,
  type ImageSkill,
  type ImageGeneration,
  type ImageHistoryItem,
  type ImageSource,
  type UploadResponse,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { ImageEditView } from "@/components/image-edit-view";
import { ImageTemplatesModal } from "@/components/image-templates-modal";
import { ImageUploadWorkspace } from "@/components/image-source-choice";
import { LoadingCard } from "@/components/ui/spinner";
import { Skeleton } from "@/components/ui/skeleton";
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
  const [uploading, setUploading] = useState(false);
  const [cutoutArtifactId, setCutoutArtifactId] = useState<string | null>(null);
  const [choice, setChoice] = useState<"original" | "cutout">("original");
  const [bgBusy, setBgBusy] = useState(false);
  const [bgWarning, setBgWarning] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [busy, setBusy] = useState(false);
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
        onPreview({ source: "artifact", id: gen.artifact_id, filename: gen.filename, mime: gen.mime });
      }
    },
    [onPreview],
  );

  function resetUpload() {
    setUpload(null);
    setCutoutArtifactId(null);
    setChoice("original");
    setBgWarning(null);
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

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError(t.imagePromptPlaceholder);
      return;
    }
    const source: ImageSource = upload
      ? choice === "cutout" && cutoutArtifactId
        ? { type: "cutout", id: cutoutArtifactId }
        : { type: "upload", id: upload.file_id }
      : { type: "none" };
    setBusy(true);
    setError(null);
    try {
      const gen = await generateImage({ prompt: prompt.trim(), style_key: activeStyle, source });
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

  const activeSkill = skills.find((s) => s.id === activeStyle);

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <ImageIcon size={15} className="text-feature-image" />
          <span>{t.marketingImage}</span>
        </div>
        <div className="w-16" />
      </header>

      {/* workspace */}
      <div className="relative flex-1 overflow-y-auto">
        <div
          className={`mx-auto max-w-3xl px-4 ${
            upload ? "py-6 space-y-4" : "min-h-full flex flex-col items-center justify-center py-10 text-center"
          }`}
        >
          {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}

          {upload ? (
            <div className="rounded-xl border border-border p-3 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">{t.imageUploadedTitle}</p>
                <button
                  onClick={resetUpload}
                  className="inline-flex items-center gap-1 text-xs text-fg-subtle hover:text-danger"
                >
                  <X size={13} />
                  {t.imageRemoveUpload}
                </button>
              </div>
              <ImageUploadWorkspace
                fileId={upload.file_id}
                cutoutArtifactId={cutoutArtifactId}
                choice={choice}
                onChoice={setChoice}
                onRemoveBg={removeBackground}
                bgBusy={bgBusy}
                warning={bgWarning}
              />
            </div>
          ) : (
            <div className="flex flex-col items-center">
              <ImageHeroArt />
              <h1 className="mt-5 text-2xl font-semibold tracking-tight">{t.imageHeroTitle}</h1>
              <p className="mt-2 max-w-md text-sm text-fg-muted">{t.imageHeroBody}</p>
              <label className="btn-accent mt-5 cursor-pointer px-4 py-2.5 text-sm">
                {uploading ? <Loader2 size={16} className="animate-spin text-feature-analytics" /> : <Upload size={16} />}
                {t.imageUploadButton}
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
            </div>
          )}
        </div>
        {busy ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-bg/60 backdrop-blur-sm animate-fade-in">
            <LoadingCard label={t.imageGenerating} variant="image" />
          </div>
        ) : null}
      </div>

      {/* integrated skills + input + actions */}
      <div className="border-t border-border bg-bg-elevated/60 backdrop-blur">
        <div className="max-w-3xl mx-auto px-4 py-3">
          <div className="input-shell overflow-hidden">
            {/* skills — collapsible card attached to the top of the input */}
            <button
              onClick={() => setSkillsOpen((v) => !v)}
              className="w-full flex items-center justify-between px-3.5 py-2.5 text-sm border-b border-border hover:bg-bg-subtle/50 transition"
            >
              <span className="flex items-center gap-2 font-medium">
                <Wand2 size={15} className="text-accent" />
                {t.imageStyles}
              </span>
              <span className="flex items-center gap-1.5 text-xs text-fg-subtle">
                {activeSkill ? activeSkill.name : t.imageStylesHint}
                <ChevronDown
                  size={14}
                  className={`transition-transform ${skillsOpen ? "rotate-180" : ""}`}
                />
              </span>
            </button>
            {skillsOpen ? (
              <div className="grid gap-2 border-b border-border p-3 sm:grid-cols-2">
                {skills.map((s) => {
                  const active = activeStyle === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => {
                        setActiveStyle(active ? null : s.id);
                        setSkillsOpen(false);
                      }}
                      className={`text-left rounded-lg border px-3 py-2 hover-lift ${
                        active ? "border-accent bg-accent/10 ring-1 ring-accent" : "border-border hover:bg-bg-elevated"
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

            {/* action row: upload / history / templates (equal width) */}
            <div className="grid grid-cols-3 gap-2 border-b border-border p-2">
              <label
                className={`inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm cursor-pointer transition ${
                  upload
                    ? "border-border text-fg-muted hover:bg-bg-elevated"
                    : "border-accent/40 bg-accent/10 text-accent hover:bg-accent/15"
                }`}
              >
                {uploading ? <Loader2 size={15} className="animate-spin text-feature-analytics" /> : <Upload size={15} />}
                <span className="truncate">{t.imageUploadButton}</span>
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
              <button
                onClick={() => setHistoryOpen(true)}
                className="btn-ghost border border-border px-3 py-2 text-sm"
              >
                <History size={15} className="text-feature-content" />
                <span className="truncate">{t.imageHistory}</span>
              </button>
              <button
                onClick={() => setTemplatesOpen(true)}
                className="btn-ghost border border-border px-3 py-2 text-sm"
              >
                <LayoutTemplate size={15} className="text-feature-research" />
                <span className="truncate">{t.imageTemplates}</span>
              </button>
            </div>

            {/* prompt input — at the very bottom */}
            <div className="flex items-end gap-2 px-2 py-1.5">
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={1}
                placeholder={t.imagePromptPlaceholder}
                disabled={busy}
                className="flex-1 resize-none bg-transparent px-2 py-2.5 text-sm placeholder:text-fg-subtle focus:outline-none disabled:opacity-50 max-h-40"
                style={{ minHeight: 44 }}
              />
              <button
                onClick={handleGenerate}
                disabled={busy || uploading}
                className="btn-accent m-1 px-3.5 h-9 text-sm"
              >
                {busy ? <Loader2 size={15} className="animate-spin text-feature-image" /> : <Wand2 size={15} />}
                <span>{busy ? t.imageGenerating : t.imageGenerate}</span>
              </button>
            </div>
          </div>
        </div>
      </div>

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
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} variant="image" className="h-32 w-full rounded-xl" />
          ))}
        </div>
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
                {it.artifact_id ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={artifactPreviewUrl(it.artifact_id)}
                    alt={it.prompt}
                    loading="lazy"
                    decoding="async"
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

/** Decorative marketing-image illustration for the panel's centered empty state. */
function ImageHeroArt() {
  return (
    <div className="flex h-28 w-28 items-center justify-center rounded-2xl bg-accent/10 text-accent">
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="8" y="12" width="48" height="40" rx="5" className="fill-accent/10" />
        <circle cx="22" cy="25" r="4" className="fill-accent/30" stroke="none" />
        <path d="M12 46l13-14 9 9 7-6 11 11" />
        <path d="M50 8l1.6 3.6L55 13l-3.4 1.4L50 18l-1.6-3.6L45 13l3.4-1.4z" className="fill-accent" stroke="none" />
      </svg>
    </div>
  );
}
