from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_project import (
    approve_sprite,
    load_project,
    merge_sprites,
    move_sprite_bbox,
    redo_last_edit,
    reject_sprite,
    render_project_outputs,
    save_project,
    split_sprite,
    undo_last_edit,
    update_sprite,
)


def sample_project() -> dict[str, object]:
    return {
        "schema_version": 1,
        "tool": "spritecut",
        "settings": {"mode": "tileset"},
        "summary": {"total_sprites": 1},
        "errors": [],
        "sprites": [
            {
                "id": "sheet_props_medium_props_001",
                "display_name": "sheet_props_medium_props_001",
                "category": "medium_props",
                "source_file": "G:/assets/props.png",
                "output_file": "G:/assets/out/sprites/medium_props/sheet_props_medium_props_001.png",
                "bbox": {"x": 10, "y": 20, "width": 30, "height": 40},
                "pivot": {"x": 0.5, "y": 0.8, "method": "hybrid"},
                "confidence": 0.72,
                "review_flags": ["touches_edge"],
                "review_status": "needs_review",
            }
        ],
    }


def sample_render_project(root: Path) -> dict[str, object]:
    source = root / "source.png"
    image = Image.new("RGBA", (32, 24), (255, 255, 255, 0))
    for x in range(2, 10):
        for y in range(3, 15):
            image.putpixel((x, y), (220, 40, 40, 255))
    for x in range(18, 28):
        for y in range(4, 18):
            image.putpixel((x, y), (40, 180, 80, 255))
    image.save(source)
    return {
        "schema_version": 1,
        "tool": "spritecut",
        "settings": {},
        "summary": {"total_sprites": 2},
        "errors": [],
        "history": [],
        "redo_stack": [],
        "sprites": [
            {
                "id": "sprite_001",
                "display_name": "red_crate_01",
                "category": "crates",
                "kind": "sprite",
                "source_file": str(source),
                "output_file": str(root / "old" / "sprite_001.png"),
                "bbox": {"x": 2, "y": 3, "width": 8, "height": 12},
                "pivot": {"x": 0.5, "y": 0.5, "method": "manual"},
                "confidence": 1.0,
                "review_flags": [],
                "review_status": "approved",
            },
            {
                "id": "sprite_002",
                "display_name": "green_bin_01",
                "category": "bins",
                "kind": "sprite",
                "source_file": str(source),
                "output_file": str(root / "old" / "sprite_002.png"),
                "bbox": {"x": 18, "y": 4, "width": 10, "height": 14},
                "pivot": {"x": 0.5, "y": 0.5, "method": "manual"},
                "confidence": 0.0,
                "review_flags": ["rejected"],
                "review_status": "rejected",
            },
        ],
    }


class SpriteProjectTests(unittest.TestCase):
    def test_save_and_load_project_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.spritecut.json"
            project = sample_project()

            save_project(project, path)
            loaded = load_project(path)

            self.assertEqual(loaded["schema_version"], 1)
            self.assertEqual(loaded["sprites"][0]["id"], "sheet_props_medium_props_001")

    def test_update_sprite_edits_reviewable_fields_and_records_history(self) -> None:
        project = sample_project()

        update_sprite(
            project,
            "sheet_props_medium_props_001",
            display_name="shelf_broken_01",
            category="tall_shelves_and_racks",
            bbox={"x": 12, "y": 18, "width": 32, "height": 44},
            pivot={"x": 0.45, "y": 0.9, "method": "manual"},
            review_status="needs_review",
            review_flags=["manual_bbox"],
        )

        sprite = project["sprites"][0]
        self.assertEqual(sprite["display_name"], "shelf_broken_01")
        self.assertEqual(sprite["category"], "tall_shelves_and_racks")
        self.assertEqual(sprite["bbox"]["x"], 12)
        self.assertEqual(sprite["pivot"]["method"], "manual")
        self.assertEqual(sprite["review_flags"], ["manual_bbox"])
        self.assertEqual(project["history"][0]["sprite_id"], "sheet_props_medium_props_001")
        self.assertIn("before", project["history"][0])
        self.assertIn("after", project["history"][0])

    def test_approve_sprite_marks_sprite_approved_and_clears_flags(self) -> None:
        project = sample_project()

        approve_sprite(project, "sheet_props_medium_props_001")

        sprite = project["sprites"][0]
        self.assertEqual(sprite["review_status"], "approved")
        self.assertEqual(sprite["review_flags"], [])
        self.assertEqual(sprite["confidence"], 1.0)

    def test_reject_sprite_marks_sprite_rejected(self) -> None:
        project = sample_project()

        reject_sprite(project, "sheet_props_medium_props_001")

        sprite = project["sprites"][0]
        self.assertEqual(sprite["review_status"], "rejected")
        self.assertIn("rejected", sprite["review_flags"])
        self.assertEqual(sprite["confidence"], 0.0)

    def test_move_sprite_bbox_records_manual_bbox_edit(self) -> None:
        project = sample_project()

        move_sprite_bbox(project, "sheet_props_medium_props_001", dx=5, dy=-7)

        sprite = project["sprites"][0]
        self.assertEqual(sprite["bbox"], {"x": 15, "y": 13, "width": 30, "height": 40})
        self.assertIn("manual_bbox", sprite["review_flags"])
        self.assertEqual(sprite["review_status"], "needs_review")

    def test_split_sprite_adds_manual_child_sprites_and_rejects_original(self) -> None:
        project = sample_project()

        children = split_sprite(
            project,
            "sheet_props_medium_props_001",
            [
                {"x": 10, "y": 20, "width": 12, "height": 40},
                {"x": 24, "y": 20, "width": 16, "height": 40},
            ],
        )

        self.assertEqual([child["id"] for child in children], ["sheet_props_medium_props_001_split_01", "sheet_props_medium_props_001_split_02"])
        self.assertEqual(project["sprites"][0]["review_status"], "rejected")
        self.assertEqual(len(project["sprites"]), 3)
        self.assertEqual(project["sprites"][1]["bbox"]["width"], 12)
        self.assertIn("manual_split", project["sprites"][1]["review_flags"])
        self.assertEqual(project["sprites"][1]["review_status"], "needs_review")
        self.assertEqual(project["history"][-1]["action"], "split_sprite")

    def test_merge_sprites_adds_union_sprite_and_rejects_sources(self) -> None:
        project = sample_project()
        split_sprite(
            project,
            "sheet_props_medium_props_001",
            [
                {"x": 10, "y": 20, "width": 12, "height": 40},
                {"x": 24, "y": 20, "width": 16, "height": 40},
            ],
        )

        merged = merge_sprites(
            project,
            ["sheet_props_medium_props_001_split_01", "sheet_props_medium_props_001_split_02"],
            merged_id="shelf_merged_01",
            display_name="shelf_merged_01",
        )

        self.assertEqual(merged["id"], "shelf_merged_01")
        self.assertEqual(merged["bbox"], {"x": 10, "y": 20, "width": 30, "height": 40})
        self.assertIn("manual_merge", merged["review_flags"])
        self.assertEqual(merged["review_status"], "needs_review")
        self.assertEqual(project["sprites"][1]["review_status"], "rejected")
        self.assertEqual(project["sprites"][2]["review_status"], "rejected")
        self.assertEqual(project["history"][-1]["action"], "merge_sprites")

    def test_undo_and_redo_last_edit_restore_sprite_state(self) -> None:
        project = sample_project()
        update_sprite(project, "sheet_props_medium_props_001", display_name="shelf_broken_01")

        undo_last_edit(project)
        sprite = project["sprites"][0]
        self.assertEqual(sprite["display_name"], "sheet_props_medium_props_001")
        self.assertEqual(len(project["history"]), 0)
        self.assertEqual(len(project["redo_stack"]), 1)

        redo_last_edit(project)
        self.assertEqual(sprite["display_name"], "shelf_broken_01")
        self.assertEqual(len(project["history"]), 1)
        self.assertEqual(len(project["redo_stack"]), 0)

    def test_undo_and_redo_split_restore_sprite_collection(self) -> None:
        project = sample_project()

        split_sprite(
            project,
            "sheet_props_medium_props_001",
            [
                {"x": 10, "y": 20, "width": 12, "height": 40},
                {"x": 24, "y": 20, "width": 16, "height": 40},
            ],
        )
        self.assertEqual(len(project["sprites"]), 3)

        undo_last_edit(project)

        self.assertEqual(len(project["sprites"]), 1)
        self.assertEqual(project["sprites"][0]["id"], "sheet_props_medium_props_001")
        self.assertEqual(project["sprites"][0]["review_status"], "needs_review")
        self.assertEqual(len(project["redo_stack"]), 1)

        redo_last_edit(project)

        self.assertEqual(len(project["sprites"]), 3)
        self.assertEqual(project["sprites"][0]["review_status"], "rejected")
        self.assertEqual([sprite["id"] for sprite in project["sprites"][1:]], ["sheet_props_medium_props_001_split_01", "sheet_props_medium_props_001_split_02"])

    def test_undo_and_redo_merge_restore_sprite_collection(self) -> None:
        project = sample_project()
        split_sprite(
            project,
            "sheet_props_medium_props_001",
            [
                {"x": 10, "y": 20, "width": 12, "height": 40},
                {"x": 24, "y": 20, "width": 16, "height": 40},
            ],
        )
        merge_sprites(
            project,
            ["sheet_props_medium_props_001_split_01", "sheet_props_medium_props_001_split_02"],
            merged_id="shelf_merged_01",
            display_name="shelf_merged_01",
        )

        undo_last_edit(project)

        self.assertNotIn("shelf_merged_01", [sprite["id"] for sprite in project["sprites"]])
        self.assertEqual(project["sprites"][1]["review_status"], "needs_review")
        self.assertEqual(project["sprites"][2]["review_status"], "needs_review")

        redo_last_edit(project)

        self.assertIn("shelf_merged_01", [sprite["id"] for sprite in project["sprites"]])
        self.assertEqual(project["sprites"][1]["review_status"], "rejected")
        self.assertEqual(project["sprites"][2]["review_status"], "rejected")

    def test_render_project_outputs_writes_reviewed_crops_and_skips_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = sample_render_project(root)
            project_path = root / "project.spritecut.json"
            save_project(project, project_path)

            result = render_project_outputs(project, project_path)

            self.assertEqual(result["rendered"], 1)
            self.assertEqual(result["skipped_rejected"], 1)
            rendered_file = root / "applied_project" / "sprites" / "crates" / "red_crate_01.png"
            rejected_file = root / "applied_project" / "sprites" / "bins" / "green_bin_01.png"
            self.assertTrue(rendered_file.exists())
            self.assertFalse(rejected_file.exists())
            with Image.open(rendered_file) as image:
                self.assertEqual(image.size, (8, 12))
                self.assertEqual(image.getpixel((0, 0)), (220, 40, 40, 255))
            self.assertEqual(project["sprites"][0]["applied_output_file"], str(rendered_file))
            self.assertTrue((root / "applied_project" / "manifest" / "project_sprites.json").exists())

    def test_render_project_outputs_uses_unique_paths_for_duplicate_display_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = sample_render_project(root)
            duplicate = dict(project["sprites"][0])
            duplicate["id"] = "sprite_003"
            duplicate["bbox"] = {"x": 3, "y": 4, "width": 6, "height": 8}
            duplicate["display_name"] = "red_crate_01"
            project["sprites"].append(duplicate)
            project_path = root / "project.spritecut.json"
            save_project(project, project_path)

            render_project_outputs(project, project_path)

            output_files = [Path(sprite["applied_output_file"]).name for sprite in project["sprites"] if sprite.get("applied_output_file")]
            self.assertEqual(output_files, ["red_crate_01.png", "red_crate_01_02.png"])
            self.assertTrue((root / "applied_project" / "sprites" / "crates" / "red_crate_01_02.png").exists())

    def test_render_project_outputs_clamps_out_of_bounds_bbox_and_flags_sprite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = sample_render_project(root)
            project["sprites"][0]["bbox"] = {"x": -2, "y": -1, "width": 12, "height": 16}
            project_path = root / "project.spritecut.json"
            save_project(project, project_path)

            result = render_project_outputs(project, project_path)

            rendered_file = Path(project["sprites"][0]["applied_output_file"])
            self.assertEqual(result["rendered"], 1)
            self.assertIn("bbox_clamped", project["sprites"][0]["review_flags"])
            self.assertEqual(project["sprites"][0]["bbox"], {"x": 0, "y": 0, "width": 10, "height": 15})
            with Image.open(rendered_file) as image:
                self.assertEqual(image.size, (10, 15))

    def test_render_project_outputs_writes_review_aware_engine_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = sample_render_project(root)
            project["settings"]["engine_exports"] = ["unity", "godot", "unreal"]
            project["animation_clips"] = [
                {
                    "name": "sheet_idle",
                    "source_sheet": "sheet",
                    "sequence": "idle",
                    "frame_rate": 10,
                    "loop": True,
                    "frames": [
                        {"sprite": "sprite_001", "frame": 1, "duration": 0.1, "source_file": "old/red.png"},
                        {"sprite": "sprite_002", "frame": 2, "duration": 0.1, "source_file": "old/green.png"},
                    ],
                }
            ]
            project_path = root / "project.spritecut.json"
            save_project(project, project_path)

            result = render_project_outputs(project, project_path)

            exports_dir = root / "applied_project" / "exports"
            self.assertEqual(sorted(result["exports"]), ["godot", "unity", "unreal"])
            with (exports_dir / "unity_sprites.json").open(encoding="utf-8") as handle:
                unity = json.load(handle)
            self.assertEqual(unity["sprites"][0]["display_name"], "red_crate_01")
            self.assertEqual(unity["sprites"][0]["source_file"], project["sprites"][0]["applied_output_file"])
            self.assertEqual(len(unity["sprites"]), 1)
            self.assertEqual(unity["animation_clips"][0]["frame_count"], 1)
            self.assertEqual(unity["animation_clips"][0]["frames"][0]["source_file"], project["sprites"][0]["applied_output_file"])
            self.assertTrue((exports_dir / "godot_sprites.json").exists())
            self.assertTrue((exports_dir / "unreal_sprites.json").exists())


if __name__ == "__main__":
    unittest.main()
