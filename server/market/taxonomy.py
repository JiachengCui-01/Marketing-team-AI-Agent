"""The furniture browse tree: which Amazon nodes this business actually sells into.

Two jobs.

**A fixed catalog.** ``TRACKED_NODES`` carries the real ``nodeIdPath`` for every
category in ``marketing_agent.domain.PRODUCT_CATEGORIES``, captured from a live
``product_node`` reply and checked in under ``tests/fixtures/sellersprite/``. Browse
node ids are stable for years, so bootstrapping the warehouse costs **zero vendor
calls** — the old sweep spent four of its sixteen calls re-resolving these on every
single run.

**Resolution for everything else.** A deep dive on a category outside the catalog
still needs a node id, so ``pick_node`` stays: it scores a ``product_node`` reply and
refuses rather than guessing. It moved here from ``server/selection.py`` unchanged
and is re-exported there, because driving analysis off a free-text keyword instead of
a node id is what makes the vendor answer a furniture query with toilet paper.
"""
from __future__ import annotations

import json
import math
import os
import re

from marketing_agent.domain import PRODUCT_CATEGORIES

from . import store

MARKETPLACE = "US"

# The department root. Its own row is the market-wide roll-up the overview needs.
FURNITURE_ROOT = "1055398:1063306"
FURNITURE_ROOT_LABEL = "Home & Kitchen:Furniture"

# The browse scope this business sells into. Four departments, because Amazon
# does not keep the product line in one place: patio furniture lives under Patio,
# Lawn & Garden, task seating under Office Products, and pet beds under Pet
# Supplies. Scoping to Furniture alone made those three invisible.
#
# Still a scope and not a free-for-all: ``product_node`` answers a furniture query
# with whatever matches, and a "sofa" result under Toys is a doll's couch.
_HOME_FURNITURE_PREFIX = "home & kitchen:furniture"
SCOPE_PREFIXES: tuple[str, ...] = (
    _HOME_FURNITURE_PREFIX,
    "patio, lawn & garden:patio furniture",
    "office products:office furniture",
    "pet supplies",
)
_STOPWORDS = {"and", "or", "the", "of", "with", "for", "&"}

# The seed queries discovery runs, one per product line. These are the business's
# own product lines rather than a guess about what matters — which is why they
# live next to ``PRODUCT_CATEGORIES`` and read the same.
DISCOVERY_SEEDS: tuple[tuple[str, str], ...] = (
    ("sofas and sectionals", "sofas and sectionals"),
    ("bed frames headboards", "bed frames and headboards"),
    ("dining tables chairs", "dining tables and chairs"),
    ("storage cabinets sideboards", "storage cabinets and sideboards"),
    ("dressers armoires wardrobes", "storage cabinets and sideboards"),
    ("bookcases shelving units", "storage cabinets and sideboards"),
    ("desks home office", "desks"),
    ("coffee tables end tables", "coffee and side tables"),
    ("nightstands accent tables", "coffee and side tables"),
    ("patio furniture sets outdoor", "outdoor and patio furniture"),
    ("outdoor sofa dining set", "outdoor and patio furniture"),
    ("office chairs desk chairs", "office chairs and seating"),
    ("dog beds pet furniture", "pet beds and furniture"),
    ("cat tree pet house", "pet beds and furniture"),
)

# A node this small does not repay a monthly pack, and the cap keeps one odd
# ``product_node`` reply from quietly enrolling the whole marketplace and eating
# the daily budget for a week. Both are engineering limits, not editorial ones —
# raise them with the env vars if the quota allows.
MIN_DISCOVERED_LISTINGS = int(os.environ.get("MARKETING_AGENT_MARKET_MIN_NODE", "800"))
MAX_TRACKED_NODES = int(os.environ.get("MARKETING_AGENT_MARKET_MAX_NODES", "60"))

# (node_id_path, node_label_path, brand_category, tier, listing count at capture)
#
# Tier 1 nodes additionally get the per-ASIN traffic and review packs, which are the
# expensive half of the collection plan; tier 2 gets category and product packs only.
# The split is by how much of the product line rides on the node, not by size.
_CATALOG: tuple[tuple[str, str, str | None, int, int], ...] = (
    (FURNITURE_ROOT, FURNITURE_ROOT_LABEL, None, 1, 199_398),
    # The other three departments' roots. Roll-ups like the furniture root, so
    # they never appear as board rows; their ids come from the same captured
    # ``product_node`` reply as everything else here.
    ("2972638011:553824",
     "Patio, Lawn & Garden:Patio Furniture & Accessories",
     "outdoor and patio furniture", 2, 71_510),
    ("1064954:1069102",
     "Office Products:Office Furniture & Lighting",
     "office chairs and seating", 2, 26_197),

    ("1055398:1063306:1063318:3733551",
     "Home & Kitchen:Furniture:Living Room Furniture:Sofas & Couches",
     "sofas and sectionals", 1, 10_941),

    ("1055398:1063306:1063308:3733101",
     "Home & Kitchen:Furniture:Bedroom Furniture:Beds, Frames & Bases",
     "bed frames and headboards", 1, 21_310),
    ("1055398:1063306:1063308:3733101:3248801011",
     "Home & Kitchen:Furniture:Bedroom Furniture:Beds, Frames & Bases:Bed Frames",
     "bed frames and headboards", 2, 16_940),

    ("1055398:1063306:3733781:3733811",
     "Home & Kitchen:Furniture:Kitchen & Dining Room Furniture:Tables",
     "dining tables and chairs", 1, 7_256),
    ("1055398:1063306:3733781:3733821",
     "Home & Kitchen:Furniture:Kitchen & Dining Room Furniture:Chairs",
     "dining tables and chairs", 2, 12_000),

    # The worked example: freight-friendly, objective return reasons, mid AOV.
    ("1055398:1063306:3733781:3733831",
     "Home & Kitchen:Furniture:Kitchen & Dining Room Furniture:Buffets & Sideboards",
     "storage cabinets and sideboards", 1, 4_210),
    ("1055398:1063306:16543322011:681151011",
     "Home & Kitchen:Furniture:Accent Furniture:Storage Cabinets",
     "storage cabinets and sideboards", 2, 5_549),
    ("1055398:1063306:1063318:1063310",
     "Home & Kitchen:Furniture:Living Room Furniture:TV & Media Furniture",
     "storage cabinets and sideboards", 2, 12_067),
    ("1055398:1063306:1063308:3733251",
     "Home & Kitchen:Furniture:Bedroom Furniture:Nightstands",
     "storage cabinets and sideboards", 2, 8_247),

    ("1055398:1063306:1063312:3733671",
     "Home & Kitchen:Furniture:Home Office Furniture:Home Office Desks",
     "desks", 1, 13_347),

    ("1055398:1063306:1063318:680098011:3733631",
     "Home & Kitchen:Furniture:Living Room Furniture:Tables:Coffee Tables",
     "coffee and side tables", 1, 5_744),
    ("1055398:1063306:1063318:680098011:3733641",
     "Home & Kitchen:Furniture:Living Room Furniture:Tables:End Tables",
     "coffee and side tables", 2, 6_579),
)

TRACKED_NODES: tuple[dict, ...] = tuple(
    {
        "marketplace": MARKETPLACE,
        "node_id_path": path,
        "node_label_path": label,
        "brand_category": brand_category,
        "tracked": True,
        "tier": tier,
        "products": products,
    }
    for path, label, brand_category, tier, products in _CATALOG
)

TRACKED_PATHS: frozenset[str] = frozenset(node["node_id_path"] for node in TRACKED_NODES)

# Department roll-ups. Each is the sum of its own descendants, so ranking one
# against the categories inside it would put a total at the top of a list of
# parts. Identified by depth: a scope prefix with nothing under it.
# The roots the monthly walk starts from, one per department in scope. Their ids
# come from the same captured ``product_node`` reply as the rest of the catalog,
# so bootstrapping still costs no vendor calls.
#
# Pet Supplies is absent: its browse id was not in the captured reply, and
# guessing a browse node id is the one thing in this module that must never
# happen — a wrong id answers with a real-looking market that is not the one
# asked for. It is enrolled the moment the id is supplied.
AREA_ROOTS: tuple[str, ...] = (
    FURNITURE_ROOT,
    "2972638011:553824",        # Patio, Lawn & Garden:Patio Furniture & Accessories
    "1064954:1069102",          # Office Products:Office Furniture & Lighting
)

ROLLUP_PATHS: frozenset[str] = frozenset(
    node["node_id_path"] for node in TRACKED_NODES
    if node["node_label_path"].lower() in {prefix for prefix in (
        FURNITURE_ROOT_LABEL.lower(),
        "patio, lawn & garden:patio furniture & accessories",
        "office products:office furniture & lighting")}
)
TIER1_PATHS: tuple[str, ...] = tuple(
    node["node_id_path"] for node in TRACKED_NODES if node["tier"] == 1
)


def ensure_nodes(marketplace: str = MARKETPLACE) -> int:
    """Make sure the catalog is in the warehouse. Idempotent, and never calls the vendor."""
    if marketplace != MARKETPLACE:
        return 0
    return store.upsert_nodes(TRACKED_NODES)


def tracked_nodes(marketplace: str = MARKETPLACE) -> list[dict]:
    """Tracked nodes as stored, bootstrapping the catalog on first use."""
    nodes = store.list_nodes(marketplace)
    if not nodes and marketplace == MARKETPLACE:
        ensure_nodes(marketplace)
        nodes = store.list_nodes(marketplace)
    return nodes


def leaf_nodes(marketplace: str = MARKETPLACE) -> list[dict]:
    """Tracked nodes minus the department roll-ups.

    A roll-up is the sum of its own descendants, so ranking one against the
    categories inside it would put a total at the top of a list of parts.
    """
    return [n for n in tracked_nodes(marketplace)
            if n["node_id_path"] not in ROLLUP_PATHS
            and n["node_id_path"] != FURNITURE_ROOT]


def label_for(node_id_path: str, marketplace: str = MARKETPLACE) -> str:
    node = store.get_node(marketplace, node_id_path)
    if node:
        return node["node_label_path"]
    for candidate in TRACKED_NODES:
        if candidate["node_id_path"] == node_id_path:
            return candidate["node_label_path"]
    return node_id_path


def short_label(node_label_path: str) -> str:
    parts = [part for part in (node_label_path or "").split(":") if part]
    return parts[-1] if parts else node_label_path


def in_scope(node_label_path: str) -> bool:
    """True when a node sits in one of the departments this business sells into."""
    lowered = (node_label_path or "").lower()
    return any(lowered.startswith(prefix) for prefix in SCOPE_PREFIXES)


def is_furniture(node_label_path: str) -> bool:
    """Kept as the narrow test: Home & Kitchen furniture specifically.

    ``in_scope`` is the one to use for collection. This one still answers the
    question it always answered, which some callers genuinely want.
    """
    return (node_label_path or "").lower().startswith(_HOME_FURNITURE_PREFIX)


def _category_tokens(category: str) -> set[str]:
    words = re.split(r"[^a-z0-9]+", (category or "").lower())
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def pick_node(payload: str, category: str) -> tuple[str, str] | None:
    """Choose the best category node from a ``product_node`` reply.

    Returns ``(nodeIdPath, nodeLabelPath)``, or ``None`` when nothing usable came
    back. Picking matters more than it looks: driving the rest of the sweep off a
    free-text keyword instead of a node id is what makes the vendor answer a
    furniture query with toilet paper.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None

    tokens = _category_tokens(category)
    best: tuple[float, str, str] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("nodeIdPath") or "").strip()
        label = str(row.get("nodeLabelPath") or "").strip()
        if not path:
            continue
        lowered = label.lower()
        score = 0.0
        # Being in the right tree outweighs any keyword or size signal.
        if in_scope(label):
            score += 1000.0
        elif "furniture" in lowered:
            score += 200.0
        score += 100.0 * sum(1 for token in tokens if token in lowered)
        try:
            products = float(row.get("products") or 0)
        except (TypeError, ValueError):
            products = 0.0
        # A node with more listings is the more representative read of the
        # category, but only as a tiebreak — hence the log.
        score += math.log10(products + 1)
        if best is None or score > best[0]:
            best = (score, path, label)
    if best is None or best[0] < 100.0:
        # Neither the right tree nor a keyword match: better to report a gap than
        # to analyze whatever the vendor's first row happened to be.
        return None
    return best[1], best[2]


def parse_nodes(payload: str, *, marketplace: str = MARKETPLACE,
                seed: str = "", tracked: bool | None = None) -> list[dict]:
    """Every in-scope node in a ``product_node`` reply, as warehouse rows.

    ``seed`` is the query that produced the reply. When given, a node is kept only
    if its own leaf label shares a word with the query — the department prefix
    alone is too loose for a department as wide as Pet Supplies, where a search
    for "dog beds" also matches food and grooming nodes. Deriving the test from
    the query rather than from a list of furniture words keeps the filter honest
    as the seeds change.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    wanted = _category_tokens(seed) if seed else set()
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("nodeIdPath") or "").strip()
        label = str(row.get("nodeLabelPath") or "").strip()
        if not path or not in_scope(label):
            continue
        if wanted:
            leaf = short_label(label).lower()
            if not any(token.rstrip("s") in leaf for token in wanted):
                continue
        out.append({
            "marketplace": marketplace,
            "node_id_path": path,
            "node_label_path": label,
            "tracked": (path in TRACKED_PATHS) if tracked is None else tracked,
            "tier": 1 if path in TIER1_PATHS else 2,
            "products": row.get("products"),
            "brand_category": brand_category_for(label) or (seed or None),
        })
    return out


def brand_category_for(node_label_path: str) -> str | None:
    """Map a node onto the product line it serves, or ``None`` when it serves none.

    Catalog membership wins; otherwise the leaf label is matched against the
    product-line vocabulary so a discovered node still lands in the right bucket.
    """
    for candidate in TRACKED_NODES:
        if candidate["node_label_path"] == node_label_path:
            return candidate["brand_category"]
    leaf = short_label(node_label_path).lower()
    for category in PRODUCT_CATEGORIES:
        tokens = _category_tokens(category)
        if any(token.rstrip("s") in leaf for token in tokens):
            return category
    return None
