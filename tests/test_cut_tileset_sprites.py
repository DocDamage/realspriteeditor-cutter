from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from tools.cut_tileset_sprites import BUILT_IN_PRESETS, DetectedSprite, discover_sheet_files, infer_auto_defaults, load_config_defaults, load_existing_records, looks_like_animation_sheet


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "cut_tileset_sprites.py"


def run_cutter(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def make_animation_sheet(path: Path) -> None:
    image = Image.new("RGBA", (150, 96), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    idle_frames = [(6, 10, 17, 25), (48, 7, 19, 28), (96, 12, 18, 23)]
    run_frames = [(5, 58, 24, 18), (49, 55, 22, 23), (94, 60, 26, 17)]
    for index, (x, y, w, h) in enumerate(idle_frames):
        draw.rectangle((x, y, x + w, y + h), fill=(90 + index * 25, 120, 210, 255))
        draw.rectangle((x + 4, y - 3, x + 9, y + 2), fill=(60, 80, 180, 255))
    for index, (x, y, w, h) in enumerate(run_frames):
        draw.rectangle((x, y, x + w, y + h), fill=(210, 100 + index * 25, 80, 255))
        draw.rectangle((x + 2, y + h + 1, x + 7, y + h + 4), fill=(140, 70, 50, 255))

    image.save(path)


def make_varied_tileset_sheet(path: Path) -> None:
    image = Image.new("RGBA", (180, 130), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    boxes = [
        (5, 5, 42, 21),
        (74, 4, 18, 50),
        (120, 12, 58, 34),
        (9, 70, 25, 24),
        (53, 72, 70, 17),
        (142, 82, 24, 48),
    ]
    for index, (x, y, w, h) in enumerate(boxes):
        draw.rectangle((x, y, x + w, y + h), fill=(60 + index * 20, 90, 120, 255))
    image.save(path)


def make_mixed_prop_sheet_with_one_uniform_row(path: Path) -> None:
    image = Image.new("RGBA", (220, 180), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)

    uniform_row = [(12, 8, 18, 18), (45, 10, 17, 20), (82, 7, 19, 19), (119, 9, 18, 18)]
    varied_rows = [
        (5, 52, 70, 24),
        (95, 48, 25, 62),
        (146, 55, 58, 36),
        (12, 122, 31, 30),
        (61, 119, 90, 21),
        (172, 116, 24, 58),
    ]
    for index, (x, y, w, h) in enumerate(uniform_row + varied_rows):
        draw.rectangle((x, y, x + w, y + h), fill=(80 + index * 12, 90, 140, 255))

    image.save(path)


def make_border_and_color_sheet(path: Path) -> None:
    image = Image.new("RGBA", (120, 90), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 6, 23, 31), fill=(220, 40, 40, 255))
    draw.rectangle((52, 12, 85, 45), fill=(30, 180, 70, 255))
    draw.rectangle((62, 50, 99, 80), fill=(30, 180, 70, 130))
    image.save(path)


def make_dark_background_sheet(path: Path) -> None:
    image = Image.new("RGBA", (128, 96), (18, 18, 18, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 10, 40, 42), fill=(210, 60, 50, 255))
    draw.rectangle((62, 8, 104, 44), fill=(45, 170, 90, 255))
    draw.rectangle((28, 62, 82, 86), fill=(220, 180, 70, 255))
    image.save(path)


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def detection(label: int, x: int, y: int, width: int, height: int) -> DetectedSprite:
    return DetectedSprite(label=label, x=x, y=y, width=width, height=height, foreground_pixels=width * height)


class CutTilesetSpritesTests(unittest.TestCase):
    def test_infer_auto_defaults_detects_transparent_animation_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "hero.png"
            make_animation_sheet(sheet)

            defaults = infer_auto_defaults([sheet])

            self.assertTrue(defaults["auto_detect_all"])
            self.assertEqual(defaults["mode"], "auto")
            self.assertEqual(defaults["animation_fps"], 12)
            self.assertEqual(defaults["min_sprite_pixels"], 16)
            self.assertTrue(defaults["pack_atlases"])
            self.assertEqual(defaults["engine_exports"], "all")

    def test_infer_auto_defaults_detects_dark_background_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sheet = root / "props.png"
            make_dark_background_sheet(sheet)

            defaults = infer_auto_defaults([sheet])

            self.assertEqual(defaults["dark_artifact_threshold"], 60)
            self.assertEqual(defaults["crop_padding"], 2)
            self.assertEqual(defaults["atlas_padding"], 3)
            self.assertTrue(defaults["pack_atlases"])

    def test_animation_detector_rejects_busy_sheet_with_only_one_frame_like_row(self) -> None:
        detections = [
            detection(1, 5, 5, 20, 20),
            detection(2, 40, 7, 19, 19),
            detection(3, 76, 6, 21, 20),
            detection(4, 112, 8, 20, 21),
            detection(5, 6, 45, 80, 24),
            detection(6, 105, 42, 22, 66),
            detection(7, 150, 46, 56, 38),
            detection(8, 5, 112, 32, 29),
            detection(9, 58, 115, 92, 18),
            detection(10, 170, 108, 25, 59),
        ]

        self.assertFalse(looks_like_animation_sheet(detections, min_frames=3))

    def test_forced_animation_mode_names_rows_and_preserves_fixed_frame_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_animation_sheet(root / "1.png")

            result = run_cutter(root, "--mode", "animation", "--animation-names", "idle,run", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            idle_dir = root / "out" / "animations" / "sheet_01" / "idle"
            run_dir = root / "out" / "animations" / "sheet_01" / "run"
            self.assertEqual([path.name for path in sorted(idle_dir.glob("*.png"))], ["idle_001.png", "idle_002.png", "idle_003.png"])
            self.assertEqual([path.name for path in sorted(run_dir.glob("*.png"))], ["run_001.png", "run_002.png", "run_003.png"])

            idle_sizes = {image_size(path) for path in idle_dir.glob("*.png")}
            run_sizes = {image_size(path) for path in run_dir.glob("*.png")}
            self.assertEqual(len(idle_sizes), 1)
            self.assertEqual(len(run_sizes), 1)

            with (root / "out" / "manifest" / "sprites.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 6)
            self.assertEqual([row["sequence"] for row in rows[:3]], ["idle", "idle", "idle"])
            self.assertEqual([row["frame"] for row in rows[:3]], ["1", "2", "3"])

    def test_auto_mode_detects_irregular_animation_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_animation_sheet(root / "hero.png")

            result = run_cutter(root, "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "out" / "animations" / "sheet_hero").exists())
            self.assertFalse((root / "out" / "sprites").exists())

    def test_default_cli_run_uses_auto_detect_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_animation_sheet(root / "hero.png")

            result = run_cutter(root, "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "settings.json").open(encoding="utf-8") as handle:
                settings = json.load(handle)
            self.assertTrue(settings["auto_detect_all"])
            self.assertTrue(settings["pack_atlases"])
            self.assertEqual(settings["engine_exports"], ["unity", "godot", "unreal"])
            self.assertEqual(settings["animation_fps"], 12)
            self.assertTrue((root / "out" / "atlases").exists())
            self.assertTrue((root / "out" / "exports" / "unity_sprites.json").exists())
            self.assertTrue((root / "out" / "exports" / "godot_sprites.json").exists())
            self.assertTrue((root / "out" / "exports" / "unreal_sprites.json").exists())

    def test_auto_mode_keeps_varied_prop_sheets_in_tileset_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_varied_tileset_sheet(root / "props.png")

            result = run_cutter(root, "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "out" / "sprites").exists())
            self.assertFalse((root / "out" / "animations").exists())

    def test_discovery_skips_existing_spritecut_output_folders_with_custom_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_varied_tileset_sheet(root / "props.png")
            generated = root / "artist_named_output"
            (generated / "sprites" / "props").mkdir(parents=True)
            (generated / "project.spritecut.json").write_text('{"schema_version": 1, "sprites": []}', encoding="utf-8")
            Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(generated / "sprites" / "props" / "generated.png")

            sheets = discover_sheet_files(root)

            self.assertEqual([path.name for path in sheets], ["props.png"])

    def test_auto_mode_does_not_treat_one_uniform_prop_row_as_animation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_mixed_prop_sheet_with_one_uniform_row(root / "mixed_props.png")

            result = run_cutter(root, "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "out" / "sprites").exists())
            self.assertFalse((root / "out" / "animations").exists())

    def test_manifest_includes_metadata_partial_flags_and_pivots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--pivot-debug", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "sprites.json").open(encoding="utf-8") as handle:
                records = json.load(handle)

            self.assertGreaterEqual(len(records), 3)
            for record in records:
                self.assertIn("transparency_ratio", record)
                self.assertIn("aspect_ratio", record)
                self.assertIn("dominant_colors", record)
                self.assertIn("is_partial", record)
                self.assertIn("confidence", record)
                self.assertIn("review_flags", record)
                self.assertIn("review_status", record)
                self.assertIn("pivot", record)
                self.assertIn(record["pivot"]["method"], {"centroid", "contour", "hybrid"})
                self.assertIsInstance(record["review_flags"], list)
                self.assertGreaterEqual(record["confidence"], 0.0)
                self.assertLessEqual(record["confidence"], 1.0)

            self.assertTrue(any(record["is_partial"] for record in records))
            self.assertTrue(any("touches_edge" in record["review_flags"] for record in records))
            self.assertTrue((root / "out" / "previews" / "pivots").exists())
            self.assertGreater(len(list((root / "out" / "previews" / "pivots").glob("*.png"))), 0)

    def test_can_pack_extracted_sprites_into_atlases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--pack-atlases", "--atlas-size", "96", "--atlas-padding", "2", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            atlas_dir = root / "out" / "atlases"
            atlas_pngs = sorted(atlas_dir.glob("*.png"))
            atlas_jsons = sorted(atlas_dir.glob("*.json"))
            self.assertGreater(len(atlas_pngs), 0)
            self.assertGreater(len(atlas_jsons), 0)

            with atlas_jsons[0].open(encoding="utf-8") as handle:
                atlas = json.load(handle)
            self.assertIn("frames", atlas)
            self.assertGreater(len(atlas["frames"]), 0)
            first_frame = atlas["frames"][0]
            self.assertIn("atlas", first_frame)
            self.assertIn("rect", first_frame)
            self.assertIn("source_id", first_frame)

    def test_engine_exports_include_sprite_pivots_and_atlas_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(
                root,
                "--mode",
                "tileset",
                "--pack-atlases",
                "--atlas-size",
                "96",
                "--engine-exports",
                "unity,godot,unreal",
                "--out-name",
                "out",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            exports_dir = root / "out" / "exports"
            expected = ["unity_sprites.json", "godot_sprites.json", "unreal_sprites.json"]
            for name in expected:
                self.assertTrue((exports_dir / name).exists(), name)

            with (exports_dir / "unity_sprites.json").open(encoding="utf-8") as handle:
                unity = json.load(handle)
            self.assertIn("sprites", unity)
            self.assertGreater(len(unity["sprites"]), 0)
            self.assertIn("pivot", unity["sprites"][0])
            self.assertIn("atlas", unity["sprites"][0])

    def test_animation_mode_writes_clip_metadata_and_engine_animation_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_animation_sheet(root / "hero.png")

            result = run_cutter(
                root,
                "--mode",
                "animation",
                "--animation-names",
                "idle,run",
                "--animation-fps",
                "12",
                "--engine-exports",
                "unity,godot,unreal",
                "--out-name",
                "out",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            clips_path = root / "out" / "manifest" / "animation_clips.json"
            self.assertTrue(clips_path.exists())
            with clips_path.open(encoding="utf-8") as handle:
                clips = json.load(handle)["animation_clips"]
            self.assertEqual([clip["sequence"] for clip in clips], ["idle", "run"])
            self.assertEqual(clips[0]["frame_rate"], 12)
            self.assertTrue(clips[0]["loop"])
            self.assertEqual([frame["frame"] for frame in clips[0]["frames"]], [1, 2, 3])
            self.assertIn("duration", clips[0]["frames"][0])

            with (root / "out" / "project.spritecut.json").open(encoding="utf-8") as handle:
                project = json.load(handle)
            self.assertEqual(len(project["animation_clips"]), 2)
            self.assertEqual(project["settings"]["animation_fps"], 12)

            with (root / "out" / "exports" / "unity_sprites.json").open(encoding="utf-8") as handle:
                unity = json.load(handle)
            self.assertIn("import_settings", unity)
            self.assertEqual(unity["animation_clips"][0]["frame_rate"], 12)

            with (root / "out" / "exports" / "godot_sprites.json").open(encoding="utf-8") as handle:
                godot = json.load(handle)
            self.assertIn("animations", godot)
            self.assertEqual(godot["animations"][0]["speed_fps"], 12)

            with (root / "out" / "exports" / "unreal_sprites.json").open(encoding="utf-8") as handle:
                unreal = json.load(handle)
            self.assertIn("flipbooks", unreal)
            self.assertEqual(unreal["flipbooks"][0]["frames"][0]["key_frame"], 0)

            report = (root / "out" / "manifest" / "report.html").read_text(encoding="utf-8")
            self.assertIn("Animation Clips", report)
            self.assertIn("data-clip=", report)
            self.assertIn("sheet_hero_idle", report)

    def test_batch_discovery_processes_nested_common_image_formats_and_skips_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            make_border_and_color_sheet(root / "top.png")
            make_border_and_color_sheet(nested / "nested.png")
            skip_dir = root / "_organized_sprites_old"
            skip_dir.mkdir()
            make_border_and_color_sheet(skip_dir / "skip.png")

            result = run_cutter(root, "--mode", "tileset", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "summary.txt").open(encoding="utf-8") as handle:
                summary = handle.read()
            self.assertIn("sheets_processed=2", summary)
            self.assertNotIn("sheet_skip", summary)

    def test_config_file_can_supply_repeatable_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")
            config_path = root / "preset.json"
            config_path.write_text(
                json.dumps(
                    {
                        "out_name": "from_config",
                        "mode": "tileset",
                        "pack_atlases": True,
                        "atlas_size": 96,
                        "engine_exports": ["unity"],
                    }
                ),
                encoding="utf-8",
            )

            result = run_cutter(root, "--config", str(config_path))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "from_config" / "atlases").exists())
            self.assertTrue((root / "from_config" / "exports" / "unity_sprites.json").exists())

    def test_builtin_preset_can_supply_repeatable_options(self) -> None:
        self.assertIn("packed_props_dark_bg", BUILT_IN_PRESETS)
        defaults = load_config_defaults(None, "transparent_animation_rows")

        self.assertEqual(defaults["mode"], "animation")
        self.assertEqual(defaults["animation_frame_mode"], "fixed")
        self.assertIn("animation_fps", defaults)

    def test_config_overrides_builtin_preset_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "preset.json"
            config_path.write_text(json.dumps({"mode": "tileset", "animation_fps": 20}), encoding="utf-8")

            defaults = load_config_defaults(config_path, "transparent_animation_rows")

            self.assertEqual(defaults["mode"], "tileset")
            self.assertEqual(defaults["animation_fps"], 20)

    def test_workers_and_max_megapixels_are_written_to_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--workers", "2", "--max-image-megapixels", "1", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "settings.json").open(encoding="utf-8") as handle:
                settings = json.load(handle)
            self.assertEqual(settings["workers"], 2)
            self.assertEqual(settings["max_image_megapixels"], 1.0)

    def test_cli_prints_per_sheet_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PROCESSING", result.stdout)
            self.assertIn("DONE", result.stdout)

    def test_max_megapixels_skips_oversized_sheet_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--max-image-megapixels", "0.001", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "errors.json").open(encoding="utf-8") as handle:
                errors = json.load(handle)
            self.assertEqual(len(errors), 1)
            self.assertIn("exceeds max_image_megapixels", errors[0]["error"])

    def test_html_report_is_written_with_summary_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--pack-atlases", "--atlas-size", "96", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            report_path = root / "out" / "manifest" / "report.html"
            self.assertTrue(report_path.exists())
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Sprite Sheet Processing Report", report)
            self.assertIn("total_sprites", report)
            self.assertIn("atlases", report)
            self.assertIn("<img", report)
            self.assertIn('loading="lazy"', report)
            self.assertIn("Review Filters", report)
            self.assertIn("filterSprites", report)
            self.assertIn("data-status=", report)
            self.assertIn("data-flags=", report)
            self.assertIn("visual_qa.html", report)
            visual_qa_report = root / "out" / "manifest" / "visual_qa.html"
            visual_qa_manifest = root / "out" / "manifest" / "visual_qa.json"
            self.assertTrue(visual_qa_report.exists())
            self.assertTrue(visual_qa_manifest.exists())
            qa_html = visual_qa_report.read_text(encoding="utf-8")
            self.assertIn("Visual QA Review", qa_html)
            self.assertIn("Before / After Crop Sheets", qa_html)
            self.assertIn("Flagged Crop Issues", qa_html)
            self.assertIn("Palette Change Samples", qa_html)
            self.assertIn("Autotile Variant Samples", qa_html)
            qa_manifest = json.loads(visual_qa_manifest.read_text(encoding="utf-8"))
            self.assertIn("before_after_sheets", qa_manifest)
            self.assertIn("flagged_crop_issues", qa_manifest)
            self.assertIn("palette_change_samples", qa_manifest)
            self.assertIn("autotile_variant_samples", qa_manifest)
            self.assertGreater(len(qa_manifest["before_after_sheets"]), 0)
            self.assertGreater(len(qa_manifest["palette_change_samples"]), 0)
            self.assertGreater(len(qa_manifest["autotile_variant_samples"]), 0)
            visual_regression = root / "out" / "manifest" / "visual_regression.json"
            self.assertTrue(visual_regression.exists())
            visual = json.loads(visual_regression.read_text(encoding="utf-8"))
            self.assertIn("preview_artifacts", visual)
            self.assertGreater(len(visual["preview_artifacts"]), 0)
            self.assertIn("sha256", visual["preview_artifacts"][0])

    def test_detection_settings_can_filter_small_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = Image.new("RGBA", (80, 50), (255, 255, 255, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((4, 4, 8, 8), fill=(240, 40, 40, 255))
            draw.rectangle((30, 10, 58, 38), fill=(40, 180, 80, 255))
            image.save(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--min-sprite-pixels", "200", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "sprites.json").open(encoding="utf-8") as handle:
                records = json.load(handle)
            self.assertEqual(len(records), 1)

    def test_resume_reuses_existing_output_and_skips_processed_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            first = run_cutter(root, "--mode", "tileset", "--out-name", "out")
            second = run_cutter(root, "--mode", "tileset", "--resume", "--out-name", "out")

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn(f"OUTPUT={root / 'out'}", second.stdout)
            self.assertFalse((root / "out_2").exists())
            with (root / "out" / "manifest" / "settings.json").open(encoding="utf-8") as handle:
                settings = json.load(handle)
            self.assertTrue(settings["resume"])

    def test_load_existing_records_ignores_unknown_manifest_fields_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest"
            manifest.mkdir()
            record = {
                "id": "sprite_001",
                "display_name": "sprite_001",
                "source_sheet": "sheet",
                "source_file": "G:/source.png",
                "kind": "sprite",
                "sheet_mode": "tileset",
                "category": "props",
                "sequence": None,
                "frame": None,
                "output_file": "G:/out/sprite.png",
                "bbox": {"x": 1, "y": 2, "width": 3, "height": 4},
                "width": 3,
                "height": 4,
                "slot_width": None,
                "slot_height": None,
                "foreground_pixels": 12,
                "alpha_mode": "component",
                "is_partial": False,
                "transparency_ratio": 0.0,
                "aspect_ratio": 0.75,
                "dominant_colors": ["#ff0000"],
                "pivot": {"x": 0.5, "y": 0.5, "method": "manual"},
                "confidence": 1.0,
                "review_flags": [],
                "review_status": "approved",
                "atlas": None,
                "future_field": "newer tool metadata",
            }
            (manifest / "sprites.json").write_text(json.dumps([record]), encoding="utf-8")

            records = load_existing_records(manifest)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].id, "sprite_001")

    def test_manifest_writes_normalized_run_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(
                root,
                "--mode",
                "tileset",
                "--min-sprite-pixels",
                "200",
                "--crop-padding",
                "4",
                "--pack-atlases",
                "--atlas-size",
                "96",
                "--engine-exports",
                "unity,godot",
                "--out-name",
                "out",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            settings_path = root / "out" / "manifest" / "settings.json"
            self.assertTrue(settings_path.exists())
            with settings_path.open(encoding="utf-8") as handle:
                settings = json.load(handle)
            self.assertEqual(settings["mode"], "tileset")
            self.assertEqual(settings["detection_settings"]["min_sprite_pixels"], 200)
            self.assertEqual(settings["detection_settings"]["crop_padding"], 4)
            self.assertTrue(settings["pack_atlases"])
            self.assertEqual(settings["atlas_size"], 96)
            self.assertEqual(settings["engine_exports"], ["unity", "godot"])

    def test_project_file_captures_reviewable_sprite_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "props.png")

            result = run_cutter(root, "--mode", "tileset", "--pack-atlases", "--atlas-size", "96", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            project_path = root / "out" / "project.spritecut.json"
            self.assertTrue(project_path.exists())
            with project_path.open(encoding="utf-8") as handle:
                project = json.load(handle)

            self.assertEqual(project["schema_version"], 1)
            self.assertIn("settings", project)
            self.assertIn("sprites", project)
            self.assertEqual(project["history"], [])
            self.assertEqual(project["redo_stack"], [])
            self.assertGreater(len(project["sprites"]), 0)
            first = project["sprites"][0]
            for key in ["id", "display_name", "source_file", "output_file", "bbox", "pivot", "confidence", "review_flags", "review_status"]:
                self.assertIn(key, first)
            self.assertIn(first["review_status"], {"needs_review", "approved"})
            self.assertIsInstance(first["review_flags"], list)
            self.assertIn("atlas", first)

    def test_bad_sheet_is_skipped_and_reported_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "valid.png")
            (root / "bad.png").write_bytes(b"not a real png")

            result = run_cutter(root, "--mode", "tileset", "--out-name", "out")

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "out" / "manifest" / "summary.txt").open(encoding="utf-8") as handle:
                summary = handle.read()
            self.assertIn("sheets_processed=1", summary)
            self.assertIn("sheets_failed=1", summary)
            with (root / "out" / "manifest" / "errors.json").open(encoding="utf-8") as handle:
                errors = json.load(handle)
            self.assertEqual(len(errors), 1)
            self.assertIn("bad.png", errors[0]["source_file"])

    def test_fail_fast_mode_returns_error_for_bad_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_border_and_color_sheet(root / "valid.png")
            (root / "bad.png").write_bytes(b"not a real png")

            result = run_cutter(root, "--mode", "tileset", "--on-error", "fail", "--out-name", "out")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bad.png", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
