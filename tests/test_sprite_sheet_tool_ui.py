from __future__ import annotations

import json
import copy
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from PIL import Image

import tools.sprite_sheet_tool_ui as ui_module
from tools.sprite_sheet_tool_ui import (
    CenterPreviewPanel,
    CutterUiSettings,
    DetectionSettingsPanel,
    EditorSettingsPanel,
    LeftInputPanel,
    OutputSettingsPanel,
    ProcessingController,
    ReviewSettingsPanel,
    ReviewProjectController,
    RunSettingsPanel,
    SpriteSheetToolUi,
    SettingsTabsPanel,
    StudioSettingsPanel,
    StudioController,
    SpriteEditorController,
    TOOLTIP_TEXT,
    builtin_preset_names,
    build_cutter_command,
    cancel_button_state,
    detect_preview_boxes,
    discover_sheet_files,
    editor_callable_actions,
    editor_color_wheel_preview,
    editor_palette_summary,
    editor_parse_rect_text,
    editor_parse_size_text,
    editor_variant_package,
    format_project_sprite_label,
    load_preset_file,
    output_targets_from_cli_line,
    apply_preview_accessibility_mode,
    create_ui_sample_pack,
    load_recent_projects,
    parse_bbox_fields,
    parse_flags_text,
    parse_pivot_fields,
    project_animation_clip_frames,
    project_animation_clip_names,
    project_sprite_preview_path_text,
    project_sprite_rows,
    scale_bbox_for_canvas,
    translate_bbox_by_canvas_delta,
    render_detection_preview,
    remember_recent_project,
    save_preset_file,
    settings_from_preset_dict,
    settings_from_builtin_preset,
    settings_to_preset_dict,
    studio_asset_label,
    studio_asset_rows,
    studio_dashboard_text,
    studio_default_taxonomy_rules,
    studio_project_diff_text,
    studio_queue_labels,
    summarize_cli_output_line,
    tooltip_text,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_SCRIPT = REPO_ROOT / "tools" / "sprite_sheet_tool_ui.py"


def sample_project() -> dict[str, object]:
    return {
        "schema_version": 1,
        "animation_clips": [
            {
                "name": "sheet_hero_idle",
                "sequence": "idle",
                "frame_rate": 12,
                "loop": True,
                "frames": [
                    {"sprite": "sprite_001", "duration": 0.0833, "source_file": "idle_001.png"},
                    {"sprite": "sprite_002", "duration": 0.0833, "source_file": "idle_002.png"},
                ],
            }
        ],
        "sprites": [
            {
                "id": "sprite_001",
                "display_name": "broken_shelf_01",
                "category": "shelves",
                "review_status": "needs_review",
                "review_flags": ["touches_edge"],
                "confidence": 0.75,
                "bbox": {"x": 1, "y": 2, "width": 30, "height": 40},
                "pivot": {"x": 0.5, "y": 0.9, "method": "hybrid"},
            },
            {
                "id": "sprite_002",
                "display_name": "floor_tile_01",
                "category": "floors",
                "review_status": "approved",
                "review_flags": [],
                "confidence": 1.0,
                "bbox": {"x": 50, "y": 2, "width": 16, "height": 16},
                "pivot": {"x": 0.5, "y": 0.5, "method": "hybrid"},
            },
        ],
    }


class SpriteSheetToolUiTests(unittest.TestCase):
    def test_ui_construction_is_split_into_panel_builders(self) -> None:
        app = SpriteSheetToolUi(build=False)

        panel_names = [type(panel).__name__ for panel in app._panel_builders()]

        self.assertEqual(panel_names, ["LeftInputPanel", "CenterPreviewPanel", "SettingsTabsPanel"])
        for panel_type in [
            LeftInputPanel,
            CenterPreviewPanel,
            SettingsTabsPanel,
            RunSettingsPanel,
            DetectionSettingsPanel,
            OutputSettingsPanel,
            ReviewSettingsPanel,
            StudioSettingsPanel,
            EditorSettingsPanel,
        ]:
            self.assertTrue(callable(getattr(panel_type(app), "build")))

    def test_ui_behavior_is_split_into_controller_helpers(self) -> None:
        app = SpriteSheetToolUi(build=False)

        controller_names = [type(controller).__name__ for controller in app._controllers()]

        self.assertEqual(controller_names, ["ProcessingController", "ReviewProjectController", "StudioController", "SpriteEditorController"])
        self.assertIsInstance(app.processing_controller, ProcessingController)
        self.assertIsInstance(app.review_controller, ReviewProjectController)
        self.assertIsInstance(app.studio_controller, StudioController)
        self.assertIsInstance(app.editor_controller, SpriteEditorController)

    @unittest.skipUnless(
        ui_module.dpg is not None and sys.platform.startswith("win"),
        "Dear PyGUI construction smoke test requires the optional Windows UI dependency",
    )
    def test_dearpygui_ui_constructs_without_container_errors(self) -> None:
        try:
            app = SpriteSheetToolUi()
            self.assertIsInstance(app, SpriteSheetToolUi)
        finally:
            ui_module.dpg.destroy_context()

    @unittest.skipUnless(
        ui_module.dpg is not None and sys.platform.startswith("win"),
        "Dear PyGUI state smoke test requires the optional Windows UI dependency",
    )
    def test_processing_state_disables_process_and_enables_cancel(self) -> None:
        try:
            app = SpriteSheetToolUi()

            app._set_processing(True)

            self.assertFalse(ui_module.dpg.get_item_configuration("process_button")["enabled"])
            self.assertTrue(ui_module.dpg.get_item_configuration("cancel_button")["enabled"])
            self.assertEqual(ui_module.dpg.get_value("progress_text"), "Processing...")

            app._set_processing(False)

            self.assertTrue(ui_module.dpg.get_item_configuration("process_button")["enabled"])
            self.assertFalse(ui_module.dpg.get_item_configuration("cancel_button")["enabled"])
            self.assertEqual(ui_module.dpg.get_value("progress_text"), "Idle")
        finally:
            ui_module.dpg.destroy_context()

    @unittest.skipUnless(
        ui_module.dpg is not None and sys.platform.startswith("win"),
        "Dear PyGUI review smoke test requires the optional Windows UI dependency",
    )
    def test_empty_review_filter_clears_stale_review_fields(self) -> None:
        try:
            app = SpriteSheetToolUi()
            app.current_project = sample_project()
            app.refresh_project_rows()
            self.assertEqual(str(app.review_name.get()), "broken_shelf_01")

            app.review_query.set("not-present")
            app.refresh_project_rows()

            self.assertEqual(str(app.review_name.get()), "")
            self.assertEqual(str(app.review_category.get()), "")
            self.assertEqual(str(app.review_bbox_x.get()), "")
            self.assertEqual(str(app.review_flags.get()), "")
        finally:
            ui_module.dpg.destroy_context()

    @unittest.skipUnless(
        ui_module.dpg is not None and sys.platform.startswith("win"),
        "Dear PyGUI message smoke test requires the optional Windows UI dependency",
    )
    def test_messages_are_recorded_and_logged_for_feedback(self) -> None:
        try:
            app = SpriteSheetToolUi()

            app._show_error("Missing Output", "No output has been generated.")

            self.assertEqual(app.last_message, ("Missing Output", "No output has been generated.", "error"))
            self.assertIn("Error - Missing Output: No output has been generated.", app.log_lines[-1])
        finally:
            ui_module.dpg.destroy_context()

    def test_discover_sheet_files_finds_supported_images_and_skips_output_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(root / "b.png")
            Image.new("RGB", (8, 8), (0, 255, 0)).save(root / "a.jpg")
            (root / "notes.txt").write_text("ignore", encoding="utf-8")
            output_dir = root / "_organized_sprites"
            output_dir.mkdir()
            Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(output_dir / "skip.png")

            files = discover_sheet_files(root)

            self.assertEqual([path.name for path in files], ["a.jpg", "b.png"])

    def test_discover_sheet_files_skips_custom_named_spritecut_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(root / "source.png")
            generated = root / "batch_review_output"
            (generated / "sprites" / "props").mkdir(parents=True)
            (generated / "project.spritecut.json").write_text('{"schema_version": 1, "sprites": []}', encoding="utf-8")
            Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(generated / "sprites" / "props" / "generated.png")

            files = discover_sheet_files(root)

            self.assertEqual([path.name for path in files], ["source.png"])

    def test_build_cutter_command_reflects_ui_settings(self) -> None:
        settings = CutterUiSettings(
            input_path=Path("G:/assets/sheets"),
            auto_detect_all=False,
            out_name="_ui_output",
            mode="animation",
            animation_names="idle,run",
            animation_frame_mode="trimmed",
            animation_anchor="center",
            animation_min_frames=4,
            animation_fps=12,
            pivot_debug=True,
            pack_atlases=True,
            atlas_size=1024,
            atlas_padding=3,
            atlas_allow_rotation=True,
            engine_exports=["unity", "godot"],
            alpha_threshold=22,
            white_threshold=245,
            white_tolerance=12,
            dark_artifact_threshold=55,
            min_sprite_pixels=100,
            min_sprite_width=6,
            min_sprite_height=7,
            crop_padding=3,
            on_error="fail",
        )

        command = build_cutter_command(settings, python_executable="python")

        self.assertEqual(command[0], "python")
        self.assertIn("--mode", command)
        self.assertIn("animation", command)
        self.assertIn("--animation-fps", command)
        self.assertIn("12", command)
        self.assertIn("--pivot-debug", command)
        self.assertIn("--pack-atlases", command)
        self.assertIn("--atlas-allow-rotation", command)
        self.assertIn("--engine-exports", command)
        self.assertIn("unity,godot", command)
        self.assertIn("--alpha-threshold", command)
        self.assertIn("22", command)
        self.assertIn("--min-sprite-pixels", command)
        self.assertIn("100", command)
        self.assertIn("--on-error", command)
        self.assertIn("fail", command)
        self.assertEqual(command[-1].replace("/", "\\"), "G:\\assets\\sheets")

    def test_build_cutter_command_uses_minimal_auto_detect_all_command_by_default(self) -> None:
        settings = CutterUiSettings(input_path=Path("G:/assets/sheets"))

        command = build_cutter_command(settings, python_executable="python")

        self.assertIn("--auto-detect-all", command)
        self.assertNotIn("--alpha-threshold", command)
        self.assertNotIn("--engine-exports", command)
        self.assertNotIn("--pack-atlases", command)
        self.assertEqual(command[-1].replace("/", "\\"), "G:\\assets\\sheets")

    def test_tooltip_copy_covers_primary_workflow_controls(self) -> None:
        required = [
            "input_path",
            "add_folder",
            "add_file",
            "refresh_files",
            "file_list",
            "preview_accessibility",
            "process",
            "cancel",
            "open_output",
            "open_report",
            "open_project",
            "auto_detect_all",
            "mode",
            "animation_names",
            "alpha_threshold",
            "dark_artifact_threshold",
            "pack_atlases",
            "engine_exports",
            "load_project",
            "apply_outputs",
            "review_source_canvas",
            "split_selected",
            "merge_selected",
            "studio_refresh",
            "studio_review_apply",
            "studio_auto_name",
            "studio_train_preset",
            "studio_diff_project",
            "studio_generate_profiles",
            "studio_dashboard",
            "studio_queue",
            "studio_asset_query",
            "studio_asset_list",
            "studio_taxonomy_pattern",
            "editor_load_sprite",
            "editor_save_package",
            "editor_palette_summary",
            "editor_source_color",
            "editor_target_color",
            "editor_swap_colors",
            "editor_hue_degrees",
            "editor_hue_shift",
            "editor_color_wheel",
            "editor_autotile_name",
            "editor_generate_autotile",
            "editor_ide_api",
        ]

        missing = [key for key in required if key not in TOOLTIP_TEXT]

        self.assertEqual(missing, [])
        for key in required:
            self.assertGreaterEqual(len(tooltip_text(key)), 32, key)

    def test_studio_helpers_summarize_dashboard_queue_and_asset_search(self) -> None:
        project = sample_project()

        dashboard = studio_dashboard_text(project)
        queue = studio_queue_labels(project)
        rows = studio_asset_rows(project, query="shelf", status_filter="needs_review")
        label = studio_asset_label(rows[0])

        self.assertIn("Health", dashboard)
        self.assertIn("needs_review=1", dashboard)
        self.assertIn("queue=1", dashboard)
        self.assertTrue(queue[0].startswith("sprite_001"))
        self.assertEqual(rows[0]["sprite_id"], "sprite_001")
        self.assertIn("broken_shelf_01", label)

    def test_studio_default_taxonomy_rules_normalize_blank_patterns(self) -> None:
        default_rules = studio_default_taxonomy_rules("")
        custom_rules = studio_default_taxonomy_rules("{category}_{index:02d}")

        self.assertEqual(default_rules["display_name_pattern"], "{category}_{source_sheet}_{index:03d}")
        self.assertFalse(default_rules["include_rejected"])
        self.assertEqual(custom_rules["display_name_pattern"], "{category}_{index:02d}")

    def test_studio_project_diff_text_summarizes_rerun_changes(self) -> None:
        old_project = sample_project()
        new_project = copy.deepcopy(old_project)
        new_project["sprites"][0]["bbox"]["width"] = 34
        new_project["sprites"] = new_project["sprites"][0:1]
        new_project["sprites"].append(
            {
                "id": "sprite_003",
                "display_name": "new_counter_01",
                "category": "counters",
                "review_status": "approved",
                "review_flags": [],
                "confidence": 1.0,
                "bbox": {"x": 1, "y": 1, "width": 8, "height": 8},
            }
        )

        text = studio_project_diff_text(old_project, new_project)

        self.assertIn("added=1", text)
        self.assertIn("removed=1", text)
        self.assertIn("changed=1", text)

    def test_editor_helpers_summarize_palette_color_wheel_and_ide_actions(self) -> None:
        image = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        for x in range(2):
            for y in range(2):
                image.putpixel((x, y), (0, 255, 0, 255))

        palette = editor_palette_summary(image, max_colors=4)
        wheel = editor_color_wheel_preview("#ff0000", "complementary")
        actions = editor_callable_actions()

        self.assertIn("colors=2", palette)
        self.assertIn("#ff0000", palette)
        self.assertIn("#00ffff", wheel)
        self.assertIn("sprite.edit", actions)
        self.assertIn("sprite.batch_edit", actions)
        self.assertIn("palette.variants", actions)
        self.assertIn("palette.swap", actions)
        self.assertIn("autotile.generate", actions)

    def test_editor_transform_text_parsers_accept_common_formats(self) -> None:
        self.assertEqual(editor_parse_rect_text("1, 2, 30, 40"), (1, 2, 30, 40))
        self.assertEqual(editor_parse_rect_text("1 2 30 40"), (1, 2, 30, 40))
        self.assertEqual(editor_parse_size_text("16x24"), (16, 24))
        self.assertEqual(editor_parse_size_text("16, 24"), (16, 24))

        with self.assertRaises(ValueError):
            editor_parse_rect_text("1, 2, 3")
        with self.assertRaises(ValueError):
            editor_parse_size_text("0x24")

    def test_editor_transform_methods_apply_existing_backend_operations(self) -> None:
        image = Image.new("RGBA", (4, 3), (0, 0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0, 255))
        app = SpriteSheetToolUi(build=False)
        app.editor_session = ui_module.SpriteEditSession.from_image(image, name="sample")

        app.editor_crop_rect.set("0,0,2,2")
        app.apply_editor_crop()
        self.assertEqual(app.editor_session.size, (2, 2))

        app.undo_editor_edit()
        self.assertEqual(app.editor_session.size, (4, 3))
        app.redo_editor_edit()
        self.assertEqual(app.editor_session.size, (2, 2))

        app.editor_resize_size.set("4x4")
        app.apply_editor_resize()
        self.assertEqual(app.editor_session.size, (4, 4))

        app.editor_flip_axis.set("horizontal")
        app.apply_editor_flip()
        app.apply_editor_rotate(clockwise=False)
        self.assertIn("Rotate", app.log_lines[-1])

    def test_editor_variant_package_writes_colorway_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
            session = ui_module.SpriteEditSession.from_image(image, name="crate")

            package = editor_variant_package(
                session,
                Path(tmp),
                name="crate",
                base_color="#ff0000",
                harmony="complementary",
            )

            self.assertEqual(len(package["variants"]), 2)
            self.assertTrue(Path(package["manifest"]).exists())
            self.assertTrue(Path(package["contact_sheet"]).exists())

    def test_settings_presets_round_trip_without_input_path(self) -> None:
        settings = CutterUiSettings(
            input_path=Path("G:/assets/sheets"),
            auto_detect_all=False,
            out_name="custom_out",
            mode="tileset",
            pack_atlases=True,
            engine_exports=["unity", "unreal"],
            min_sprite_pixels=88,
            crop_padding=4,
            on_error="fail",
        )

        preset = settings_to_preset_dict(settings)
        restored = settings_from_preset_dict(preset, input_path=Path("D:/other"))

        self.assertNotIn("input_path", preset)
        self.assertEqual(restored.input_path, Path("D:/other"))
        self.assertEqual(restored.out_name, "custom_out")
        self.assertTrue(restored.pack_atlases)
        self.assertEqual(restored.engine_exports, ["unity", "unreal"])
        self.assertEqual(restored.min_sprite_pixels, 88)
        self.assertEqual(restored.crop_padding, 4)
        self.assertEqual(restored.on_error, "fail")

    def test_builtin_presets_can_be_loaded_into_ui_settings(self) -> None:
        names = builtin_preset_names()
        settings = settings_from_builtin_preset("transparent_animation_rows", input_path=Path("G:/sprites"))

        self.assertIn("transparent_animation_rows", names)
        self.assertEqual(settings.input_path, Path("G:/sprites"))
        self.assertEqual(settings.mode, "animation")
        self.assertEqual(settings.animation_fps, 12)
        self.assertIn("unity", settings.engine_exports)

    def test_preset_file_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preset_path = Path(tmp) / "preset.json"
            settings = CutterUiSettings(
                input_path=Path("G:/assets/sheets"),
                out_name="preset_out",
                mode="animation",
                animation_names="idle,run",
                animation_fps=14,
                engine_exports=["godot"],
                alpha_threshold=18,
            )

            save_preset_file(settings, preset_path)
            loaded = load_preset_file(preset_path, input_path=Path("X:/sprites"))

            self.assertEqual(json.loads(preset_path.read_text(encoding="utf-8"))["out_name"], "preset_out")
            self.assertEqual(loaded.input_path, Path("X:/sprites"))
            self.assertEqual(loaded.mode, "animation")
            self.assertEqual(loaded.animation_names, "idle,run")
            self.assertEqual(loaded.animation_fps, 14)
            self.assertEqual(loaded.engine_exports, ["godot"])
            self.assertEqual(loaded.alpha_threshold, 18)

    def test_recent_project_helpers_dedupe_and_drop_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_file = root / "recent_projects.json"
            first = root / "first.spritecut.json"
            second = root / "second.spritecut.json"
            first.write_text("{}", encoding="utf-8")
            second.write_text("{}", encoding="utf-8")

            remember_recent_project(state_file, first, limit=3)
            remember_recent_project(state_file, second, limit=3)
            remember_recent_project(state_file, first, limit=3)

            self.assertEqual(load_recent_projects(state_file), [first, second])
            second.unlink()
            self.assertEqual(load_recent_projects(state_file), [first])

    def test_create_ui_sample_pack_writes_golden_fixture_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = create_ui_sample_pack(Path(tmp))

            self.assertTrue((output / "transparent_animation_rows" / "hero.png").exists())
            self.assertTrue((output / "packed_props_dark_bg" / "props.png").exists())
            self.assertTrue((output / "expected.json").exists())

    def test_render_detection_preview_draws_on_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sheet.png"
            Image.new("RGBA", (40, 40), (255, 255, 255, 0)).save(source)

            preview = render_detection_preview(source, [(5, 6, 20, 22)], max_size=(80, 80))

            self.assertEqual(preview.size, (40, 40))
            self.assertNotEqual(preview.getpixel((5, 6)), (255, 255, 255, 0))

    def test_accessibility_preview_modes_transform_colors(self) -> None:
        image = Image.new("RGBA", (1, 1), (220, 40, 20, 255))

        grayscale = apply_preview_accessibility_mode(image, "grayscale")
        deuteranopia = apply_preview_accessibility_mode(image, "deuteranopia")
        normal = apply_preview_accessibility_mode(image, "normal")

        gray_pixel = grayscale.getpixel((0, 0))
        self.assertEqual(gray_pixel[0], gray_pixel[1])
        self.assertEqual(gray_pixel[1], gray_pixel[2])
        self.assertNotEqual(deuteranopia.getpixel((0, 0)), image.getpixel((0, 0)))
        self.assertEqual(normal.getpixel((0, 0)), image.getpixel((0, 0)))

    def test_detect_preview_boxes_uses_cutter_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sheet.png"
            image = Image.new("RGBA", (60, 40), (255, 255, 255, 0))
            for x in range(4, 18):
                for y in range(5, 19):
                    image.putpixel((x, y), (220, 40, 40, 255))
            for x in range(34, 51):
                for y in range(8, 28):
                    image.putpixel((x, y), (40, 180, 80, 255))
            image.save(source)

            boxes = detect_preview_boxes(source)

            self.assertEqual(len(boxes), 2)

    def test_detect_preview_boxes_respects_ui_detection_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sheet.png"
            image = Image.new("RGBA", (80, 50), (255, 255, 255, 0))
            for x in range(4, 10):
                for y in range(5, 11):
                    image.putpixel((x, y), (220, 40, 40, 255))
            for x in range(34, 58):
                for y in range(8, 32):
                    image.putpixel((x, y), (40, 180, 80, 255))
            image.save(source)

            default_boxes = detect_preview_boxes(source)
            strict_boxes = detect_preview_boxes(
                source,
                CutterUiSettings(input_path=source, min_sprite_pixels=200),
            )

            self.assertEqual(len(default_boxes), 2)
            self.assertEqual(len(strict_boxes), 1)

    def test_help_flag_exits_without_opening_ui(self) -> None:
        result = subprocess.run(
            [sys.executable, str(UI_SCRIPT), "--help"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Sprite Sheet Processor UI", result.stdout)

    def test_output_line_summary_adds_report_and_folder_links(self) -> None:
        line = "OUTPUT=C:\\tmp\\sprites\\out"

        summary = summarize_cli_output_line(line)

        self.assertEqual(summary[0], line)
        self.assertIn("report.html", summary[1])
        self.assertIn("Open output folder", summary[2])

    def test_output_targets_from_cli_line_returns_folder_and_report_paths(self) -> None:
        targets = output_targets_from_cli_line("OUTPUT=C:\\tmp\\sprites\\out")

        self.assertIsNotNone(targets)
        assert targets is not None
        self.assertEqual(targets.output_dir, Path("C:/tmp/sprites/out"))
        self.assertEqual(targets.report_path, Path("C:/tmp/sprites/out/manifest/report.html"))
        self.assertEqual(targets.project_path, Path("C:/tmp/sprites/out/project.spritecut.json"))
        self.assertIsNone(output_targets_from_cli_line("Loaded 4 sheet(s)."))

    def test_project_sprite_rows_filter_by_status_and_query(self) -> None:
        project = sample_project()

        needs_review = project_sprite_rows(project, status_filter="needs_review")
        shelf_query = project_sprite_rows(project, query="shelf")

        self.assertEqual([row["id"] for row in needs_review], ["sprite_001"])
        self.assertEqual([row["id"] for row in shelf_query], ["sprite_001"])
        self.assertEqual(len(project_sprite_rows(project)), 2)

    def test_format_project_sprite_label_includes_status_confidence_and_flags(self) -> None:
        label = format_project_sprite_label(sample_project()["sprites"][0])

        self.assertIn("broken_shelf_01", label)
        self.assertIn("needs_review", label)
        self.assertIn("0.75", label)
        self.assertIn("touches_edge", label)

    def test_project_sprite_preview_path_prefers_applied_output(self) -> None:
        self.assertEqual(
            project_sprite_preview_path_text({"output_file": "old.png", "applied_output_file": "applied.png"}),
            "applied.png",
        )
        self.assertEqual(project_sprite_preview_path_text({"output_file": "old.png"}), "old.png")
        self.assertEqual(project_sprite_preview_path_text({}), "")

    def test_review_field_parsers_normalize_bbox_pivot_and_flags(self) -> None:
        self.assertEqual(parse_bbox_fields("1", "2", "30", "40"), {"x": 1, "y": 2, "width": 30, "height": 40})
        self.assertEqual(parse_pivot_fields("0.25", "0.75"), {"x": 0.25, "y": 0.75, "method": "manual"})
        self.assertEqual(parse_flags_text("touches_edge, manual_bbox | odd_aspect"), ["touches_edge", "manual_bbox", "odd_aspect"])

    def test_project_animation_clip_helpers_return_names_and_frames(self) -> None:
        project = sample_project()

        names = project_animation_clip_names(project)
        frames = project_animation_clip_frames(project, "sheet_hero_idle")

        self.assertEqual(names, ["sheet_hero_idle"])
        self.assertEqual([frame["sprite"] for frame in frames], ["sprite_001", "sprite_002"])

    def test_apply_project_outputs_method_renders_reviewed_crops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "sheet.png"
            image = Image.new("RGBA", (24, 18), (255, 255, 255, 0))
            for x in range(4, 14):
                for y in range(5, 13):
                    image.putpixel((x, y), (200, 70, 30, 255))
            image.save(source)
            project_path = root / "project.spritecut.json"
            project = {
                "schema_version": 1,
                "tool": "spritecut",
                "sprites": [
                    {
                        "id": "sprite_001",
                        "display_name": "rusty_can_01",
                        "category": "props",
                        "source_file": str(source),
                        "bbox": {"x": 4, "y": 5, "width": 10, "height": 8},
                        "review_status": "approved",
                    }
                ],
            }
            project_path.write_text(json.dumps(project), encoding="utf-8")

            class DummyUi:
                def __init__(self) -> None:
                    self.current_project = project
                    self.current_project_path = project_path
                    self.logs: list[str] = []
                    self.refreshed = False

                def append_log(self, text: str) -> None:
                    self.logs.append(text)

                def refresh_project_rows(self) -> None:
                    self.refreshed = True

            ui = DummyUi()

            SpriteSheetToolUi.apply_project_outputs(ui)  # type: ignore[arg-type]

            rendered = root / "applied_project" / "sprites" / "props" / "rusty_can_01.png"
            self.assertTrue(rendered.exists())
            self.assertTrue(ui.refreshed)
            self.assertIn("rendered=1", ui.logs[-1])

    def test_cancel_button_state_reflects_active_process(self) -> None:
        self.assertEqual(cancel_button_state(True), "normal")
        self.assertEqual(cancel_button_state(False), "disabled")

    def test_canvas_bbox_helpers_scale_and_translate_source_boxes(self) -> None:
        preview = scale_bbox_for_canvas(
            {"x": 10, "y": 20, "width": 30, "height": 40},
            image_size=(100, 100),
            canvas_size=(200, 100),
        )

        self.assertEqual(preview["rect"], (60, 20, 90, 60))
        self.assertEqual(preview["scale"], 1.0)
        self.assertEqual(preview["offset"], (50, 0))
        self.assertEqual(
            translate_bbox_by_canvas_delta({"x": 10, "y": 20, "width": 30, "height": 40}, dx=12, dy=-7, scale=2.0),
            {"x": 16, "y": 16, "width": 30, "height": 40},
        )


if __name__ == "__main__":
    unittest.main()
