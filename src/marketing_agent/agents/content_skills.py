"""Platform-specific copywriting skills for the content agent."""
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
    "linkedin": ContentSkill(
        key="linkedin",
        label="LinkedIn",
        aliases=("linkedin", "linked in", "\u9886\u82f1"),
        rules=(
            "Write for B2B decision-makers and practitioners.",
            "Lead with a sharp business problem, market observation, or outcome.",
            "Use short paragraphs and clear line breaks for scanability.",
            "Prefer concrete benefits, proof points, and operational language.",
            "End with a light CTA or discussion prompt.",
        ),
        output_contract=(
            "Keep each post under 1300 characters unless the brief asks otherwise.",
            "If multiple variants are requested, prefix each with 'Variant N:'.",
            "Use 1-4 relevant hashtags, not a hashtag block.",
        ),
        avoid=(
            "Overly inspirational corporate filler.",
            "Dense paragraphs or generic thought-leadership cliches.",
        ),
    ),
    "twitter": ContentSkill(
        key="twitter",
        label="Twitter/X",
        aliases=("twitter", "x/twitter", "tweet", "tweets", "x post"),
        rules=(
            "Write compact, punchy copy with one clear idea per post.",
            "Use a strong first sentence and avoid setup-heavy intros.",
            "Favor specificity, contrast, or a practical takeaway.",
        ),
        output_contract=(
            "Keep each post under 280 characters.",
            "If a thread is requested, number each tweet.",
            "Use at most 1-2 hashtags.",
        ),
        avoid=("Long CTAs.", "LinkedIn-style paragraph structure."),
    ),
    "xiaohongshu": ContentSkill(
        key="xiaohongshu",
        label="Xiaohongshu / Little Red Book",
        aliases=("xiaohongshu", "little red book", "\u5c0f\u7ea2\u4e66", "xhs", "rednote"),
        rules=(
            "Use a warm, conversational, experience-sharing tone.",
            "Open with a direct hook in the first line.",
            "Use short, mobile-friendly paragraphs.",
            "Use emoji naturally to create rhythm and warmth.",
            "Make the content feel useful, relatable, and save-worthy.",
        ),
        output_contract=(
            "Write 3-7 short paragraphs unless the brief asks otherwise.",
            "End with 3-5 topic hashtags.",
            "If variants are requested, prefix each with 'Variant N:'.",
        ),
        avoid=(
            "Overly corporate B2B phrasing.",
            "Long essay-like paragraphs.",
            "Hard-sell language that feels like an ad.",
        ),
    ),
    "blog": ContentSkill(
        key="blog",
        label="Blog",
        aliases=("blog", "article", "\u6587\u7ae0", "\u535a\u5ba2"),
        rules=(
            "Use an editorial structure with a clear argument.",
            "Start with a hook paragraph that frames the reader's problem.",
            "Use H2 sections that progress logically from problem to solution.",
            "Include practical examples or implications where useful.",
        ),
        output_contract=(
            "Include an H1 title.",
            "Include a hook paragraph.",
            "Use H2 headings for the outline/body.",
            "For a full draft, target 600-900 words unless otherwise specified.",
        ),
    ),
    "email": ContentSkill(
        key="email",
        label="Email",
        aliases=("email", "\u90ae\u4ef6", "newsletter", "edm"),
        rules=(
            "Make the value proposition obvious above the fold.",
            "Use concise paragraphs and one primary message.",
            "Keep the CTA specific and action-oriented.",
        ),
        output_contract=(
            "Include 'Subject:' and 'Preheader:' lines.",
            "Keep the body under 200 words unless otherwise specified.",
            "Use a single CTA.",
        ),
        avoid=("Multiple competing CTAs.", "Long background sections."),
    ),
    "ad_copy": ContentSkill(
        key="ad_copy",
        label="Ad Copy",
        aliases=("ad", "ad_copy", "\u5e7f\u544a", "paid social", "search ad"),
        rules=(
            "Focus on one pain point, one benefit, and one action.",
            "Make the promise clear without overclaiming.",
            "Use direct response phrasing where appropriate.",
        ),
        output_contract=(
            "Provide 2-3 variants.",
            "Each variant includes Headline, Description, and CTA.",
            "Headline should be under 40 characters.",
            "Description should be under 90 characters.",
        ),
    ),
    "pdf": ContentSkill(
        key="pdf",
        label="PDF Deliverable",
        aliases=("pdf", "one-pager", "brochure", "brief", "deck"),
        rules=(
            "Structure content as a polished shareable marketing deliverable.",
            "Use concise sections with clear headings.",
            "Make reasonable assumptions when audience or product details are missing.",
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
            "Write clear, benefit-led social copy.",
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
    "social_post": "linkedin",
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
