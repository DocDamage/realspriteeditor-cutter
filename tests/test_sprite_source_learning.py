from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.sprite_source_learning import build_source_learning_index, safe_name, write_source_learning_index


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-an-image-but-a-source-file-placeholder")


class SpriteSourceLearningTests(unittest.TestCase):
    def test_safe_name_normalizes_asset_terms(self) -> None:
        self.assertEqual(safe_name("Enemy Death! 01"), "enemy_death_01")
        self.assertEqual(safe_name(" explosion-1-b "), "explosion_1_b")

    def test_build_source_learning_index_groups_animation_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansimuz"
            touch(root / "Legacy Collection" / "Assets" / "Explosions and Magic" / "EnemyDeath" / "Sprites" / "enemy-death1.png")
            touch(root / "Legacy Collection" / "Assets" / "Explosions and Magic" / "EnemyDeath" / "Sprites" / "enemy-death2.png")
            touch(root / "Legacy Collection" / "Assets" / "Explosions and Magic" / "Explosions pack" / "explosion-1-b" / "Sprites" / "explosion-1-b-1.png")
            touch(root / "Legacy Collection" / "Assets" / "Explosions and Magic" / "Explosions pack" / "explosion-1-b" / "Sprites" / "explosion-1-b-2.png")
            touch(root / "__MACOSX" / "._ignored.png")

            index = build_source_learning_index(root)

            self.assertEqual(index["total_images"], 4)
            groups = {group["semantic_base"]: group for group in index["groups"]}
            self.assertIn("enemy_death", groups)
            self.assertIn("explosion_1_b", groups)
            self.assertEqual(groups["enemy_death"]["kind"], "animation_sequence")
            self.assertEqual(groups["enemy_death"]["frame_count"], 2)
            self.assertEqual(groups["enemy_death"]["rename_pattern"], "enemy_death_frame_{frame:03d}")
            self.assertEqual(groups["explosion_1_b"]["suggested_category"], "animation")

    def test_write_source_learning_index_creates_compact_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansimuz"
            output = Path(tmp) / "ansimuz_learning.json"
            touch(root / "Assets" / "UI Icons" / "heart-icon.png")

            result = write_source_learning_index(root, output)

            self.assertTrue(result["ok"])
            self.assertTrue(output.exists())
            self.assertEqual(result["total_images"], 1)

    def test_generic_frame_names_use_parent_folder_as_semantic_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ansimuz"
            touch(root / "Assets" / "Explosions pack" / "explosion-1-g" / "Sprites" / "frame_01.png")
            touch(root / "Assets" / "Explosions pack" / "explosion-1-g" / "Sprites" / "frame_02.png")

            index = build_source_learning_index(root)

            groups = {group["semantic_base"]: group for group in index["groups"]}
            self.assertIn("explosion_1_g", groups)
            self.assertEqual(groups["explosion_1_g"]["rename_pattern"], "explosion_1_g_frame_{frame:03d}")


if __name__ == "__main__":
    unittest.main()
