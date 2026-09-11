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
import re

from marketing_agent.domain import PRODUCT_CATEGORIES

from . import store

MARKETPLACE = "US"

# The department root. Its own row is the market-wide roll-up the overview needs.
FURNITURE_ROOT = "1055398:1063306"
FURNITURE_ROOT_LABEL = "Home & Kitchen:Furniture"

# The browse tree this business actually sells into. ``product_node`` happily returns
# office and outdoor furniture nodes for the same keyword, and a "sofa" under Office
# Products is a task chair — a different price band, buyer, and freight profile.
_HOME_FURNITURE_PREFIX = "home & kitchen:furniture"
_STOPWORDS = {"and", "or", "the", "of", "with", "for", "&"}

# (node_id_path, node_label_path, brand_category, tier, listing count at capture)
#
# Tier 1 nodes additionally get the per-ASIN traffic and review packs, which are the
# expensive half of the collection plan; tier 2 gets category and product packs only.
# The split is by how much of the product line rides on the node, not by size.
_CATALOG: tuple[tuple[str, str, str | None, int, int], ...] = (
    (FURNITURE_ROOT, FURNITURE_ROOT_LABEL, None, 1, 199_398),

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
    """Tracked nodes minus the department root.

    The root is a roll-up: including it in a ranked board would put the sum of the
    categories at the top of a list of categories.
    """
    return [n for n in tracked_nodes(marketplace) if n["node_id_path"] != FURNITURE_ROOT]


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


def is_furniture(node_label_path: str) -> bool:
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
        if lowered.startswith(_HOME_FURNITURE_PREFIX):
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


def parse_nodes(payload: str, *, marketplace: str = MARKETPLACE) -> list[dict]:
    """Every furniture node in a ``product_node`` reply, as warehouse rows.

    Used when a deep dive resolves a category the catalog does not cover: the
    reply is already paid for, so the whole furniture subtree is worth keeping.
    """
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("nodeIdPath") or "").strip()
        label = str(row.get("nodeLabelPath") or "").strip()
        if not path or not is_furniture(label):
            continue
        out.append({
            "marketplace": marketplace,
            "node_id_path": path,
            "node_label_path": label,
            "tracked": path in TRACKED_PATHS,
            "tier": 1 if path in TIER1_PATHS else 2,
            "products": row.get("products"),
            "brand_category": brand_category_for(label),
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
