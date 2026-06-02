from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_project import save_project
from tools.sprite_studio import (
    apply_taxonomy_rules,
    asset_browser_index,
    batch_health_score,
    build_atlas_upgrade_plan,
    build_engine_import_plans,
    build_review_dashboard,
    diff_projects,
    generate_collision_profiles,
    review_and_apply_project,
    search_assets,
    train_preset_from_project,
)


def sample_project(source_file: str = "supermarket.png") -> dict[str, object]:
    return {
        "schema_version": 1,
        "tool": "spritecut",
        "settings": {
            "mode": "auto",
            "engine_exports": ["unity", "godot", "unreal"],
            "atlas_size": 2048,
            "atlas_padding": 2,
        },
        "summary": {"total_sprites": 4},
        "errors": [],
        "history": [],
        "redo_stack": [],
        "animation_clips": [
            {
                "name": "hero_idle",
                "source_sheet": "supermarket",
                "sequence": "idle",
                "frame_rate": 12,
                "loop": True,
                "frames": [{"sprite": "hero_idle_001", "frame": 1, "duration": 0.0833}],
            }
        ],
        "sprites": [
            {
                "id": "shelf_001",
                "display_name": "duplicate_name",
                "category": "shelves",
                "kind": "sprite",
                "source_file": source_file,
                "bbox": {"x": 2, "y": 3, "width": 16, "height": 24},
                "pivot": {"x": 0.5, "y": 0.85, "method": "hybrid"},
                "confidence": 0.96,
                "review_flags": [],
                "review_status": "approved",
            },
            {
                "id": "prop_001",
                "display_name": "duplicate_name",
                "category": "props",
                "kind": "sprite",
                "source_file": source_file,
                "bbox": {"x": 22, "y": 5, "width": 10, "height": 8},
                "pivot": {"x": 0.5, "y": 0.5, "method": "hybrid"},
                "confidence": 0.62,
                "review_flags": ["touches_edge", "tiny_component"],
                "review_status": "needs_review",
            },
            {
                "id": "hero_idle_001",
                "display_name": "hero_idle_001",
                "category": "props",
                "kind": "animation_frame",
                "sequence": "idle",
                "frame": 1,
                "source_file": source_file,
                "bbox": {"x": 4, "y": 34, "width": 18, "height": 26},
                "pivot": {"x": 0.5, "y": 0.9, "method": "hybrid"},
                "confidence": 0.9,
                "review_flags": ["manual_bbox"],
                "review_status": "approved",
            },
            {
                "id": "trash_rejected_001",
                "display_name": "trash_rejected_001",
                "category": "noise",
                "kind": "sprite",
                "source_file": source_file,
                "bbox": {"x": 40, "y": 5, "width": 3, "height": 3},
                "confidence": 0.0,
                "review_flags": ["rejected", "tiny_component"],
                "review_status": "rejected",
            },
        ],
    }


def renderable_project(root: Path) -> dict[str, object]:
    source = root / "supermarket.png"
    image = Image.new("RGBA", (72, 72), (255, 255, 255, 0))
    for x in range(2, 18):
        for y in range(3, 27):
            image.putpixel((x, y), (120, 80, 55, 255))
    for x in range(22, 32):
        for y in range(5, 13):
            image.putpixel((x, y), (80, 160, 90, 255))
    for x in range(4, 22):
        for y in range(34, 60):
            image.putpixel((x, y), (60, 90, 220, 255))
    image.save(source)
    return sample_project(str(source))


class SpriteStudioTests(unittest.TestCase):
    def test_review_dashboard_prioritizes_flagged_low_confidence_sprites(self) -> None:
        dashboard = build_review_dashboard(sample_project(), confidence_threshold=0.85)

        self.assertEqual(dashboard["counts"]["approved"], 2)
        self.assertEqual(dashboard["counts"]["needs_review"], 1)
        self.assertEqual(dashboard["counts"]["rejected"], 1)
        self.assertEqual(dashboard["flag_counts"]["touches_edge"], 1)
        self.assertEqual(dashboard["queue"][0]["sprite_id"], "prop_001")
        self.assertIn("low_confidence", dashboard["queue"][0]["reasons"])
        self.assertIn("duplicate_display_name", dashboard["queue"][0]["reasons"])

    def test_apply_taxonomy_rules_writes_unique_display_names(self) -> None:
        project = sample_project()

        result = apply_taxonomy_rules(
            project,
            {"display_name_pattern": "{category}_{source_sheet}", "include_rejected": False},
        )

        active_names = [sprite["display_name"] for sprite in project["sprites"] if sprite["review_status"] != "rejected"]
        self.assertEqual(result["renamed"], 3)
        self.assertEqual(active_names, ["shelves_supermarket", "props_supermarket", "props_supermarket_02"])
        self.assertEqual(project["sprites"][3]["display_name"], "trash_rejected_001")
        self.assertIn("auto_named", project["sprites"][1]["review_flags"])

    def test_diff_projects_reports_added_removed_and_bbox_changes(self) -> None:
        old_project = sample_project()
        new_project = copy.deepcopy(old_project)
        new_project["sprites"][0]["bbox"]["width"] = 18
        new_project["sprites"] = new_project["sprites"][:-1]
        new_project["sprites"].append(
            {
                "id": "new_checkout_001",
                "display_name": "new_checkout_001",
                "category": "counters",
                "kind": "sprite",
                "source_file": "supermarket.png",
                "bbox": {"x": 50, "y": 10, "width": 12, "height": 16},
                "review_status": "approved",
                "review_flags": [],
                "confidence": 0.95,
            }
        )

        diff = diff_projects(old_project, new_project)

        self.assertEqual([item["sprite_id"] for item in diff["added"]], ["new_checkout_001"])
        self.assertEqual([item["sprite_id"] for item in diff["removed"]], ["trash_rejected_001"])
        self.assertEqual(diff["changed"][0]["sprite_id"], "shelf_001")
        self.assertIn("bbox", diff["changed"][0]["changed_fields"])

    def test_engine_import_plans_include_unity_godot_unreal_specific_assets(self) -> None:
        project = sample_project()
        generate_collision_profiles(project)

        plans = build_engine_import_plans(project, engines=["unity", "godot", "unreal"])

        self.assertIn("unity_importer_settings", plans["unity"])
        self.assertEqual(plans["unity"]["unity_importer_settings"]["filter_mode"], "Point")
        self.assertFalse(plans["godot"]["texture_import"]["filter"])
        self.assertIn("Paper2D", plans["unreal"]["import_pipeline"])
        self.assertEqual(len(plans["unity"]["sprites"]), 3)
        self.assertIn("collision", plans["unity"]["sprites"][0])

    def test_collision_profiles_add_category_based_shapes_and_anchor_profiles(self) -> None:
        project = sample_project()

        profiles = generate_collision_profiles(project)

        self.assertEqual(profiles["shelf_001"]["collision"]["shape"], "box")
        self.assertEqual(profiles["shelf_001"]["anchor"]["preset"], "bottom_center")
        self.assertEqual(profiles["prop_001"]["collision"]["shape"], "tight_rect")
        self.assertEqual(profiles["hero_idle_001"]["anchor"]["preset"], "bottom_center")
        self.assertEqual(project["sprites"][0]["collision"], profiles["shelf_001"]["collision"])

    def test_atlas_upgrade_plan_groups_animation_frames_and_tracks_policy(self) -> None:
        plan = build_atlas_upgrade_plan(sample_project(), max_size=1024, extrusion_pixels=2, power_of_two=True)

        self.assertEqual(plan["settings"]["max_size"], 1024)
        self.assertTrue(plan["settings"]["power_of_two"])
        self.assertEqual(plan["settings"]["extrusion_pixels"], 2)
        self.assertIn("category:props", plan["groups"])
        self.assertTrue(plan["groups"]["sequence:idle"]["keep_together"])
        self.assertIn("hero_idle_001", plan["groups"]["sequence:idle"]["sprites"])

    def test_batch_health_score_reports_grade_warnings_and_blockers(self) -> None:
        health = batch_health_score(sample_project())

        self.assertLess(health["score"], 100)
        self.assertEqual(health["counts"]["needs_review"], 1)
        self.assertIn("duplicate_display_names", health["warnings"])
        self.assertIn("needs_review_sprites", health["blockers"])
        self.assertEqual(health["flag_counts"]["touches_edge"], 1)

    def test_batch_health_score_blocks_handoff_until_active_sprites_have_vision_labels(self) -> None:
        project = sample_project()
        for sprite in project["sprites"]:
            if sprite["id"] == "trash_rejected_001":
                continue
            sprite["review_status"] = "approved"
            sprite["review_flags"] = []
            sprite["confidence"] = 1.0
            sprite["vision_label"] = {
                "display_name": sprite["display_name"],
                "category": sprite["category"],
                "confidence": 0.95,
                "provider": "fixture",
            }
        del project["sprites"][0]["vision_label"]

        health = batch_health_score(project)

        self.assertIn("missing_vision_labels", health["blockers"])
        self.assertEqual(health["vision"]["missing"], 1)
        self.assertEqual(health["vision"]["labeled"], 2)

    def test_review_dashboard_queues_sprites_missing_required_vision_labels(self) -> None:
        project = sample_project()
        for sprite in project["sprites"]:
            if sprite["id"] == "trash_rejected_001":
                continue
            sprite["review_status"] = "approved"
            sprite["review_flags"] = []
            sprite["confidence"] = 1.0

        dashboard = build_review_dashboard(project)

        self.assertIn("missing_vision_labels", dashboard["queue"][0]["reasons"])
        self.assertEqual(dashboard["vision"]["missing"], 3)

    def test_preset_trainer_uses_project_settings_and_review_corrections(self) -> None:
        preset = train_preset_from_project(sample_project())

        self.assertEqual(preset["mode"], "auto")
        self.assertEqual(preset["atlas"]["size"], 2048)
        self.assertIn("props", preset["taxonomy"]["category_counts"])
        self.assertIn("{category}", preset["taxonomy"]["display_name_pattern"])
        self.assertIn("manual_bbox", preset["review_learning"]["common_flags"])

    def test_asset_browser_index_searches_status_flags_and_category(self) -> None:
        index = asset_browser_index(sample_project())

        flagged = search_assets(index, "touches_edge", status="needs_review")
        props = search_assets(index, "supermarket", category="props")

        self.assertEqual([item["sprite_id"] for item in flagged], ["prop_001"])
        self.assertEqual([item["sprite_id"] for item in props], ["prop_001", "hero_idle_001"])
        self.assertIn("duplicate_name", index[0]["search_text"])

    def test_review_and_apply_project_runs_full_studio_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = renderable_project(root)
            project_path = root / "project.spritecut.json"
            save_project(project, project_path)
            output_dir = root / "studio_apply"

            result = review_and_apply_project(
                project,
                project_path,
                output_dir=output_dir,
                naming_rules={"display_name_pattern": "{category}_{index:02d}", "include_rejected": False},
            )

            self.assertEqual(result["apply"]["rendered"], 3)
            self.assertTrue((output_dir / "sprites" / "shelves" / "shelves_01.png").exists())
            self.assertTrue((output_dir / "studio" / "review_dashboard.json").exists())
            self.assertTrue((output_dir / "studio" / "batch_health.json").exists())
            self.assertTrue((output_dir / "import_plans" / "unity_importer_settings.json").exists())
            self.assertEqual(json.loads((output_dir / "studio" / "review_dashboard.json").read_text(encoding="utf-8"))["counts"]["needs_review"], 1)


if __name__ == "__main__":
    unittest.main()
