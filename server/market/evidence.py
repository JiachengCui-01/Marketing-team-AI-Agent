"""Evidence: the mechanism that makes "every number is traceable" checkable.

The old guarantee was an honour system — the system prompt said *every number you
output must be copied from the supplied payloads* and nothing verified it. Here it
is mechanical, in three parts:

1. **The model never sees a raw payload.** ``extract.py`` turns payload into typed
   values and mints one evidence row per material number, recording the field path
   it came from. The model sees :func:`sheet` — one line per citable fact.
2. **Every claim carries ``evidence_ids``.** :func:`validate_citations` deletes any
   claim whose ids are unknown, and any *sentence containing a digit* that carries
   no citation. Digits are the failure mode that matters: an unsourced adjective is
   noise, an unsourced number is a lie.
3. **Quality travels with the number.** :func:`assess` labels thin samples, outliers
   and stale periods, and the sheet shows the label, so "the market says" cannot be
   written on top of a sample of 17.

Ids are deterministic in ``(marketplace, subject, metric, period, tool)`` — *not* in
the call id, which changes every run and would mint a fresh id for the same fact
every month.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# Vendor-modelled figures. The vendor observes price, BSR, rating and review counts;
# it estimates everything about volume and money. The distinction is enforced here
# rather than asked for in a prompt.
ESTIMATED_METRICS = frozenset({
    "units", "revenue", "profit", "total_units", "total_revenue", "avg_units",
    "avg_revenue", "avg_profit", "new_avg_units_l12", "new_avg_revenue_l12",
    "monthly_units", "monthly_revenue", "sales", "amount", "amz_units",
    "predicted_units", "predicted_revenue", "purchases", "impressions", "clicks",
})

SMALL_SAMPLE = 30            # below this an aggregate is indicative, not evidence
SMALL_REVIEW_SAMPLE = 20
OUTLIER_IQR_MULTIPLIER = 3.0

# Chinese sentences end without a following space, so the split cannot require one
# after CJK punctuation — otherwise a whole paragraph is one "sentence" and a single
# citation at the front launders every uncited number behind it.
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；])|(?<=[.!?])\s+|\n+")
# Deliberately not hex-only: a hallucinated id is precisely the one that will not
# look like a real one, and it still has to be caught and stripped.
_CITATION = re.compile(r"\[(?P<label>[^\]]+)\]\(evidence:(?P<eid>ev_[0-9A-Za-z_]{4,40})\)")
_DIGIT = re.compile(r"\d")
# A markdown table row or a heading is structure, not a sentence; the digit rule
# would shred a table where every cell is a cited number rendered by the UI.
_STRUCTURAL = re.compile(r"^\s*(\||#{1,6}\s|[-*+]\s*$|\d+\.\s*$)")


def mint_id(
    *, marketplace: str, subject_kind: str, subject_id: str, metric: str,
    period: str, tool: str,
) -> str:
    raw = f"{marketplace}|{subject_kind}|{subject_id}|{metric}|{period}|{tool}"
    return "ev_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def is_estimated(metric: str) -> bool:
    return metric in ESTIMATED_METRICS


def assess(
    *, metric: str, sample_size: int | None = None, period: str = "",
    current_period: str = "", siblings: Sequence[float] | None = None,
    value: float | None = None,
) -> str:
    """Label one number's trustworthiness: ok | small_sample | outlier | stale."""
    if period and current_period and period < current_period:
        # One month behind is normal mid-month; two is a collection gap worth saying.
        if _months_between(period, current_period) >= 2:
            return "stale"
    threshold = SMALL_REVIEW_SAMPLE if metric.startswith("review") else SMALL_SAMPLE
    if sample_size is not None and 0 < sample_size < threshold:
        return "small_sample"
    if value is not None and siblings and len(siblings) >= 4 and _is_outlier(value, siblings):
        return "outlier"
    return "ok"


def _months_between(earlier: str, later: str) -> int:
    try:
        y1, m1 = int(earlier[:4]), int(earlier[4:6])
        y2, m2 = int(later[:4]), int(later[4:6])
    except (ValueError, IndexError):
        return 0
    return (y2 - y1) * 12 + (m2 - m1)


def _is_outlier(value: float, siblings: Sequence[float]) -> bool:
    ordered = sorted(float(s) for s in siblings if s is not None)
    if len(ordered) < 4:
        return False
    q1 = ordered[len(ordered) // 4]
    q3 = ordered[(3 * len(ordered)) // 4]
    iqr = q3 - q1
    if iqr <= 0:
        return False
    return value < q1 - OUTLIER_IQR_MULTIPLIER * iqr or value > q3 + OUTLIER_IQR_MULTIPLIER * iqr


@dataclass
class EvidenceIndex:
    """The evidence collected for one report, and the sheet the model reads."""

    marketplace: str = "US"
    period: str = ""
    rows: dict[str, dict] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)

    def mint(
        self, *, subject_kind: str, subject_id: str, metric: str, value: Any,
        tool: str, field_path: str = "", period: str | None = None, unit: str = "",
        observed: bool | None = None, sample_size: int | None = None,
        quality: str | None = None, call_id: str = "", arguments: dict | None = None,
        label: str = "",
    ) -> str | None:
        """Record one citable number. Returns its id, or ``None`` for a missing value.

        A missing vendor field mints nothing and is reported as a gap: an evidence
        row holding ``None`` would let a claim cite the absence of data as if it
        were data.
        """
        if value is None or (isinstance(value, str) and not value.strip()):
            self.note_gap(f"{subject_id}:{metric}")
            return None
        row_period = self.period if period is None else period
        eid = mint_id(marketplace=self.marketplace, subject_kind=subject_kind,
                      subject_id=subject_id, metric=metric, period=row_period, tool=tool)
        numeric: float | None
        try:
            numeric = float(value)
            text = None
        except (TypeError, ValueError):
            numeric = None
            text = str(value)[:300]
        self.rows[eid] = {
            "id": eid,
            "marketplace": self.marketplace,
            "tool": tool,
            "arguments": arguments or {},
            "field_path": field_path,
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "metric": metric,
            "label": label or metric,
            "period": row_period,
            "value_num": numeric,
            "value_text": text,
            "unit": unit,
            "observed": (not is_estimated(metric)) if observed is None else observed,
            "sample_size": sample_size,
            "quality": quality or assess(metric=metric, sample_size=sample_size,
                                         period=row_period, current_period=self.period),
            "call_id": call_id,
        }
        return eid

    def note_gap(self, what: str) -> None:
        if what not in self.gaps:
            self.gaps.append(what)

    def merge(self, other: "EvidenceIndex") -> None:
        self.rows.update(other.rows)
        for gap in other.gaps:
            self.note_gap(gap)

    def ids(self) -> set[str]:
        return set(self.rows)

    def known(self, evidence_id: str) -> bool:
        return evidence_id in self.rows

    def all_rows(self) -> list[dict]:
        return list(self.rows.values())

    def subset(self, ids: Iterable[str]) -> list[dict]:
        return [self.rows[i] for i in ids if i in self.rows]

    def __len__(self) -> int:
        return len(self.rows)

    def __bool__(self) -> bool:
        return bool(self.rows)

    def sheet(self, *, language: str = "zh", max_rows: int = 400) -> str:
        """The pipe-delimited block the model reads instead of a payload.

        ~60 bytes per line, every one of them a citable number — against ~9 KB per
        raw payload, most of it field-name noise the model cannot cite.
        """
        header = (
            "证据索引（只能引用下列 id，禁止编造 id）\n"
            "id | 对象 | 指标 | 值 | 单位 | 期间 | 实测/估算 | 质量"
            if language == "zh" else
            "EVIDENCE INDEX (cite these ids only; never invent one)\n"
            "id | subject | metric | value | unit | period | basis | quality"
        )
        lines = [header]
        for row in list(self.rows.values())[:max_rows]:
            value, unit = _display(row["value_num"], row["value_text"], row["unit"])
            basis = ("实测" if row["observed"] else "估算") if language == "zh" else (
                "observed" if row["observed"] else "ESTIMATE")
            quality = row["quality"]
            if row.get("sample_size"):
                quality = f"{quality} n={row['sample_size']}"
            lines.append(
                f"{row['id']} | {row['subject_id']} | {row['label']} | {value} | "
                f"{unit} | {row['period']} | {basis} | {quality}"
            )
        if self.gaps:
            label = "数据缺口（这些字段未取到，不得推断）" if language == "zh" else (
                "GAPS (not collected — do not infer these)")
            lines.append(f"{label}: {', '.join(self.gaps[:40])}")
        return "\n".join(lines)


def _format(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _display(value_num: float | None, value_text: str | None,
             unit: str) -> tuple[str, str]:
    """One evidence value as the model should copy it into prose.

    Shares are stored as fractions, which is right for arithmetic and wrong for
    reading: handed ``0.0177 share`` a model writes "0.0177" and a human reads
    it as a rounding error. Worse, two decimal places turn a 1.77% return rate
    into ``0.02``. Shares are therefore shown as percentages with enough digits
    to survive, so the prose matches what the panels print beside it.
    """
    if value_num is None:
        return (value_text or "—"), unit
    if unit == "share":
        percent = value_num * 100.0
        digits = 2 if abs(percent) < 10 else 1
        return f"{percent:,.{digits}f}", "%"
    return _format(value_num), unit


def index_from_rows(rows: Sequence[dict], *, marketplace: str = "US",
                    period: str = "") -> EvidenceIndex:
    """Rebuild an index from stored evidence rows, for a re-render or the API."""
    index = EvidenceIndex(marketplace=marketplace, period=period)
    for row in rows:
        eid = str(row.get("id") or "")
        if not eid:
            continue
        merged = dict(row)
        merged.setdefault("label", merged.get("metric", ""))
        index.rows[eid] = merged
    return index


# --------------------------------------------------------------- validation ----

def validate_citations(
    payload: Any, allowed: set[str], *, path: str = "$",
) -> tuple[Any, list[str]]:
    """Strip everything the evidence does not support.

    Returns the cleaned payload and a list of human-readable drop notes. Rules:

    * an object declaring ``evidence_ids`` keeps only ids in ``allowed``; if none
      survive, the whole object is dropped — an uncited claim is the failure mode
      this design exists to prevent;
    * a markdown string loses links to unknown ids, and loses any sentence that
      contains a digit but no citation.
    """
    dropped: list[str] = []
    cleaned = _walk(payload, allowed, path, dropped)
    return cleaned, dropped


def _walk(node: Any, allowed: set[str], path: str, dropped: list[str]) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        if "evidence_ids" in node:
            kept = [i for i in _as_ids(node.get("evidence_ids")) if i in allowed]
            if not kept:
                dropped.append(path)
                return None
            node = {**node, "evidence_ids": kept}
        for key, value in node.items():
            child = _walk(value, allowed, f"{path}.{key}", dropped)
            if child is not None:
                out[key] = child
            elif isinstance(value, (dict, list)):
                out[key] = {} if isinstance(value, dict) else []
        return out
    if isinstance(node, list):
        kept_items = []
        for i, item in enumerate(node):
            child = _walk(item, allowed, f"{path}[{i}]", dropped)
            if child is not None:
                kept_items.append(child)
        return kept_items
    if isinstance(node, str):
        return _clean_markdown(node, allowed, path, dropped)
    return node


def _as_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int))]
    return []


def _clean_markdown(text: str, allowed: set[str], path: str, dropped: list[str]) -> str:
    if "evidence:" not in text and not _DIGIT.search(text):
        return text

    def _replace(match: re.Match) -> str:
        if match.group("eid") in allowed:
            return match.group(0)
        dropped.append(f"{path}:unknown-id:{match.group('eid')}")
        return match.group("label")

    text = _CITATION.sub(_replace, text)
    if "\n" not in text and len(text) < 400 and not _CITATION.search(text):
        # Short single-line strings are labels and enum values, not prose.
        return text

    kept: list[str] = []
    for line in text.split("\n"):
        if _STRUCTURAL.match(line) or not line.strip():
            kept.append(line)
            continue
        sentences = [s for s in _SENTENCE_SPLIT.split(line) if s.strip()]
        survivors = []
        for sentence in sentences:
            if _DIGIT.search(sentence) and not _CITATION.search(sentence):
                dropped.append(f"{path}:uncited-number")
                continue
            survivors.append(sentence)
        if survivors:
            kept.append(" ".join(survivors))
    return "\n".join(kept).strip()


def citation_notes(dropped: Sequence[str], language: str = "zh") -> list[str]:
    """Turn drop paths into notes a reader can act on.

    A silently shortened report is worse than a visibly shortened one.
    """
    if not dropped:
        return []
    uncited = sum(1 for d in dropped if d.endswith(":uncited-number"))
    unknown = sum(1 for d in dropped if ":unknown-id:" in d)
    objects = len(dropped) - uncited - unknown
    notes: list[str] = []
    if language == "zh":
        if objects:
            notes.append(f"{objects} 条结论因缺少可引用证据被移除。")
        if uncited:
            notes.append(f"{uncited} 处带数字但无出处的表述被移除。")
        if unknown:
            notes.append(f"{unknown} 处引用了不存在的证据编号，已降级为普通文本。")
    else:
        if objects:
            notes.append(f"{objects} conclusion(s) removed for lacking citable evidence.")
        if uncited:
            notes.append(f"{uncited} uncited numeric statement(s) removed.")
        if unknown:
            notes.append(f"{unknown} citation(s) pointed at an unknown evidence id.")
    return notes
