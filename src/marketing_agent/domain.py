"""Business domain vocabulary — the single source of truth for prompt wording.

The company this workspace serves designs large furniture in-house, has it built
by contract suppliers, and sells it direct-to-consumer into the United States.
Every agent prompt, skill definition, and tool schema pulls its nouns from here
so the whole system speaks with one voice: if the product line, channel mix, or
KPI set changes, this file changes and the prompts follow.

The brand name is deliberately a placeholder — see ``BRAND``.
"""
from __future__ import annotations

# Placeholder for the company/brand name. Swap this for the real name (or read it
# from the environment) once it is decided; every prompt interpolates it.
BRAND = "[BRAND]"

BUSINESS_SUMMARY = (
    f"{BRAND} is a design-led large-furniture brand selling direct to consumers in the "
    "United States. The company designs its own pieces in house, has them manufactured "
    "by contract suppliers in Asia, imports them, and sells through its own Shopify site "
    "plus marketplaces (Amazon, Wayfair) and social channels. There is no reseller or "
    "wholesale motion — the buyer is the person who will live with the furniture."
)

# Sales and marketing channels, in rough order of revenue importance.
CHANNELS = (
    "Amazon",
    "Wayfair / Overstock",
    "own Shopify store (DTC site)",
    "Instagram",
    "Pinterest",
    "TikTok",
    "email / EDM",
    "Google Shopping",
    "Meta Ads",
    "blog / organic search",
)

# Product line. Everything is bulky, shipped freight, and assembled by the buyer.
PRODUCT_CATEGORIES = (
    "sofas and sectionals",
    "bed frames and headboards",
    "dining tables and chairs",
    "storage cabinets and sideboards",
    "desks",
    "coffee and side tables",
)

# The attributes that actually decide a furniture purchase.
PRODUCT_ATTRIBUTES = (
    "overall dimensions and footprint",
    "materials (solid wood, engineered wood, upholstery fabric, metal)",
    "construction and joinery quality",
    "weight capacity",
    "assembly requirement and time",
    "finish and colorway options",
)

AUDIENCES = (
    "US homeowners furnishing or upgrading a room",
    "renters who need pieces that fit a small or awkward space",
    "first-time buyers furnishing a new apartment or house",
    "people who just moved and are replacing furniture",
    "design-minded shoppers browsing for room inspiration",
)

# Metrics that matter for a high-AOV, freight-shipped, high-return-cost product.
KPIS = (
    "ACOS and TACOS (ad cost of sale, total ad cost of sale)",
    "conversion rate by channel and by listing",
    "AOV (average order value)",
    "return rate and the reasons behind returns",
    "review volume and average rating",
    "gross margin after landed cost (FOB, ocean freight, drayage, LTL delivery)",
    "inventory turns and out-of-stock rate",
)

# Things a generic marketing tool gets wrong about large furniture. These are the
# guardrails worth repeating in prompts.
DOMAIN_RULES = (
    "Dimensions are the single most common reason a shopper hesitates or returns — "
    "state them plainly and early, and never guess them.",
    "Delivery is freight, not parcel: LTL curbside, threshold, or white-glove. Say "
    "which one applies rather than implying it ships like a small package.",
    "Assembly effort and required tools materially affect reviews — be honest about them.",
    "A return costs more than the margin on the order, so copy must set accurate "
    "expectations instead of maximizing clicks.",
    "Reviews and ratings drive marketplace conversion more than ad copy does.",
    "Compliance matters: CPSC tip-over and flammability rules, Prop 65 where relevant, "
    "and tariff/AD-CVD exposure on imported furniture.",
)

# Never invent these. Copy that fabricates a spec creates a return and a bad review.
NEVER_FABRICATE = (
    "dimensions",
    "materials",
    "weight capacity",
    "assembly time",
    "delivery timelines",
    "certifications",
    "warranty terms",
)


def _bullets(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items)


def business_context_block() -> str:
    """The shared preamble injected into every agent's system prompt."""
    return "\n".join(
        [
            "## Business context",
            "",
            BUSINESS_SUMMARY,
            "",
            f"Product line: {', '.join(PRODUCT_CATEGORIES)}.",
            f"Channels: {', '.join(CHANNELS)}.",
            "",
            "Audiences:",
            _bullets(AUDIENCES),
            "",
            "What matters in this category:",
            _bullets(DOMAIN_RULES),
            "",
            "Never state a specific "
            + ", ".join(NEVER_FABRICATE)
            + " unless it appears in the user's brief, an attached file, or a cited "
            "source. If a figure is missing, write a clearly marked placeholder such as "
            "[confirm dimensions] instead of inventing one.",
        ]
    )


def kpi_block() -> str:
    """KPI guidance for the analytics agent and any KPI-aware prompt."""
    return "\n".join(["Metrics that matter in this business:", _bullets(KPIS)])
