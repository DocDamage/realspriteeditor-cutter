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


if __name__ == "__main__":
    unittest.main()
