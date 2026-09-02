"""Tool schemas the orchestrator exposes — each maps to one sub-agent."""
from __future__ import annotations

DELEGATION_TOOLS = [
    {
        "name": "delegate_to_content_agent",
        "description": (
            "Send a brief to the content/copywriting specialist. Use this for ANY request "
            "to draft customer-facing copy: marketplace listings, product pages, social "
            "posts, video scripts, email, ads, blog guides, or PDF deliverables such as a "
            "spec sheet or catalog page. Do NOT write copy yourself — always delegate it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The copywriting brief: what to write, which product, key message, "
                        "and any known specs (dimensions, materials, finish, assembly, "
                        "delivery method). Pass through every spec the user gave — the "
                        "specialist is forbidden from inventing them."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": [
                        "listing",
                        "product_page",
                        "social_post",
                        "blog",
                        "email",
                        "ad_copy",
                        "pdf",
                    ],
                    "description": "Channel / format of the copy.",
                },
                "platform": {
                    "type": "string",
                    "enum": [
                        "amazon_listing",
                        "wayfair_listing",
                        "dtc_product_page",
                        "instagram",
                        "pinterest",
                        "tiktok",
                        "blog",
                        "email",
                        "ad_copy",
                        "pdf",
                        "generic_social",
                    ],
                    "description": (
                        "Optional channel/style skill to apply. Use amazon_listing for "
                        "Amazon titles/bullets/A+, wayfair_listing for Wayfair or "
                        "Overstock attribute copy, dtc_product_page for our own store's "
                        "product detail page, pinterest for search-driven room "
                        "inspiration pins, tiktok for short video scripts."
                    ),
                },
                "tone": {
                    "type": "string",
                    "description": "Optional tone descriptor (e.g. 'warm', 'understated', 'confident').",
                },
                "audience": {
                    "type": "string",
                    "description": (
                        "Optional target audience (e.g. 'US renters furnishing a small "
                        "apartment', 'homeowners replacing a worn sectional')."
                    ),
                },
                "length_hint": {
                    "type": "string",
                    "description": "Optional length hint (e.g. '3 variants', '1200 words').",
                },
            },
            "required": ["task", "format"],
        },
    },
    {
        "name": "delegate_to_analytics_agent",
        "description": (
            "Send a data-analytics task to the analytics specialist. Use this for any "
            "request that involves analyzing a data file (CSV, Excel, or JSON) of sales, "
            "advertising, listing, or returns data — computing ACOS/TACOS, conversion "
            "rate, AOV, return rate, margin after landed cost, or inventory turns, "
            "spotting trends, and producing performance insights. The specialist runs "
            "pandas over the file and can handle large datasets — never compute metrics "
            "yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What the analyst should investigate or report on.",
                },
                "data_path": {
                    "type": "string",
                    "description": (
                        "Path to the uploaded data file (CSV, Excel .xlsx/.xls, or JSON). "
                        "Use the path noted next to the attached data file."
                    ),
                },
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of specific questions the analysis should answer.",
                },
            },
            "required": ["task", "data_path"],
        },
    },
    {
        "name": "delegate_to_research_agent",
        "description": (
            "Send a market/competitor/product-selection task to the research specialist. "
            "Use this for ANY request that needs external market data or facts, including: "
            "competitor research and listing comparison; product-selection and niche "
            "analysis (选品/选品分析/机会品类); an ASIN's price, BSR, rating, review count, "
            "or their history; keyword search volume, keyword mining, and traffic sources; "
            "category size, demand trend, brand/seller concentration, price bands; US "
            "furniture and home-furnishings demand and style trends; marketplace policy "
            "changes, tariffs and duties, product-safety rules. The specialist queries "
            "SellerSprite (卖家精灵) as its primary data source and falls back to web "
            "search and live page browsing only for what SellerSprite cannot answer. "
            "Never answer these from memory yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What to research, framed as a question or directive.",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topics or themes to investigate.",
                },
                "competitors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of competing brands or sellers to focus on "
                        "(e.g. Article, Castlery, Burrow, West Elm, or an Amazon seller)."
                    ),
                },
            },
            "required": ["task", "topics"],
        },
    },
]
