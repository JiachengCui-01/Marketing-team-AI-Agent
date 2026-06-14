from __future__ import annotations

import unittest
from unittest import mock

from marketing_agent.agents import content_agent
from marketing_agent.agents.content_skills import select_content_skill


class ContentSkillTests(unittest.TestCase):
    def test_selects_xiaohongshu_from_task(self) -> None:
        skill = select_content_skill(
            "social_post",
            "\u4e3a\u5c0f\u7ea2\u4e66\u751f\u6210\u4e00\u7bc7\u65b0\u54c1\u79cd\u8349\u6587\u6848",
        )
        self.assertEqual(skill.key, "xiaohongshu")

    def test_social_post_defaults_to_linkedin(self) -> None:
        skill = select_content_skill("social_post", "Announce our new feature")
        self.assertEqual(skill.key, "linkedin")

    def test_explicit_platform_overrides_format_default(self) -> None:
        skill = select_content_skill(
            "social_post",
            "Announce our new feature",
            platform="twitter",
        )
        self.assertEqual(skill.key, "twitter")

    def test_content_agent_injects_selected_skill(self) -> None:
        captured: dict[str, str] = {}

        def fake_run_agent(**kwargs):
            captured["system"] = kwargs["system"]
            captured["user_message"] = kwargs["user_message"]
            return "ok"

        with mock.patch.object(content_agent, "run_agent", side_effect=fake_run_agent):
            result = content_agent.run(
                client=mock.Mock(),
                task="\u4e3a\u5c0f\u7ea2\u4e66\u751f\u6210\u65b0\u54c1\u79cd\u8349\u6587\u6848",
                format="social_post",
            )

        self.assertEqual(result, "ok")
        self.assertIn("Platform skill: Xiaohongshu", captured["user_message"])
        self.assertIn("Selected platform skill: xiaohongshu", captured["user_message"])
        self.assertNotIn("Twitter/X", captured["system"])


if __name__ == "__main__":
    unittest.main()
