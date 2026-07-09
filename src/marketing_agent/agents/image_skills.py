"""Platform-specific image styles for the marketing image generator.

Mirrors ``content_skills.py``: a frozen dataclass registry keyed by ``key`` with a
selector that resolves an explicit style key, task text, or a default. Each style
turns into prompt guidance (``prompt_prefix``) injected into the Gemini call so a
product photo is re-composed in the right platform aesthetic.
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
    "xiaohongshu": ImageSkill(
        key="xiaohongshu",
        label="Xiaohongshu / Little Red Book",
        aliases=("xiaohongshu", "little red book", "小红书", "xhs", "rednote"),
        aspect_ratio="3:4",
        style_rules=(
            "Warm, aspirational lifestyle scene with the product as the hero.",
            "Soft natural lighting, cozy props, and an inviting real-life context.",
            "Leave clean space at the top for a caption sticker.",
        ),
        background_guidance="a tasteful lifestyle setting (desk, cafe, vanity) that fits the product",
        negative_hints=("no heavy text overlay", "no watermark", "no cluttered composition"),
        description="生活化种草风：暖光、real-life 场景、竖版 3:4，突出商品氛围感。",
    ),
    "taobao": ImageSkill(
        key="taobao",
        label="Taobao / Tmall Main Image",
        aliases=("taobao", "tmall", "淘宝", "天猫", "主图", "电商"),
        aspect_ratio="1:1",
        style_rules=(
            "Clean e-commerce main image with the product perfectly centered and sharp.",
            "Bright, even studio lighting with crisp detail and true-to-life color.",
            "Product fills most of the frame.",
        ),
        background_guidance="a pure white or very light seamless studio background",
        negative_hints=("no text", "no logos", "no props that obscure the product", "no busy background"),
        description="电商主图风：纯白背景、居中、影棚打光、方图 1:1，突出商品本体。",
    ),
    "amazon": ImageSkill(
        key="amazon",
        label="Amazon Listing Main Image",
        aliases=("amazon", "亚马逊", "亚马逊主图", "listing"),
        aspect_ratio="1:1",
        style_rules=(
            "Compliant marketplace main image: product only, straight-on hero angle.",
            "Neutral, professional studio lighting with accurate color.",
            "Product occupies roughly 85% of the frame.",
        ),
        background_guidance="a pure white (RGB 255,255,255) background as required by marketplace rules",
        negative_hints=("no text", "no badges", "no borders", "no additional props"),
        description="亚马逊 listing 主图：纯白合规、仅商品、方图 1:1、专业布光。",
    ),
    "instagram": ImageSkill(
        key="instagram",
        label="Instagram",
        aliases=("instagram", "ins", "照片墙", "ig"),
        aspect_ratio="4:5",
        style_rules=(
            "Editorial, on-trend feed aesthetic with confident styling.",
            "Cohesive color palette, shallow depth of field, and a strong focal point.",
            "Vertical 4:5 framing optimized for the feed.",
        ),
        background_guidance="a stylish, color-coordinated backdrop that complements the product",
        negative_hints=("no watermark", "no low-resolution artifacts"),
        description="Ins 风：杂志感、统一色调、浅景深、竖版 4:5，适合信息流。",
    ),
    "generic": ImageSkill(
        key="generic",
        label="Generic Marketing Image",
        aliases=("generic", "通用", "图片", "default"),
        aspect_ratio="1:1",
        style_rules=(
            "Clean, versatile marketing composition with the product as the clear subject.",
            "Balanced lighting and a professional, uncluttered look.",
        ),
        background_guidance="a simple, neutral background that keeps focus on the product",
        negative_hints=("no watermark",),
        description="通用营销图：干净中性背景、专业布光、方图 1:1。",
    ),
}


IMAGE_FORMAT_DEFAULTS = {
    "product": "taobao",
    "lifestyle": "xiaohongshu",
    "listing": "amazon",
    "social": "instagram",
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
