"""Channel-specific image styles for the marketing image generator.

Mirrors ``content_skills.py``: a frozen dataclass registry keyed by ``key`` with a
selector that resolves an explicit style key, task text, or a default. Each style
turns into prompt guidance (``prompt_prefix``) injected into the Gemini call so a
product photo is re-composed in the right channel aesthetic.

The channel set matches where a US DTC furniture brand actually publishes. Note
that furniture is bulky: hand-held and flat-lay compositions are physically
impossible here, so every style is either a studio hero shot or a room set.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageSkill:
    key: str
    label: str
    aliases: tuple[str, ...]
    aspect_ratio: str  # "1:1", "3:4", "4:5", "16:9"
    style_rules: tuple[str, ...]  # composition / lighting / mood directives
    background_guidance: str  # what background suits the platform
    negative_hints: tuple[str, ...] = ()  # e.g. "no text overlay", "no watermark"
    description: str = ""  # short human-facing blurb for the UI skills picker

    def render(self) -> str:
        lines = [f"Image style: {self.label}", f"Aspect ratio: {self.aspect_ratio}", "", "Style rules:"]
        lines.extend(f"- {rule}" for rule in self.style_rules)
        lines.append("")
        lines.append(f"Background: {self.background_guidance}")
        if self.negative_hints:
            lines.append("")
            lines.append("Avoid:")
            lines.extend(f"- {hint}" for hint in self.negative_hints)
        return "\n".join(lines)

    def prompt_prefix(self) -> str:
        """Single string prepended to the user's prompt for the image model."""
        parts = [
            f"Produce a {self.label} style marketing image with a {self.aspect_ratio} aspect ratio.",
            " ".join(self.style_rules),
            f"Background: {self.background_guidance}.",
        ]
        if self.negative_hints:
            parts.append("Avoid: " + ", ".join(self.negative_hints) + ".")
        return " ".join(parts)


IMAGE_SKILLS: dict[str, ImageSkill] = {
    "amazon": ImageSkill(
        key="amazon",
        label="Amazon Listing Main Image",
        aliases=("amazon", "亚马逊", "亚马逊主图", "listing", "白底", "主图"),
        aspect_ratio="1:1",
        style_rules=(
            "Compliant marketplace main image: the furniture piece alone, shot at a "
            "three-quarter hero angle that reveals both depth and profile.",
            "Neutral, even studio lighting with accurate wood tone and fabric color.",
            "Piece occupies roughly 85% of the frame and sits flat, not floating.",
        ),
        background_guidance="a pure white (RGB 255,255,255) background as required by marketplace rules",
        negative_hints=("no text", "no badges", "no borders", "no props", "no room context"),
        description="亚马逊 listing 主图：纯白合规、仅家具本体、四分之三角度、方图 1:1。",
    ),
    "wayfair": ImageSkill(
        key="wayfair",
        label="Wayfair Listing Image",
        aliases=("wayfair", "overstock", "属性图"),
        aspect_ratio="1:1",
        style_rules=(
            "Catalog-style shot that reads clearly at thumbnail size in a browse grid.",
            "Show the piece styled minimally in a lightly furnished room so scale is legible.",
            "Even daylight, true-to-life finish color, full silhouette visible.",
        ),
        background_guidance="a clean, softly furnished interior with a light neutral wall and floor",
        negative_hints=("no text overlay", "no watermark", "no clutter competing with the piece"),
        description="Wayfair 列表图：浅色简约室内、缩略图下轮廓清晰、方图 1:1。",
    ),
    "dtc_site": ImageSkill(
        key="dtc_site",
        label="DTC Site Hero",
        aliases=("dtc", "dtc_site", "shopify", "独立站", "官网", "hero", "banner", "横幅"),
        aspect_ratio="16:9",
        style_rules=(
            "Wide editorial hero for a storefront banner, with the piece placed off-center.",
            "Full room context and natural window light, styled but livable.",
            "Leave clear negative space on one side for a headline and button.",
        ),
        background_guidance="a real, well-composed interior that suits the piece's style",
        negative_hints=("no text overlay", "no watermark", "no harsh flash lighting"),
        description="独立站 hero 图：宽幅 16:9、完整房间场景、一侧留白放标题按钮。",
    ),
    "instagram": ImageSkill(
        key="instagram",
        label="Instagram",
        aliases=("instagram", "ins", "ig", "meta", "facebook", "照片墙"),
        aspect_ratio="4:5",
        style_rules=(
            "Editorial, on-trend room set where the piece anchors the composition.",
            "Cohesive color palette, soft directional daylight, styled with plants, "
            "textiles, and ceramics rather than product props.",
            "Vertical 4:5 framing optimized for the feed.",
        ),
        background_guidance="a styled real interior with a coordinated palette that complements the finish",
        negative_hints=("no watermark", "no low-resolution artifacts", "no text overlay"),
        description="Instagram 风：杂志感房间实景、统一色调、竖版 4:5，适合信息流。",
    ),
    "pinterest": ImageSkill(
        key="pinterest",
        label="Pinterest",
        aliases=("pinterest", "pin", "灵感", "灵感图"),
        aspect_ratio="3:4",
        style_rules=(
            "Tall room-inspiration image that reads as a save-worthy interior idea.",
            "Show the full room story — the piece in context with the wall, floor, and "
            "styling that make the look reproducible.",
            "Bright, airy, high-contrast enough to stand out in a dense grid.",
        ),
        background_guidance="an aspirational but achievable interior in a clearly identifiable style",
        negative_hints=("no watermark", "no cropped-off furniture", "no text overlay"),
        description="Pinterest 灵感图：竖版 3:4、完整房间搭配、明亮通透、可复刻的风格感。",
    ),
    "generic": ImageSkill(
        key="generic",
        label="Generic Marketing Image",
        aliases=("generic", "通用", "图片", "default"),
        aspect_ratio="1:1",
        style_rules=(
            "Clean, versatile composition with the furniture piece as the clear subject.",
            "Balanced lighting and a professional, uncluttered look.",
        ),
        background_guidance="a simple, neutral background that keeps focus on the piece",
        negative_hints=("no watermark",),
        description="通用营销图：干净中性背景、专业布光、方图 1:1。",
    ),
}


IMAGE_FORMAT_DEFAULTS = {
    "product": "amazon",
    "listing": "amazon",
    "lifestyle": "instagram",
    "social": "instagram",
    "room": "dtc_site",
    "inspiration": "pinterest",
}


def select_image_skill(
    style: str | None, task: str = "", platform: str | None = None
) -> ImageSkill:
    """Resolve the best image style from an explicit style key, platform, or task text."""
    candidates = [style, platform, task]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.lower()
        for skill in IMAGE_SKILLS.values():
            if skill.key == normalized or any(alias in normalized for alias in skill.aliases):
                return skill

    return IMAGE_SKILLS[IMAGE_FORMAT_DEFAULTS.get(style or "", "generic")]
