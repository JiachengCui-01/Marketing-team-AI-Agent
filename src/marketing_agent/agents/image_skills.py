"""Channel-specific image styles for the marketing image generator.

Mirrors ``content_skills.py``: a frozen dataclass registry keyed by ``key`` with a
selector that resolves an explicit style key, task text, or a default. Each style
turns into prompt guidance injected into the Gemini call so a product photo is
re-composed in the right channel aesthetic.

The channel set matches where a US DTC furniture brand actually publishes. Note
that furniture is bulky: hand-held and flat-lay compositions are physically
impossible here, so every style is either a studio hero shot or a room set.

Three things a style has to carry for its output to be *publishable* rather than
merely pretty, and they are kept in separate fields because they have different
authority:

- ``platform_rules`` — what the channel enforces or crops. A user request cannot
  overrule these; asking for a room set on an Amazon main image just gets the
  listing suppressed, so the rule wins and the rest of the request still applies.
- ``art_direction`` — the look. A user request overrides this freely; it is our
  house default, not a constraint.
- ``default_request`` — the brief to run when the user selected a style, attached a
  photo, and typed nothing. Blocking on an empty box was the wrong call: the style
  already fully describes a deliverable.
"""
from __future__ import annotations

from dataclasses import dataclass

# True of every channel: the file has to survive being uploaded as-is. Image models
# also cannot spell — generated glyphs come out malformed, which is why baked-in text
# is refused globally unless the request explicitly asks for a callout.
BASE_DELIVERY_RULES: tuple[str, ...] = (
    "Photographic realism throughout — real materials, real optics, no illustration, "
    "render-preview, or CGI-plastic look.",
    "Correct furniture construction: leg count, cushion count, drawer count, joinery, "
    "and hardware match a piece that could actually be built and shipped.",
    "Physically plausible geometry — straight lines stay straight, panels stay square, "
    "the piece rests on the floor plane, and cast shadows agree with the light sources.",
    "The whole piece is inside the frame with breathing room; nothing important is "
    "clipped by an edge.",
    "Sharp focus on the product with no upscaling mush, banding, moiré, or duplicated "
    "structural parts.",
    "No text, letters, numerals, logos, price tags, badges, or watermarks unless the "
    "request explicitly asks for a labeled callout.",
    "No people, hands, pets, or brand marks from other companies.",
)


@dataclass(frozen=True)
class ImageSkill:
    key: str
    label: str
    aliases: tuple[str, ...]
    aspect_ratio: str  # "1:1", "4:5", "2:3", "16:9"
    pixel_target: str  # concrete output size that clears the channel's display needs
    art_direction: tuple[str, ...]  # composition / lighting / mood — user may override
    background_guidance: str  # what background suits the platform
    default_request: str  # brief used when the user gives no instruction of their own
    platform_rules: tuple[str, ...] = ()  # channel-enforced; a user request cannot void
    delivery_rules: tuple[str, ...] = ()  # channel-specific additions to the base rules
    negative_hints: tuple[str, ...] = ()  # e.g. "no text overlay", "no watermark"
    description: str = ""  # short human-facing blurb for the UI skills picker
    usage_note: str = ""  # where the output slots into the channel, for the UI

    # ``style_rules`` was the old name for ``art_direction``; kept as a read-only alias
    # so existing callers and prompts that ask for "the style rules" keep working.
    @property
    def style_rules(self) -> tuple[str, ...]:
        return self.art_direction

    def all_delivery_rules(self) -> tuple[str, ...]:
        return BASE_DELIVERY_RULES + self.delivery_rules

    def render(self) -> str:
        lines = [
            f"Image style: {self.label}",
            f"Aspect ratio: {self.aspect_ratio}",
            f"Output size: {self.pixel_target}",
        ]
        if self.platform_rules:
            lines += ["", "Platform rules (non-negotiable):"]
            lines += [f"- {rule}" for rule in self.platform_rules]
        lines += ["", "Art direction:"]
        lines += [f"- {rule}" for rule in self.art_direction]
        lines += ["", f"Background: {self.background_guidance}"]
        lines += ["", "Delivery quality:"]
        lines += [f"- {rule}" for rule in self.all_delivery_rules()]
        if self.negative_hints:
            lines += ["", "Avoid:"]
            lines += [f"- {hint}" for hint in self.negative_hints]
        return "\n".join(lines)

    def prompt_prefix(self) -> str:
        """Single string summarizing the style, for one-line prompt contexts."""
        parts = [
            f"Produce a {self.label} style marketing image with a {self.aspect_ratio} "
            f"aspect ratio at {self.pixel_target}.",
            " ".join(self.platform_rules),
            " ".join(self.art_direction),
            f"Background: {self.background_guidance}.",
        ]
        if self.negative_hints:
            parts.append("Avoid: " + ", ".join(self.negative_hints) + ".")
        return " ".join(part for part in parts if part.strip())


IMAGE_SKILLS: dict[str, ImageSkill] = {
    "amazon": ImageSkill(
        key="amazon",
        label="Amazon Listing Main Image",
        aliases=("amazon", "亚马逊", "亚马逊主图", "listing", "白底", "主图"),
        aspect_ratio="1:1",
        pixel_target="2000 x 2000 px",
        # Amazon's main-image policy, not taste: a violation gets the listing
        # suppressed, so these hold even when the typed request contradicts them.
        platform_rules=(
            "Pure white background: every pixel outside the piece and its contact "
            "shadow is RGB 255,255,255 — no off-white, no gradient, no vignette, no "
            "seamless-sweep curve, no visible floor or wall line.",
            "The product alone. No props, no rug, no plant, no room set, no second "
            "piece of furniture, no packaging.",
            "Zero graphics: no text, dimension callouts, badges, borders, frames, "
            "inset panels, collage tiles, or logos anywhere in the frame.",
            "The piece fills about 85% of the frame's longest side, fully inside the "
            "frame, centered, and not cropped.",
            "Square 1:1 at 2000 x 2000 px, which clears Amazon's 1600 px zoom "
            "threshold — shoppers judge material quality in zoom.",
        ),
        art_direction=(
            "Three-quarter hero angle from slightly above seat height, showing the "
            "front face and one side so depth, profile, and leg shape all read.",
            "Even, soft studio lighting: large key from the front-left, fill from the "
            "right, gentle top light to separate the piece from the backdrop.",
            "A tight, soft contact shadow directly beneath the piece so it sits on a "
            "surface instead of floating; no long cast shadow across the white.",
            "Colorimetrically honest finish — true wood tone and grain direction, "
            "correct fabric weave and sheen, correct metal or powder-coat finish.",
        ),
        background_guidance="a pure white (RGB 255,255,255) seamless studio background",
        default_request=(
            "Re-shoot the attached furniture piece as an upload-ready Amazon main "
            "image: three-quarter hero angle on pure white, even studio light, the "
            "piece filling roughly 85% of the frame with a soft contact shadow, and "
            "no text or props of any kind."
        ),
        delivery_rules=(
            "Edges, legs, seams, and cushion piping stay crisp at full resolution — "
            "the image will be viewed in zoom.",
            "Fabric and wood texture is visible rather than smoothed away.",
        ),
        negative_hints=("no text", "no badges", "no borders", "no props", "no room context",
                        "no colored or gray backdrop", "no reflective studio floor"),
        description="亚马逊 listing 主图：纯白合规、仅家具本体、四分之三角度、方图 1:1、2000px 可放大。",
        usage_note="可直接作为 Amazon 主图上传（符合纯白底、无文字、占比 85% 规则）。",
    ),
    "wayfair": ImageSkill(
        key="wayfair",
        label="Wayfair Listing Image",
        aliases=("wayfair", "overstock", "属性图"),
        aspect_ratio="1:1",
        pixel_target="2000 x 2000 px",
        platform_rules=(
            "Square 1:1 — the browse grid crops anything else.",
            "The full silhouette is in frame with even margins; the piece is never "
            "obstructed by a prop, plant, or another item of furniture.",
            "Readable as a ~220 px thumbnail: one clear subject, high separation from "
            "the background, no busy pattern competing with the piece.",
            "No text overlay, watermark, or promotional graphic.",
        ),
        art_direction=(
            "Catalog styling: the piece centered and shot straight-on to slightly "
            "three-quarter, presented plainly rather than as an editorial scene.",
            "A minimally furnished, light-neutral setting — a hint of floor and wall so "
            "a shopper can judge scale, styled with at most one restrained accessory.",
            "Even, cool-neutral daylight; true-to-life finish color with no warm or "
            "moody color grade that would misrepresent the product.",
        ),
        background_guidance=(
            "a clean, softly furnished interior with a light neutral wall and a plain "
            "light floor, or a seamless light-gray studio sweep"
        ),
        default_request=(
            "Present the attached furniture piece as a Wayfair listing image: square "
            "framing, light neutral setting with a hint of floor and wall for scale, "
            "even daylight, full silhouette in frame and legible at thumbnail size."
        ),
        delivery_rules=(
            "Scale cues stay honest — floor, wall, and any accessory are sized to a "
            "real room, so the piece does not read as a doll-house or oversized copy.",
        ),
        negative_hints=("no text overlay", "no watermark", "no clutter competing with the piece",
                        "no dark or moody grade", "no props overlapping the product"),
        description="Wayfair 列表图：浅色简约室内、缩略图下轮廓清晰、真实配色、方图 1:1。",
        usage_note="适合 Wayfair / Overstock 列表位与属性图，缩略图下仍能看清轮廓。",
    ),
    "dtc_site": ImageSkill(
        key="dtc_site",
        label="DTC Site Hero",
        aliases=("dtc", "dtc_site", "shopify", "独立站", "官网", "hero", "banner", "横幅"),
        aspect_ratio="16:9",
        pixel_target="2560 x 1440 px",
        platform_rules=(
            "Wide 16:9 full-bleed composition at 2560 px wide, so it stays sharp on a "
            "retina desktop banner.",
            "Reserve a calm overlay zone: roughly 35% of the width on one side stays "
            "low-detail and even in tone — no product parts, no high-contrast edges, "
            "no busy pattern — so a live headline and button remain legible on top.",
            "No baked-in text, button, or logo; the storefront renders those as real "
            "HTML over the image.",
            "Composition survives a center crop to 3:2 and 1:1 for tablet and mobile — "
            "the piece is not parked at the extreme frame edge.",
        ),
        art_direction=(
            "Editorial hero: the piece placed off-center on a rule-of-thirds line, in a "
            "real, well-composed interior that suits its style.",
            "Natural window light with soft directional falloff; styled but livable, "
            "with the restraint of a brand campaign rather than a catalog page.",
            "Cohesive palette drawn from the piece's own finish, warm mid-tones, and "
            "depth from foreground-to-background layering.",
        ),
        background_guidance="a real, well-composed interior that suits the piece's style",
        default_request=(
            "Build a storefront hero banner around the attached furniture piece: wide "
            "16:9 editorial interior, natural window light, the piece off-center, and a "
            "calm low-detail area on one side left clear for a headline and button."
        ),
        delivery_rules=(
            "Room proportions and ceiling height read as a real US home, not a stage set.",
        ),
        negative_hints=("no text overlay", "no watermark", "no harsh flash lighting",
                        "no busy pattern in the overlay zone", "no fisheye distortion"),
        description="独立站 hero 图：宽幅 16:9、真实室内场景、一侧留出可放标题按钮的干净区域。",
        usage_note="可直接做首页 / 落地页 banner，一侧留白用于叠加标题与 CTA。",
    ),
    "instagram": ImageSkill(
        key="instagram",
        label="Instagram",
        aliases=("instagram", "ins", "ig", "meta", "facebook", "照片墙"),
        aspect_ratio="4:5",
        pixel_target="1080 x 1350 px",
        platform_rules=(
            "Vertical 4:5 at 1080 x 1350 px — the largest footprint the feed renders.",
            "Keep the subject and every essential detail inside the central square: the "
            "profile grid crops 4:5 down to 1:1.",
            "Feed-native and unbranded: no text overlay, no logo bug, no frame or border.",
            "Reads at phone size — one unmistakable focal point, not a wide room survey.",
        ),
        art_direction=(
            "Editorial room set where the piece anchors the composition and fills a "
            "confident share of the frame.",
            "Cohesive, on-trend palette; soft directional daylight with visible but "
            "gentle shadow shape.",
            "Styled with lived-in props — plants, textiles, ceramics, books — never "
            "product-shot props or studio gear.",
            "A human trace without a person: a throw slightly askew, a half-read book, "
            "an open window.",
        ),
        background_guidance="a styled real interior with a coordinated palette that complements the finish",
        default_request=(
            "Style the attached furniture piece into an Instagram feed image: vertical "
            "4:5 editorial room set, cohesive palette, soft daylight, lived-in props, "
            "the piece anchoring the frame and reading clearly at phone size."
        ),
        delivery_rules=(
            "Colors stay printable-honest: grade for mood, but the finish color remains "
            "the color a customer will receive.",
        ),
        negative_hints=("no watermark", "no low-resolution artifacts", "no text overlay",
                        "no HDR halos", "no oversaturated filter"),
        description="Instagram 风：杂志感房间实景、统一色调、竖版 4:5，主体居中兼容 1:1 网格裁切。",
        usage_note="可直接发信息流；主体居中，切成 1:1 网格图也不丢主体。",
    ),
    "pinterest": ImageSkill(
        key="pinterest",
        label="Pinterest",
        aliases=("pinterest", "pin", "灵感", "灵感图"),
        # 2:3 is Pinterest's own recommended pin ratio; taller pins get truncated.
        aspect_ratio="2:3",
        pixel_target="1000 x 1500 px",
        platform_rules=(
            "Vertical 2:3 at 1000 x 1500 px — Pinterest's recommended pin ratio; "
            "anything taller is truncated in the feed.",
            "Stands out in a dense multi-column grid: bright, airy, and high enough in "
            "contrast to survive being one narrow column among many.",
            "The complete look is visible — no furniture cropped off at the frame edge, "
            "because the pin is the whole idea being saved.",
            "No baked-in text or watermark; the pin title and description carry the copy.",
        ),
        art_direction=(
            "Tall room-inspiration frame that reads as a save-worthy interior idea "
            "rather than a product shot.",
            "Show the full room story — wall treatment, flooring, textiles, lighting, "
            "and companion pieces that make the look reproducible.",
            "Bright, airy daylight and a clearly identifiable style (coastal, "
            "mid-century, Japandi, farmhouse) so the pin is searchable by vibe.",
        ),
        background_guidance="an aspirational but achievable interior in a clearly identifiable style",
        default_request=(
            "Turn the attached furniture piece into a Pinterest inspiration pin: "
            "vertical 2:3, full room story with reproducible styling, bright airy "
            "daylight, a clearly identifiable interior style, nothing cropped off."
        ),
        delivery_rules=(
            "Every styling element is something a US shopper could plausibly buy and "
            "recreate — the pin is a shopping list, not a fantasy.",
        ),
        negative_hints=("no watermark", "no cropped-off furniture", "no text overlay",
                        "no collage or split-screen layout"),
        description="Pinterest 灵感图：竖版 2:3、完整房间搭配、明亮通透、风格可识别可复刻。",
        usage_note="按 Pinterest 推荐比例 2:3 输出，可直接建 pin。",
    ),
    "generic": ImageSkill(
        key="generic",
        label="Generic Marketing Image",
        aliases=("generic", "通用", "图片", "default"),
        aspect_ratio="1:1",
        pixel_target="2000 x 2000 px",
        platform_rules=(
            "Square 1:1 at 2000 x 2000 px so the file can be re-cropped for any channel.",
            "The full piece is in frame with even margins and one clear subject.",
            "No text, watermark, or border baked in.",
        ),
        art_direction=(
            "Clean, versatile composition with the furniture piece as the unmistakable "
            "subject at a three-quarter angle.",
            "Balanced soft lighting, neutral color grade, professional and uncluttered.",
        ),
        background_guidance="a simple, neutral, evenly lit background that keeps focus on the piece",
        default_request=(
            "Photograph the attached furniture piece as a clean, versatile marketing "
            "image: three-quarter angle, neutral evenly lit background, balanced light, "
            "no props and no text."
        ),
        negative_hints=("no watermark", "no text", "no distracting props"),
        description="通用营销图：干净中性背景、专业布光、方图 1:1，可再裁给各渠道。",
        usage_note="通用底图，可再裁切复用到各渠道。",
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
