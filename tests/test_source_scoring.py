from __future__ import annotations

import unittest

from marketing_agent import source_scoring


class SourceScoringTests(unittest.TestCase):
    def test_official_and_authoritative_sources_score_high(self) -> None:
        official = source_scoring.score_url("https://www.sec.gov/news/press-release")
        media = source_scoring.score_url("https://www.reuters.com/technology/ai-news")

        self.assertEqual(official.tier, 1)
        self.assertEqual(media.tier, 2)
        self.assertFalse(official.is_weak_signal)
        self.assertGreater(official.score, media.score)

    def test_self_media_and_community_sources_are_weak(self) -> None:
        medium = source_scoring.score_url("https://medium.com/@analyst/post")
        substack = source_scoring.score_url("https://example.substack.com/p/post")
        reddit = source_scoring.score_url("https://www.reddit.com/r/marketing/comments/1")
        zhihu = source_scoring.score_url("https://www.zhihu.com/question/123")

        self.assertEqual(medium.tier, 3)
        self.assertEqual(substack.tier, 3)
        self.assertEqual(reddit.tier, 4)
        self.assertEqual(zhihu.tier, 4)
        self.assertTrue(all(s.is_weak_signal for s in (medium, substack, reddit, zhihu)))

    def test_chinese_media_sources_score_as_authoritative(self) -> None:
        xinhua = source_scoring.score_url("https://www.news.cn/tech/2026-07/18/c_123.htm")
        caixin = source_scoring.score_url("https://www.caixin.com/2026-07-18/101.htm")
        kr = source_scoring.score_url("https://www.36kr.com/p/123")

        self.assertEqual(xinhua.tier, 2)
        self.assertEqual(caixin.tier, 2)
        self.assertEqual(kr.tier, 2)
        self.assertFalse(any(source.is_weak_signal for source in (xinhua, caixin, kr)))

    def test_extracts_markdown_and_bare_urls_once(self) -> None:
        text = (
            "See [SEC](https://www.sec.gov/news/press-release). "
            "Also https://www.reuters.com/world/. "
            "Duplicate https://www.reuters.com/world/."
        )

        urls = source_scoring.extract_urls(text)

        self.assertEqual(
            urls,
            [
                "https://www.sec.gov/news/press-release",
                "https://www.reuters.com/world/",
            ],
        )

    def test_extracts_bare_url_before_chinese_punctuation(self) -> None:
        urls = source_scoring.extract_urls("参考：https://www.news.cn/tech/2026.htm）。")

        self.assertEqual(urls, ["https://www.news.cn/tech/2026.htm"])

    def test_extract_source_references_uses_markdown_title(self) -> None:
        refs = source_scoring.extract_source_references(
            "See [Reuters AI update](https://www.reuters.com/technology/ai-news)."
        )

        self.assertEqual(refs[0].title, "Reuters AI update")
        self.assertEqual(refs[0].display_text, "Reuters AI update")
        self.assertEqual(refs[0].domain, "reuters.com")

    def test_sources_are_sorted_by_score(self) -> None:
        text = "\n".join(
            [
                "https://www.reddit.com/r/marketing/comments/1",
                "https://www.sec.gov/news/press-release",
                "https://medium.com/post",
            ]
        )

        sources = source_scoring.score_sources(text)

        self.assertEqual([source.domain for source in sources], ["sec.gov", "medium.com", "reddit.com"])

    def test_annotation_adds_weak_signal_notice(self) -> None:
        annotated = source_scoring.annotate_markdown_with_source_tiers(
            "## Summary\nA market rumor. https://www.reddit.com/r/marketing/comments/1",
            language="en",
        )

        self.assertIn("## Source Credibility", annotated)
        self.assertIn("weak signals", annotated)
        self.assertIn("Tier 4", annotated)

    def test_annotation_strips_raw_source_sections_after_scoring(self) -> None:
        annotated = source_scoring.annotate_markdown_with_source_tiers(
            "## Summary\nFresh news.\n\n## Sources\n1. https://www.reuters.com/technology/",
            language="en",
        )

        self.assertIn("## Source Credibility", annotated)
        self.assertNotIn("## Sources", annotated)
        self.assertIn("[reuters.com](https://www.reuters.com/technology/)", annotated)

    def test_strip_raw_source_sections_preserves_credibility_section(self) -> None:
        text = (
            "## Summary\nFresh news.\n\n"
            "## 来源\n1. https://www.news.cn/tech/\n\n"
            "## 来源可信度\n本摘要优先基于 Tier 1/Tier 2 来源。"
        )

        stripped = source_scoring.strip_raw_source_sections(text)

        self.assertNotIn("## 来源\n", stripped)
        self.assertNotIn("https://www.news.cn/tech/", stripped)
        self.assertIn("## 来源可信度", stripped)


if __name__ == "__main__":
    unittest.main()
