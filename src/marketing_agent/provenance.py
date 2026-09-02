"""Data-source provenance: which source actually produced the numbers.

Every answer that carries data has to end with a "数据来源 / Data Sources"
section naming where the figures came from. That label is built from what the
agents *actually called*, not from what the model remembers doing — the same
reason ``source_scoring`` extracts citation URLs deterministically instead of
trusting a model-written source list.

Layering: a specialist renders the section for its own answer, and the
orchestrator (or OA copilot) re-derives a merged section from the specialist
outputs it synthesized, so the label survives a rewrite that drops it.

This module owns the provenance wording the way ``domain`` owns the business
vocabulary — prompts pull the rules from here so the phrasing cannot drift.
"""
from __future__ import annotations

import re

# Source keys, ordered by precedence: SellerSprite is the primary market-data
# source, and the web/browser path is explicitly the fallback.
SELLERSPRITE = "sellersprite"
LIVE_BROWSER = "live_browser"
WEB_SEARCH = "web_search"
DATA_FILE = "data_file"
KNOWLEDGE_BASE = "knowledge_base"

_ORDER = (SELLERSPRITE, LIVE_BROWSER, WEB_SEARCH, DATA_FILE, KNOWLEDGE_BASE)

HEADINGS = {"zh": "数据来源", "en": "Data Sources"}

_LABELS = {
    "zh": {
        SELLERSPRITE: "卖家精灵（SellerSprite）市场数据 —— 主数据源",
        LIVE_BROWSER: "竞品页实时浏览器采集（Playwright）—— 兜底",
        WEB_SEARCH: "公开网络搜索 —— 兜底",
        DATA_FILE: "用户上传的数据文件（本地 pandas 计算）",
        KNOWLEDGE_BASE: "企业知识库文档检索",
    },
    "en": {
        SELLERSPRITE: "SellerSprite market data — primary source",
        LIVE_BROWSER: "Live competitor-page browser extraction (Playwright) — fallback",
        WEB_SEARCH: "Public web search — fallback",
        DATA_FILE: "User-supplied data file (computed locally with pandas)",
        KNOWLEDGE_BASE: "Company knowledge-base retrieval",
    },
}

# Matched against a rendered section to recover which sources it named, so the
# orchestrator can merge specialist footers without re-plumbing return values.
_FINGERPRINTS = {
    SELLERSPRITE: ("卖家精灵", "sellersprite"),
    LIVE_BROWSER: ("实时浏览器采集", "browser extraction"),
    WEB_SEARCH: ("公开网络搜索", "public web search"),
    DATA_FILE: ("用户上传的数据文件", "user-supplied data file"),
    KNOWLEDGE_BASE: ("企业知识库", "knowledge-base retrieval"),
}


class SourceLedger:
    """Records which data sources a run actually used, in first-use order."""

    def __init__(self) -> None:
        self._used: list[str] = []
        self._notes: dict[str, list[str]] = {}

    def record(self, source: str, note: str | None = None) -> None:
        if source not in _LABELS["zh"]:
            return
        if source not in self._used:
            self._used.append(source)
        if note:
            notes = self._notes.setdefault(source, [])
            if note not in notes:
                notes.append(note)

    def merge(self, other: "SourceLedger") -> None:
        for source in other.used:
            self.record(source)
            for note in other._notes.get(source, []):
                self.record(source, note)

    @property
    def used(self) -> list[str]:
        """Used sources, in the canonical precedence order."""
        return [source for source in _ORDER if source in self._used]

    def __bool__(self) -> bool:
        return bool(self._used)

    def render(self, language: str = "zh") -> str:
        """Render the markdown section, or an empty string when nothing was used."""
        used = self.used
        if not used:
            return ""
        lang = "zh" if language == "zh" else "en"
        lines = [f"## {HEADINGS[lang]}"]
        for source in used:
            label = _LABELS[lang][source]
            notes = self._notes.get(source) or []
            suffix = f"（{'；'.join(notes)}）" if notes and lang == "zh" else (
                f" ({'; '.join(notes)})" if notes else ""
            )
            lines.append(f"- {label}{suffix}")
        return "\n".join(lines)


def detect_sources(text: str) -> SourceLedger:
    """Recover the sources named in an already-rendered section."""
    ledger = SourceLedger()
    lowered = (text or "").lower()
    for source, needles in _FINGERPRINTS.items():
        if any(needle.lower() in lowered for needle in needles):
            ledger.record(source)
    return ledger


def strip_section(text: str) -> str:
    """Remove any existing data-source section so re-appending stays idempotent."""
    if not text:
        return text
    headings = "|".join(re.escape(value) for value in HEADINGS.values())
    pattern = re.compile(
        rf"\n*#{{1,6}}\s*(?:{headings})\s*\n(?:(?!\n#{{1,6}}\s).)*",
        re.IGNORECASE | re.DOTALL,
    )
    return pattern.sub("\n", text).rstrip()


def append_section(text: str, ledger: SourceLedger, language: str = "zh") -> str:
    """Append the authoritative data-source section to ``text``."""
    section = ledger.render(language)
    if not section:
        return text
    body = strip_section(text)
    if not body.strip():
        return section
    return f"{body}\n\n{section}"


def language_for_text(text: str) -> str:
    """Same heuristic the rest of the stack uses, kept here to avoid an import cycle."""
    cjk = sum(1 for char in text if "一" <= char <= "鿿")
    letters = sum(1 for char in text if char.isalpha())
    return "zh" if cjk >= max(4, letters // 5) else "en"


def prompt_rules(language: str = "zh") -> str:
    """The shared prompt clause telling an agent how to treat data provenance."""
    if language == "en":
        return (
            "Data provenance: SellerSprite is the primary source for Amazon market and "
            "competitor data. Use web search and the live product browser only when "
            "SellerSprite is unavailable or cannot supply the specific field, and say so "
            "when you do. Do not write your own Data Sources section — the system appends "
            "an authoritative one based on the tools actually called."
        )
    return (
        "数据来源纪律：Amazon 市场与竞品数据以卖家精灵（SellerSprite）为主数据源；"
        "只有当卖家精灵不可用、或所需字段它查不到时，才使用公开网络搜索与实时商品页浏览器兜底，"
        "并在正文中说明是兜底取得的。不要自己写「数据来源」段落——"
        "系统会根据实际调用过的工具自动追加权威版本。"
    )
