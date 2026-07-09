"use client";

import { API_BASE, type ImageProcessResult } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

function abs(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE}${url}`;
}

/** Original-vs-cutout picker shown in the confirm modal and inline in the templates modal. */
export function SourceChoice({
  result,
  value,
  onChange,
}: {
  result: ImageProcessResult;
  value: "original" | "cutout";
  onChange: (v: "original" | "cutout") => void;
}) {
  const { t } = useI18n();
  const hasCutout = !!result.cutout;
  return (
    <div>
      <p className="mb-2 text-xs text-fg-muted">
        {result.classification === "object" ? t.imageClassObject : t.imageClassScreenshot}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => onChange("original")}
          className={`rounded-lg border p-2 transition ${
            value === "original" ? "border-accent bg-accent/10" : "border-border hover:bg-bg-elevated"
          }`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={abs(result.original.preview_url)}
            alt="original"
            className="mx-auto h-40 w-full rounded object-contain"
          />
          <span className="mt-1 block text-center text-xs">{t.imageOriginalLabel}</span>
        </button>
        <button
          onClick={() => hasCutout && onChange("cutout")}
          disabled={!hasCutout}
          className={`rounded-lg border p-2 transition disabled:opacity-40 ${
            value === "cutout" ? "border-accent bg-accent/10" : "border-border hover:bg-bg-elevated"
          }`}
        >
          {hasCutout ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={abs(result.cutout!.preview_url)}
              alt="cutout"
              className="mx-auto h-40 w-full rounded object-contain"
            />
          ) : (
            <div className="flex h-40 items-center justify-center text-xs text-fg-subtle">
              {t.imageNoCutout}
            </div>
          )}
          <span className="mt-1 block text-center text-xs">{t.imageCutoutLabel}</span>
        </button>
      </div>
    </div>
  );
}
