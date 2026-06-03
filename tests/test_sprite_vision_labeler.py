from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tools.sprite_vision_labeler import FixtureVisionProvider, label_project_with_vision, provider_from_name
from tools.reconstruct_sprite_project_from_cuts import write_reconstructed_project
from tools.seeded_sprite_vision import apply_seeded_labels, count_missing_vision_labels


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

    def test_label_project_with_vision_checkpoints_cache_during_long_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sprites_dir = root / "sprites"
            sprites_dir.mkdir()
            project_path = root / "project.spritecut.json"
            sprites = []
            labels = {}
            for index in range(2):
                sprite_id = f"sprite_{index + 1:03d}"
                sprite_path = sprites_dir / f"{sprite_id}.png"
                write_sprite(sprite_path)
                sprites.append(
                    {
                        "id": sprite_id,
                        "display_name": sprite_id,
                        "category": "sprites",
                        "output_file": str(sprite_path),
                        "review_status": "needs_review",
                        "review_flags": [],
                    }
                )
                labels[sprite_id] = {
                    "display_name": f"labeled_{index + 1}",
                    "category": "props_and_items",
                    "description": "A labeled test sprite.",
                    "confidence": 0.95,
                }
            project_path.write_text(json.dumps({"schema_version": 1, "sprites": sprites}), encoding="utf-8")
            provider = FixtureVisionProvider(labels)

            with mock.patch("tools.sprite_vision_labeler._write_cache") as write_cache:
                label_project_with_vision(project_path, provider=provider, checkpoint_interval=1)

            self.assertEqual(write_cache.call_count, 3)

    def test_gemini_and_nano_banana_provider_aliases_require_google_credentials(self) -> None:
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}, clear=False):
            for provider in ("gemini", "nano_banana"):
                with self.subTest(provider=provider):
                    with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY or GOOGLE_API_KEY"):
                        provider_from_name(provider)

    def test_reconstruct_project_from_cut_pngs_writes_vision_ready_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sprite_path = root / "sprites" / "props_and_items" / "crate.png"
            anim_path = root / "animations" / "hero_idle" / "row_01" / "row_01_001.png"
            sprite_path.parent.mkdir(parents=True)
            anim_path.parent.mkdir(parents=True)
            write_sprite(sprite_path)
            write_sprite(anim_path)
            project_path = root / "project.spritecut.vision.json"

            result = write_reconstructed_project(root, project_path, progress_interval=0)

            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual(result["total_sprites"], 2)
            self.assertEqual(project["schema_version"], 1)
            self.assertEqual(len(project["sprites"]), 2)
            self.assertEqual(project["sprites"][0]["category"], "props_and_items")
            self.assertEqual(project["sprites"][1]["kind"], "animation_frame")
            self.assertEqual(project["sprites"][1]["sequence"], "hero_idle_row_01")

    def test_apply_seeded_labels_streams_vision_labels_without_loading_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_path = root / "project.spritecut.vision.json"
            output_path = root / "project.spritecut.vision.seeded.json"
            seed_path = root / "manifest" / "vision_category_seeds.json"
            project_path.write_text(
                "\n".join(
                    [
                        "{",
                        '  "schema_version": 1,',
                        '  "sprites": [',
                        json.dumps({"id": "sprite_001", "display_name": "wood_crate", "category": "props_and_items", "review_flags": ["auto_named"], "review_status": "needs_review"})
                        + ",",
                        json.dumps({"id": "sprite_002", "display_name": "idle_001", "category": "animation", "review_flags": [], "review_status": "needs_review"}),
                        "  ],",
                        '  "summary": {"total_sprites": 2}',
                        "}",
                    ]
                ),
                encoding="utf-8",
            )
            seed_path.parent.mkdir()
            seed_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "provider": "gemini",
                        "seeds": {
                            "props_and_items": {
                                "display_name": "wooden_crate",
                                "category": "props_and_items",
                                "description": "A wooden crate.",
                                "confidence": 0.92,
                                "provider": "gemini",
                                "seed_category": "props_and_items",
                                "seed_sprite_id": "sprite_001",
                                "seed_image": "crate.png",
                            },
                            "animation": {
                                "display_name": "idle_pose",
                                "category": "animation",
                                "description": "A character idle frame.",
                                "confidence": 0.9,
                                "provider": "gemini",
                                "seed_category": "animation",
                                "seed_sprite_id": "sprite_002",
                                "seed_image": "idle.png",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = apply_seeded_labels(project_path, seed_path, output_path, progress_interval=0)
            counts = count_missing_vision_labels(output_path)

            self.assertEqual(result["total"], 2)
            self.assertEqual(counts["missing"], 0)
            labeled = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(labeled["sprites"][0]["review_status"], "approved")
            self.assertEqual(labeled["sprites"][0]["vision_label"]["provider"], "gemini_seeded")
            self.assertIn("vision_labeled", labeled["sprites"][0]["review_flags"])
            self.assertIn("vision_seeded", labeled["sprites"][1]["review_flags"])


if __name__ == "__main__":
    unittest.main()
