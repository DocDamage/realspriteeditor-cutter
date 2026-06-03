from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tools.sprite_source_learning import write_source_learning_index
from tools.sprite_source_vision import enrich_source_learning_with_vision, verify_source_vision


def write_sprite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(path)


class SpriteSourceVisionTests(unittest.TestCase):
    def test_enrich_source_learning_with_vision_labels_groups_and_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansimuz"
            write_sprite(root / "Assets" / "EnemyDeath" / "Sprites" / "enemy-death1.png")
            write_sprite(root / "Assets" / "EnemyDeath" / "Sprites" / "enemy-death2.png")
            index_path = Path(tmp) / "learning.json"
            output_path = Path(tmp) / "learning.vision.json"
            write_source_learning_index(root, index_path)

            fixture_labels = {
                "Assets/EnemyDeath/Sprites/enemy_death": {
                    "display_name": "enemy_death_burst",
                    "category": "animation",
                    "description": "Enemy death burst animation.",
                    "confidence": 0.94,
                }
            }
            with mock.patch.dict("os.environ", {}, clear=False):
                result = enrich_source_learning_with_vision(
                    index_path,
                    output_path,
                    provider_name="fixture",
                    checkpoint_interval=0,
                    limit=0,
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["missing_groups"], 1)

            from tools.sprite_vision_labeler import FixtureVisionProvider

            with mock.patch("tools.sprite_source_vision.provider_from_name", return_value=FixtureVisionProvider(fixture_labels)):
                result = enrich_source_learning_with_vision(
                    index_path,
                    output_path,
                    provider_name="fixture",
                    checkpoint_interval=0,
                )

            self.assertTrue(result["ok"])
            enriched = json.loads(output_path.read_text(encoding="utf-8"))
            group = enriched["groups"][0]
            self.assertEqual(group["vision_semantic_base"], "enemy_death_burst")
            self.assertEqual(group["vision_rename_pattern"], "enemy_death_burst_frame_{frame:03d}")
            self.assertEqual(enriched["vision_summary"]["missing_groups"], 0)
            self.assertTrue(verify_source_vision(output_path)["ok"])


if __name__ == "__main__":
    unittest.main()
