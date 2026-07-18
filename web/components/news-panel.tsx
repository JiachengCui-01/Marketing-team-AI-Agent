"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Settings, RefreshCw, Loader2, Newspaper, AlertTriangle, ShieldCheck } from "lucide-react";
import {
  getNewsConfig,
  getNewsSummary,
  saveNewsConfig,
  refreshNews,
  cancelNews,
  type NewsConfig,
  type NewsSummary,
  type NewsSource,
} from "@/lib/api";
import { localizeError, useI18n } from "@/lib/i18n";
import { Modal } from "@/components/modal";
import { Skeleton } from "@/components/ui/skeleton";
import { LoadingCard, Spinner } from "@/components/ui/spinner";
import { CitationCapsules, CitationMarkdown, faviconUrl, type CitationSource } from "@/components/citation-markdown";

export function NewsPanel({ onBack }: { onBack: () => void }) {
  const { locale, t } = useI18n();
  const [config, setConfig] = useState<NewsConfig | null>(null);
  const [summary, setSummary] = useState<NewsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cancelled = !!config && config.enabled === false && config.cancelled_at != null;
  const refreshingEmpty = refreshing && !summary;
  const refreshingExisting = refreshing && !!summary;

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

          <div className="mb-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <div className="min-w-0 truncate text-xs text-fg-subtle">
              {config
                ? `${config.industry} · ${config.summary_time} (${config.timezone})`
                : t.newsNoConfig}
            </div>
            <div className="min-h-[28px] min-w-[120px] justify-self-center">
              {refreshingExisting ? (
                <Spinner size={14} label={t.newsCollecting} variant="news" className="text-xs" />
              ) : null}
            </div>
            <button
              onClick={handleRefresh}
              disabled={refreshing || !config || cancelled}
              className="btn-accent justify-self-end px-3 py-1.5 text-xs"
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
              <CitationMarkdown
                content={summary.summary}
                stripSourceSections
                stripCredibilitySections={!!summary.sources?.length}
              />
              <SourceCredibility summary={summary} />
              <p className="mt-6 text-[11px] text-fg-subtle">
                {t.newsGeneratedAt}: {new Date(summary.generated_at * 1000).toLocaleString()}
              </p>
            </>
          ) : refreshingEmpty ? (
            <div className="flex min-h-[360px] items-center justify-center">
              <LoadingCard label={t.newsCollecting} variant="news" />
            </div>
          ) : (
            <div className="py-16 text-center">
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

function SourceCredibility({ summary }: { summary: NewsSummary }) {
  const { locale } = useI18n();
  const sources = summary.sources ?? [];
  if (sources.length === 0) return null;

  const weakCount = summary.weak_source_count ?? sources.filter((s) => s.is_weak_signal).length;
  const strongCount = summary.strong_source_count ?? sources.filter((s) => s.tier <= 2).length;
  const title = locale === "zh" ? "来源可信度" : "Source credibility";
  const scoreLabel = locale === "zh" ? "综合评分" : "Score";
  const note =
    locale === "zh"
      ? weakCount > 0 && strongCount === 0
        ? "当前主要来自自媒体或社区讨论，仅适合作为弱信号参考，不宜作为事实依据。"
        : weakCount > 0
          ? "已优先采用高等级来源；自媒体和社区讨论仅作为弱信号参考。"
          : "本摘要优先基于高等级来源。"
      : weakCount > 0 && strongCount === 0
        ? "Sources are mainly self-media or community discussion, so treat them as weak signals rather than standalone factual evidence."
        : weakCount > 0
          ? "Higher-tier sources are prioritized; self-media and community discussion are included only as weak signals."
          : "This summary prioritizes higher-tier sources.";

  return (
    <section className="mt-5 border-t border-border pt-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-fg">
          <ShieldCheck size={15} className="text-feature-news" />
          <span>{title}</span>
        </div>
        <span className="text-xs text-fg-subtle">
          {scoreLabel}: {summary.source_score ?? 0}
        </span>
      </div>
      <p className="mb-3 text-xs leading-relaxed text-fg-muted">{note}</p>
      <ol className="space-y-2">
        {sources.map((source, index) => (
          <SourceRow key={source.url} source={source} index={index + 1} />
        ))}
      </ol>
    </section>
  );
}

function SourceRow({ source, index }: { source: NewsSource; index: number }) {
  const citationSource = toCitationSource(source);
  return (
    <li className="text-sm leading-relaxed text-fg">
      <span className="mr-1 text-fg-muted">{index}.</span>
      <span>
        {source.tier_label} ({source.score})
        {source.is_weak_signal ? " · weak signal" : ""}
      </span>
      <CitationCapsules sources={[citationSource]} />
    </li>
  );
}

function toCitationSource(source: NewsSource): CitationSource {
  return {
    url: source.url,
    domain: source.domain,
    tier: source.tier,
    score: source.score,
    reason: source.reason,
    displayText: source.display_text || source.title || source.domain,
    faviconUrl: faviconUrl(source.domain),
  };
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
