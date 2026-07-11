"use client";

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, Settings, RefreshCw, Loader2, Newspaper, AlertTriangle } from "lucide-react";
import {
  getNewsConfig,
  getNewsSummary,
  saveNewsConfig,
  refreshNews,
  cancelNews,
  type NewsConfig,
  type NewsSummary,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { Skeleton } from "@/components/ui/skeleton";

export function NewsPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [config, setConfig] = useState<NewsConfig | null>(null);
  const [summary, setSummary] = useState<NewsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cancelled = !!config && config.enabled === false && config.cancelled_at != null;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, sum] = await Promise.all([getNewsConfig(), getNewsSummary()]);
      setConfig(cfg);
      setSummary(sum);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setLoading(false);
    }
  }, [locale]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      const sum = await refreshNews(locale);
      setSummary(sum);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 panel-card">
      <header className="col-header">
        <button onClick={onBack} className="btn-ghost px-2.5 py-1.5 text-sm">
          <ArrowLeft size={15} />
          <span>{t.back}</span>
        </button>
        <div className="flex items-center gap-2 mx-auto text-sm font-medium">
          <Newspaper size={15} className="text-feature-news" />
          <span>{t.industryNews}</span>
        </div>
        <button
          onClick={() => setSettingsOpen(true)}
          className="btn-ghost px-2.5 py-1.5 text-sm"
          title={t.newsSettings}
        >
          <Settings size={15} />
          <span>{t.newsSettings}</span>
        </button>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 py-6">
          {cancelled ? (
            <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-warn/40 bg-warn/10 px-3.5 py-3 text-sm text-warn">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <p>{t.newsCancelledNotice}</p>
            </div>
          ) : null}

          <div className="mb-4 flex items-center justify-between">
            <div className="text-xs text-fg-subtle">
              {config
                ? `${config.industry} · ${config.summary_time} (${config.timezone})`
                : t.newsNoConfig}
            </div>
            <button
              onClick={handleRefresh}
              disabled={refreshing || !config || cancelled}
              className="btn-accent px-3 py-1.5 text-xs"
            >
              {refreshing ? <Loader2 size={13} className="animate-spin text-feature-news" /> : <RefreshCw size={13} />}
              <span>{refreshing ? t.newsRefreshing : t.newsRefreshNow}</span>
            </button>
          </div>

          {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

          {loading ? (
            <div className="space-y-2.5">
              <Skeleton variant="news" className="h-6 w-2/3" />
              <Skeleton variant="news" className="h-4 w-full" />
              <Skeleton variant="news" className="h-4 w-full" />
              <Skeleton variant="news" className="h-4 w-5/6" />
              <Skeleton variant="news" className="h-4 w-3/4" />
            </div>
          ) : !config ? (
            <div className="text-center py-16">
              <Newspaper size={28} className="mx-auto text-fg-subtle mb-3" />
              <p className="text-sm text-fg-muted">{t.newsSetupHint}</p>
              <button
                onClick={() => setSettingsOpen(true)}
                className="mt-4 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-fg"
              >
                {t.newsSettings}
              </button>
            </div>
          ) : summary ? (
            <>
              <div className="prose-chat">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary.summary}</ReactMarkdown>
              </div>
              <p className="mt-6 text-[11px] text-fg-subtle">
                {t.newsGeneratedAt}: {new Date(summary.generated_at * 1000).toLocaleString()}
              </p>
            </>
          ) : (
            <div className="text-center py-16">
              <p className="text-sm text-fg-muted">{t.newsEmpty}</p>
            </div>
          )}
        </div>
      </div>

      {settingsOpen ? (
        <NewsSettingsDialog
          config={config}
          onClose={() => setSettingsOpen(false)}
          onSaved={(cfg) => {
            setConfig(cfg);
            setSettingsOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

function NewsSettingsDialog({
  config,
  onClose,
  onSaved,
}: {
  config: NewsConfig | null;
  onClose: () => void;
  onSaved: (cfg: NewsConfig) => void;
}) {
  const { locale, t } = useI18n();
  // A cancelled task keeps its row on the backend, but the settings form should read
  // as a blank slate (defaults) so it reflects "no active task".
  const isCancelled = !!config && config.enabled === false && config.cancelled_at != null;
  const canCancel = !!config && config.enabled !== false;
  const [industry, setIndustry] = useState(isCancelled ? "" : config?.industry ?? "");
  const [detailLevel, setDetailLevel] = useState<"brief" | "detailed">(
    isCancelled ? "brief" : config?.detail_level ?? "brief",
  );
  const [summaryTime, setSummaryTime] = useState(isCancelled ? "09:00" : config?.summary_time ?? "09:00");
  const [saving, setSaving] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCancelTask() {
    setCancelling(true);
    setError(null);
    try {
      const cfg = await cancelNews();
      setIndustry("");
      setDetailLevel("brief");
      setSummaryTime("09:00");
      onSaved(cfg);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setCancelling(false);
    }
  }

  async function handleSave() {
    if (!industry.trim()) {
      setError(t.newsIndustryRequired);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const cfg = await saveNewsConfig({
        industry: industry.trim(),
        detail_level: detailLevel,
        summary_time: summaryTime,
        timezone,
        language: locale,
      });
      onSaved(cfg);
    } catch (e) {
      setError(localizeError(e, locale));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={t.newsSettings} onClose={onClose}>
      <div className="space-y-4">
        <label className="block text-xs font-medium text-fg-muted">
          {t.newsIndustry}
          <input
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            placeholder={t.newsIndustryHint}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent"
          />
        </label>

        <label className="block text-xs font-medium text-fg-muted">
          {t.newsDetail}
          <select
            value={detailLevel}
            onChange={(e) => setDetailLevel(e.target.value as "brief" | "detailed")}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          >
            <option value="brief">{t.newsDetailBrief}</option>
            <option value="detailed">{t.newsDetailDetailed}</option>
          </select>
        </label>

        <label className="block text-xs font-medium text-fg-muted">
          {t.newsTime}
          <input
            type="time"
            value={summaryTime}
            onChange={(e) => setSummaryTime(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
          />
          <span className="mt-1 block text-[11px] text-fg-subtle">{t.newsTimeHint}</span>
        </label>

        {error ? <p className="text-[11px] text-danger">{error}</p> : null}

        <div className="flex items-center gap-2 pt-1">
          {canCancel ? (
            <button
              type="button"
              onClick={handleCancelTask}
              disabled={cancelling || saving}
              className="inline-flex items-center gap-1.5 rounded-lg border border-danger/40 px-4 py-2 text-sm text-danger hover:bg-danger/10 disabled:opacity-40"
            >
              {cancelling ? <Loader2 size={14} className="animate-spin text-danger" /> : null}
              {t.newsCancelTask}
            </button>
          ) : null}
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border px-4 py-2 text-sm text-fg-muted hover:bg-bg-subtle"
            >
              {t.cancel}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || cancelling}
              className="btn-accent px-4 py-2 text-sm"
            >
              {saving ? <Loader2 size={14} className="animate-spin text-feature-news" /> : null}
              {saving ? t.saving : t.save}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
