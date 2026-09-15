"""Style and feature elements: what the market is asking for, not which category.

A category tells a product team *where* to work. It does not tell them what to
draw. "Sideboards are growing 12%" is not a brief; "fluted fronts are up 38%
across nine phrases while tufted is down 14%" is — one of those sentences can be
handed to a designer.

The vocabulary below is a **constant**, the same way the freight tiers in
``monitor`` are a constant. It is the set of material, form, feature, size, style
and room words that this business can actually decide about: a fluted door is a
tooling decision, boucle is a supplier decision, "narrow / 12 inch deep" is a
dimension decision. A model asked to "find the trending styles" invents
plausible ones at a steady rate whether or not the data contains any, so the
matching is literal and the arithmetic is ours.

What this module will *not* do is guess. An element with one matching phrase, or
with no growth figure behind it, is reported as observed-but-unrated rather than
promoted into a recommendation.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .scoring import _num

# Kinds, in the order a product decision meets them.
MATERIAL, FORM, FEATURE, SIZE, STYLE, ROOM = (
    "material", "form", "feature", "size", "style", "room")

KIND_LABELS: dict[str, tuple[str, str]] = {
    MATERIAL: ("材质", "Material"),
    FORM: ("形态", "Form"),
    FEATURE: ("功能", "Feature"),
    SIZE: ("尺寸", "Size"),
    STYLE: ("风格", "Style"),
    ROOM: ("空间", "Room"),
}

# (key, zh, en, kind, tokens). Tokens are matched case-insensitively on word
# boundaries, so "cane" does not match "canended" and "oak" does not match "soak".
VOCABULARY: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    # ---- material ----------------------------------------------------------
    ("boucle", "boucle 羊羔绒", "Boucle", MATERIAL, ("boucle", "bouclé")),
    ("velvet", "天鹅绒", "Velvet", MATERIAL, ("velvet",)),
    ("rattan", "藤编", "Rattan / cane", MATERIAL, ("rattan", "cane", "wicker")),
    ("oak", "橡木", "Oak", MATERIAL, ("oak",)),
    ("walnut", "胡桃木", "Walnut", MATERIAL, ("walnut",)),
    ("acacia", "相思木/芒果木", "Acacia / mango", MATERIAL, ("acacia", "mango wood")),
    ("marble", "大理石/石材", "Marble / stone", MATERIAL,
     ("marble", "travertine", "terrazzo")),
    ("leather", "皮革", "Leather", MATERIAL, ("leather", "leathaire")),
    ("linen", "亚麻/棉麻", "Linen", MATERIAL, ("linen",)),
    ("sherpa", "羊羔毛/泰迪绒", "Sherpa / teddy", MATERIAL, ("sherpa", "teddy")),
    ("metal", "金属", "Metal", MATERIAL, ("metal", "steel", "iron", "brass")),
    ("glass", "玻璃", "Glass", MATERIAL, ("glass", "acrylic")),
    # ---- form --------------------------------------------------------------
    ("fluted", "竖纹/罗马柱", "Fluted / reeded", FORM, ("fluted", "reeded", "ribbed")),
    ("arched", "拱形", "Arched", FORM, ("arch", "arched")),
    ("curved", "曲面", "Curved", FORM, ("curved", "curve")),
    ("round", "圆形", "Round", FORM, ("round", "circular")),
    ("sectional", "组合沙发", "Sectional", FORM, ("sectional", "l shaped", "l-shaped")),
    ("modular", "模块化", "Modular", FORM, ("modular",)),
    ("slat", "木条/板条", "Slat", FORM, ("slat", "slatted", "spindle")),
    ("pedestal", "独脚底座", "Pedestal", FORM, ("pedestal",)),
    ("floating", "悬挂/壁挂", "Floating / wall-mounted", FORM,
     ("floating", "wall mounted", "wall-mounted")),
    ("tufted", "拉扣", "Tufted", FORM, ("tufted", "tufting")),
    ("channel", "直条绗缝", "Channel tufted", FORM, ("channel tufted", "channel back")),
    # ---- feature -----------------------------------------------------------
    ("storage", "带收纳", "With storage", FEATURE,
     ("with storage", "storage drawer", "hidden storage")),
    ("convertible", "可变形/沙发床", "Convertible / sleeper", FEATURE,
     ("convertible", "sleeper", "pull out")),
    ("reclining", "可躺/电动", "Reclining / power", FEATURE,
     ("recliner", "reclining", "power reclining")),
    ("adjustable", "可调节", "Adjustable", FEATURE, ("adjustable", "height adjustable")),
    ("extendable", "可延长", "Extendable", FEATURE, ("extendable", "extending", "drop leaf")),
    ("charging", "带充电口", "Charging / USB", FEATURE,
     ("usb", "charging station", "power outlet")),
    ("lift_top", "升降台面", "Lift top", FEATURE, ("lift top", "lift-top")),
    ("no_assembly", "免组装", "No assembly", FEATURE,
     ("no assembly", "pre assembled", "preassembled", "fully assembled")),
    # ---- size --------------------------------------------------------------
    ("narrow", "窄进深", "Narrow / slim", SIZE, ("narrow", "slim", "shallow")),
    ("small_space", "小户型", "Small space", SIZE,
     ("small space", "apartment", "compact", "space saving")),
    ("oversized", "超大尺寸", "Oversized", SIZE, ("oversized", "extra large", "xl")),
    ("deep", "大进深", "Deep seat", SIZE, ("deep seat", "extra deep")),
    # ---- style -------------------------------------------------------------
    ("mid_century", "中古现代", "Mid-century", STYLE, ("mid century", "mid-century", "mcm")),
    ("farmhouse", "农舍风", "Farmhouse", STYLE, ("farmhouse", "rustic")),
    ("boho", "波西米亚", "Boho", STYLE, ("boho", "bohemian")),
    ("japandi", "日式北欧", "Japandi", STYLE, ("japandi", "wabi sabi")),
    ("scandinavian", "北欧", "Scandinavian", STYLE, ("scandinavian", "nordic")),
    ("industrial", "工业风", "Industrial", STYLE, ("industrial",)),
    ("coastal", "海岸风", "Coastal", STYLE, ("coastal", "nautical")),
    ("art_deco", "装饰艺术", "Art deco", STYLE, ("art deco", "deco")),
    ("minimalist", "极简", "Minimalist", STYLE, ("minimalist", "minimal")),
    # ---- room --------------------------------------------------------------
    ("entryway", "玄关", "Entryway", ROOM, ("entryway", "hallway", "foyer", "mudroom")),
    ("dining", "餐厅", "Dining room", ROOM, ("dining room", "dining")),
    ("living", "客厅", "Living room", ROOM, ("living room",)),
    ("bedroom", "卧室", "Bedroom", ROOM, ("bedroom",)),
    ("home_office", "居家办公", "Home office", ROOM, ("home office", "office desk")),
    ("nursery", "儿童房", "Nursery / kids", ROOM, ("nursery", "kids", "toddler")),
    ("outdoor", "户外", "Outdoor / patio", ROOM, ("outdoor", "patio")),
)

# An element has to clear all three before it may be called a trend. One phrase
# moving 40% is one phrase, not a direction.
MIN_KEYWORDS = 2
MIN_SEARCHES = 3_000.0
RISING_PCT = 10.0
FALLING_PCT = -10.0

_PATTERNS: dict[str, re.Pattern[str]] = {
    key: re.compile(r"\b(?:" + "|".join(re.escape(t) for t in tokens) + r")\b")
    for key, _zh, _en, _kind, tokens in VOCABULARY
}
_BY_KEY = {key: (zh, en, kind) for key, zh, en, kind, _t in VOCABULARY}


def label_for(key: str, zh: bool) -> str:
    entry = _BY_KEY.get(key)
    if not entry:
        return key
    return entry[0] if zh else entry[1]


def kind_label(kind: str, zh: bool) -> str:
    names = KIND_LABELS.get(kind, (kind, kind))
    return names[0] if zh else names[1]


# Which window a growth figure came from, worst to best. Reported alongside the
# number because "up 18%" means different things over a month and over a year,
# and a seasonal category will disagree with itself between the two.
STORED, MOM, YOY = "stored", "mom", "yoy"


def _growth_of(row: Mapping[str, Any],
               previous: Mapping[str, float] | None) -> tuple[float | None, str]:
    """``(percent, window)`` — never a rank movement dressed up as demand growth.

    ``rank_growth_rate`` is deliberately not consulted. It is ABA's *rank*
    movement, where lower is better and the scale is a ratio of positions; the
    old code fell back to it whenever ``growth`` was absent, so an ABA-sourced
    phrase reported 0.9951 as "up 99.51%".
    """
    keyword = str(row.get("keyword") or "")
    now = _num(row.get("searches"))
    before = (previous or {}).get(keyword)
    if now is not None and before:
        # Two months we stored and can point at, so this wins when it exists.
        return (now - before) / before * 100.0, STORED
    for column, window in (("searches_mom_pct", MOM), ("searches_yoy_pct", YOY),
                           ("searches_growth", MOM)):
        value = _num(row.get(column))
        if value is None:
            continue
        # The vendor reports these as a percentage on keyword_research and as a
        # ratio on some others; nothing in this market grows 0.4% and says so.
        return (value * 100.0 if -3.0 <= value <= 3.0 else value), window
    return None, ""


def scan(
    keywords: Sequence[Mapping[str, Any]],
    *, previous: Sequence[Mapping[str, Any]] = (),
) -> list[dict]:
    """Aggregate stored keyword rows into element rows, strongest demand first.

    ``previous`` is the same query one month back; when a phrase appears in both
    the change is computed from the two stored values rather than trusted to the
    vendor's own growth column.
    """
    before = {str(r.get("keyword") or ""): _num(r.get("searches")) or 0.0
              for r in previous}
    buckets: dict[str, dict[str, Any]] = {}
    for row in keywords:
        phrase = str(row.get("keyword") or "").strip().lower()
        if not phrase:
            continue
        searches = _num(row.get("searches")) or 0.0
        growth, window = _growth_of(row, before)
        for key, pattern in _PATTERNS.items():
            if not pattern.search(phrase):
                continue
            bucket = buckets.setdefault(key, {
                "key": key, "kind": _BY_KEY[key][2], "keywords": [],
                "searches": 0.0, "_weighted": 0.0, "_weight": 0.0, "_windows": {},
            })
            bucket["keywords"].append({"keyword": str(row.get("keyword")),
                                       "searches": searches, "growth_pct": growth})
            bucket["searches"] += searches
            if growth is not None and searches > 0:
                bucket["_weighted"] += growth * searches
                bucket["_weight"] += searches
                bucket["_windows"][window] = bucket["_windows"].get(window, 0.0) + searches

    out: list[dict] = []
    for bucket in buckets.values():
        weight = bucket.pop("_weight")
        weighted = bucket.pop("_weighted")
        windows = bucket.pop("_windows")
        # The window most of this element's search volume was measured over. A
        # bucket can mix them when the phrases came from different tools, and the
        # label has to say which one dominates rather than imply they agree.
        bucket["window"] = max(windows, key=windows.get) if windows else ""
        # Search-weighted: a 300%-growth phrase with 40 searches a month is noise
        # next to a 12% move on a phrase with 40,000.
        bucket["growth_pct"] = round(weighted / weight, 1) if weight else None
        bucket["keyword_count"] = len(bucket["keywords"])
        bucket["keywords"] = sorted(bucket["keywords"],
                                    key=lambda k: k["searches"], reverse=True)[:5]
        bucket["searches"] = round(bucket["searches"])
        bucket["rated"] = bool(
            bucket["growth_pct"] is not None
            and bucket["keyword_count"] >= MIN_KEYWORDS
            and bucket["searches"] >= MIN_SEARCHES)
        out.append(bucket)
    out.sort(key=lambda b: b["searches"], reverse=True)
    return out


def split(rows: Iterable[dict], *, limit: int = 6) -> tuple[list[dict], list[dict]]:
    """``(rising, falling)`` — only elements that cleared the evidence bar."""
    rated = [r for r in rows if r.get("rated")]
    rising = sorted([r for r in rated if (r["growth_pct"] or 0) >= RISING_PCT],
                    key=lambda r: r["growth_pct"], reverse=True)[:limit]
    falling = sorted([r for r in rated if (r["growth_pct"] or 0) <= FALLING_PCT],
                     key=lambda r: r["growth_pct"])[:limit]
    return rising, falling


def localize(rows: Sequence[dict], zh: bool) -> list[dict]:
    """Attach display labels. Kept out of :func:`scan` so the arithmetic stays
    language-free and a test can assert on keys rather than on translations."""
    return [{**row, "label": label_for(row["key"], zh),
             "kind_label": kind_label(row["kind"], zh)} for row in rows]


def brief(rising: Sequence[dict], falling: Sequence[dict], zh: bool) -> str:
    """The element read, as the model receives it. Names only; no new numbers."""
    if not rising and not falling:
        return ""
    lines = ["ELEMENT DEMAND (search-weighted, computed server-side — do not restate "
             "the percentages, cite the keyword evidence instead):"]
    for row in rising:
        lines.append(f"  RISING {row['key']} ({row['kind']}) {row['growth_pct']:+.1f}% "
                     f"over {row['keyword_count']} phrases, {row['searches']:,} searches")
    for row in falling:
        lines.append(f"  FALLING {row['key']} ({row['kind']}) {row['growth_pct']:+.1f}% "
                     f"over {row['keyword_count']} phrases, {row['searches']:,} searches")
    return "\n".join(lines)


# --------------------------------------------------------------- shelf side ----
# Demand says what people ask for; this says what is already selling. Both come
# from calls the sweep already makes — the titles arrive with every
# ``product_research`` row — so the whole supply half of the element picture
# costs nothing extra.

MIN_SHELF_ASINS = 3


def shelf_share(products: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Element share of the head set's revenue, matched on listing titles.

    Revenue rather than listing count on purpose: ten listings nobody buys prove
    a style is *available*, not that it works. A listing carrying three elements
    counts toward all three, so the shares sum past 100 — they are "share of head
    revenue whose listing mentions this", not slices of a pie, and the chart says
    so.
    """
    total = sum((_num(p.get("revenue")) or 0.0) for p in products)
    if total <= 0:
        return []
    buckets: dict[str, dict[str, Any]] = {}
    for product in products:
        title = str(product.get("title") or "").strip().lower()
        if not title:
            continue
        revenue = _num(product.get("revenue")) or 0.0
        price = _num(product.get("price"))
        for key, pattern in _PATTERNS.items():
            if not pattern.search(title):
                continue
            bucket = buckets.setdefault(key, {
                "key": key, "kind": _BY_KEY[key][2], "asins": 0,
                "revenue": 0.0, "_prices": [],
            })
            bucket["asins"] += 1
            bucket["revenue"] += revenue
            if price is not None:
                bucket["_prices"].append(price)

    out: list[dict] = []
    for bucket in buckets.values():
        prices = bucket.pop("_prices")
        bucket["avg_price"] = round(sum(prices) / len(prices), 2) if prices else None
        bucket["revenue_share_pct"] = round(bucket["revenue"] / total * 100.0, 1)
        bucket["revenue"] = round(bucket["revenue"], 2)
        bucket["shelf_rated"] = bucket["asins"] >= MIN_SHELF_ASINS
        out.append(bucket)
    out.sort(key=lambda b: b["revenue_share_pct"], reverse=True)
    return out


def merge(demand: Sequence[Mapping[str, Any]],
          shelf: Sequence[Mapping[str, Any]]) -> list[dict]:
    """One row per element carrying both halves, for the demand-vs-shelf matrix.

    An element present on only one side is kept, not dropped: a style with search
    growth and no shelf presence is the most interesting cell on the chart, and a
    style holding revenue with no search trend behind it is the second most.
    """
    rows: dict[str, dict] = {}
    for item in demand:
        rows[item["key"]] = {**item}
    for item in shelf:
        rows.setdefault(item["key"], {"key": item["key"], "kind": item["kind"],
                                      "keywords": [], "searches": 0,
                                      "growth_pct": None, "keyword_count": 0,
                                      "rated": False, "window": ""})
        rows[item["key"]].update({
            "asins": item["asins"], "revenue": item["revenue"],
            "revenue_share_pct": item["revenue_share_pct"],
            "avg_price": item["avg_price"], "shelf_rated": item["shelf_rated"],
        })
    for row in rows.values():
        row.setdefault("asins", 0)
        row.setdefault("revenue", 0.0)
        row.setdefault("revenue_share_pct", 0.0)
        row.setdefault("avg_price", None)
        row.setdefault("shelf_rated", False)
    return sorted(rows.values(), key=lambda r: r["searches"], reverse=True)
