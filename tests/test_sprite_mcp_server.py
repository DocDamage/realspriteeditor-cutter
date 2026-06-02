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
    autotile_generate,
    build_mcp_server,
    main,
    palette_extract,
    palette_swap,
    sprite_edit,
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
        self.run_calls: list[str] = []

    def tool(self) -> object:
        def decorator(function: object) -> object:
            self.tools[getattr(function, "__name__")] = function
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
        self.assertEqual(server.name, "SpriteCut")

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
