"""产品定义书 (PRD) generation — the end of the chain, and the most dangerous page.

Everything upstream reports what the market *is*. A PRD describes a product that
does not exist yet, which is exactly where a language model will happily supply a
dimension, a carton plan, or an FOB cost that reads perfectly and is invented.

So the enforcement here is not advisory. The prompt asks for placeholders; the
server then **overwrites** the fields anyway:

* physical specs (dimension, material, load, assembly, carton) become
  ``[待确认 …]`` unless they are a competitor's observed attribute with a live
  evidence id, and even then they are labelled as a competitor reference;
* cost and margin are *always* placeholders — the vendor has no cost data, and a
  plausible-looking landed cost is the single most expensive hallucination this
  product could ship. Whatever the model wrote is demoted into ``assumptions``
  with an explicit "unsupported inference" prefix;
* a differentiator without a resolvable citation is forced to ``to_validate``;
* every placeholder gets a row in the validation plan, generated if the model
  forgot.

``domain.NEVER_FABRICATE`` is the same list the content agent obeys; this module is
its enforcement point for the product-definition surface.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from marketing_agent.domain import NEVER_FABRICATE
from marketing_agent.source_policy import data_gap_message

from . import evidence as ev
from . import gateway, render, store, taxonomy

logger = logging.getLogger(__name__)

TOOL_NAME = "publish_product_definition"

# field key -> (placeholder, what the validation row should ask)
PLACEHOLDERS: dict[str, tuple[str, str]] = {
    "dimensions": ("[待确认 尺寸]", "确认整体尺寸与内部净空"),
    "materials": ("[待确认 材质]", "确认板材/饰面/五金材质与供应商"),
    "load_capacity": ("[待确认 承重]", "确认层板与整机承重测试值"),
    "assembly_parts": ("[待确认 组装件数]", "确认组装件数与包装拆分"),
    "assembly_minutes": ("[待确认 组装时长]", "实测单人组装时长"),
    "carton_plan": ("[待确认 箱规]", "确认箱规、体积重与跌落测试方案"),
    "landed_cost": ("[待确认 落地成本]", "向供应商询价并核算到岸成本"),
    "gross_margin": ("[待确认 毛利区间]", "按目标零售价与到岸成本核算毛利区间"),
}

_UNSUPPORTED_PREFIX = "模型推断（未经证据支持）："
_UNSUPPORTED_PREFIX_EN = "Model inference (not evidence-backed): "

_EVIDENCE_IDS = {"type": "array", "items": {"type": "string"}}

TOOL = {
    "name": TOOL_NAME,
    "description": "Publish the product definition for one scored opportunity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "positioning": {"type": "string"},
            "target_user": {"type": "string"},
            "use_scenario": {"type": "string"},
            "opportunity_basis": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"}, "evidence_ids": _EVIDENCE_IDS,
            }, "required": ["claim", "evidence_ids"]}},
            "target_price_band": {"type": "string", "description":
                                  "Must sit inside an observed price band."},
            "price_rationale": {"type": "string"},
            "dimensions": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
                "source": {"enum": ["to_confirm", "competitor_observed"]},
                "evidence_ids": _EVIDENCE_IDS,
            }, "required": ["name", "source"]}},
            "materials": {"type": "array", "items": {"type": "object", "properties": {
                "part": {"type": "string"},
                "material": {"type": "string"},
                "source": {"enum": ["to_confirm", "competitor_observed"]},
                "evidence_ids": _EVIDENCE_IDS,
            }, "required": ["part", "source"]}},
            "load_capacity": {"type": "string"},
            "structure_notes": {"type": "string"},
            "assembly": {"type": "object", "properties": {
                "parts_count": {"type": "string"}, "est_minutes": {"type": "string"},
                "tool_free": {"type": "string"}, "notes": {"type": "string"},
                "evidence_ids": _EVIDENCE_IDS,
            }},
            "packaging": {"type": "object", "properties": {
                "carton_plan": {"type": "string"},
                "fragile_points": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
                "evidence_ids": _EVIDENCE_IDS,
            }},
            "differentiators": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"},
                "backing": {"enum": ["pain_point", "keyword_gap", "price_gap",
                                     "to_validate"]},
                "evidence_ids": _EVIDENCE_IDS,
            }, "required": ["claim", "backing"]}},
            "economics": {"type": "object", "properties": {
                "target_landed_cost_range": {"type": "string"},
                "target_gross_margin_range": {"type": "string"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
            }},
            "risks": {"type": "array", "items": {"type": "object", "properties": {
                "risk": {"type": "string"},
                "kind": {"enum": ["return", "competition", "entrenchment",
                                  "seasonality", "compliance", "cost"]},
                "evidence_ids": _EVIDENCE_IDS,
            }, "required": ["risk", "kind"]}},
            "validation_plan": {"type": "array", "items": {"type": "object", "properties": {
                "question": {"type": "string"}, "method": {"type": "string"},
                "decision_rule": {"type": "string"},
            }, "required": ["question"]}},
            "gaps": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "positioning", "target_user", "target_price_band",
                     "differentiators", "risks", "validation_plan"],
    },
}

_PRD_RULES = f"""
HARD RULE — physical specs and money. SellerSprite holds no dimension, material,
load, assembly-time, carton, cost or margin data for a product that does not exist
yet. Write exactly these strings in those fields:
{", ".join(value[0] for value in PLACEHOLDERS.values())}
A plausible-looking dimension is a return and a one-star review; a plausible-looking
landed cost is a product programme built on a number nobody measured.
You may describe a COMPETITOR's dimension or material when it is in the evidence
index: label it source="competitor_observed" with its evidence id, and phrase it as
a competitor reference, never as our specification.
Never fabricate: {", ".join(NEVER_FABRICATE)}.
Every placeholder you write must have a matching row in validation_plan.
"""


def _placeholder(key: str) -> str:
    return PLACEHOLDERS[key][0]


def generate_prd(
    *, user_id: str, node_id_path: str, opportunity_id: str = "",
    marketplace: str = "US", period: str | None = None, language: str = "zh",
    client=None,
) -> dict:
    """Build one PRD from stored evidence. Makes zero vendor calls."""
    period = (period or store.latest_period(marketplace, node_id_path)
              or gateway.previous_period())
    snapshot = store.get_node_snapshot(marketplace, node_id_path, period)
    if not snapshot:
        raise render.RenderError("no snapshot for this category and period")

    payload = render.build_category(marketplace, node_id_path, period, language)
    # build_category returns the deterministic half only. The design directives
    # are the category read's conclusion about what to build differently, and
    # they live on the saved dashboard — carried forward here so the PRD does not
    # re-derive them from the same evidence one call later and drift.
    stored = store.latest_dashboard(marketplace=marketplace, scope="category",
                                    language=language, node_id_path=node_id_path,
                                    period=period)
    payload["design_directives"] = (
        (stored or {}).get("dashboard", {}).get("design_directives") or [])
    opportunity = _pick_opportunity(payload["opportunities"], opportunity_id)
    if opportunity is None:
        raise render.RenderError("no scored opportunity for this category")

    index = ev.index_from_rows(
        render._evidence_for_category(marketplace, node_id_path, period, payload),
        marketplace=marketplace, period=period)
    if not index:
        # Nothing citable: a PRD assembled from no evidence is a wish list.
        return store.add_prd(
            user_id=user_id, marketplace=marketplace, node_id_path=node_id_path,
            period=period, language=language, opportunity_id=opportunity["id"],
            title=opportunity["title"], prd={"status": "data_gap"},
            assumptions=[], evidence_ids=[], notes=[data_gap_message(language)])

    user = "\n\n".join([
        f"CATEGORY: {payload['header']['node_label_path']}   PERIOD: {period}",
        _opportunity_brief(opportunity, payload, language),
        index.sheet(language=language),
    ])
    system = (render._SYSTEM_BASE + _PRD_RULES
              + render._LANGUAGE_CLAUSE.get(language, render._LANGUAGE_CLAUSE["zh"]))
    if client is None:
        raw, source = {}, "unavailable"
    else:
        try:
            response = render._call_model(client, system=system, tool=TOOL, user=user,
                                          max_tokens=8000)
            raw = render._parse(response, TOOL_NAME) or {}
            source = "llm" if raw else "no_tool_call"
        except Exception as exc:  # noqa: BLE001
            logger.warning("PRD generation failed: %s", exc)
            raw, source = {}, "error"

    # Differentiators bypass the generic citation sweep. That pass deletes any
    # object whose evidence_ids do not resolve, which is right for a factual claim
    # and wrong here: an unsupported design hypothesis is still worth keeping, it
    # just has to be labelled to_validate. ``enforce`` applies that rule instead.
    raw = dict(raw) if isinstance(raw, dict) else {}
    hypotheses = raw.pop("differentiators", None)
    cleaned, dropped = ev.validate_citations(raw, index.ids())
    if hypotheses is not None:
        cleaned["differentiators"] = hypotheses
    document, assumptions, notes = enforce(cleaned, index=index, language=language)
    notes += ev.citation_notes(dropped, language)
    document["source"] = source
    document["opportunity"] = {
        "id": opportunity["id"], "anchor_asin": opportunity["anchor_asin"],
        "product_score": opportunity["product_score"],
        "score_breakdown": opportunity["score_breakdown"],
        "score_confidence": opportunity["score_confidence"],
    }
    document["category"] = {
        "node_id_path": node_id_path,
        "node_label_path": payload["header"]["node_label_path"],
        "label": taxonomy.short_label(payload["header"]["node_label_path"]),
        "category_score": payload["header"]["category_score"],
    }
    return store.add_prd(
        user_id=user_id, marketplace=marketplace, node_id_path=node_id_path,
        period=period, language=language, opportunity_id=opportunity["id"],
        title=document.get("title") or opportunity["title"], prd=document,
        assumptions=assumptions, evidence_ids=sorted(_cited_ids(document)), notes=notes)


def enforce(document: dict, *, index: ev.EvidenceIndex, language: str = "zh"
            ) -> tuple[dict, list[str], list[str]]:
    """Apply every hard rule. Returns ``(document, assumptions, notes)``.

    Separated from :func:`generate_prd` so the rules can be tested without a model.
    """
    out = dict(document or {})
    notes: list[str] = []
    assumptions: list[str] = list(
        ((out.get("economics") or {}).get("assumptions") or []))
    placeholders_used: list[str] = []

    # --- physical specs -----------------------------------------------------
    dimensions = []
    for item in out.get("dimensions") or []:
        entry = dict(item)
        if not _competitor_backed(entry, index):
            entry["source"] = "to_confirm"
            entry["value"] = _placeholder("dimensions")
            entry["evidence_ids"] = []
            placeholders_used.append("dimensions")
        dimensions.append(entry)
    if not dimensions:
        dimensions = [{"name": "整体尺寸" if language == "zh" else "Overall dimensions",
                       "value": _placeholder("dimensions"), "source": "to_confirm",
                       "evidence_ids": []}]
        placeholders_used.append("dimensions")
    out["dimensions"] = dimensions

    materials = []
    for item in out.get("materials") or []:
        entry = dict(item)
        if not _competitor_backed(entry, index):
            entry["source"] = "to_confirm"
            entry["material"] = _placeholder("materials")
            entry["evidence_ids"] = []
            placeholders_used.append("materials")
        materials.append(entry)
    if not materials:
        materials = [{"part": "柜体" if language == "zh" else "Case",
                      "material": _placeholder("materials"), "source": "to_confirm",
                      "evidence_ids": []}]
        placeholders_used.append("materials")
    out["materials"] = materials

    out["load_capacity"] = _placeholder("load_capacity")
    placeholders_used.append("load_capacity")

    assembly = dict(out.get("assembly") or {})
    assembly["parts_count"] = _placeholder("assembly_parts")
    assembly["est_minutes"] = _placeholder("assembly_minutes")
    placeholders_used += ["assembly_parts", "assembly_minutes"]
    out["assembly"] = assembly

    packaging = dict(out.get("packaging") or {})
    packaging["carton_plan"] = _placeholder("carton_plan")
    placeholders_used.append("carton_plan")
    out["packaging"] = packaging

    # --- money --------------------------------------------------------------
    economics = dict(out.get("economics") or {})
    prefix = _UNSUPPORTED_PREFIX if language == "zh" else _UNSUPPORTED_PREFIX_EN
    for field, key in (("target_landed_cost_range", "landed_cost"),
                       ("target_gross_margin_range", "gross_margin")):
        written = str(economics.get(field) or "").strip()
        if written and written != _placeholder(key):
            assumptions.append(f"{prefix}{written}")
        economics[field] = _placeholder(key)
        placeholders_used.append(key)
    economics["assumptions"] = assumptions
    out["economics"] = economics

    # --- differentiators ----------------------------------------------------
    differentiators = []
    for item in out.get("differentiators") or []:
        entry = dict(item)
        ids = [i for i in (entry.get("evidence_ids") or []) if index.known(i)]
        if entry.get("backing") != "to_validate" and not ids:
            entry["backing"] = "to_validate"
            notes.append("一条差异化主张缺少证据，已标记为待验证。" if language == "zh"
                         else "A differentiation claim had no evidence and is marked to_validate.")
        entry["evidence_ids"] = ids
        differentiators.append(entry)
    out["differentiators"] = differentiators

    # --- validation plan ----------------------------------------------------
    plan = [dict(row) for row in (out.get("validation_plan") or []) if row.get("question")]
    existing = " ".join(str(row.get("question", "")) for row in plan)
    for key in dict.fromkeys(placeholders_used):
        placeholder, question = PLACEHOLDERS[key]
        if placeholder in existing or question in existing:
            continue
        plan.append({"question": question, "method": "", "decision_rule": "",
                     "generated": True})
    for item in differentiators:
        if item.get("backing") == "to_validate":
            claim = str(item.get("claim") or "")[:60]
            if claim and claim not in existing:
                plan.append({"question": f"验证差异化假设：{claim}" if language == "zh"
                             else f"Validate differentiation hypothesis: {claim}",
                             "method": "", "decision_rule": "", "generated": True})
    out["validation_plan"] = plan
    out["placeholders"] = sorted(set(placeholders_used))
    return out, assumptions, notes


def _competitor_backed(entry: dict, index: ev.EvidenceIndex) -> bool:
    """A competitor's observed attribute may be quoted — with a live citation."""
    if entry.get("source") != "competitor_observed":
        return False
    return any(index.known(i) for i in (entry.get("evidence_ids") or []))


def _cited_ids(document: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            if key == "evidence_ids" and isinstance(value, list):
                found.update(str(v) for v in value)
            else:
                found |= _cited_ids(value)
    elif isinstance(document, list):
        for item in document:
            found |= _cited_ids(item)
    return found


def _pick_opportunity(opportunities: Sequence[dict], opportunity_id: str) -> dict | None:
    if not opportunities:
        return None
    if opportunity_id:
        for item in opportunities:
            if item["id"] == opportunity_id or item["anchor_asin"] == opportunity_id:
                return item
    return opportunities[0]


def _opportunity_brief(opportunity: dict, payload: dict, language: str) -> str:
    lines = [
        f"OPPORTUNITY: {opportunity['title']} (anchor {opportunity['anchor_asin']}, "
        f"score {opportunity['product_score']}/100, "
        f"confidence {opportunity['score_confidence']}) — score is final.",
    ]
    bands = payload["structure"]["price_bands"]
    if bands:
        lines.append("OBSERVED PRICE BANDS: " + ", ".join(b["bucket_key"] for b in bands))
    if payload["pain"]:
        lines.append("PAIN THEMES: " + ", ".join(
            f"{t['theme']} ({t['mention_count']}/{t['sample_size']}, "
            f"fixable={bool(t['fixable_in_design'])})" for t in payload["pain"]))
    directives = payload.get("design_directives") or []
    if directives:
        lines.append("DESIGN DIRECTIVES FROM THE CATEGORY READ (carry these forward; "
                     "do not re-derive them):")
        for item in directives[:6]:
            lines.append(f"  [{item.get('priority', '')}/{item.get('stage', '')}] "
                         f"{item.get('directive', '')}")
    spec = payload.get("spec") or {}
    if spec.get("tiles"):
        lines.append("SHELF ENVELOPE (the design has to sit near this): " + " | ".join(
            f"{t['label']} {t['value']}" for t in spec["tiles"]))
    if payload["keywords"]:
        lines.append("KEYWORDS: " + ", ".join(k["keyword"] for k in payload["keywords"][:10]))
    competitors = payload["competitors"][:5]
    if competitors:
        lines.append("COMPETITOR ATTRIBUTES (the only physical specs you may quote): "
                     + "; ".join(
                         f"{c['asin']} {c.get('dimension') or '—'} / "
                         f"{c.get('weight') or '—'} lb" for c in competitors))
    return "\n".join(lines)
