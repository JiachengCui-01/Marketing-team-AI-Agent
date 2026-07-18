"""URL source-tier extraction, scoring, and markdown annotation.

The scoring here is intentionally deterministic and dependency-free. It is not a
truth validator; it gives the research/news flows a stable way to sort and label
sources so weak platforms are not treated like fact-bearing references.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class SourceMeta:
    url: str
    domain: str
    tier: int
    tier_label: str
    score: int
    reason: str
    is_weak_signal: bool
    title: str | None = None
    display_text: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


TIER_LABELS = {
    1: "Tier 1 - official / primary authority",
    2: "Tier 2 - authoritative media / official website",
    3: "Tier 3 - industry self-media / commentary",
    4: "Tier 4 - community discussion / social platform",
}

TIER_SCORES = {1: 100, 2: 80, 3: 50, 4: 25}

OFFICIAL_EXACT_DOMAINS = {
    "sec.gov",
    "ftc.gov",
    "fda.gov",
    "federalreserve.gov",
    "whitehouse.gov",
    "congress.gov",
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
}

OFFICIAL_SUFFIXES = (
    ".gov",
    ".gov.cn",
    ".gouv.fr",
    ".gov.uk",
    ".gc.ca",
    ".europa.eu",
)

AUTHORITATIVE_EXACT_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "economist.com",
    "nytimes.com",
    "washingtonpost.com",
    "bbc.com",
    "bbc.co.uk",
    "theguardian.com",
    "cnbc.com",
    "forbes.com",
    "technologyreview.com",
    "harvardbusinessreview.org",
    "mckinsey.com",
    "bcg.com",
    "bain.com",
    "gartner.com",
    "idc.com",
    "forrester.com",
    "cbinsights.com",
    "statista.com",
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
}

SELF_MEDIA_DOMAINS = {
    "medium.com",
    "substack.com",
    "wordpress.com",
    "blogspot.com",
    "weebly.com",
    "ghost.io",
    "mp.weixin.qq.com",
    "weixin.qq.com",
}

COMMUNITY_DOMAINS = {
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
}

OFFICIAL_PATH_HINTS = (
    "/newsroom",
    "/press",
    "/media",
    "/investor",
    "/investors",
    "/ir/",
    "/company/news",
    "/blog/news",
    "/announcements",
    "/releases",
)

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)", re.IGNORECASE)
_BARE_URL_RE = re.compile(r"https?://[^\s<>()\]]+", re.IGNORECASE)
_TRAILING_PUNCT = ".,;:!?)]}\"'。！？，；：、）】》」』"
_RAW_SOURCE_SECTION_HEADINGS = {
    "sources",
    "source",
    "references",
    "information sources",
    "information source",
    "信息来源",
    "来源",
}


def extract_urls(text: str) -> list[str]:
    """Return unique normalized URLs from markdown links and bare URLs."""
    urls: list[str] = []
    seen: set[str] = set()
    raw_urls = [
        *(match.group(1) for match in _MARKDOWN_LINK_RE.finditer(text)),
        *(match.group(0) for match in _BARE_URL_RE.finditer(text)),
    ]
    for raw in raw_urls:
        url = _normalize_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def score_url(url: str) -> SourceMeta:
    parsed = urlparse(url)
    domain = _normalize_domain(parsed.netloc)
    path = parsed.path.lower()

    if not domain:
        return _meta(url, "", 4, "URL could not be parsed")
    if _matches(domain, COMMUNITY_DOMAINS):
        return _meta(url, domain, 4, "Community or social discussion platform")
    if _matches(domain, SELF_MEDIA_DOMAINS) or "substack.com" in domain:
        return _meta(url, domain, 3, "Self-media, personal publishing, or commentary platform")
    if domain in OFFICIAL_EXACT_DOMAINS or any(domain.endswith(suffix) for suffix in OFFICIAL_SUFFIXES):
        return _meta(url, domain, 1, "Government, regulator, or primary authority domain")
    if _matches(domain, AUTHORITATIVE_EXACT_DOMAINS):
        return _meta(url, domain, 2, "Recognized media, research, or advisory institution")
    if any(hint in path for hint in OFFICIAL_PATH_HINTS):
        return _meta(url, domain, 2, "Official-site path such as newsroom, press, or investor relations")
    return _meta(url, domain, 2, "Standard website domain; treat as stronger than self-media/community but verify claims")


def extract_source_references(text: str) -> list[SourceMeta]:
    """Extract source references with display text from markdown links when present."""
    refs: list[SourceMeta] = []
    seen: set[str] = set()

    for match in _MARKDOWN_LINK_RE.finditer(text):
        title = _clean_title(match.group(0).split("](", 1)[0].lstrip("["))
        url = _normalize_url(match.group(1))
        if not url or url in seen:
            continue
        seen.add(url)
        refs.append(_with_display(score_url(url), title))

    for match in _BARE_URL_RE.finditer(text):
        url = _normalize_url(match.group(0))
        if not url or url in seen:
            continue
        seen.add(url)
        refs.append(_with_display(score_url(url), None))

    return sorted(refs, key=lambda source: (-source.score, source.domain, source.url))


def score_sources(text: str) -> list[SourceMeta]:
    """Extract, score, and sort sources by credibility score then domain."""
    return sorted(
        (score_url(url) for url in extract_urls(text)),
        key=lambda source: (-source.score, source.domain, source.url),
    )


def summarize_sources(sources: list[SourceMeta]) -> dict:
    if not sources:
        return {
            "source_score": 0,
            "strong_source_count": 0,
            "weak_source_count": 0,
        }
    strong = sum(1 for source in sources if source.tier <= 2)
    weak = sum(1 for source in sources if source.is_weak_signal)
    weighted = round(sum(source.score for source in sources) / len(sources))
    return {
        "source_score": weighted,
        "strong_source_count": strong,
        "weak_source_count": weak,
    }


def source_dicts(sources: list[SourceMeta]) -> list[dict]:
    return [source.to_dict() for source in sources]


def annotate_markdown_with_source_tiers(text: str, *, language: str | None = None) -> str:
    """Append a deterministic source-tier section to research/news markdown."""
    sources = score_sources(text)
    if not sources:
        return text.strip()

    marker = "## Source Credibility"
    zh_marker = "## 来源可信度"
    base = strip_raw_source_sections(
        _strip_existing_credibility_section(text, marker, zh_marker)
    ).rstrip()
    zh = language == "zh" or ("## 摘要" in text and language != "en")
    weak = any(source.is_weak_signal for source in sources)
    strong = any(source.tier <= 2 for source in sources)

    heading = zh_marker if zh else marker
    lines = ["", "", heading]
    if zh:
        if weak and not strong:
            lines.append("当前来源主要来自行业自媒体或社区讨论，只适合作为弱信号参考，不能单独作为事实依据。")
        elif weak:
            lines.append("已优先采用 Tier 1/Tier 2 来源；Tier 3/Tier 4 仅作为市场讨论和弱信号参考。")
        else:
            lines.append("本摘要优先基于 Tier 1/Tier 2 来源。")
    else:
        if weak and not strong:
            lines.append("The available sources are mainly self-media or community discussion, so treat them as weak signals rather than standalone factual evidence.")
        elif weak:
            lines.append("Tier 1/Tier 2 sources are prioritized; Tier 3/Tier 4 sources are included only as weak market-signal context.")
        else:
            lines.append("This summary prioritizes Tier 1/Tier 2 sources.")

    for index, source in enumerate(sources, start=1):
        weak_note = " weak signal" if source.is_weak_signal and not zh else ""
        zh_weak_note = "，弱信号" if source.is_weak_signal and zh else ""
        note = zh_weak_note if zh else weak_note
        lines.append(
            f"{index}. {source.tier_label} ({source.score}){note}: "
            f"[{source.domain}]({source.url})"
        )
    return base + "\n".join(lines)


def strip_raw_source_sections(text: str) -> str:
    """Remove model-authored raw source/reference sections from visible markdown."""
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    skip_level = 0

    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().rstrip(":：").lower()
            if skipping and level <= skip_level:
                skipping = False
            if not skipping and title in _RAW_SOURCE_SECTION_HEADINGS:
                skipping = True
                skip_level = level
                continue
        if not skipping:
            kept.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _normalize_url(raw: str) -> str:
    url = raw.strip().strip(_TRAILING_PUNCT)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed.geturl()


def _normalize_domain(netloc: str) -> str:
    domain = netloc.lower().split("@")[-1].split(":")[0].strip(".")
    for prefix in ("www.", "m."):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    return domain


def _matches(domain: str, domains: set[str]) -> bool:
    return domain in domains or any(domain.endswith("." + candidate) for candidate in domains)


def _meta(url: str, domain: str, tier: int, reason: str) -> SourceMeta:
    return SourceMeta(
        url=url,
        domain=domain,
        tier=tier,
        tier_label=TIER_LABELS[tier],
        score=TIER_SCORES[tier],
        reason=reason,
        is_weak_signal=tier >= 3,
        title=None,
        display_text=_derive_display_text(url, domain),
    )


def _strip_existing_credibility_section(text: str, *headings: str) -> str:
    positions = [text.find(heading) for heading in headings if text.find(heading) >= 0]
    return text[: min(positions)].rstrip() if positions else text


def _with_display(source: SourceMeta, title: str | None) -> SourceMeta:
    display = title or _derive_display_text(source.url, source.domain)
    return SourceMeta(
        url=source.url,
        domain=source.domain,
        tier=source.tier,
        tier_label=source.tier_label,
        score=source.score,
        reason=source.reason,
        is_weak_signal=source.is_weak_signal,
        title=title,
        display_text=display,
    )


def _clean_title(raw: str) -> str | None:
    title = re.sub(r"\s+", " ", raw).strip()
    return title or None


def _derive_display_text(url: str, domain: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path or "").strip("/")
    if not path:
        return domain or url
    tail = path.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").strip()
    return tail[:80] if tail else domain or url
