"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, Trash2, Loader2, FileText } from "lucide-react";
import {
  createKbDocument,
  deleteKbDocument,
  listKbDocuments,
  uploadFile,
  type KbDocument,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

/** Personal knowledge-base management (upload + list + delete). No search here — the
 * AI workspace answers from the KB directly. Scoped to the current user's own account. */
export function KbManager() {
  const { locale } = useI18n();
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const zh = locale === "zh";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocs(await listKbDocuments());
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  const onUpload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);
      try {
        const up = await uploadFile(file);
        await createKbDocument({ upload_id: up.file_id, title: up.original_name });
        await load();
      } catch (e) {
        setError(localizeError(e, locale));
      } finally {
        setUploading(false);
      }
    },
    [load, locale],
  );

  const onDelete = useCallback(
    async (id: string) => {
      try {
        await deleteKbDocument(id);
        setDocs((prev) => prev.filter((d) => d.id !== id));
      } catch (e) {
        setError(localizeError(e, locale));
      }
    },
    [locale],
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-fg-muted max-w-md">
          {zh
            ? "这里维护的是你个人账号的知识库，仅你自己的 AI 工作台会调用，不影响企业共享知识库。"
            : "Your personal knowledge base — only your own AI workspace uses it. It does not affect the shared enterprise KB."}
        </p>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="btn-accent h-8 px-3 text-sm shrink-0 disabled:opacity-50"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          {zh ? "上传文档" : "Upload"}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,.csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
            e.target.value = "";
          }}
        />
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="max-h-[52vh] overflow-y-auto space-y-2">
        {loading ? (
          <div className="flex justify-center py-8 text-fg-muted">
            <Loader2 size={18} className="animate-spin" />
          </div>
        ) : docs.length === 0 ? (
          <p className="text-sm text-fg-subtle text-center py-8">
            {zh
              ? "还没有文档。上传 PDF / Word / 文本后，AI 工作台即可基于这些内容回答。"
              : "No documents yet. Upload PDF / Word / text and the AI workspace can answer from them."}
          </p>
        ) : (
          docs.map((d) => (
            <div
              key={d.id}
              className="border border-border rounded-xl p-3 bg-bg-subtle flex items-center gap-3"
            >
              <FileText size={16} className="text-fg-muted shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-sm text-fg truncate">{d.title}</div>
                <div className="text-[11px] text-fg-subtle">
                  {d.text_length ? (zh ? `${d.text_length} 字` : `${d.text_length} chars`) : ""}
                </div>
              </div>
              <button
                onClick={() => onDelete(d.id)}
                className="btn-ghost w-8 h-8 text-fg-subtle"
                aria-label={zh ? "删除" : "Delete"}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
