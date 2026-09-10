from __future__ import annotations

import io
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from server import marketing_skills as skills


def archive(files: dict) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            if isinstance(name, str):
                info = zipfile.ZipInfo(name)
                info.filename = name  # Keep hostile paths verbatim on Windows too.
                name = info
            zipped.writestr(name, content)
    return output.getvalue()


class SkillUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "skills"
        patch = mock.patch.object(skills, "SKILLS_DIR", self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def test_wrapped_skill_is_discovered_and_injected(self):
        result = skills.install_skill_archive(archive({
            "bundle/custom/SKILL.md": "# Custom SOP\n\nUse our launch method.",
            "bundle/custom/references/nested/guide.md": "Reference evidence.",
            "bundle/custom/scripts/helper.py": "raise RuntimeError('must not run')",
            "bundle/custom/assets/template.txt": "Template",
        }), "download.zip")
        self.assertEqual(result["id"], "custom")
        self.assertEqual(result["name"], "Custom SOP")
        prompt = skills.build_skill_addendum(["custom"])
        self.assertIn("Use our launch method.", prompt)
        self.assertIn("Reference evidence.", prompt)
        self.assertTrue((self.root / "custom/scripts/helper.py").is_file())
        self.assertEqual(len(skills.list_skills()), 1)

    def test_flat_archive_creates_standard_directories_and_rejects_overwrite(self):
        data = archive({"SKILL.md": "# Flat\nInstructions"})
        skills.install_skill_archive(data, "my-skill.zip")
        for folder in ("references", "scripts", "assets"):
            self.assertTrue((self.root / "my-skill" / folder).is_dir())
        with self.assertRaises(FileExistsError):
            skills.install_skill_archive(data, "my-skill.zip")
        self.assertEqual((self.root / "my-skill/SKILL.md").read_text(), "# Flat\nInstructions")

    def test_frontmatter_name_and_multiline_description(self):
        result = skills.install_skill_archive(archive({"SKILL.md":
            "---\nname: custom-name\ndescription: >\n  First line\n  second line\n---\nFollow this SOP."
        }), "metadata.zip")
        self.assertEqual(result["name"], "custom-name")
        self.assertEqual(result["description"], "First line second line")

    def test_invalid_archives_leave_no_installed_skill(self):
        cases = [
            {"../escape": "bad", "SKILL.md": "ok"},
            {"C:/escape": "bad", "SKILL.md": "ok"},
            {"a\\escape": "bad", "SKILL.md": "ok"},
            {"NUL.txt": "bad", "SKILL.md": "ok"},
            {"readme.md": "missing"},
            {"a/SKILL.md": "a", "b/SKILL.md": "b"},
            {"SKILL.md": "   "},
            {"SKILL.md": b"\xff\xfe"},
            {"SKILL.md": "ok", "references": "file"},
            {"SKILL.md": "ok", "a": "file", "a/b": "child"},
            {"SKILL.md": "ok", "A.md": "one", "a.md": "two"},
        ]
        for files in cases:
            with self.subTest(files=list(files)), self.assertRaises(ValueError):
                skills.install_skill_archive(archive(files), "bad.zip")
            self.assertEqual(skills.list_skills(), [])
        with self.assertRaises(ValueError):
            skills.install_skill_archive(b"not a zip", "bad.zip")

    def test_symlink_and_resource_limits(self):
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            skills.install_skill_archive(archive({"SKILL.md": "ok", link: "outside"}), "bad.zip")
        with mock.patch.object(skills, "MAX_EXTRACTED_BYTES", 5), self.assertRaises(ValueError):
            skills.install_skill_archive(archive({"SKILL.md": "too large"}), "bad.zip")
        with mock.patch.object(skills, "MAX_ARCHIVE_FILES", 1), self.assertRaises(ValueError):
            skills.install_skill_archive(archive({"SKILL.md": "ok", "a": "b"}), "bad.zip")
        with mock.patch.object(skills, "MAX_ARCHIVE_BYTES", 1), self.assertRaises(ValueError):
            skills.install_skill_archive(b"ab", "bad.zip")

    def test_upload_api_auth_discovery_and_errors(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from server import routes

        app = FastAPI()
        app.include_router(routes.router)
        client = TestClient(app)
        data = archive({"SKILL.md": "# API skill\nUse this custom procedure."})
        with mock.patch.object(routes.auth, "require_user", side_effect=HTTPException(401, "Unauthorized")):
            self.assertEqual(client.post("/api/skills/upload", files={"file": ("api-skill.zip", data)}).status_code, 401)
        self.assertEqual(skills.list_skills(), [])
        with mock.patch.object(routes.auth, "require_user", return_value={"id": "test"}):
            response = client.post("/api/skills/upload", files={"file": ("api-skill.zip", data)})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["skill"]["id"], "api-skill")
            self.assertEqual(client.get("/api/skills").json()["skills"][0]["id"], "api-skill")
            self.assertEqual(client.post("/api/skills/upload", files={"file": ("api-skill.zip", data)}).status_code, 409)
            self.assertEqual(client.post("/api/skills/upload", files={"file": ("bad.zip", b"bad")}).status_code, 400)
            with mock.patch.object(skills, "MAX_ARCHIVE_BYTES", 1):
                self.assertEqual(client.post("/api/skills/upload", files={"file": ("big.zip", data)}).status_code, 413)

    def test_delete_removes_files_and_prompt_without_touching_other_skills(self):
        data = archive({"SKILL.md": "# Custom\nUnique SOP.", "references/a.md": "Evidence"})
        skills.install_skill_archive(data, "remove-me.zip")
        skills.install_skill_archive(data, "keep-me.zip")
        skills.delete_skill("remove-me")
        self.assertFalse((self.root / "remove-me").exists())
        self.assertEqual(skills.build_skill_addendum(["remove-me"]), "")
        self.assertEqual([s["id"] for s in skills.list_skills()], ["keep-me"])
        with self.assertRaises(FileNotFoundError):
            skills.delete_skill("remove-me")
        for invalid in ("..", "../keep-me", "..\\keep-me", str(self.root), ".hidden"):
            with self.assertRaises(ValueError):
                skills.delete_skill(invalid)
        self.assertTrue((self.root / "keep-me/SKILL.md").exists())

    def test_delete_api_requires_login_and_reports_missing_skill(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from server import routes

        app = FastAPI()
        app.include_router(routes.router)
        client = TestClient(app)
        skills.install_skill_archive(archive({"SKILL.md": "# Test\nSOP"}), "delete-me.zip")
        with mock.patch.object(routes.auth, "require_user", side_effect=HTTPException(401, "Unauthorized")):
            self.assertEqual(client.delete("/api/skills/delete-me").status_code, 401)
        self.assertTrue((self.root / "delete-me").exists())
        with mock.patch.object(routes.auth, "require_user", return_value={"id": "test"}):
            response = client.delete("/api/skills/delete-me")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"deleted": "delete-me"})
            self.assertEqual(client.delete("/api/skills/delete-me").status_code, 404)


if __name__ == "__main__":
    unittest.main()
