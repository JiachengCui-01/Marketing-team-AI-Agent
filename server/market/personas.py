"""Who sees what: 老板 / 产品经理 / 数据分析, as a server-owned section table.

Three roles want the *same numbers* at different depth and in different order, not
different numbers — so this is gating, not three component trees. The table lives on
the server for two reasons: the frontend has no test runner (``web/package.json``
has only lint and typecheck), and a persona rule that cannot be unit-tested is a
persona rule that will drift.

The frontend cost is one ``<SectionGate>`` and a ``sections`` array in the payload;
each panel renders ``sections.map(renderSection)``, so adding a section is one entry
here and one ``case`` there.
"""
from __future__ import annotations

from typing import Literal

Persona = Literal["boss", "pm", "analyst"]
PERSONAS: tuple[str, ...] = ("boss", "pm", "analyst")
DEFAULT_PERSONA = "pm"

BOSS, PM, ANALYST = "boss", "pm", "analyst"
_ALL = (BOSS, PM, ANALYST)
_PM_UP = (PM, ANALYST)
_ANALYST_ONLY = (ANALYST,)

# The layering invariant, asserted in the tests: boss ⊂ pm ⊂ analyst. The roles
# differ in depth, not in which facts they are allowed to know, so a section
# visible to the boss and hidden from the analyst is always a mistake.

# ``detail`` is a contract with the component: "headline" means render your own
# compact mode (top rows only, no breakdown strip, no metric grid).
# (id, personas, detail, order)
SECTIONS: tuple[tuple[str, tuple[str, ...], str, int], ...] = (
    # ---- 全盘发现 -------------------------------------------------------
    ("overview.headline", _ALL, "full", 10),
    ("overview.thesis", _ALL, "full", 20),
    ("overview.board", _ALL, "headline", 30),
    ("overview.movers", _ALL, "full", 40),
    ("overview.returnrisk", _ALL, "full", 50),
    ("overview.map", _PM_UP, "full", 60),
    ("overview.newproduct", _PM_UP, "full", 70),
    ("overview.price", _PM_UP, "full", 80),
    ("overview.concentration", _ANALYST_ONLY, "full", 90),
    ("overview.budget", _ANALYST_ONLY, "full", 95),
    ("overview.gaps", _PM_UP, "full", 100),
    # ---- 品类深度 -------------------------------------------------------
    ("category.header", _ALL, "full", 110),
    ("category.narrative", _ALL, "full", 120),
    ("category.opportunities", _ALL, "headline", 130),
    ("category.pain", _PM_UP, "full", 140),
    ("category.competitors", _PM_UP, "full", 150),
    ("category.keywords", _PM_UP, "full", 160),
    ("category.structure", _PM_UP, "full", 170),
    ("category.traffic", _ANALYST_ONLY, "full", 180),
    ("category.evidence", _ANALYST_ONLY, "full", 185),
    ("category.gaps", _PM_UP, "full", 190),
)

# The boss reads a verdict, not a leaderboard: the thesis comes before the board,
# and the category narrative before the opportunity list.
PERSONA_ORDER_OVERRIDE: dict[str, dict[str, int]] = {
    BOSS: {"overview.thesis": 15, "category.narrative": 115},
}

# "headline" in the table means "compact for the persona that needs a verdict, not
# a worksheet" — and that persona is the boss. A product manager reading an
# opportunity list without its score breakdown cannot tell a demand-driven score
# from a risk-discounted one, which is most of what the breakdown is for.
_HEADLINE_PERSONAS = {BOSS}


def normalize(persona: str | None) -> str:
    return persona if persona in PERSONAS else DEFAULT_PERSONA


def sections_for(persona: str | None, surface: str) -> list[dict]:
    """The ordered, gated section list for one persona and one surface.

    ``surface`` is the id prefix (``overview`` / ``category``).
    """
    who = normalize(persona)
    overrides = PERSONA_ORDER_OVERRIDE.get(who, {})
    out = []
    for section_id, personas, detail, order in SECTIONS:
        if not section_id.startswith(f"{surface}."):
            continue
        if who not in personas:
            continue
        out.append({
            "id": section_id,
            "detail": detail if who in _HEADLINE_PERSONAS else "full",
            "order": overrides.get(section_id, order),
        })
    out.sort(key=lambda s: s["order"])
    return out


def hidden_count(persona: str | None, surface: str) -> int:
    """How many sections this persona is not shown — the UI says so in a footer,
    because a silently shorter page reads as a broken page."""
    total = len([s for s in SECTIONS if s[0].startswith(f"{surface}.")])
    return total - len(sections_for(persona, surface))


def describe() -> list[dict]:
    """Persona metadata for the settings dialog and the view switch."""
    return [
        {"id": BOSS, "label_zh": "老板视角", "label_en": "Executive",
         "hint_zh": "一屏读完：该不该进、风险在哪、下一步做什么",
         "hint_en": "One screen: enter or not, where the risk is, what to do next"},
        {"id": PM, "label_zh": "产品经理视角", "label_en": "Product manager",
         "hint_zh": "机会、关键词、竞品、评论痛点，以及生成产品定义书",
         "hint_en": "Opportunities, keywords, competitors, pain points, and the PRD"},
        {"id": ANALYST, "label_zh": "数据分析视角", "label_en": "Analyst",
         "hint_zh": "全部指标、样本量与质量标记、证据抽屉、厂商调用与配额",
         "hint_en": "Every metric, sample sizes and quality flags, evidence, vendor spend"},
    ]


def all_section_ids(surface: str | None = None) -> list[str]:
    return [s[0] for s in SECTIONS if surface is None or s[0].startswith(f"{surface}.")]
