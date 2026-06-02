from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tools.sprite_mcp_server import (
    MCP_TOOL_NAMES,
    PROMPT_NAMES,
    RESOURCE_URIS,
    apply_project_outputs,
    autotile_generate,
    build_mcp_server,
    create_sample_pack,
    generate_import_plans,
    generate_sprite_edit_request,
    load_project_summary,
    main,
    mcp_client_config,
    mcp_health_check,
    palette_extract,
    palette_swap,
    plan_palette_variants,
    prepare_engine_handoff,
    process_sheets,
    read_actions_resource,
    read_commands_resource,
    read_quality_checklist_resource,
    read_sample_pack_resource,
    review_and_apply_project,
    review_dashboard,
    review_sprite_project,
    sprite_edit,
    sprite_save_to_project,
    project_vision_label,
)


def write_source(path: Path) -> None:
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    image.putpixel((7, 7), (0, 0, 0, 0))
    image.save(path)


class FakeMcp:
    def __init__(self, name: str, json_response: bool = True) -> None:
        self.name = name
        self.json_response = json_response
        self.tools: dict[str, object] = {}
        self.resources: dict[str, object] = {}
        self.prompts: dict[str, object] = {}
        self.run_calls: list[str] = []

    def tool(self) -> object:
        def decorator(function: object) -> object:
            self.tools[getattr(function, "__name__")] = function
            return function

        return decorator

    def resource(self, uri: str) -> object:
        def decorator(function: object) -> object:
            self.resources[uri] = function
            return function

        return decorator

    def prompt(self) -> object:
        def decorator(function: object) -> object:
            self.prompts[getattr(function, "__name__")] = function
            return function

        return decorator

    def run(self, transport: str = "stdio") -> None:
        self.run_calls.append(transport)


class SpriteMcpServerTests(unittest.TestCase):
    def test_palette_extract_wraps_existing_ide_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            write_source(source)

            result = palette_extract(str(source), max_colors=4)

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "palette.extract")
            self.assertEqual(result["input"], str(source))
            self.assertTrue(result["palette"])

    def test_palette_swap_and_sprite_edit_write_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            swapped = root / "blue.png"
            edited = root / "edited.png"
            write_source(source)

            swap_result = palette_swap(str(source), str(swapped), {"#ff0000": "#0000ff"})
            edit_result = sprite_edit(
                str(source),
                output=str(edited),
                operations=[{"tool": "replace_color", "source": "#ff0000", "target": "#00ff00"}],
            )

            self.assertEqual(swap_result["action"], "palette.swap")
            self.assertTrue(swapped.exists())
            self.assertEqual(edit_result["summary"]["applied"], 1)
            self.assertTrue(edited.exists())
            with Image.open(swapped) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_sprite_save_to_project_updates_project_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            project_path = root / "project.spritecut.json"
            write_source(source)
            project_path.write_text(
                '{"schema_version": 1, "sprites": [{"id": "sprite_001", "review_status": "needs_review", "review_flags": []}]}',
                encoding="utf-8",
            )

            result = sprite_save_to_project(
                str(project_path),
                "sprite_001",
                str(source),
                operations=[{"tool": "replace_color", "source": "#ff0000", "target": "#00ff00"}],
            )

            self.assertEqual(result["ok"], True)
            self.assertTrue(Path(result["output"]).exists())
            self.assertIn("sprite.save_to_project", read_actions_resource())
            self.assertEqual(load_project_summary(str(project_path))["statuses"], {"approved": 1})

    def test_project_vision_label_updates_manifest_through_mcp_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            project_path = root / "project.spritecut.json"
            write_source(source)
            project_path.write_text(
                '{"schema_version": 1, "sprites": [{"id": "sprite_001", "display_name": "unknown", "category": "sprites", "output_file": "'
                + str(source).replace("\\", "\\\\")
                + '", "review_status": "needs_review", "review_flags": []}]}',
                encoding="utf-8",
            )

            result = project_vision_label(
                str(project_path),
                provider="fixture",
                fixture_labels={
                    "sprite_001": {
                        "display_name": "red_pickup",
                        "category": "props_and_items",
                        "description": "A red pickup item.",
                        "confidence": 0.92,
                    }
                },
            )

            self.assertEqual(result["ok"], True)
            self.assertIn("project.vision_label", read_actions_resource())
            self.assertEqual(load_project_summary(str(project_path))["categories"], {"props_and_items": 1})

    def test_autotile_generate_writes_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output_dir = root / "autotile"
            write_source(source)

            result = autotile_generate(str(source), str(output_dir), name="red_floor", engine="godot")

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["action"], "autotile.generate")
            self.assertTrue(Path(result["sheet"]).exists())
            self.assertTrue(Path(result["rules"]).exists())

    def test_build_mcp_server_registers_all_tool_names(self) -> None:
        server = build_mcp_server(fast_mcp_factory=FakeMcp)

        self.assertEqual(sorted(server.tools), sorted(MCP_TOOL_NAMES))
        self.assertEqual(sorted(server.resources), sorted(RESOURCE_URIS))
        self.assertEqual(sorted(server.prompts), sorted(PROMPT_NAMES))
        self.assertEqual(server.name, "SpriteCut")

    def test_resource_readers_return_agent_context(self) -> None:
        self.assertIn("palette.extract", read_actions_resource())
        self.assertIn("sprite_ide_api.py", read_commands_resource())
        self.assertIn("Review + Apply", read_quality_checklist_resource())
        self.assertIn("misaligned_sheet.png", read_sample_pack_resource())

    def test_prompt_helpers_include_user_supplied_context(self) -> None:
        self.assertIn("project.spritecut.json", review_sprite_project("project.spritecut.json"))
        self.assertIn("#ff0000", plan_palette_variants("crate.png", "#ff0000"))
        self.assertIn("replace_color", generate_sprite_edit_request("crate.png", "replace_color"))
        self.assertIn("godot", prepare_engine_handoff("project.spritecut.json", "godot").lower())

    def test_mcp_health_check_and_client_config_are_json_ready(self) -> None:
        health = mcp_health_check()
        config = mcp_client_config("SpriteCut", python_command="python")

        self.assertEqual(health["ok"], True)
        self.assertIn("sprite_mcp_server.py", " ".join(health["command"]))
        self.assertEqual(config["mcpServers"]["SpriteCut"]["command"], "python")
        self.assertIn("tools\\sprite_mcp_server.py", config["mcpServers"]["SpriteCut"]["args"])

    def test_create_sample_pack_and_process_sheets_write_project_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = create_sample_pack(str(root / "sample"))

            self.assertEqual(sample["ok"], True)
            self.assertTrue((Path(sample["output_dir"]) / "expected.json").exists())

            result = process_sheets(
                str(Path(sample["output_dir"]) / "packed_props_dark_bg"),
                out_name="_mcp_sprites",
                preset="packed_props_dark_bg",
            )

            self.assertEqual(result["ok"], True)
            self.assertEqual(result["return_code"], 0)
            self.assertTrue(Path(result["project_path"]).exists())
            self.assertTrue(Path(result["report_path"]).exists())
            self.assertIn("OUTPUT=", result["stdout"])

    def test_project_summary_dashboard_apply_and_import_plan_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = create_sample_pack(str(root / "sample"))
            run = process_sheets(
                str(Path(sample["output_dir"]) / "packed_props_dark_bg"),
                out_name="_mcp_sprites",
                preset="packed_props_dark_bg",
            )
            project_path = str(run["project_path"])

            summary = load_project_summary(project_path)
            dashboard = review_dashboard(project_path)
            apply_result = apply_project_outputs(project_path, output_dir=str(root / "applied"))
            plans = generate_import_plans(project_path, engines=["unity", "godot"])
            studio = review_and_apply_project(project_path, output_dir=str(root / "studio_apply"))

            self.assertEqual(summary["ok"], True)
            self.assertGreater(summary["sprite_count"], 0)
            self.assertEqual(dashboard["ok"], True)
            self.assertIn("queue", dashboard["dashboard"])
            self.assertEqual(apply_result["ok"], True)
            self.assertGreater(apply_result["summary"]["rendered"], 0)
            self.assertEqual(plans["ok"], True)
            self.assertEqual(sorted(plans["plans"]), ["godot", "unity"])
            self.assertEqual(studio["ok"], True)
            self.assertTrue(Path(studio["output_dir"]).exists())

    def test_main_reports_missing_optional_mcp_dependency_to_stderr(self) -> None:
        def missing_factory(*_args: object, **_kwargs: object) -> object:
            raise ImportError("No module named mcp")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main(fast_mcp_factory=missing_factory)

        self.assertEqual(result, 1)
        self.assertIn("pip install -r requirements-mcp.txt", stderr.getvalue())

    def test_main_runs_stdio_transport_when_server_builds(self) -> None:
        server = FakeMcp("SpriteCut")
        with mock.patch("tools.sprite_mcp_server.build_mcp_server", return_value=server):
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(server.run_calls, ["stdio"])


if __name__ == "__main__":
    unittest.main()
