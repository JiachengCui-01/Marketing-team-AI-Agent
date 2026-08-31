from __future__ import annotations

import unittest
from unittest import mock

from marketing_agent.agents import content_agent
from marketing_agent.agents.content_skills import select_content_skill
from server import marketing_skills


class ContentSkillTests(unittest.TestCase):
    def test_selects_amazon_listing_from_task(self) -> None:
        skill = select_content_skill("listing", "\u7ed9\u8fd9\u5f20\u9910\u684c\u5199\u4e00\u4efd\u4e9a\u9a6c\u900a listing")
        self.assertEqual(skill.key, "amazon_listing")

    def test_social_post_defaults_to_instagram(self) -> None:
        # The generic build defaulted social_post to LinkedIn; this business is
        # consumer-facing, so the default has to be a visual consumer channel.
        skill = select_content_skill("social_post", "Announce our new collection")
        self.assertEqual(skill.key, "instagram")

    def test_listing_format_defaults_to_amazon(self) -> None:
        skill = select_content_skill("listing", "Announce our new collection")
        self.assertEqual(skill.key, "amazon_listing")

    def test_explicit_platform_overrides_format_default(self) -> None:
        skill = select_content_skill(
            "social_post",
            "Announce our new collection",
            platform="pinterest",
        )
        self.assertEqual(skill.key, "pinterest")

    def test_content_agent_injects_selected_skill(self) -> None:
        captured: dict[str, str] = {}

        def fake_run_agent(**kwargs):
            captured["system"] = kwargs["system"]
            captured["user_message"] = kwargs["user_message"]
            return "ok"

        with mock.patch.object(content_agent, "run_agent", side_effect=fake_run_agent):
            result = content_agent.run(
                client=mock.Mock(),
                task="\u7ed9\u8fd9\u6b3e\u5b9e\u6728\u9910\u684c\u5199\u4e9a\u9a6c\u900a listing",
                format="listing",
            )

        self.assertEqual(result, "ok")
        self.assertIn("Platform skill: Amazon Listing", captured["user_message"])
        self.assertIn("Selected platform skill: amazon_listing", captured["user_message"])
        self.assertIn("Output language: Simplified Chinese", captured["user_message"])
        # The system prompt must forbid inventing physical specs.
        self.assertIn("[confirm", captured["system"])

    def test_content_agent_respects_explicit_english_request(self) -> None:
        captured: dict[str, str] = {}

        def fake_run_agent(**kwargs):
            captured["user_message"] = kwargs["user_message"]
            return "ok"

        with mock.patch.object(content_agent, "run_agent", side_effect=fake_run_agent):
            content_agent.run(
                client=mock.Mock(),
                task="请用英文生成一份竞品分析 PDF",
                format="pdf",
            )

        self.assertIn("Output language: English", captured["user_message"])

    def test_competitive_skill_requires_pdf_deliverable(self) -> None:
        skills = {skill["id"]: skill for skill in marketing_skills.list_skills()}

        self.assertTrue(skills["competitive-positioning-brief"]["requires_pdf"])
        self.assertFalse(skills["product-launch-campaign"]["requires_pdf"])
        self.assertTrue(marketing_skills.requires_pdf_deliverable(["competitive-positioning-brief"]))


if __name__ == "__main__":
    unittest.main()
