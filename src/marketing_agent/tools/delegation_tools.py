"""Tool schemas the orchestrator exposes — each maps to one sub-agent."""
from __future__ import annotations

DELEGATION_TOOLS = [
    {
        "name": "delegate_to_content_agent",
        "description": (
            "Send a brief to the content/copywriting specialist. Use this for ANY request "
            "to draft marketing copy: social posts, blog drafts, email campaigns, ad copy. "
            "Do NOT write copy yourself — always delegate it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The copywriting brief: what to write, key message, any constraints.",
                },
                "format": {
                    "type": "string",
                    "enum": ["social_post", "blog", "email", "ad_copy", "pdf"],
                    "description": "Channel / format of the copy.",
                },
                "platform": {
                    "type": "string",
                    "enum": [
                        "linkedin",
                        "twitter",
                        "xiaohongshu",
                        "blog",
                        "email",
                        "ad_copy",
                        "pdf",
                        "generic_social",
                    ],
                    "description": (
                        "Optional platform/style skill to apply. Use xiaohongshu for "
                        "小红书/Little Red Book requests, linkedin for B2B LinkedIn posts, "
                        "twitter for X/Twitter posts."
                    ),
                },
                "tone": {
                    "type": "string",
                    "description": "Optional tone descriptor (e.g. 'confident', 'playful', 'authoritative').",
                },
                "audience": {
                    "type": "string",
                    "description": "Optional target audience (e.g. 'B2B SaaS marketers').",
                },
                "length_hint": {
                    "type": "string",
                    "description": "Optional length hint (e.g. '3 variants', '600 words').",
                },
            },
            "required": ["task", "format"],
        },
    },
    {
        "name": "delegate_to_analytics_agent",
        "description": (
            "Send a data-analytics task to the analytics specialist. Use this for any "
            "request that involves analyzing a data file (CSV, Excel, or JSON) of campaign "
            "data, computing KPIs (CTR, ROAS, CPA, etc.), spotting trends, or producing "
            "performance insights. The specialist loads the file in a code-execution "
            "sandbox and can handle large files — never compute metrics yourself."
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
            "Send a market/competitor research task to the research specialist. Use this "
            "for ANY request that requires current external information: industry trends, "
            "competitor announcements, market signals, recent news. The specialist uses "
            "web search and cites sources — never make up external facts."
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
                    "description": "Optional list of competitor names to focus on.",
                },
            },
            "required": ["task", "topics"],
        },
    },
]
