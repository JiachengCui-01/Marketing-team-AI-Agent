"""``returnFields`` registry — the one lever that shrinks a vendor payload at the source.

Every SellerSprite tool accepts ``returnFields``: a comma-separated list of the keys
to return. Nothing in this repo ever set it, which costs three different things:

1. **Bytes.** An unpruned ``product_research`` row carries ~46 fields; at ``size=50``
   that is ~105 KB per call, most of it fields no view or score reads.
2. **Correctness on the agent path.** ``sellersprite.format_result`` truncates at
   ``MAX_RESULT_CHARS = 20_000``, so an unpruned 50-row reply reaches the model cut
   off mid-object — invalid JSON, silently. Pruned, the same call fits whole.
3. **Prompt weight.** Field-name noise is most of an untrimmed payload and none of
   it is citable.

The field names below are **observed**, not guessed: they were captured from live
replies for one furniture node and checked in under ``tests/fixtures/sellersprite/``.
Anything absent from a fixture is absent here too.

Field names are a vendor contract this repo does not own. ``on_empty_retry_args``
exists because a rename would otherwise turn every call into a silent empty and the
warehouse would record a month of gaps instead of an error.
"""
from __future__ import annotations

# Keyed by vendor tool name. A tool with no entry is called unpruned — correct by
# default, just larger. Nested containers (``items``, ``asins``) are never listed:
# the vendor applies returnFields to the row objects, and naming a container has no
# effect, while omitting one that carries the rows would empty the reply.
FIELD_SETS: dict[str, tuple[str, ...]] = {
    # ---- category structure -------------------------------------------------
    # One call carries the concentration ratios (top5*Crn), newcomer viability
    # (l1/l3/l6/l12New*), the return rate with its sibling-category average, and
    # the freight profile — five of the seven scoring factors.
    "market_research": (
        "marketplace", "nodeId", "nodeIdPath", "nodeLabelPath", "nodeLabelPathLocale",
        "totalProducts", "brands", "sellers", "totalUnits", "totalRevenue",
        "avgUnits", "avgRevenue", "avgPrice", "avgRatings", "avgRating", "avgBsr",
        "avgVolume", "avgWeight", "avgProfit", "avgSellers",
        "ebcProportion", "amazonSelfProportion", "fbaProportion", "fbmProportion",
        "returnRatio", "avgReturnRatio", "searchToPurchaseRatio",
        "top5BrandCrn", "top5SellerCrn", "top5ProductCrn", "top10BrandCrn",
        "top5BrandRevenue", "top5SellerRevenue",
        "l3NewRatio", "l6NewRatio",
        "l12NewRatio", "l12NewCount", "l12NewAvgSales", "l12NewAvgRevenue",
        "l12NewAvgReviews", "l12NewAvgRating", "l12NewAvgPrice",
    ),
    "market_research_statistics": (
        "marketplace", "nodeIdPath", "nodeLabelPath", "currency",
        "totalProducts", "products", "brands", "sellers",
        "avgBsr", "avgVolume", "avgWeight", "avgProfit", "avgUnits", "avgRevenue",
        "avgPrice", "avgRatings", "avgRating", "avgRatingsCv", "avgSellers",
        "hlProducts", "hlAvgBsr", "hlAvgUnits", "hlAvgRevenue", "hlAvgPrice",
        "hlAvgRatings", "hlAvgRating",
        "newProducts", "newProductProportion", "newAvgPrice", "newAvgRatings",
        "newAvgRating", "newAvgUnits", "newAvgRevenue",
        "firstShelfDate", "lastShelfDate",
    ),
    # Deliberately unpruned: the whole reply is under 1 KB and its payload is a
    # nested {summary + items[]} shape that returnFields does not address.
    "market_product_demand_trend": (),

    # ---- distributions ------------------------------------------------------
    # ``asins`` is the sample-ASIN array and is the bulk of these replies; the
    # buckets are what the charts and the price-band score read.
    "market_price_distribution": ("label", "products", "units", "revenue", "unitsRatio"),
    "market_rating_distribution": ("label", "products", "units", "revenue", "unitsRatio"),
    "market_ratings_count_distribution": ("label", "products", "units", "revenue", "unitsRatio"),
    "market_listing_date_distribution": (
        "label", "shelfTime", "products", "units", "revenue", "unitsRatio",
    ),
    "market_ebc_distribution": ("label", "products", "productsRatio", "units", "unitsRatio"),
    "market_seller_country_distribution": (
        "label", "country", "products", "units", "revenue", "unitsRatio", "revenueRatio",
    ),
    "market_listing_trend_distribution": ("label", "products", "units", "revenue", "unitsRatio"),

    # ---- concentration ------------------------------------------------------
    "market_brand_concentration": (
        "brand", "ranking", "products", "newProducts", "newUnits", "newRevenue",
        "newUnitsRatio", "newRevenueRatio", "avgPrice", "ratings", "rating", "reviews",
        "totalUnits", "totalRevenue", "totalUnitsRatio", "totalRevenueRatio",
    ),
    "market_seller_concentration": (
        "sellerName", "ranking", "products", "newProducts", "newUnits", "newRevenue",
        "newUnitsRatio", "newRevenueRatio", "avgPrice", "ratings", "rating", "reviews",
        "totalUnits", "totalRevenue", "totalUnitsRatio", "totalRevenueRatio",
    ),
    "market_seller_type_concentration": (
        "label", "asinNum", "asinRatio", "units", "unitsRatio", "ratings", "rating",
        "productNum",
    ),
    "market_product_concentration": (
        "asin", "title", "brand", "ranking", "totalUnits", "totalRevenue",
        "totalUnitsRatio", "totalRevenueRatio", "avgPrice", "rating", "ratings",
    ),

    # ---- products -----------------------------------------------------------
    # 50 rows of this is the highest-yield call the vendor has: it fills a whole
    # month of per-ASIN metrics, and it carries dimension/weight, so the cheap
    # sweep already knows the freight profile without a per-ASIN asin_detail.
    "product_research": (
        "asin", "brand", "title", "imageUrl", "nodeId", "nodeIdPath", "nodeLabelPath",
        "bsr", "bsrCv", "bsrCr", "units", "unitsGr", "revenue", "price", "averagePrice",
        "profit", "fba", "ratings", "ratingsRate", "rating", "ratingsCv", "ratingDelta",
        "availableDate", "fulfillment", "variations", "sellers", "sellerName",
        "sellerNation", "lqs", "weight", "dimension", "pkgWeight", "pkgDimensions",
    ),
    "competitor_lookup": (
        "asin", "brand", "title", "nodeIdPath", "bsr", "units", "revenue", "price",
        "rating", "ratings", "sellerName", "sellerNation", "fulfillment", "variations",
        "availableDate",
    ),
    "asin_detail": (
        "asin", "title", "brand", "availableDate", "firstRatingDate",
        "bsrRank", "bsrLabel", "nodeId", "nodeIdPath", "nodeLabelPath",
        "dimensions", "weight", "price", "primePrice", "deliveryPrice", "coupon",
        "rating", "ratings", "reviews", "questions", "sellers", "sellerName",
        "fulfillment", "variations", "lqs", "imageUrl",
    ),
    # Nested {asinDetail, monthItemList[], dailyItemList[]}; dailyItemList is ~400
    # rows and is the bulk, but returnFields cannot address a nested container, so
    # this one is pruned at extraction instead.
    "asin_prediction": (),
    "asin_sales_trend": (),
    "keepa_info": (),
    "asin_competitor": ("asin", "title", "brand", "price", "rating", "ratings", "bsr"),

    # ---- keywords -----------------------------------------------------------
    # ``topAsins`` is a nested array on every keyword row and roughly doubles the
    # payload; nothing downstream reads it.
    "keyword_research": (
        "keywords", "month", "searches", "purchases", "growth", "purchaseRate",
        "products", "supplyDemandRatio", "avgPrice", "avgRatings", "avgRating",
        "bid", "bidMin", "bidMax", "araClickRate", "araShareRate", "goodsValue",
        "marketPeriod", "titleDensityExact", "searchMonthlyCr", "searchNearlyCr",
        "hasBrandWord",
    ),
    "keyword_miner": (
        "keyword", "month", "searches", "purchases", "purchaseRate",
        "monopolyClickRate", "products", "adProducts", "supplyDemandRatio",
        "avgPrice", "avgRatings", "avgRating", "bid", "bidMin", "bidMax",
        "wordCount", "titleDensity", "spr", "relevancy", "amazonChoice", "searchRank",
    ),
    "keyword_conversion": (
        "keyword", "searches", "purchases", "conversionRate", "clickConvRate",
        "searchConvRate", "ppc", "acos", "cpa", "clicks", "clickingRate",
        "productPrice", "phraseCount",
    ),
    "aba_research_monthly": (
        "keyword", "date", "searchRank", "searchRankCv", "searchRankCr", "searches",
        "purchases", "purchaseRate", "clicks", "impressions",
        "searchRankGrowthValue", "searchRankGrowthRate",
        "cvsShareRate", "clickShareRate", "titleDensityExact", "cprExact",
        "bid", "bidMin", "bidMax",
    ),
    "aba_research_weekly": (
        "keyword", "date", "searchRank", "searchRankCv", "searchRankCr", "searches",
        "purchases", "purchaseRate", "searchRankGrowthRate", "cvsShareRate",
        "clickShareRate", "titleDensityExact", "bid",
    ),
    "keyword_research_trends": (),
    "aba_research_trend": (),
    "google_trend": (),

    # ---- traffic ------------------------------------------------------------
    "traffic_keyword": (
        "keyword", "searches", "products", "purchases", "purchaseRate",
        "bid", "bidMin", "bidMax", "adPosition", "searchesRank", "supplyDemandRatio",
        "trafficPercentage", "trafficKeywordType", "conversionKeywordType",
        "titleDensity", "spr", "monopolyClickRate",
        "top3ClickingRate", "top3ConversionRate", "naturalRatio", "adRatio",
    ),
    "traffic_source": (
        "keywords", "searchKeywords", "acKeywords", "editorialKeywords",
        "fourStarsKeywords", "hrKeywords", "adKeywords", "videoKeywords",
        "brandKeywords",
    ),
    "traffic_keyword_stat": (),
    "traffic_listing": (
        "asin", "title", "brand", "keywords", "naturalKeywords", "adKeywords",
    ),

    # ---- reviews ------------------------------------------------------------
    # No review id is returned, so ``store`` derives a dedupe key from
    # (asin, author, date, title). ``videos``/``image``/``video`` are media URLs.
    "review": ("author", "title", "content", "date", "star", "verified", "vine"),

    # ---- taxonomy -----------------------------------------------------------
    "product_node": ("nodeIdPath", "nodeLabelPath", "products"),
}

# Tools whose replies are already small enough that pruning buys nothing, or whose
# payload is nested past where returnFields reaches. Listed explicitly so an empty
# tuple reads as a decision rather than an omission.
UNPRUNED = frozenset(tool for tool, fields in FIELD_SETS.items() if not fields)


def as_param(tool: str) -> str:
    """The ``returnFields`` value for ``tool``, or ``""`` when it should not be set."""
    return ",".join(FIELD_SETS.get(tool, ()))


def apply(tool: str, arguments: dict) -> dict:
    """Return ``arguments`` with ``returnFields`` injected where the tool supports it.

    Never overwrites a caller-supplied ``returnFields``. Handles both argument
    shapes the vendor uses: flat (``{"marketplace": …}``) and nested
    (``{"request": {…}}``).
    """
    value = as_param(tool)
    if not value:
        return arguments
    if "request" in arguments and isinstance(arguments["request"], dict):
        inner = dict(arguments["request"])
        inner.setdefault("returnFields", value)
        return {**arguments, "request": inner}
    out = dict(arguments)
    out.setdefault("returnFields", value)
    return out


def strip(arguments: dict) -> dict:
    """Return ``arguments`` without ``returnFields``, for the field-drift retry."""
    if "request" in arguments and isinstance(arguments["request"], dict):
        inner = {k: v for k, v in arguments["request"].items() if k != "returnFields"}
        return {**arguments, "request": inner}
    return {k: v for k, v in arguments.items() if k != "returnFields"}


def has_fields(arguments: dict) -> bool:
    """True when ``arguments`` carries a ``returnFields`` value we injected."""
    inner = arguments.get("request") if isinstance(arguments.get("request"), dict) else arguments
    return bool(inner.get("returnFields"))
