"use client";

import {
  Paperclip,
  X,
  FileSpreadsheet,
  FileText,
  FileImage,
  File as FileIcon,
  Loader2,
} from "lucide-react";
import { useRef, useState } from "react";
import { uploadFile, type UploadResponse } from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

const ACCEPT = ".csv,.pdf,.docx,image/png,image/jpeg";

function iconFor(mime: string) {
  if (mime.startsWith("image/")) return FileImage;
  if (mime === "application/pdf") return FileText;
  if (mime.includes("csv") || mime.includes("excel")) return FileSpreadsheet;
  return FileIcon;
}

export function FileUploader({
  attached,
  onAttach,
  onRemove,
  onPreview,
}: {
  attached: UploadResponse[];
  onAttach: (f: UploadResponse) => void;
  onRemove: (fileId: string) => void;
  onPreview?: (f: UploadResponse) => void;
}) {
  const { locale, t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(files: FileList) {
    setError(null);
    setBusy(true);
    try {
      for (const file of Array.from(files)) {
        const resp = await uploadFile(file);
        onAttach(resp);
      }
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="inline-flex items-center gap-2 text-xs text-fg-muted hover:text-fg transition disabled:opacity-50"
        >
          {busy ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Paperclip size={14} />
          )}
          <span>{busy ? t.uploading : t.attachFiles}</span>
        </button>
        <span className="text-[10px] text-fg-subtle">
          {t.fileTypes}
        </span>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            if (e.target.files && e.target.files.length) handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {attached.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {attached.map((f) => {
            const Icon = iconFor(f.mime);
            return (
              <div
                key={f.file_id}
                className="flex items-center gap-2 rounded-lg border border-border bg-bg-elevated px-2.5 py-1.5 text-xs"
              >
                <Icon size={13} className="text-accent shrink-0" />
                <button
                  onClick={() => onPreview?.(f)}
                  className="truncate max-w-[18ch] hover:underline"
                  title={f.original_name}
                >
                  {f.original_name}
                </button>
                <span className="text-fg-subtle">
                  {(f.size / 1024).toFixed(0)} KB
                </span>
                <button
                  onClick={() => onRemove(f.file_id)}
                  className="ml-0.5 text-fg-subtle hover:text-danger transition"
                  aria-label={t.removeFile}
                >
                  <X size={13} />
                </button>
              </div>
            );
          })}
        </div>
      ) : null}

      {error && <span className="text-xs text-danger">{error}</span>}
    </div>
  );
}
