from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_source_final_renames import build_final_rename_manifest, verify_final_rename_manifest
from tools.sprite_source_learning import write_source_learning_index


def write_sprite(path: Path, color: tuple[int, int, int, int] = (255, 0, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), color).save(path)


class SpriteSourceFinalRenamesTests(unittest.TestCase):
    def test_build_final_rename_manifest_uses_provider_name_for_sequence_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansimuz"
            write_sprite(root / "Assets" / "EnemyDeath" / "Sprites" / "enemy-death1.png")
            write_sprite(root / "Assets" / "EnemyDeath" / "Sprites" / "enemy-death2.png")
            index_path = Path(tmp) / "learning.json"
            output_path = Path(tmp) / "final-renames.json"
            write_source_learning_index(root, index_path)

            fixture_labels = {
                "Assets/EnemyDeath/Sprites/enemy_death": {
                    "final_semantic_base": "enemy_death_burst",
                    "category": "effects_and_particles",
                    "rename_confidence": 0.93,
                    "rationale": "Path says enemy death; image reads as an impact burst.",
                }
            }
            result = build_final_rename_manifest(
                index_path,
                output_path,
                provider_name="fixture",
                checkpoint_interval=0,
                fixture_labels=fixture_labels,
            )

            self.assertTrue(result["ok"])
            manifest = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["groups"][0]["final_semantic_base"], "enemy_death_burst")
            self.assertEqual(
                [item["target"] for item in manifest["file_renames"]],
                [
                    "Assets/EnemyDeath/Sprites/enemy_death_burst_frame_001.png",
                    "Assets/EnemyDeath/Sprites/enemy_death_burst_frame_002.png",
                ],
            )
            self.assertTrue(verify_final_rename_manifest(output_path)["ok"])

    def test_build_final_rename_manifest_disambiguates_duplicate_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansimuz"
            write_sprite(root / "Assets" / "Items" / "coin.png")
            write_sprite(root / "Assets" / "Items" / "gem.png", (0, 0, 255, 255))
            index_path = Path(tmp) / "learning.json"
            output_path = Path(tmp) / "final-renames.json"
            write_source_learning_index(root, index_path)

            fixture_labels = {
                "Assets/Items/coin": {
                    "final_semantic_base": "pickup_icon",
                    "category": "props_and_items",
                    "rename_confidence": 0.8,
                    "rationale": "Collectible pickup.",
                },
                "Assets/Items/gem": {
                    "final_semantic_base": "pickup_icon",
                    "category": "props_and_items",
                    "rename_confidence": 0.8,
                    "rationale": "Collectible pickup.",
                },
            }
            result = build_final_rename_manifest(
                index_path,
                output_path,
                provider_name="fixture",
                checkpoint_interval=0,
                fixture_labels=fixture_labels,
            )

            self.assertTrue(result["ok"])
            targets = [item["target"] for item in json.loads(output_path.read_text(encoding="utf-8"))["file_renames"]]
            self.assertEqual(targets, ["Assets/Items/pickup_icon.png", "Assets/Items/pickup_icon_02.png"])
            self.assertTrue(verify_final_rename_manifest(output_path)["ok"])


if __name__ == "__main__":
    unittest.main()
