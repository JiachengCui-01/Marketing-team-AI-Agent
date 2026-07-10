"use client";

import { Loader2, Scissors, Check } from "lucide-react";
import { uploadPreviewUrl, artifactPreviewUrl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/**
 * Uploaded-image workspace shared by the panel and the templates modal.
 *
 * Shows the original immediately (token-authed preview URL). Background removal is
 * on demand: until the user clicks "remove background" only the original is shown;
 * once a cutout exists, the original/cutout pair becomes a selectable toggle.
 */
export function ImageUploadWorkspace({
  fileId,
  cutoutArtifactId,
  choice,
  onChoice,
  onRemoveBg,
  bgBusy,
  warning,
}: {
  fileId: string;
  cutoutArtifactId: string | null;
  choice: "original" | "cutout";
  onChoice: (v: "original" | "cutout") => void;
  onRemoveBg: () => void;
  bgBusy: boolean;
  warning?: string | null;
}) {
  const { t } = useI18n();
  const hasCutout = !!cutoutArtifactId;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3">
        {/* original */}
        <button
          type="button"
          onClick={() => onChoice("original")}
          className={`rounded-lg border p-2 transition ${
            !hasCutout || choice === "original"
              ? "border-accent bg-accent/10"
              : "border-border hover:bg-bg-elevated"
          }`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={uploadPreviewUrl(fileId)}
            alt="original"
            decoding="async"
            className="mx-auto h-40 w-full rounded object-contain"
          />
          <span className="mt-1 flex items-center justify-center gap-1 text-xs">
            {hasCutout && choice === "original" ? <Check size={12} className="text-accent" /> : null}
            {t.imageOriginalLabel}
          </span>
        </button>

        {/* cutout slot */}
        {hasCutout ? (
          <button
            type="button"
            onClick={() => onChoice("cutout")}
            className={`rounded-lg border p-2 transition ${
              choice === "cutout" ? "border-accent bg-accent/10" : "border-border hover:bg-bg-elevated"
            }`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={artifactPreviewUrl(cutoutArtifactId!)}
              alt="cutout"
              decoding="async"
              className="mx-auto h-40 w-full rounded object-contain"
              style={{
                backgroundImage: "repeating-conic-gradient(#e5e7eb 0% 25%, transparent 0% 50%)",
                backgroundSize: "16px 16px",
              }}
            />
            <span className="mt-1 flex items-center justify-center gap-1 text-xs">
              {choice === "cutout" ? <Check size={12} className="text-accent" /> : null}
              {t.imageCutoutLabel}
            </span>
          </button>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-2 text-center">
            <button
              type="button"
              onClick={onRemoveBg}
              disabled={bgBusy}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-fg hover:opacity-90 transition disabled:opacity-40"
            >
              {bgBusy ? <Loader2 size={14} className="animate-spin" /> : <Scissors size={14} />}
              {bgBusy ? t.imageRemovingBg : t.imageRemoveBg}
            </button>
            <span className="text-[11px] text-fg-subtle leading-snug">{t.imageRemoveBgHint}</span>
          </div>
        )}
      </div>
      {warning ? <p className="text-[11px] text-danger">{warning}</p> : null}
    </div>
  );
}
