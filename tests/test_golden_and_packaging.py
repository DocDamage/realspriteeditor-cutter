from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.golden_sprite_fixtures import create_golden_pack, verify_golden_output


REPO_ROOT = Path(__file__).resolve().parents[1]


class GoldenAndPackagingTests(unittest.TestCase):
    def test_create_golden_pack_writes_expected_sheets_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            expected_path = create_golden_pack(root)

            self.assertTrue((root / "transparent_animation_rows" / "hero.png").exists())
            self.assertTrue((root / "packed_props_dark_bg" / "props.png").exists())
            self.assertTrue(expected_path.exists())
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            self.assertIn("cases", expected)
            self.assertIn("transparent_animation_rows", expected["cases"])

    def test_verify_golden_output_compares_summary_to_expected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected_path = root / "expected.json"
            expected_path.write_text(
                json.dumps({"cases": {"sample": {"summary": {"total_sprites": 2, "sheets_processed": 1}}}}),
                encoding="utf-8",
            )
            out_dir = root / "sample" / "out" / "manifest"
            out_dir.mkdir(parents=True)
            (out_dir / "summary.txt").write_text("total_sprites=2\nsheets_processed=1\n", encoding="utf-8")

            result = verify_golden_output(root / "sample" / "out", expected_path, "sample")

            self.assertEqual(result["status"], "pass")

    def test_docs_and_launchers_exist_for_handoff(self) -> None:
        readme = REPO_ROOT / "README.md"
        guide = REPO_ROOT / "docs" / "sprite_tool_aaa_guide.md"
        batch_launcher = REPO_ROOT / "launch_sprite_tool.bat"
        powershell_package = REPO_ROOT / "tools" / "package_sprite_tool.ps1"

        for path in [readme, guide, batch_launcher, powershell_package]:
            self.assertTrue(path.exists(), str(path))

        self.assertIn("AAA", guide.read_text(encoding="utf-8"))
        launcher_text = batch_launcher.read_text(encoding="utf-8")
        self.assertIn("sprite_sheet_tool_ui.py", launcher_text)
        self.assertIn("%*", launcher_text)
        self.assertIn("pause", launcher_text.lower())

    def test_duplicate_ui_entrypoints_delegate_to_canonical_tool_module(self) -> None:
        root_entrypoint = REPO_ROOT / "sprite_sheet_tool_ui.py"
        converted_entrypoint = REPO_ROOT / "realspriteeditor-cutter-dearpygui" / "tools" / "sprite_sheet_tool_ui.py"

        for path in [root_entrypoint, converted_entrypoint]:
            text = path.read_text(encoding="utf-8")
            self.assertLessEqual(len(text.splitlines()), 40, str(path))
            self.assertIn("tools.sprite_sheet_tool_ui", text)
            result = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Sprite Sheet Processor UI", result.stdout)

    def test_package_script_accepts_absolute_output_dir(self) -> None:
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell is not available.")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bundle"

            result = subprocess.run(
                [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(REPO_ROOT / "tools" / "package_sprite_tool.ps1"), "-OutDir", str(target)],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((target / "tools" / "cut_tileset_sprites.py").exists())
            self.assertTrue((target / "launch_sprite_tool.bat").exists())
            self.assertTrue((target / "requirements-ui.txt").exists())
            self.assertTrue((target / "requirements-dev.txt").exists())
            self.assertTrue((target / "requirements-mcp.txt").exists())
            self.assertTrue((target / "requirements-vision.txt").exists())
            self.assertTrue((target / "tools" / "sprite_mcp_server.py").exists())
            self.assertTrue((target / "tools" / "sprite_vision_labeler.py").exists())
            self.assertTrue((target / "skills" / "codex" / "spritecut-pipeline" / "SKILL.md").exists())

    def test_github_workflows_run_tests_compile_and_release_packaging(self) -> None:
        ci = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        release = REPO_ROOT / ".github" / "workflows" / "release.yml"

        self.assertTrue(ci.exists(), str(ci))
        self.assertTrue(release.exists(), str(release))

        ci_text = ci.read_text(encoding="utf-8")
        release_text = release.read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests -p \"test_*.py\"", ci_text)
        self.assertIn("python -m py_compile", ci_text)
        self.assertIn("tools/package_sprite_tool.ps1", ci_text)
        self.assertIn("actions/upload-artifact", release_text)
        self.assertIn("sprite-sheet-processor", release_text)

    def test_dev_requirements_document_test_dependencies(self) -> None:
        requirements = REPO_ROOT / "requirements-dev.txt"

        self.assertTrue(requirements.exists(), str(requirements))
        text = requirements.read_text(encoding="utf-8").lower()
        self.assertIn("pillow", text)
        self.assertIn("numpy", text)

    def test_mcp_requirements_and_readme_document_ide_server(self) -> None:
        requirements = REPO_ROOT / "requirements-mcp.txt"
        readme = REPO_ROOT / "README.md"

        self.assertTrue(requirements.exists(), str(requirements))
        self.assertIn("mcp[cli]", requirements.read_text(encoding="utf-8").lower())

        text = readme.read_text(encoding="utf-8")
        self.assertIn("SpriteCut MCP Server", text)
        self.assertIn("tools\\sprite_mcp_server.py", text)
        self.assertIn("requirements-mcp.txt", text)
        self.assertIn("spritecut://quality-checklist", text)
        self.assertIn("review_and_apply_project", text)
        self.assertIn("mcp_client_config", text)

    def test_vision_requirements_and_readme_document_semantic_labeling(self) -> None:
        requirements = REPO_ROOT / "requirements-vision.txt"
        readme = REPO_ROOT / "README.md"

        self.assertTrue(requirements.exists(), str(requirements))
        self.assertIn("openai", requirements.read_text(encoding="utf-8").lower())

        text = readme.read_text(encoding="utf-8")
        self.assertIn("project.vision_label", text)
        self.assertIn("requirements-vision.txt", text)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertIn("project_vision_label", text)


if __name__ == "__main__":
    unittest.main()
