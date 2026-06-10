"use client";

import { Paperclip, X, FileSpreadsheet, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { uploadCsv, type UploadResponse } from "@/lib/api";

export function FileUploader({
  attached,
  onAttached,
  onCleared,
}: {
  attached: UploadResponse | null;
  onAttached: (f: UploadResponse) => void;
  onCleared: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setError(null);
    setBusy(true);
    try {
      const resp = await uploadCsv(file);
      onAttached(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  if (attached) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border bg-bg-elevated px-3 py-2 text-xs">
        <FileSpreadsheet size={14} className="text-accent shrink-0" />
        <span className="truncate flex-1" title={attached.original_name}>
          {attached.original_name}
        </span>
        <span className="text-fg-subtle">
          {(attached.size / 1024).toFixed(1)} KB
        </span>
        <button
          onClick={onCleared}
          className="ml-1 text-fg-subtle hover:text-danger transition"
          aria-label="Remove file"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <>
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
        <span>{busy ? "Uploading…" : "Attach CSV"}</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
          e.target.value = "";
        }}
      />
      {error && <span className="text-xs text-danger">{error}</span>}
    </>
  );
}
