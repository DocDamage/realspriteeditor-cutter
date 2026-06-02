from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_ide_api import run_ide_command


REPO_ROOT = Path(__file__).resolve().parents[1]
IDE_SCRIPT = REPO_ROOT / "tools" / "sprite_ide_api.py"


def write_source(path: Path) -> None:
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    image.putpixel((7, 7), (0, 0, 0, 0))
    image.save(path)


class SpriteIdeApiTests(unittest.TestCase):
    def test_run_ide_command_dispatches_palette_swap_as_json_ready_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "blue.png"
            write_source(source)

            result = run_ide_command(
                {
                    "action": "palette.swap",
                    "input": str(source),
                    "output": str(output),
                    "swaps": {"#ff0000": "#0000ff"},
                }
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "palette.swap")
            self.assertEqual(result["output"], str(output))
            with Image.open(output) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_run_ide_command_dispatches_autotile_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output_dir = root / "autotile"
            write_source(source)

            result = run_ide_command(
                {
                    "action": "autotile.generate",
                    "input": str(source),
                    "output_dir": str(output_dir),
                    "name": "red_floor",
                    "engine": "godot",
                }
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "autotile.generate")
            self.assertTrue(Path(result["sheet"]).exists())
            self.assertTrue(Path(result["rules"]).exists())

    def test_run_ide_command_dispatches_sprite_edit_operation_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "edited.png"
            package_dir = root / "package"
            write_source(source)

            result = run_ide_command(
                {
                    "action": "sprite.edit",
                    "input": str(source),
                    "output": str(output),
                    "package_dir": str(package_dir),
                    "operations": [
                        {"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"},
                        {"tool": "crop", "rect": [0, 0, 4, 4]},
                        {"tool": "resize", "size": [8, 8]},
                    ],
                }
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "sprite.edit")
            self.assertEqual(result["summary"]["applied"], 3)
            self.assertTrue(output.exists())
            self.assertTrue(Path(result["package"]["manifest"]).exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (8, 8))
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_run_ide_command_dispatches_layer_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            package_dir = root / "package"
            write_source(source)

            result = run_ide_command(
                {
                    "action": "sprite.edit",
                    "input": str(source),
                    "package_dir": str(package_dir),
                    "operations": [
                        {"tool": "add_layer", "name": "paint"},
                        {"tool": "rename_layer", "index": 1, "name": "details"},
                        {"tool": "duplicate_layer", "index": 1, "name": "details_copy"},
                        {"tool": "reorder_layer", "from_index": 2, "to_index": 0},
                        {"tool": "set_layer_visibility", "index": 1, "visible": False},
                        {"tool": "set_layer_opacity", "index": 0, "opacity": 0.5},
                        {"tool": "select_layer", "index": 0},
                    ],
                }
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["summary"]["applied"], 7)
            self.assertEqual(result["summary"]["layers"], ["details_copy", "base", "details"])
            manifest = json.loads(Path(result["package"]["manifest"]).read_text(encoding="utf-8"))
            self.assertFalse(manifest["layers"][1]["visible"])
            self.assertEqual(manifest["layers"][0]["opacity"], 0.5)

    def test_run_ide_command_saves_sprite_edit_back_to_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            project_path = root / "project.spritecut.json"
            write_source(source)
            project_path.write_text(
                json.dumps({"schema_version": 1, "sprites": [{"id": "sprite_001", "review_status": "needs_review", "review_flags": ["edited"]}]}),
                encoding="utf-8",
            )

            result = run_ide_command(
                {
                    "action": "sprite.save_to_project",
                    "project_path": str(project_path),
                    "sprite_id": "sprite_001",
                    "input": str(source),
                    "operations": [{"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"}],
                }
            )

            updated = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual(result["ok"], True)
            self.assertTrue(Path(result["output"]).exists())
            self.assertEqual(updated["sprites"][0]["review_status"], "approved")
            self.assertEqual(updated["sprites"][0]["applied_output_file"], result["output"])
            with Image.open(result["output"]) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_run_ide_command_dispatches_palette_variant_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output_dir = root / "variants"
            write_source(source)

            result = run_ide_command(
                {
                    "action": "palette.variants",
                    "input": str(source),
                    "output_dir": str(output_dir),
                    "name": "crate",
                    "variants": [
                        {"name": "blue", "swaps": {"#ff0000": "#0000ff"}},
                        {"name": "green", "swaps": {"#ff0000": "#00ff00"}},
                    ],
                }
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "palette.variants")
            self.assertEqual(len(result["variants"]), 2)
            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["contact_sheet"]).exists())
            with Image.open(result["variants"][0]["image"]) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_run_ide_command_dispatches_sprite_batch_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.png"
            second = root / "second.png"
            output_dir = root / "batch"
            write_source(first)
            write_source(second)

            result = run_ide_command(
                {
                    "action": "sprite.batch_edit",
                    "inputs": [str(first), str(second)],
                    "output_dir": str(output_dir),
                    "operations": [{"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"}],
                }
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "sprite.batch_edit")
            self.assertEqual(result["edited"], 2)
            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["contact_sheet"]).exists())
            self.assertEqual(len(result["outputs"]), 2)

    def test_cli_accepts_json_request_file_and_prints_machine_readable_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "shifted.png"
            request = root / "request.json"
            write_source(source)
            request.write_text(
                json.dumps(
                    {
                        "action": "palette.hue_shift",
                        "input": str(source),
                        "output": str(output),
                        "degrees": 120,
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(IDE_SCRIPT), "--request", str(request)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            self.assertEqual(completed.returncode, 0)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["ok"], True)
            self.assertTrue(output.exists())

    def test_cli_request_file_resolves_relative_paths_from_request_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_dir = root / "sample-pack"
            request_dir.mkdir()
            source = request_dir / "source.png"
            output = request_dir / "outputs" / "blue.png"
            request = request_dir / "request.json"
            write_source(source)
            request.write_text(
                json.dumps(
                    {
                        "action": "palette.swap",
                        "input": "source.png",
                        "output": "outputs/blue.png",
                        "swaps": {"#ff0000": "#0000ff"},
                    }
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(IDE_SCRIPT), "--request", str(request)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["ok"], True)
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
