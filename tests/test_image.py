from __future__ import annotations

import os
import unittest
from unittest import mock

from server import db, image_processing
from marketing_agent.agents.image_skills import IMAGE_SKILLS, select_image_skill
from marketing_agent.tools import image_gen

# A minimal valid 1x1 PNG.
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


class ImageSkillTests(unittest.TestCase):
    def test_select_by_chinese_alias(self) -> None:
        self.assertEqual(select_image_skill(None, "帮我做一张小红书封面").key, "xiaohongshu")
        self.assertEqual(select_image_skill(None, "淘宝主图").key, "taobao")

    def test_explicit_style_key_wins(self) -> None:
        self.assertEqual(select_image_skill("amazon", "random").key, "amazon")

    def test_unknown_defaults_to_generic(self) -> None:
        self.assertEqual(select_image_skill(None, "hello world").key, "generic")

    def test_prompt_prefix_mentions_platform_and_ratio(self) -> None:
        skill = IMAGE_SKILLS["taobao"]
        prefix = skill.prompt_prefix()
        self.assertIn(skill.label, prefix)
        self.assertIn(skill.aspect_ratio, prefix)


class ImageGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_key = os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self) -> None:
        if self._saved_key is not None:
            os.environ["GEMINI_API_KEY"] = self._saved_key
        else:
            os.environ.pop("GEMINI_API_KEY", None)

    def test_unavailable_without_key(self) -> None:
        result = image_gen.generate_image("a bottle", skill=IMAGE_SKILLS["generic"])
        self.assertTrue(result["unavailable"])
        self.assertFalse(result["ok"])
        self.assertIn("GEMINI_API_KEY", result["message"])

    def test_success_writes_png(self) -> None:
        os.environ["GEMINI_API_KEY"] = "test-key"
        with mock.patch.object(image_gen, "_generate_raw", return_value=_PNG_1x1) as raw:
            result = image_gen.generate_image(
                "a bottle on a desk",
                skill=IMAGE_SKILLS["xiaohongshu"],
                reference_images=[(b"ref", "image/png")],
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mime"], "image/png")
        self.assertTrue(os.path.exists(result["path"]))
        raw.assert_called_once()
        os.remove(result["path"])

    def test_empty_model_response_is_unavailable(self) -> None:
        os.environ["GEMINI_API_KEY"] = "test-key"
        with mock.patch.object(image_gen, "_generate_raw", return_value=None):
            result = image_gen.generate_image("x", skill=IMAGE_SKILLS["generic"])
        self.assertTrue(result["unavailable"])

    def test_sdk_error_degrades_gracefully(self) -> None:
        os.environ["GEMINI_API_KEY"] = "test-key"
        with mock.patch.object(image_gen, "_generate_raw", side_effect=RuntimeError("boom")):
            result = image_gen.generate_image("x", skill=IMAGE_SKILLS["generic"])
        self.assertTrue(result["unavailable"])
        self.assertIn("boom", result["message"])


class ImageProcessingTests(unittest.TestCase):
    def _client_returning(self, text: str):
        client = mock.Mock()
        block = mock.Mock()
        block.type = "text"
        block.text = text
        response = mock.Mock()
        response.content = [block]
        client.messages.create.return_value = response
        return client

    def test_classify_object(self) -> None:
        client = self._client_returning("object")
        self.assertEqual(image_processing.classify_subject(client, b"x", "image/png"), "object")

    def test_classify_screenshot(self) -> None:
        client = self._client_returning("screenshot")
        self.assertEqual(image_processing.classify_subject(client, b"x", "image/png"), "screenshot")

    def test_classify_ambiguous_defaults_to_screenshot(self) -> None:
        client = self._client_returning("¯\\_(ツ)_/¯")
        self.assertEqual(image_processing.classify_subject(client, b"x", "image/png"), "screenshot")

    def test_classify_error_defaults_to_screenshot(self) -> None:
        client = mock.Mock()
        client.messages.create.side_effect = RuntimeError("api down")
        self.assertEqual(image_processing.classify_subject(client, b"x", "image/png"), "screenshot")

    def test_process_object_runs_cutout(self) -> None:
        client = self._client_returning("object")
        with mock.patch.object(image_processing, "cutout", return_value=b"CUT") as cut:
            out = image_processing.process_upload(client, b"img", "image/png")
        self.assertEqual(out["classification"], "object")
        self.assertEqual(out["cutout_png"], b"CUT")
        cut.assert_called_once()

    def test_process_screenshot_skips_cutout(self) -> None:
        client = self._client_returning("screenshot")
        with mock.patch.object(image_processing, "cutout") as cut:
            out = image_processing.process_upload(client, b"img", "image/png")
        self.assertIsNone(out["cutout_png"])
        cut.assert_not_called()

    def test_process_cutout_failure_degrades(self) -> None:
        client = self._client_returning("object")
        with mock.patch.object(
            image_processing, "cutout", side_effect=image_processing.CutoutUnavailable("no rembg")
        ):
            out = image_processing.process_upload(client, b"img", "image/png")
        self.assertIsNone(out["cutout_png"])
        self.assertIn("no rembg", out["warning"])


class ImageDbTests(unittest.TestCase):
    def setUp(self) -> None:
        db.reset_for_tests()
        self.a = db.create_user(
            account="a@example.com", password_hash="h", username="A",
            real_name="用户甲", id_card="11010519491231002X",
        )
        self.b = db.create_user(
            account="b@example.com", password_hash="h", username="B",
            real_name="用户乙", id_card="11010519491231002X",
        )

    def tearDown(self) -> None:
        db.reset_for_tests()

    def test_history_crud_and_isolation(self) -> None:
        rec = db.add_image_history(
            self.a["id"], prompt="p", style_key="taobao",
            artifact_id=None, source_upload_id=None, params={"aspect_ratio": "1:1"},
        )
        self.assertEqual(db.list_image_history(self.a["id"])[0]["id"], rec["id"])
        self.assertEqual(db.list_image_history(self.b["id"]), [])
        # cross-user get/delete are rejected
        self.assertIsNone(db.get_image_history(rec["id"], self.b["id"]))
        self.assertFalse(db.delete_image_history(rec["id"], self.b["id"]))
        self.assertTrue(db.delete_image_history(rec["id"], self.a["id"]))
        self.assertEqual(db.list_image_history(self.a["id"]), [])

    def test_params_roundtrip(self) -> None:
        db.add_image_history(
            self.a["id"], prompt="p", style_key="generic",
            artifact_id=None, source_upload_id=None, params={"template_id": "tpl_x"},
        )
        got = db.list_image_history(self.a["id"])[0]
        self.assertEqual(got["params"]["template_id"], "tpl_x")

    def test_templates_seeded_and_filterable(self) -> None:
        self.assertTrue(len(db.list_image_templates()) >= 5)
        taobao = db.list_image_templates("taobao")
        self.assertTrue(taobao)
        self.assertTrue(all(t["platform"] == "taobao" for t in taobao))

    def test_template_seed_is_idempotent(self) -> None:
        before = len(db.list_image_templates())
        # Re-run init seeding on a fresh connection; count must not grow.
        with db._connect() as conn:  # type: ignore[attr-defined]
            db._seed_image_templates(conn)  # type: ignore[attr-defined]
        self.assertEqual(len(db.list_image_templates()), before)


if __name__ == "__main__":
    unittest.main()
