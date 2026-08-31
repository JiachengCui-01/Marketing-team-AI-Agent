"""Channel-specific copywriting skills for the content agent.

The channel set is the one a US direct-to-consumer furniture brand actually sells
through — marketplaces, its own store, and visual social. See ``domain.py`` for
the shared business vocabulary these skills assume.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentSkill:
    key: str
    label: str
    aliases: tuple[str, ...]
    rules: tuple[str, ...]
    output_contract: tuple[str, ...]
    avoid: tuple[str, ...] = ()

    def render(self) -> str:
        lines = [f"Platform skill: {self.label}", "", "Rules:"]
        lines.extend(f"- {rule}" for rule in self.rules)
        lines.append("")
        lines.append("Output contract:")
        lines.extend(f"- {rule}" for rule in self.output_contract)
        if self.avoid:
            lines.append("")
            lines.append("Avoid:")
            lines.extend(f"- {rule}" for rule in self.avoid)
        return "\n".join(lines)


SKILLS: dict[str, ContentSkill] = {
    "amazon_listing": ContentSkill(
        key="amazon_listing",
        label="Amazon Listing",
        aliases=("amazon", "amazon_listing", "亚马逊", "asin", "listing", "五点描述", "a+"),
        rules=(
            "Lead the title with the product type, then the defining material, then the "
            "one dimension a shopper filters on (seat width, mattress size, table seats).",
            "Write bullets in benefit-then-proof order: what it does for the room, then the "
            "spec that backs it up.",
            "Dedicate one bullet to exact dimensions and one to assembly and delivery.",
            "Use the words shoppers search with (loveseat, sectional, queen bed frame, "
            "6-person dining table), not internal product names.",
            "Stay inside marketplace policy: no competitor names, no guarantees you cannot "
            "back, no promotional or shipping claims in the title or bullets.",
        ),
        output_contract=(
            "Provide: Title (under 200 characters), 5 bullets (each under 250 characters), "
            "a short product description, and 10-20 backend search terms.",
            "Give dimensions as L x W x H in inches, with a metric equivalent in parentheses.",
            "Mark any spec not supplied in the brief as [confirm ...] rather than guessing.",
        ),
        avoid=(
            "Superlatives and absolute claims ('best', 'no. 1', 'guaranteed').",
            "Emoji and decorative symbols.",
            "Vague size language like 'compact' or 'spacious' with no number attached.",
        ),
    ),
    "wayfair_listing": ContentSkill(
        key="wayfair_listing",
        label="Wayfair / Overstock Listing",
        aliases=("wayfair", "overstock", "wayfair_listing", "属性表"),
        rules=(
            "Write to the attribute grid: style, material, finish, seating capacity, "
            "assembly, weight capacity, and box count all need explicit values.",
            "Name the design style the way the site's filters do (mid-century, farmhouse, "
            "boucle, industrial) so the piece surfaces in the right browse paths.",
            "State the delivery method plainly — LTL curbside, threshold, or white-glove — "
            "and how many cartons arrive.",
            "Describe care and cleaning, which drives a large share of pre-purchase questions.",
        ),
        output_contract=(
            "Provide: product name, a 2-3 sentence overview, 5-8 feature bullets, and an "
            "attribute list as 'Attribute: value' pairs.",
            "Include assembly required (yes/no), estimated assembly time, and carton count.",
            "Mark unsupplied attributes as [confirm ...].",
        ),
        avoid=("Marketing prose in place of a missing attribute value.",),
    ),
    "dtc_product_page": ContentSkill(
        key="dtc_product_page",
        label="DTC Product Page",
        aliases=("dtc", "product page", "shopify", "独立站", "商详", "详情页", "landing page"),
        rules=(
            "Open with the room problem the piece solves, not with the product category.",
            "Move from scene, to material and craft, to hard specs — shoppers skim in that order.",
            "Answer the objections that kill a furniture sale before they are asked: will it "
            "fit, how does it arrive, how hard is assembly, what if it does not work out.",
            "Own-store copy can carry more voice than a marketplace listing, but every claim "
            "still has to be true and checkable.",
        ),
        output_contract=(
            "Provide: H1, a short hero paragraph, 4-6 benefit sections with subheads, a "
            "dimensions table, a materials and care block, and 4-6 FAQ entries.",
            "FAQs must cover fit, delivery method, assembly, and returns.",
            "Mark unsupplied specs as [confirm ...].",
        ),
        avoid=("Burying dimensions below the fold.", "Stock phrases like 'elevate your space'."),
    ),
    "instagram": ContentSkill(
        key="instagram",
        label="Instagram (and organic Meta)",
        aliases=("instagram", "ig", "ins", "meta", "facebook", "reels", "carousel", "照片墙"),
        rules=(
            "Sell the room, not the object — the piece should read as part of a life.",
            "Open with a line that works as the first two visible words in the feed.",
            "Keep it conversational; one idea per post.",
            "For carousels, give each slide a purpose (scene, detail, dimensions, styling).",
            "For Reels, write a spoken script with a hook in the first three seconds.",
        ),
        output_contract=(
            "Caption under 300 characters unless the brief asks for long-form.",
            "3-6 hashtags mixing category and style terms.",
            "For carousels, label each slide 'Slide N:'. For Reels, give timestamped beats.",
            "If variants are requested, prefix each with 'Variant N:'.",
        ),
        avoid=("Spec dumps.", "Hashtag blocks.", "Corporate B2B phrasing."),
    ),
    "pinterest": ContentSkill(
        key="pinterest",
        label="Pinterest",
        aliases=("pinterest", "pin", "pins", "灵感图"),
        rules=(
            "Pinterest is a search engine: write for the query, not for a follower.",
            "Front-load the room, style, and product type in the title.",
            "Use the description to add the searchable context the image cannot carry — "
            "room type, style, color, material, and the problem it solves.",
            "Lean into planning intent (small-space, rental-friendly, apartment dining).",
        ),
        output_contract=(
            "Provide: Pin title (under 100 characters) and description (150-300 characters).",
            "Include 3-5 style or room keywords worked into the sentences, not appended.",
            "If a board is requested, suggest a board name and 5-8 pin ideas.",
        ),
        avoid=("Clickbait with no keyword value.", "Copy that only makes sense with the image."),
    ),
    "tiktok": ContentSkill(
        key="tiktok",
        label="TikTok Script",
        aliases=("tiktok", "tik tok", "短视频", "口播", "video script", "抖音"),
        rules=(
            "Hook in the first three seconds with a visible payoff, not a brand intro.",
            "Best-performing furniture formats are unboxing, honest assembly, small-space "
            "fit checks, and room transformations — pick one and commit to it.",
            "Write how a person talks, in short spoken beats.",
            "Show the awkward parts (carton size, assembly step) — the honesty is the hook.",
        ),
        output_contract=(
            "Provide timestamped beats (0-3s, 3-8s, ...) with on-screen text and voiceover "
            "for each, plus a caption and 3-5 hashtags.",
            "Keep total runtime under 45 seconds unless the brief says otherwise.",
        ),
        avoid=("Ad-read voice.", "Feature lists with no visual to match."),
    ),
    "blog": ContentSkill(
        key="blog",
        label="Blog / SEO Guide",
        aliases=("blog", "article", "guide", "seo", "文章", "博客", "指南"),
        rules=(
            "Target one buying question per post (how to measure for a sectional, what "
            "size dining table seats eight, solid wood vs engineered wood).",
            "Answer the question in the first paragraph, then earn the rest of the read.",
            "Use H2 sections that map to how a shopper narrows a decision.",
            "Include a sizing or comparison table — this is what gets cited and linked.",
            "Reference our own pieces only where they genuinely fit the answer.",
        ),
        output_contract=(
            "Include an H1 title, a direct-answer opening paragraph, and H2 sections.",
            "Include at least one table (dimensions, materials, or comparison).",
            "Target 900-1400 words for a full draft unless otherwise specified.",
        ),
        avoid=("Thin content that restates the title.", "Pushing product before answering."),
    ),
    "email": ContentSkill(
        key="email",
        label="Email / EDM",
        aliases=("email", "edm", "newsletter", "邮件", "邮件营销"),
        rules=(
            "One email, one job: new arrival, cart recovery, delivery update, or review request.",
            "For cart recovery on a high-ticket item, remove the doubt (fit, delivery, "
            "returns) rather than shouting a discount.",
            "Put the value in the subject line and the first line of body copy.",
            "Post-delivery emails should ask for a review and offer help with assembly.",
        ),
        output_contract=(
            "Include 'Subject:' and 'Preheader:' lines.",
            "Body under 180 words with a single primary CTA.",
            "If a sequence is requested, give each email a purpose and a send delay.",
        ),
        avoid=("Multiple competing CTAs.", "Discount-first framing on premium pieces."),
    ),
    "ad_copy": ContentSkill(
        key="ad_copy",
        label="Ad Copy",
        aliases=("ad", "ad_copy", "ads", "广告", "paid social", "search ad", "sponsored"),
        rules=(
            "State which platform the copy is for; the constraints differ sharply.",
            "Meta and Pinterest: lead with the room outcome and the visual promise.",
            "Google Shopping and Amazon Sponsored Products: lead with product type, "
            "material, and size, because the query already carries the intent.",
            "One pain point, one benefit, one action per variant.",
        ),
        output_contract=(
            "Provide 3 variants.",
            "Each variant includes Headline (under 40 characters), Description (under 90 "
            "characters), and CTA.",
            "Note the intended platform for each set.",
        ),
        avoid=("Price or promo claims that are not in the brief.", "Overclaiming durability."),
    ),
    "pdf": ContentSkill(
        key="pdf",
        label="PDF Deliverable",
        aliases=("pdf", "one-pager", "spec sheet", "catalog", "brochure", "brief", "deck", "规格单", "目录"),
        rules=(
            "Structure content as a shareable document: spec sheet, category catalog page, "
            "competitor listing comparison, or a launch brief.",
            "Spec sheets lead with the dimension drawing information and the materials table.",
            "Use concise sections with clear headings.",
        ),
        output_contract=(
            "Call the generate_pdf tool with a clean title and 3-8 sections.",
            "Match the PDF language to the requested output language in the brief.",
            "After the tool returns, briefly tell the user the PDF was generated.",
            "Do not paste the full PDF body back into chat.",
        ),
    ),
    "generic_social": ContentSkill(
        key="generic_social",
        label="Generic Social Post",
        aliases=("social", "social_post"),
        rules=(
            "Write clear, benefit-led copy anchored in a real room and a real use.",
            "Use a strong hook and a concise CTA.",
            "Adapt wording to the audience and tone in the brief.",
        ),
        output_contract=(
            "If multiple variants are requested, prefix each with 'Variant N:'.",
            "Use short paragraphs and relevant hashtags sparingly.",
        ),
    ),
}


FORMAT_DEFAULTS = {
    "listing": "amazon_listing",
    "product_page": "dtc_product_page",
    "social_post": "instagram",
    "blog": "blog",
    "email": "email",
    "ad_copy": "ad_copy",
    "pdf": "pdf",
}


def select_content_skill(format: str, task: str, platform: str | None = None) -> ContentSkill:
    """Select the most relevant content skill from explicit platform, task text, or format."""
    candidates = [platform, task]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.lower()
        for skill in SKILLS.values():
            if skill.key == normalized or any(alias in normalized for alias in skill.aliases):
                return skill

    return SKILLS[FORMAT_DEFAULTS.get(format, "generic_social")]
