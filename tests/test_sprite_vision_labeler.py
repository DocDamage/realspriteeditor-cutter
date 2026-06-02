from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tools.sprite_vision_labeler import FixtureVisionProvider, label_project_with_vision, provider_from_name


def write_sprite(path: Path) -> None:
    image = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    for y in range(2, 10):
        for x in range(4, 8):
            image.putpixel((x, y), (40, 180, 40, 255))
    image.save(path)


class SpriteVisionLabelerTests(unittest.TestCase):
    def test_label_project_with_vision_updates_semantic_fields_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sprite_path = root / "sprites" / "tree.png"
            sprite_path.parent.mkdir()
            write_sprite(sprite_path)
            project_path = root / "project.spritecut.json"
            project_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sprites": [
                            {
                                "id": "sprite_001",
                                "display_name": "sheet_unknown_001",
                                "category": "geometry_rectangles",
                                "output_file": str(sprite_path),
                                "review_status": "needs_review",
                                "review_flags": ["auto_named"],
                                "confidence": 0.52,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureVisionProvider(
                {
                    "sprite_001": {
                        "display_name": "oak_tree",
                        "category": "vegetation_and_trees",
                        "description": "A small green oak tree sprite.",
                        "confidence": 0.93,
                    }
                }
            )

            result = label_project_with_vision(project_path, provider=provider, min_confidence=0.8)

            updated = json.loads(project_path.read_text(encoding="utf-8"))
            sprite = updated["sprites"][0]
            self.assertEqual(result["ok"], True)
            self.assertEqual(result["labeled"], 1)
            self.assertEqual(sprite["display_name"], "oak_tree")
            self.assertEqual(sprite["category"], "vegetation_and_trees")
            self.assertEqual(sprite["review_status"], "approved")
            self.assertIn("vision_labeled", sprite["review_flags"])
            self.assertNotIn("auto_named", sprite["review_flags"])
            self.assertEqual(sprite["vision_label"]["provider"], "fixture")
            self.assertTrue((root / "manifest" / "vision_label_cache.json").exists())

    def test_low_confidence_vision_label_marks_sprite_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sprite_path = root / "crate.png"
            write_sprite(sprite_path)
            project_path = root / "project.spritecut.json"
            project_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sprites": [
                            {
                                "id": "sprite_001",
                                "display_name": "unknown_001",
                                "category": "sprites",
                                "output_file": str(sprite_path),
                                "review_status": "needs_review",
                                "review_flags": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureVisionProvider(
                {
                    "sprite_001": {
                        "display_name": "maybe_crate",
                        "category": "props_and_items",
                        "description": "Possibly a crate.",
                        "confidence": 0.44,
                    }
                }
            )

            label_project_with_vision(project_path, provider=provider, min_confidence=0.8)

            sprite = json.loads(project_path.read_text(encoding="utf-8"))["sprites"][0]
            self.assertEqual(sprite["display_name"], "unknown_001")
            self.assertEqual(sprite["category"], "sprites")
            self.assertEqual(sprite["review_status"], "needs_review")
            self.assertIn("vision_low_confidence", sprite["review_flags"])

    def test_gemini_and_nano_banana_provider_aliases_require_google_credentials(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
            for provider in ("gemini", "nano_banana"):
                with self.subTest(provider=provider):
                    with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY or GOOGLE_API_KEY"):
                        provider_from_name(provider)


if __name__ == "__main__":
    unittest.main()
