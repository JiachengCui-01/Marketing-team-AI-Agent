"use client";

import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, Link2 } from "lucide-react";
import { cn } from "@/lib/cn";

export type CitationSource = {
  url: string;
  domain: string;
  tier: number;
  score: number;
  reason: string;
  displayText: string;
  faviconUrl: string;
};

type Segment =
  | { kind: "markdown"; text: string }
  | { kind: "citation"; body: string; sources: CitationSource[]; listPrefix?: string };

const MARKDOWN_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/gi;
const BARE_URL_RE = /https?:\/\/[^\s<>()\]]+/gi;
const LINK_OR_URL = String.raw`(?:\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s<>()\]]+)`;
const DATE_OR_STATUS = String.raw`(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|更新|updated?|更新版)`;
const TRAILING_LINK_RE = new RegExp(
  String.raw`(?:\s*(?:[-–—,;:，；、]?\s*)?${LINK_OR_URL}(?:\s*(?:[,;，；、]\s*)?${DATE_OR_STATUS})?[.)\]）]*)+$`,
  "i",
);

const RAW_SOURCE_SECTION_HEADINGS = new Set([
  "sources",
  "source",
  "references",
  "information sources",
  "information source",
  "信息来源",
  "来源",
]);
const CREDIBILITY_SECTION_HEADINGS = new Set(["source credibility", "来源可信度"]);

const OFFICIAL_DOMAINS = new Set([
  "sec.gov",
  "ftc.gov",
  "fda.gov",
  "federalreserve.gov",
  "gov.cn",
  "miit.gov.cn",
  "stats.gov.cn",
  "europa.eu",
  "who.int",
  "wto.org",
  "worldbank.org",
  "imf.org",
  "oecd.org",
  "un.org",
]);

const AUTHORITY_DOMAINS = new Set([
  "reuters.com",
  "apnews.com",
  "bloomberg.com",
  "wsj.com",
  "ft.com",
  "bbc.com",
  "theguardian.com",
  "technologyreview.com",
  "mckinsey.com",
  "gartner.com",
  "xinhuanet.com",
  "news.cn",
  "people.com.cn",
  "cctv.com",
  "cntv.cn",
  "caixin.com",
  "yicai.com",
  "cls.cn",
  "thepaper.cn",
  "jiemian.com",
  "ithome.com",
  "chinanews.com.cn",
  "ce.cn",
  "stcn.com",
  "36kr.com",
]);

const SELF_MEDIA_DOMAINS = new Set([
  "medium.com",
  "substack.com",
  "wordpress.com",
  "blogspot.com",
  "weebly.com",
  "ghost.io",
  "mp.weixin.qq.com",
  "weixin.qq.com",
]);

const COMMUNITY_DOMAINS = new Set([
  "reddit.com",
  "x.com",
  "twitter.com",
  "facebook.com",
  "linkedin.com",
  "instagram.com",
  "tiktok.com",
  "youtube.com",
  "youtu.be",
  "news.ycombinator.com",
  "producthunt.com",
  "quora.com",
  "zhihu.com",
  "tieba.baidu.com",
]);

export function CitationMarkdown({
  content,
  stripSourceSections = false,
  stripCredibilitySections = false,
}: {
  content: string;
  stripSourceSections?: boolean;
  stripCredibilitySections?: boolean;
}) {
  const normalizedContent = useMemo(
    () => stripMarkdownSections(content, { stripSourceSections, stripCredibilitySections }),
    [content, stripCredibilitySections, stripSourceSections],
  );
  const segments = useMemo(() => splitCitationSegments(normalizedContent), [normalizedContent]);

  return (
    <div className="prose-chat">
      {segments.map((segment, index) =>
        segment.kind === "markdown" ? (
          <ReactMarkdown key={index} remarkPlugins={[remarkGfm]}>
            {segment.text}
          </ReactMarkdown>
        ) : (
          <CitationLine key={index} segment={segment} />
        ),
      )}
    </div>
  );
}

function CitationLine({ segment }: { segment: Extract<Segment, { kind: "citation" }> }) {
  return (
    <div className={cn("my-1.5", segment.listPrefix ? "pl-0" : "")}>
      {segment.listPrefix ? <span className="mr-2 inline-block w-4 text-center">{listMarker(segment.listPrefix)}</span> : null}
      <span className="inline">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ p: ({ children }) => <>{children}</> }}>
          {segment.body}
        </ReactMarkdown>
      </span>
      <CitationCapsules sources={segment.sources} />
    </div>
  );
}

function listMarker(prefix: string): string {
  return /^[-*+]$/.test(prefix) ? "•" : prefix;
}

export function CitationCapsules({ sources }: { sources: CitationSource[] }) {
  const [open, setOpen] = useState(false);
  const visibleSources = sources.slice(0, 2);
  if (sources.length === 0) return null;

  return (
    <span className="relative ml-1.5 inline-flex whitespace-nowrap align-middle">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex max-w-[260px] items-center gap-1 overflow-hidden rounded-full border border-border bg-bg-subtle/80 px-1.5 py-0.5 text-[11px] leading-none text-fg-muted shadow-sm transition hover:border-accent/40 hover:text-fg"
        aria-expanded={open}
        title="Show citations"
      >
        {visibleSources.map((source) => (
          <span key={source.url} className="inline-flex min-w-0 items-center gap-1">
            <img
              src={source.faviconUrl}
              alt=""
              className="h-3.5 w-3.5 shrink-0 rounded-sm"
              onError={(event) => {
                event.currentTarget.style.display = "none";
              }}
            />
            <span className="max-w-[8.5rem] truncate">{sourceName(source.domain)}</span>
          </span>
        ))}
        {sources.length > visibleSources.length ? (
          <span className="shrink-0 text-fg-subtle">+{sources.length - visibleSources.length}</span>
        ) : null}
        <Link2 size={11} className="shrink-0" />
      </button>
      {open ? <CitationPopover sources={sources} onClose={() => setOpen(false)} /> : null}
    </span>
  );
}

function CitationPopover({ sources, onClose }: { sources: CitationSource[]; onClose: () => void }) {
  return (
    <span className="absolute left-0 top-7 z-30 block w-[min(360px,78vw)] rounded-lg border border-border bg-bg-elevated p-2.5 text-left shadow-xl">
      <span className="mb-2 flex items-center justify-between text-xs font-medium text-fg">
        <span>Citations</span>
        <button type="button" onClick={onClose} className="text-fg-subtle hover:text-fg">
          Close
        </button>
      </span>
      <span className="block space-y-2">
        {sources.map((source) => (
          <a
            key={source.url}
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="flex gap-2 rounded-md border border-border/70 bg-bg-subtle/50 p-2 transition hover:border-accent/40 hover:bg-bg-subtle"
          >
            <img src={source.faviconUrl} alt="" className="mt-0.5 h-4 w-4 rounded-sm" />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1 text-xs font-medium text-fg">
                <span className="truncate">{source.displayText}</span>
                <ExternalLink size={11} className="shrink-0 text-fg-subtle" />
              </span>
              <span className="mt-0.5 block text-[11px] text-fg-subtle">
                {source.domain} · T{source.tier} · {source.score}
              </span>
              <span className="mt-1 block text-[11px] leading-snug text-fg-muted">{source.reason}</span>
            </span>
          </a>
        ))}
      </span>
    </span>
  );
}

function splitCitationSegments(content: string): Segment[] {
  if (content.includes("```")) return [{ kind: "markdown", text: content }];

  const segments: Segment[] = [];
  let markdownBuffer: string[] = [];
  const flush = () => {
    const text = markdownBuffer.join("\n").trimEnd();
    if (text) segments.push({ kind: "markdown", text });
    markdownBuffer = [];
  };

  for (const line of content.split("\n")) {
    const standaloneSources = standaloneCitationSources(line);
    if (standaloneSources.length > 0 && attachStandaloneCitation(markdownBuffer, segments, standaloneSources)) {
      continue;
    }

    const parsed = parseCitationLine(line);
    if (!parsed) {
      markdownBuffer.push(line);
      continue;
    }
    flush();
    segments.push(parsed);
  }
  flush();
  return segments;
}

function parseCitationLine(line: string): Segment | null {
  if (!line.trim() || /^#{1,6}\s/.test(line) || /^\s*>/.test(line)) return null;
  const trailingCitation = trailingCitationText(line);
  if (!trailingCitation) return null;
  const sources = citationSources(trailingCitation.text);
  if (sources.length === 0) return null;
  const rawBody = line.slice(0, trailingCitation.start).trimEnd().replace(/\s*[-–—,;:，；、]\s*$/, "");
  if (!rawBody) return null;

  const listMatch = rawBody.match(/^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$/);
  if (listMatch) {
    return {
      kind: "citation",
      listPrefix: listMatch[1].trim(),
      body: listMatch[2].trim(),
      sources,
    };
  }
  return { kind: "citation", body: rawBody.trim(), sources };
}

function standaloneCitationSources(line: string): CitationSource[] {
  const withoutListPrefix = line.trim().replace(/^(?:[-*+]|\d+[.)])\s+/, "").trim();
  if (!withoutListPrefix) return [];
  const trailingCitation = trailingCitationText(withoutListPrefix);
  if (!trailingCitation || trailingCitation.start !== 0) return [];
  return citationSources(trailingCitation.text);
}

function attachStandaloneCitation(
  markdownBuffer: string[],
  segments: Segment[],
  sources: CitationSource[],
): boolean {
  const previousCitation = segments[segments.length - 1];
  if (markdownBuffer.length === 0 && previousCitation?.kind === "citation") {
    previousCitation.sources = mergeSources(previousCitation.sources, sources);
    return true;
  }

  let previousLineIndex = markdownBuffer.length - 1;
  while (previousLineIndex >= 0 && !markdownBuffer[previousLineIndex].trim()) {
    previousLineIndex -= 1;
  }
  if (previousLineIndex < 0) return false;

  const previousLine = markdownBuffer[previousLineIndex];
  if (/^#{1,6}\s/.test(previousLine) || /^\s*>/.test(previousLine)) return false;
  const segment = lineToCitationSegment(previousLine, sources);
  if (!segment) return false;

  const before = markdownBuffer.slice(0, previousLineIndex).join("\n").trimEnd();
  if (before) segments.push({ kind: "markdown", text: before });
  segments.push(segment);
  markdownBuffer.length = 0;
  return true;
}

function lineToCitationSegment(line: string, sources: CitationSource[]): Extract<Segment, { kind: "citation" }> | null {
  const body = line.trimEnd();
  if (!body.trim()) return null;
  const listMatch = body.match(/^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$/);
  if (listMatch) {
    return {
      kind: "citation",
      listPrefix: listMatch[1].trim(),
      body: listMatch[2].trim(),
      sources,
    };
  }
  return { kind: "citation", body: body.trim(), sources };
}

function mergeSources(existing: CitationSource[], incoming: CitationSource[]): CitationSource[] {
  const seen = new Set(existing.map((source) => source.url));
  const merged = [...existing];
  for (const source of incoming) {
    if (seen.has(source.url)) continue;
    seen.add(source.url);
    merged.push(source);
  }
  return merged.sort((a, b) => b.score - a.score || a.domain.localeCompare(b.domain));
}

function trailingCitationText(line: string): { start: number; text: string } | null {
  const effectiveLine = line.replace(/\s+$/g, "");
  const parenthesizedStart = trailingParenthesizedCitationStart(effectiveLine);
  if (parenthesizedStart != null) {
    return { start: parenthesizedStart, text: effectiveLine.slice(parenthesizedStart) };
  }

  const match = effectiveLine.match(TRAILING_LINK_RE);
  if (!match || match.index == null) return null;
  return { start: match.index, text: match[0] };
}

function trailingParenthesizedCitationStart(line: string): number | null {
  if (!/[)）][.!?。！？]*$/.test(line) || !/https?:\/\//i.test(line)) return null;

  for (let index = line.length - 1; index >= 0; index -= 1) {
    const char = line[index];
    if (char !== "(" && char !== "（") continue;
    if (line[index - 1] === "]") continue;
    const tail = line.slice(index);
    const urlIndex = tail.search(/https?:\/\//i);
    if (urlIndex < 0) continue;
    if (/[)）]/.test(tail.slice(1, urlIndex))) continue;
    if (citationSources(tail).length === 0) continue;
    return index;
  }
  return null;
}

function citationSources(text: string): CitationSource[] {
  const sources: CitationSource[] = [];
  const seen = new Set<string>();

  for (const match of text.matchAll(MARKDOWN_LINK_RE)) {
    addSource(sources, seen, match[2], match[1]);
  }
  for (const match of text.matchAll(BARE_URL_RE)) {
    addSource(sources, seen, match[0], null);
  }

  return sources.sort((a, b) => b.score - a.score || a.domain.localeCompare(b.domain));
}

function addSource(sources: CitationSource[], seen: Set<string>, rawUrl: string, title: string | null) {
  const url = normalizeUrl(rawUrl);
  if (!url || seen.has(url)) return;
  seen.add(url);
  const domain = domainFromUrl(url);
  const scored = scoreDomain(domain, url);
  sources.push({
    url,
    domain,
    ...scored,
    displayText: cleanTitle(title) || displayFromUrl(url, domain),
    faviconUrl: faviconUrl(domain),
  });
}

function normalizeUrl(raw: string): string | null {
  const url = raw.trim().replace(/[.,;:!?\])。！？，；：、）】》」』]*$/g, "");
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function domainFromUrl(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "");
  } catch {
    return url;
  }
}

function scoreDomain(domain: string, url: string): Pick<CitationSource, "tier" | "score" | "reason"> {
  if (matches(domain, COMMUNITY_DOMAINS)) return { tier: 4, score: 25, reason: "Community or social discussion platform" };
  if (matches(domain, SELF_MEDIA_DOMAINS) || domain.includes("substack.com")) return { tier: 3, score: 50, reason: "Self-media, personal publishing, or commentary platform" };
  if (OFFICIAL_DOMAINS.has(domain) || domain.endsWith(".gov") || domain.endsWith(".gov.cn")) return { tier: 1, score: 100, reason: "Government, regulator, or primary authority domain" };
  if (matches(domain, AUTHORITY_DOMAINS)) return { tier: 2, score: 80, reason: "Recognized media, research, or advisory institution" };
  if (/\/(newsroom|press|investor|investors|announcements|releases)/i.test(url)) return { tier: 2, score: 80, reason: "Official-site path such as newsroom, press, or investor relations" };
  return { tier: 2, score: 80, reason: "Standard website domain; verify claims against stronger sources when possible" };
}

function matches(domain: string, domains: Set<string>): boolean {
  return domains.has(domain) || Array.from(domains).some((candidate) => domain.endsWith(`.${candidate}`));
}

function cleanTitle(title: string | null): string | null {
  const cleaned = (title || "").replace(/\s+/g, " ").trim();
  return cleaned || null;
}

function displayFromUrl(url: string, domain: string): string {
  try {
    const path = decodeURIComponent(new URL(url).pathname).replace(/^\/|\/$/g, "");
    const tail = path.split("/").pop()?.replace(/[-_]/g, " ").trim();
    return tail ? tail.slice(0, 80) : domain;
  } catch {
    return domain || url;
  }
}

function sourceName(domain: string): string {
  const parts = domain.split(".");
  if (parts.length <= 2) return domain;
  if (domain.endsWith(".com.cn") || domain.endsWith(".gov.cn")) return parts.slice(-3).join(".");
  return parts.slice(-2).join(".");
}

export function faviconUrl(domain: string): string {
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32`;
}

function stripMarkdownSections(
  content: string,
  options: { stripSourceSections: boolean; stripCredibilitySections: boolean },
): string {
  if (!options.stripSourceSections && !options.stripCredibilitySections) return content;

  const lines = content.split("\n");
  const kept: string[] = [];
  let skipping = false;
  let skipLevel = 0;

  for (const line of lines) {
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      const level = heading[1].length;
      const title = heading[2].trim().replace(/[:：]+$/, "").toLowerCase();
      if (skipping && level <= skipLevel) {
        skipping = false;
      }
      const shouldSkip =
        (options.stripSourceSections && RAW_SOURCE_SECTION_HEADINGS.has(title)) ||
        (options.stripCredibilitySections && CREDIBILITY_SECTION_HEADINGS.has(title));
      if (!skipping && shouldSkip) {
        skipping = true;
        skipLevel = level;
        continue;
      }
    }
    if (!skipping) kept.push(line);
  }

  return kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}
