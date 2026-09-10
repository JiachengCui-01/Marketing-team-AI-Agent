from __future__ import annotations

import os
import unittest
from unittest import mock

from server import db, image_processing, image_serve
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
        self.assertEqual(select_image_skill(None, "帮我做一张亚马逊主图").key, "amazon")
        self.assertEqual(select_image_skill(None, "独立站首页 hero 图").key, "dtc_site")

    def test_explicit_style_key_wins(self) -> None:
        self.assertEqual(select_image_skill("amazon", "random").key, "amazon")

    def test_unknown_defaults_to_generic(self) -> None:
        self.assertEqual(select_image_skill(None, "hello world").key, "generic")

    def test_prompt_prefix_mentions_platform_and_ratio(self) -> None:
        skill = IMAGE_SKILLS["amazon"]
        prefix = skill.prompt_prefix()
        self.assertIn(skill.label, prefix)
        self.assertIn(skill.aspect_ratio, prefix)

    def test_every_skill_is_publishable_on_its_own(self) -> None:
        """A style has to fully specify a deliverable — that is what makes an empty
        prompt runnable instead of an error."""
        for key, skill in IMAGE_SKILLS.items():
            with self.subTest(skill=key):
                self.assertTrue(skill.default_request.strip())
                self.assertTrue(skill.platform_rules)
                self.assertTrue(skill.art_direction)
                self.assertTrue(skill.pixel_target.strip())
                self.assertTrue(skill.usage_note.strip())
                # Ratios the image model actually accepts.
                self.assertIn(skill.aspect_ratio, {"1:1", "2:3", "3:2", "4:5", "5:4", "16:9", "9:16"})
                self.assertIn(skill.aspect_ratio, skill.render())

    def test_amazon_main_image_rules_are_compliance_not_taste(self) -> None:
        rules = " ".join(IMAGE_SKILLS["amazon"].platform_rules).lower()
        self.assertIn("255,255,255", rules)
        self.assertIn("no props", rules)
        self.assertIn("no text", rules)

    def test_pinterest_uses_recommended_pin_ratio(self) -> None:
        self.assertEqual(IMAGE_SKILLS["pinterest"].aspect_ratio, "2:3")

    def test_style_rules_alias_still_reads_art_direction(self) -> None:
        skill = IMAGE_SKILLS["instagram"]
        self.assertEqual(skill.style_rules, skill.art_direction)


class BuildPromptTests(unittest.TestCase):
    def test_empty_request_runs_the_skill_default_brief(self) -> None:
        skill = IMAGE_SKILLS["amazon"]
        text = image_gen.build_prompt("", skill, reference=image_gen.REFERENCE_PRODUCT)
        self.assertIn(skill.default_request, text)
        self.assertIn("None given", text)

    def test_user_request_is_carried_verbatim(self) -> None:
        text = image_gen.build_prompt("放在暖色调餐厅里", IMAGE_SKILLS["instagram"])
        self.assertIn("放在暖色调餐厅里", text)
        self.assertNotIn("None given", text)
        self.assertNotIn(IMAGE_SKILLS["instagram"].default_request, text)

    def test_platform_rules_survive_a_conflicting_request(self) -> None:
        """The request stays in the prompt, but the compliance rule outranks it."""
        text = image_gen.build_prompt("把它放进客厅场景，加上尺寸文字", IMAGE_SKILLS["amazon"])
        self.assertIn("把它放进客厅场景", text)
        self.assertIn("255,255,255", text)
        self.assertIn("PRECEDENCE", text)
        self.assertIn("satisfy the platform rule", text)

    def test_subject_fidelity_only_when_a_photo_is_attached(self) -> None:
        skill = IMAGE_SKILLS["wayfair"]
        with_photo = image_gen.build_prompt("x", skill, reference=image_gen.REFERENCE_PRODUCT)
        self.assertIn("SUBJECT FIDELITY", with_photo)
        self.assertIn("may not redesign", with_photo)
        self.assertNotIn("SUBJECT FIDELITY", image_gen.build_prompt("x", skill))

    def test_re_edit_gets_edit_scope_not_product_fidelity(self) -> None:
        """A re-edit attachment is our own render and the request is to change it;
        the product-fidelity wording would refuse the edit just asked for."""
        text = image_gen.build_prompt(
            "把木色改成深胡桃色", IMAGE_SKILLS["amazon"],
            reference=image_gen.REFERENCE_PRIOR_RENDER,
        )
        self.assertIn("EDIT SCOPE", text)
        self.assertNotIn("SUBJECT FIDELITY", text)
        self.assertIn("unless the request explicitly asks", text)

    def test_explicit_ratio_overrides_the_skill_default(self) -> None:
        text = image_gen.build_prompt("x", IMAGE_SKILLS["amazon"], "16:9")
        self.assertIn("Aspect ratio: 16:9", text)

    def test_delivery_rules_include_the_shared_baseline(self) -> None:
        text = image_gen.build_prompt("x", IMAGE_SKILLS["generic"])
        self.assertIn("Photographic realism", text)
        self.assertIn("DELIVERY QUALITY", text)


class ImageGenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_key = os.environ.pop("GEMINI_API_KEY", None)

    def tearDown(self) -> None:
        if self._saved_key is not None:
            os.environ["GEMINI_API_KEY"] = self._saved_key
        else:
            os.environ.pop("GEMINI_API_KEY", None)

    def test_unavailable_without_key(self) -> None:
        with mock.patch.object(image_gen, "load_dotenv", return_value=False):
            result = image_gen.generate_image("a bottle", skill=IMAGE_SKILLS["generic"])
        self.assertTrue(result["unavailable"])
        self.assertFalse(result["ok"])
        self.assertIn("GEMINI_API_KEY", result["message"])

    def test_api_key_falls_back_to_dotenv_loader(self) -> None:
        def fake_load_dotenv(*args, **kwargs):
            os.environ["GEMINI_API_KEY"] = "loaded-from-dotenv"
            return True

        with mock.patch.object(image_gen, "load_dotenv", side_effect=fake_load_dotenv):
            self.assertEqual(image_gen._api_key(), "loaded-from-dotenv")

    def test_success_writes_png(self) -> None:
        os.environ["GEMINI_API_KEY"] = "test-key"
        with mock.patch.object(image_gen, "_generate_raw", return_value=_PNG_1x1) as raw:
            result = image_gen.generate_image(
                "a bottle on a desk",
                skill=IMAGE_SKILLS["pinterest"],
                reference_images=[(b"ref", "image/png")],
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mime"], "image/png")
        self.assertTrue(os.path.exists(result["path"]))
        raw.assert_called_once()
        os.remove(result["path"])

    def test_ratio_is_passed_to_the_sdk_seam(self) -> None:
        """Prompt text alone does not control the ratio; a 16:9 hero returned square
        is unusable as a banner."""
        os.environ["GEMINI_API_KEY"] = "test-key"
        with mock.patch.object(image_gen, "_generate_raw", return_value=_PNG_1x1) as raw:
            result = image_gen.generate_image("hero", skill=IMAGE_SKILLS["dtc_site"])
        self.assertEqual(raw.call_args.args[3], "16:9")
        os.remove(result["path"])

    def test_image_config_carries_the_requested_ratio(self) -> None:
        config = image_gen._image_config("4:5")
        if config is None:  # older google-genai without ImageConfig
            self.skipTest("SDK has no ImageConfig")
        self.assertEqual(config.image_config.aspect_ratio, "4:5")

    def test_only_ratio_rejections_trigger_the_bare_retry(self) -> None:
        self.assertTrue(image_gen._is_image_config_rejection(RuntimeError("image_config unsupported")))
        self.assertTrue(image_gen._is_image_config_rejection(RuntimeError("bad aspect ratio")))
        self.assertFalse(image_gen._is_image_config_rejection(RuntimeError("RESOURCE_EXHAUSTED")))

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
            self.a["id"], prompt="p", style_key="amazon",
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
        amazon = db.list_image_templates("amazon")
        self.assertTrue(amazon)
        self.assertTrue(all(t["platform"] == "amazon" for t in amazon))

    def test_template_seed_is_idempotent(self) -> None:
        before = len(db.list_image_templates())
        # Re-run init seeding on a fresh connection; count must not grow.
        with db._connect() as conn:  # type: ignore[attr-defined]
            db._seed_image_templates(conn)  # type: ignore[attr-defined]
        self.assertEqual(len(db.list_image_templates()), before)


class OptimizedPreviewTests(unittest.TestCase):
    def _write(self, name: str, img) -> str:
        import tempfile

        p = os.path.join(tempfile.mkdtemp(), name)
        img.save(p)
        return p

    def test_opaque_image_becomes_jpeg(self) -> None:
        from PIL import Image

        src = self._write("big.png", Image.new("RGB", (2000, 2000), (10, 120, 200)))
        out, media = image_serve.optimized_preview(src, "opt_opaque")
        self.assertEqual(media, "image/jpeg")
        self.assertTrue(os.path.exists(out))
        with Image.open(out) as im:  # downscaled to the max-edge cap
            self.assertLessEqual(max(im.size), image_serve.MAX_EDGE)

    def test_alpha_image_stays_png(self) -> None:
        from PIL import Image

        src = self._write("cut.png", Image.new("RGBA", (1200, 1200), (0, 0, 0, 0)))
        out, media = image_serve.optimized_preview(src, "opt_alpha")
        self.assertEqual(media, "image/png")

    def test_non_image_passes_through(self) -> None:
        import tempfile

        p = os.path.join(tempfile.mkdtemp(), "doc.pdf")
        with open(p, "wb") as fh:
            fh.write(b"%PDF-1.4")
        out, _ = image_serve.optimized_preview(p, "opt_pdf")
        self.assertEqual(out, p)


if __name__ == "__main__":
    unittest.main()
