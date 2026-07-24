"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, BookOpen, Upload, Trash2, Search, Loader2, FileText } from "lucide-react";
import {
  createKbDocument,
  deleteKbDocument,
  listKbDocuments,
  searchKb,
  uploadFile,
  type KbDocument,
  type KbSearchResult,
  type KbQueryRewrite,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";

export function KbPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<KbSearchResult[] | null>(null);
  const [rewrite, setRewrite] = useState<KbQueryRewrite | null>(null);
  const [method, setMethod] = useState<string>("");
  const [searching, setSearching] = useState(false);
  const historyRef = useRef<{ role: string; text: string }[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);

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

  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setError(null);
    try {
      const resp = await searchKb(q, historyRef.current);
      setResults(resp.results);
      setRewrite(resp.rewrite);
      setMethod(resp.method);
      // Keep a short rolling history so follow-up queries resolve coreference.
      historyRef.current = [...historyRef.current, { role: "user", text: q }].slice(-6);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setSearching(false);
    }
  }, [query, locale]);

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 ml-1">
          <BookOpen size={15} className="text-accent" />
          <span className="text-sm font-medium">{t.knowledgeBase}</span>
        </div>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="btn-accent h-8 px-3 text-sm ml-auto disabled:opacity-50"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          上传文档
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
      </header>

      <div className="p-3 border-b border-border flex items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") runSearch();
          }}
          placeholder="在知识库中检索，例如：报销制度"
          className="flex-1 h-9 px-3 rounded-lg bg-bg-elevated border border-border text-sm outline-none focus:border-accent"
        />
        <button onClick={runSearch} disabled={searching} className="btn-ghost h-9 w-9 border border-border">
          {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {error ? <p className="text-sm text-danger px-1">{error}</p> : null}

        {results !== null ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-fg-subtle">检索结果（{results.length}）</span>
              <button
                onClick={() => {
                  setResults(null);
                  setRewrite(null);
                }}
                className="text-xs text-accent"
              >
                返回文档列表
              </button>
            </div>
            {rewrite ? (
              <div className="text-[11px] text-fg-subtle border border-border rounded-lg px-2.5 py-2 bg-bg-elevated space-y-0.5">
                {rewrite.resolved && rewrite.resolved !== query ? (
                  <div>改写：{rewrite.resolved}</div>
                ) : null}
                {rewrite.expansions.length ? <div>同义扩展：{rewrite.expansions.join("、")}</div> : null}
                <div>
                  意图：{rewrite.intent} · 检索方式：{method}
                </div>
              </div>
            ) : null}
            {results.length === 0 ? (
              <p className="text-sm text-fg-subtle text-center py-6">没有匹配的内容</p>
            ) : (
              results.map((r, i) => (
                <div key={i} className="border border-border rounded-xl p-3 bg-bg-subtle">
                  <div className="text-[12px] text-accent mb-1">{r.title}</div>
                  <div className="text-[13px] text-fg-muted break-words">{r.text}</div>
                </div>
              ))
            )}
          </div>
        ) : loading ? (
          <div className="flex justify-center py-10 text-fg-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : docs.length === 0 ? (
          <p className="text-sm text-fg-subtle text-center py-10">
            还没有文档。上传 PDF / Word / 文本后，即可在 Copilot 里问答。
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
                  {d.text_length ? `${d.text_length} 字` : ""}
                </div>
              </div>
              <button
                onClick={() => onDelete(d.id)}
                className="btn-ghost w-8 h-8 text-fg-subtle"
                aria-label="删除"
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
