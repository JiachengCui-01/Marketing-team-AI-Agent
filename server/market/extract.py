"""Vendor payload → typed warehouse rows + evidence. Pure functions, no I/O.

This is where "the model never sees a raw payload" is actually implemented: every
number that reaches a dashboard is pulled out here, given a column, and minted as an
evidence row carrying the field path it came from.

Two things the vendor does that this module has to absorb, both discovered from real
replies (see ``tests/fixtures/sellersprite/``):

**Mixed ratio scales.** ``returnRatio`` is 1.5674 meaning 1.57%, ``top5BrandCrn`` is
0.3929 meaning 39.29%, and ``newProductProportion`` is 45.0 meaning 45% — the same
quantity as ``l12NewRatio`` 0.45. Everything is normalised to a **fraction of one**
on the way in, so a score never has to ask which scale it is looking at.

**Mixed date encodings.** ``availableDate`` and review dates are epoch milliseconds,
``asin_prediction`` months are ``2025-08``, ``keyword_research`` months are
``2026.08``, and ABA months are ``202608``. All become ``yyyyMM`` or an ISO date.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from .evidence import EvidenceIndex

# Vendor fields that arrive as 0-100 and mean a percentage.
_PERCENT_FIELDS = frozenset({
    "returnRatio", "avgReturnRatio", "fbaProportion", "fbmProportion",
    "ebcProportion", "amazonSelfProportion", "newProductProportion", "sellerProportion",
})

_WEIGHT_RE = re.compile(r"([\d.]+)\s*(pounds?|lbs?|kilograms?|kg|ounces?|oz|grams?|g)\b", re.I)
_TO_POUNDS = {"pound": 1.0, "lb": 1.0, "kg": 2.20462, "kilogram": 2.20462,
              "ounce": 0.0625, "oz": 0.0625, "gram": 0.00220462, "g": 0.00220462}


# ------------------------------------------------------------------ helpers ----

def parse(payload: Any) -> Any:
    """Accept a JSON string, an already-parsed body, or a gateway reply.

    Taking the reply object directly keeps every call site to one argument; the
    extractors need its ``tool``/``call_id`` for provenance anyway.
    """
    if payload is None:
        return None
    if isinstance(payload, (dict, list)):
        return payload
    if not isinstance(payload, str):
        parsed = getattr(payload, "data", None)
        if parsed is not None:
            return parsed
        payload = getattr(payload, "payload", "")
    try:
        return json.loads(payload or "")
    except (ValueError, TypeError):
        return None


def body(payload: Any) -> Any:
    """The ``data`` envelope every SellerSprite reply wraps its content in."""
    data = parse(payload)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def rows(payload: Any) -> list[dict]:
    """The row list, whether the tool paginates (``data.items``) or not (``data``)."""
    content = body(payload)
    if isinstance(content, list):
        return [r for r in content if isinstance(r, dict)]
    if isinstance(content, dict):
        for key in ("items", "records", "list", "rows"):
            value = content.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def ratio(value: Any, *, field: str = "") -> float | None:
    """Normalise a vendor ratio to a fraction of one."""
    parsed = number(value)
    if parsed is None:
        return None
    if field in _PERCENT_FIELDS:
        return parsed / 100.0
    return parsed


def pounds(value: Any) -> float | None:
    """``"75.4 pounds"`` → 75.4. Freight cost is the reason this matters."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _WEIGHT_RE.search(str(value))
    if not match:
        return number(value)
    amount = float(match.group(1))
    unit = match.group(2).lower().rstrip("s")
    return amount * _TO_POUNDS.get(unit, 1.0)


def month_key(value: Any) -> str:
    """Any of the vendor's month spellings → ``yyyyMM``."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and value > 1_000_000_000:
        return epoch_date(value)[:7].replace("-", "")
    text = str(value).strip()
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 6:
        return digits[:6]
    return ""


def epoch_date(value: Any) -> str:
    """Epoch milliseconds → ``yyyy-MM-dd``; anything already date-shaped passes through."""
    parsed = number(value)
    if parsed is None:
        return str(value or "")[:10]
    if parsed > 1_000_000_000_000:
        parsed /= 1000.0
    try:
        return datetime.fromtimestamp(parsed, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def months_since(date_text: str, *, reference: str = "") -> int | None:
    """Listing age in months — the input to newcomer viability."""
    if not date_text:
        return None
    try:
        year, month = int(date_text[:4]), int(date_text[5:7])
    except (ValueError, IndexError):
        return None
    if reference:
        ref_year, ref_month = int(reference[:4]), int(reference[4:6])
    else:
        now = datetime.now(tz=timezone.utc)
        ref_year, ref_month = now.year, now.month
    return (ref_year - year) * 12 + (ref_month - month)


def _src(reply: Any) -> dict:
    """The provenance kwargs every mint needs, from a gateway reply."""
    return {
        "tool": getattr(reply, "tool", "") or "",
        "call_id": getattr(reply, "call_id", "") or "",
        "arguments": getattr(reply, "arguments", {}) or {},
    }


# ----------------------------------------------------------- category facts ----

# (snapshot column, vendor field, unit, human label). One table instead of forty
# lines of getattr, so adding a metric is a one-line change and the evidence label
# can never drift from the column it describes.
_MARKET_RESEARCH_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("avg_price", "avgPrice", "USD", "类目均价"),
    ("avg_revenue", "avgRevenue", "USD", "单品月均销售额"),
    ("avg_units", "avgUnits", "units", "单品月均销量"),
    ("avg_profit", "avgProfit", "USD", "单品月均毛利"),
    ("avg_rating", "avgRating", "star", "平均评分"),
    ("avg_ratings", "avgRatings", "count", "平均评论数"),
    ("avg_bsr", "avgBsr", "rank", "平均 BSR"),
    ("avg_sellers", "avgSellers", "count", "平均卖家数"),
    ("avg_volume", "avgVolume", "in³", "平均体积"),
    ("avg_weight", "avgWeight", "lb", "平均重量"),
    ("total_products", "totalProducts", "count", "在售商品数"),
    ("total_revenue", "totalRevenue", "USD", "类目月销售额"),
    ("total_units", "totalUnits", "units", "类目月销量"),
    ("brands", "brands", "count", "品牌数"),
    ("sellers", "sellers", "count", "卖家数"),
    ("top5_brand_crn", "top5BrandCrn", "share", "Top5 品牌集中度"),
    ("top10_brand_crn", "top10BrandCrn", "share", "Top10 品牌集中度"),
    ("top5_seller_crn", "top5SellerCrn", "share", "Top5 卖家集中度"),
    ("top10_seller_crn", "top10SellerCrn", "share", "Top10 卖家集中度"),
    ("top5_product_crn", "top5ProductCrn", "share", "Top5 商品集中度"),
    ("top10_product_crn", "top10ProductCrn", "share", "Top10 商品集中度"),
    ("new_count_l12", "l12NewCount", "count", "近 12 月新品数"),
    ("new_ratio_l12", "l12NewRatio", "share", "近 12 月新品占比"),
    ("new_avg_revenue_l12", "l12NewAvgRevenue", "USD", "新品月均销售额"),
    ("new_avg_units_l12", "l12NewAvgSales", "units", "新品月均销量"),
    ("new_avg_reviews_l12", "l12NewAvgReviews", "count", "新品平均评论数"),
    ("new_count_l6", "l6NewCount", "count", "近 6 月新品数"),
    ("new_ratio_l6", "l6NewRatio", "share", "近 6 月新品占比"),
    ("fba_proportion", "fbaProportion", "share", "FBA 占比"),
    ("fbm_proportion", "fbmProportion", "share", "FBM 占比"),
    ("ebc_proportion", "ebcProportion", "share", "A+ 页面占比"),
    ("amazon_self_proportion", "amazonSelfProportion", "share", "亚马逊自营占比"),
    ("return_ratio", "returnRatio", "share", "退货率"),
    ("return_ratio_avg", "avgReturnRatio", "share", "同级类目平均退货率"),
    ("search_purchase_ratio", "searchToPurchaseRatio", "ratio", "搜索购买比"),
)

_STATISTICS_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("hl_avg_price", "hlAvgPrice", "USD", "头部商品均价"),
    ("hl_avg_revenue", "hlAvgRevenue", "USD", "头部商品月均销售额"),
    ("hl_avg_ratings", "hlAvgRatings", "count", "头部商品平均评论数"),
    ("new_product_proportion", "newProductProportion", "share", "新品占比"),
    ("avg_price", "avgPrice", "USD", "类目均价"),
    ("avg_revenue", "avgRevenue", "USD", "单品月均销售额"),
    ("avg_units", "avgUnits", "units", "单品月均销量"),
    ("avg_rating", "avgRating", "star", "平均评分"),
    ("avg_ratings", "avgRatings", "count", "平均评论数"),
    ("avg_bsr", "avgBsr", "rank", "平均 BSR"),
    ("avg_profit", "avgProfit", "USD", "单品月均毛利"),
    ("avg_volume", "avgVolume", "in³", "平均体积"),
    ("avg_weight", "avgWeight", "lb", "平均重量"),
    ("brands", "brands", "count", "品牌数"),
    ("sellers", "sellers", "count", "卖家数"),
    ("total_products", "totalProducts", "count", "在售商品数"),
)

_DEMAND_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("asin_count", "asinCount", "count", "类目 ASIN 数"),
    ("return_ratio", "returnRatio", "share", "退货率"),
    ("return_ratio_avg", "avgReturnRatio", "share", "同级类目平均退货率"),
    ("search_purchase_ratio", "searchToPurchaseRatio", "ratio", "搜索购买比"),
    ("search_purchase_ratio_avg", "avgSearchToPurchaseRatio", "ratio", "同级类目搜索购买比"),
)


def _map_metrics(
    source: dict, mapping: Sequence[tuple[str, str, str, str]], *, reply: Any,
    index: EvidenceIndex | None, node_id_path: str, period: str, field_root: str,
) -> dict:
    out: dict[str, Any] = {}
    for column, vendor_field, unit, label in mapping:
        value = ratio(source.get(vendor_field), field=vendor_field)
        if value is None:
            continue
        out[column] = value
        if index is not None:
            index.mint(subject_kind="node", subject_id=node_id_path, metric=column,
                       label=label, value=value, unit=unit, period=period,
                       field_path=f"{field_root}.{vendor_field}", **_src(reply))
    return out


def extract_market_research(
    reply: Any, *, node_id_path: str, period: str, index: EvidenceIndex | None = None,
) -> dict:
    """One ``market_research`` row → snapshot columns.

    This single call carries the concentration ratios, the newcomer metrics, the
    return rate with its sibling-category average, and the freight profile — five of
    the seven scoring factors come from here.
    """
    matched = [r for r in rows(reply) if str(r.get("nodeIdPath") or "") == node_id_path]
    row = (matched or rows(reply) or [{}])[0]
    return _map_metrics(row, _MARKET_RESEARCH_MAP, reply=reply, index=index,
                        node_id_path=node_id_path, period=period,
                        field_root="$.data.items[0]")


def extract_market_statistics(
    reply: Any, *, node_id_path: str, period: str, index: EvidenceIndex | None = None,
) -> dict:
    content = body(reply)
    row = content if isinstance(content, dict) else {}
    return _map_metrics(row, _STATISTICS_MAP, reply=reply, index=index,
                        node_id_path=node_id_path, period=period, field_root="$.data")


def extract_demand_trend(
    reply: Any, *, node_id_path: str, period: str, index: EvidenceIndex | None = None,
) -> tuple[dict, list[dict]]:
    """Returns ``(snapshot columns, monthly glance-view series)``."""
    content = body(reply)
    row = content if isinstance(content, dict) else {}
    metrics = _map_metrics(row, _DEMAND_MAP, reply=reply, index=index,
                           node_id_path=node_id_path, period=period, field_root="$.data")
    series: list[dict] = []
    for point in (row.get("items") or []):
        if not isinstance(point, dict):
            continue
        key = month_key(point.get("date"))
        views = number(point.get("glanceViews"))
        if key and views is not None:
            series.append({"period": key, "glance_views": views})
    series.sort(key=lambda p: p["period"])
    if series:
        latest = series[-1]["glance_views"]
        metrics["glance_views"] = latest
        if index is not None:
            index.mint(subject_kind="node", subject_id=node_id_path, metric="glance_views",
                       label="页面浏览量", value=latest, unit="views", period=period,
                       field_path="$.data.items[-1].glanceViews", **_src(reply))
    return metrics, series


def extract_distribution(
    reply: Any, *, kind: str, node_id_path: str, period: str,
    index: EvidenceIndex | None = None,
) -> list[dict]:
    """Price / rating / review-count / listing-date / A+ / seller-country buckets."""
    out: list[dict] = []
    for item in rows(reply):
        label = str(item.get("label") or item.get("country") or "").strip()
        if not label:
            continue
        bucket = {
            "bucket_key": label,
            "products": number(item.get("products") or item.get("productNum")
                               or item.get("asinNum")),
            "products_ratio": ratio(item.get("productsRatio") or item.get("asinRatio")),
            "units": number(item.get("units")),
            "units_ratio": ratio(item.get("unitsRatio")),
            "revenue": number(item.get("revenue")),
            "revenue_ratio": ratio(item.get("revenueRatio")),
        }
        if index is not None and bucket["units_ratio"] is not None:
            bucket["evidence_id"] = index.mint(
                subject_kind="node", subject_id=node_id_path,
                metric=f"{kind}_share_{label}", label=f"{kind} {label} 占比",
                value=bucket["units_ratio"], unit="share", period=period,
                field_path=f"$.data[?label={label}].unitsRatio", **_src(reply))
        out.append(bucket)
    return out


def extract_concentration(
    reply: Any, *, kind: str, node_id_path: str, period: str,
    index: EvidenceIndex | None = None,
) -> list[dict]:
    """Brand / seller / seller-type / product concentration rows."""
    out: list[dict] = []
    for position, item in enumerate(rows(reply), start=1):
        entity = str(item.get("brand") or item.get("sellerName") or item.get("label")
                     or item.get("asin") or "").strip()
        if not entity:
            continue
        record = {
            "entity": entity,
            "rank": int(number(item.get("ranking")) or position),
            "products": number(item.get("products") or item.get("productNum")
                               or item.get("asinNum")),
            "units": number(item.get("totalUnits") or item.get("units")),
            "units_ratio": ratio(item.get("totalUnitsRatio") or item.get("unitsRatio")),
            "revenue": number(item.get("totalRevenue") or item.get("revenue")),
            "revenue_ratio": ratio(item.get("totalRevenueRatio") or item.get("revenueRatio")),
            "new_products": number(item.get("newProducts")),
            "new_revenue_ratio": ratio(item.get("newRevenueRatio")),
            "rating": number(item.get("rating")),
            "ratings": number(item.get("ratings")),
        }
        if index is not None and record["revenue_ratio"] is not None and position <= 10:
            record["evidence_id"] = index.mint(
                subject_kind="node", subject_id=node_id_path,
                metric=f"{kind}_share_{entity}", label=f"{entity} 销售额占比",
                value=record["revenue_ratio"], unit="share", period=period,
                field_path=f"$.data[{position - 1}].totalRevenueRatio", **_src(reply))
        out.append(record)
    return out


# ------------------------------------------------------------ product facts ----

_PRODUCT_METRIC_MAP: tuple[tuple[str, str, str, str], ...] = (
    ("price", "price", "USD", "价格"),
    ("units", "units", "units", "月销量"),
    ("revenue", "revenue", "USD", "月销售额"),
    ("profit", "profit", "USD", "毛利"),
    ("bsr", "bsr", "rank", "BSR"),
    ("rating", "rating", "star", "评分"),
    ("ratings", "ratings", "count", "评论数"),
    ("sellers", "sellers", "count", "卖家数"),
    ("lqs", "lqs", "score", "Listing 质量分"),
    ("units_gr", "unitsGr", "share", "销量增长率"),
    ("bsr_cr", "bsrCr", "share", "BSR 变化率"),
    ("ratings_cv", "ratingsCv", "count", "新增评论数"),
)


def extract_products(
    reply: Any, *, node_id_path: str, period: str, marketplace: str = "US",
    index: EvidenceIndex | None = None, evidence_top_n: int = 10,
) -> tuple[list[dict], list[dict]]:
    """One ``product_research`` call → ``(product dimension rows, monthly metrics)``.

    Fifty rows of everything the competitive set needs in a single metered call —
    which is why per-ASIN monthly lookups are not in the collection plan at all.
    """
    products: list[dict] = []
    metrics: list[dict] = []
    for position, item in enumerate(rows(reply)):
        asin = str(item.get("asin") or "").strip()
        if not asin:
            continue
        available = epoch_date(item.get("availableDate"))
        products.append({
            "marketplace": marketplace,
            "asin": asin,
            "title": str(item.get("title") or "")[:400] or None,
            "brand": str(item.get("brand") or "") or None,
            "seller_name": str(item.get("sellerName") or "") or None,
            "seller_nation": str(item.get("sellerNation") or "") or None,
            "node_id_path": str(item.get("nodeIdPath") or node_id_path),
            "fulfillment": str(item.get("fulfillment") or "") or None,
            "available_date": available or None,
            "variations": number(item.get("variations")),
            "dimension": str(item.get("dimension") or "") or None,
            "weight": pounds(item.get("weight")),
            "pkg_dimensions": str(item.get("pkgDimensions") or "") or None,
            "pkg_weight": pounds(item.get("pkgWeight")),
        })
        row: dict[str, Any] = {
            "marketplace": marketplace, "asin": asin, "period": period,
            "node_id_path": node_id_path, "source_tool": getattr(reply, "tool", ""),
        }
        for column, vendor_field, unit, label in _PRODUCT_METRIC_MAP:
            value = ratio(item.get(vendor_field), field=vendor_field)
            if value is None:
                continue
            row[column] = value
            # Evidence only for the visible competitive set: fifty ASINs times a
            # dozen metrics would be six hundred rows the model must read past.
            if index is not None and position < evidence_top_n:
                index.mint(subject_kind="asin", subject_id=asin, metric=column,
                           label=f"{asin} {label}", value=value, unit=unit, period=period,
                           field_path=f"$.data.items[{position}].{vendor_field}",
                           **_src(reply))
        metrics.append(row)
    return products, metrics


def extract_asin_history(
    reply: Any, *, asin: str, marketplace: str = "US", limit: int = 24,
) -> list[dict]:
    """``asin_prediction`` → monthly history rows. One call carries 14 months."""
    content = body(reply)
    months = (content or {}).get("monthItemList") if isinstance(content, dict) else None
    out: list[dict] = []
    for point in (months or [])[-limit:]:
        if not isinstance(point, dict):
            continue
        period = month_key(point.get("date"))
        if not period:
            continue
        for metric, vendor_field in (("units", "sales"), ("revenue", "amount"),
                                     ("price", "price")):
            value = number(point.get(vendor_field))
            if value is None:
                continue
            out.append({
                "marketplace": marketplace, "asin": asin, "period": period,
                "grain": "month", "metric": metric, "value": value,
                # The vendor models volume and money; only price is observed.
                "observed": metric == "price",
                "source_tool": getattr(reply, "tool", "asin_prediction"),
            })
    return out


def extract_reviews(reply: Any, *, asin: str, marketplace: str = "US") -> list[dict]:
    """Reviews as theming input. The prose is never stored — see ``store.replace_review_themes``.

    The vendor returns no review id, so a stable key is derived from the fields that
    together identify one review.
    """
    out: list[dict] = []
    for item in rows(reply):
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        date = epoch_date(item.get("date"))
        out.append({
            "marketplace": marketplace,
            "asin": asin,
            "key": f"{asin}|{item.get('author') or ''}|{date}|{str(item.get('title') or '')[:40]}",
            "author": str(item.get("author") or "")[:80],
            "title": str(item.get("title") or "")[:200],
            "content": content[:1200],
            "date": date,
            "star": int(number(item.get("star")) or 0),
            "verified": bool(item.get("verified")),
            "vine": bool(item.get("vine")),
        })
    return out


# ------------------------------------------------------------ keyword facts ----

def extract_keywords(
    reply: Any, *, period: str, node_id_path: str | None = None, marketplace: str = "US",
    index: EvidenceIndex | None = None, evidence_top_n: int = 12,
) -> list[dict]:
    """``keyword_research`` / ``keyword_miner`` / ``aba_research_*`` → keyword rows.

    One extractor for three tools because the useful columns overlap almost
    entirely; the differences are which of them the tool happens to return.
    """
    tool = getattr(reply, "tool", "")
    out: list[dict] = []
    for position, item in enumerate(rows(reply)):
        keyword = str(item.get("keyword") or item.get("keywords") or "").strip()
        if not keyword:
            continue
        row = {
            "marketplace": marketplace,
            "keyword": keyword,
            "period": month_key(item.get("month") or item.get("date")) or period,
            "grain": "month",
            "node_id_path": node_id_path,
            "searches": number(item.get("searches")),
            "searches_growth": number(item.get("growth") or item.get("searchRankGrowthRate")),
            "search_rank": number(item.get("searchRank")),
            "rank_growth_rate": number(item.get("searchRankGrowthRate")),
            "purchases": number(item.get("purchases")),
            "purchase_rate": number(item.get("purchaseRate")),
            "supply_demand_ratio": number(item.get("supplyDemandRatio")),
            "monopoly_click_rate": number(item.get("monopolyClickRate")
                                          or item.get("clickShareRate")),
            "spr": number(item.get("spr") or item.get("cprExact")),
            "title_density": number(item.get("titleDensity") or item.get("titleDensityExact")),
            "products": number(item.get("products")),
            "avg_price": number(item.get("avgPrice")),
            "bid": number(item.get("bid")),
            "bid_max": number(item.get("bidMax")),
            "market_period": str(item.get("marketPeriod") or "") or None,
            "source_tool": tool,
        }
        if index is not None and position < evidence_top_n and row["searches"]:
            row["evidence_id"] = index.mint(
                subject_kind="keyword", subject_id=keyword, metric="searches",
                label=f"「{keyword}」月搜索量", value=row["searches"], unit="searches",
                period=row["period"], field_path=f"$.data.items[{position}].searches",
                **_src(reply))
            if row["supply_demand_ratio"] is not None:
                index.mint(subject_kind="keyword", subject_id=keyword,
                           metric="supply_demand_ratio", label=f"「{keyword}」供需比",
                           value=row["supply_demand_ratio"], unit="ratio",
                           period=row["period"],
                           field_path=f"$.data.items[{position}].supplyDemandRatio",
                           **_src(reply))
        out.append(row)
    return out


def extract_keyword_edges(
    reply: Any, *, asin: str, period: str, marketplace: str = "US",
    index: EvidenceIndex | None = None, evidence_top_n: int = 8,
) -> list[dict]:
    """``traffic_keyword`` → keyword↔ASIN traffic edges.

    This is what answers "is the incumbent ranking or buying its traffic", which
    decides whether the cost of entry is reviews or ad spend.
    """
    out: list[dict] = []
    for position, item in enumerate(rows(reply)):
        keyword = str(item.get("keyword") or "").strip()
        if not keyword:
            continue
        row = {
            "marketplace": marketplace, "keyword": keyword, "asin": asin, "period": period,
            "traffic_keyword_type": str(item.get("trafficKeywordType") or "") or None,
            "conversion_keyword_type": str(item.get("conversionKeywordType") or "") or None,
            "natural_rank": number(item.get("searchesRank")),
            "ad_position": number(item.get("adPosition")),
            "traffic_percentage": number(item.get("trafficPercentage")),
            "natural_ratio": number(item.get("naturalRatio")),
            "ad_ratio": number(item.get("adRatio")),
            "searches": number(item.get("searches")),
            "purchases": number(item.get("purchases")),
            "purchase_rate": number(item.get("purchaseRate")),
        }
        if index is not None and position < evidence_top_n and row["traffic_percentage"]:
            index.mint(subject_kind="asin", subject_id=asin,
                       metric=f"traffic_share_{keyword}",
                       label=f"{asin} 来自「{keyword}」的流量占比",
                       value=row["traffic_percentage"], unit="share", period=period,
                       field_path=f"$.data.items[{position}].trafficPercentage",
                       **_src(reply))
        out.append(row)
    return out


def extract_traffic_mix(
    reply: Any, *, asin: str, period: str, index: EvidenceIndex | None = None,
) -> dict:
    """``traffic_source`` → the natural / ad / recommendation split.

    The vendor returns keyword *counts* per source, not percentages, so the shares
    are computed here rather than read off.
    """
    items = rows(reply)
    row = items[0] if items else {}
    total = number(row.get("keywords")) or 0.0
    if total <= 0:
        return {}
    natural = number(row.get("searchKeywords")) or 0.0
    ads = number(row.get("adKeywords")) or 0.0
    recommended = sum(number(row.get(key)) or 0.0 for key in
                      ("acKeywords", "editorialKeywords", "fourStarsKeywords",
                       "hrKeywords", "videoKeywords"))
    mix = {
        "keywords": total,
        "natural_proportion": natural / total,
        "ad_proportion": ads / total,
        "recommendation_proportion": recommended / total,
    }
    if index is not None:
        for metric, label in (("natural_proportion", "自然流量词占比"),
                              ("ad_proportion", "广告流量词占比"),
                              ("recommendation_proportion", "推荐位流量词占比")):
            index.mint(subject_kind="asin", subject_id=asin, metric=metric, label=label,
                       value=mix[metric], unit="share", period=period,
                       field_path="$.data.items[0]", sample_size=int(total), **_src(reply))
    return mix


def extract_google_trend(reply: Any, *, keyword: str, limit: int = 24) -> list[dict]:
    """Off-Amazon demand: weekly points collapsed to a monthly mean."""
    buckets: dict[str, list[float]] = {}
    content = body(reply)
    points = (content or {}).get("items") if isinstance(content, dict) else content
    for point in (points or []):
        if not isinstance(point, dict):
            continue
        period = month_key(point.get("time"))
        value = number(point.get("value"))
        if period and value is not None:
            buckets.setdefault(period, []).append(value)
    series = [{"keyword": keyword, "period": period,
               "google_trend_index": sum(values) / len(values)}
              for period, values in sorted(buckets.items())]
    return series[-limit:]


def completeness(collected: Iterable[str], expected: Sequence[str]) -> tuple[float, list[str]]:
    """How much of a month's planned pack actually landed, and what is missing.

    A partial month is a valid, renderable state — the dashboard labels the gaps
    rather than pretending the category has no data.
    """
    done = set(collected)
    missing = [step for step in expected if step not in done]
    if not expected:
        return 1.0, []
    return (len(expected) - len(missing)) / len(expected), missing
