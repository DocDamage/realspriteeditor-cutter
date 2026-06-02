from __future__ import annotations

import sys
from typing import Any, Callable

try:
    from tools.sprite_ide_api import run_ide_command
except ModuleNotFoundError:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.sprite_ide_api import run_ide_command


MCP_TOOL_NAMES = [
    "palette_extract",
    "palette_swap",
    "palette_hue_shift",
    "palette_variants",
    "sprite_edit",
    "sprite_batch_edit",
    "autotile_generate",
]


def palette_extract(input: str, max_colors: int = 32, output: str = "") -> dict[str, Any]:
    """Extract dominant visible palette colors from a sprite image."""
    command: dict[str, Any] = {"action": "palette.extract", "input": input, "max_colors": max_colors}
    if output:
        command["output"] = output
    return run_ide_command(command)


def palette_swap(input: str, output: str, swaps: dict[str, str], tolerance: int = 0) -> dict[str, Any]:
    """Replace exact or tolerance-matched palette colors in one sprite image."""
    return run_ide_command(
        {
            "action": "palette.swap",
            "input": input,
            "output": output,
            "swaps": swaps,
            "tolerance": tolerance,
        }
    )


def palette_hue_shift(
    input: str,
    output: str,
    degrees: float,
    saturation: float = 1.0,
    value: float = 1.0,
) -> dict[str, Any]:
    """Apply hue, saturation, and value adjustments to one sprite image."""
    return run_ide_command(
        {
            "action": "palette.hue_shift",
            "input": input,
            "output": output,
            "degrees": degrees,
            "saturation": saturation,
            "value": value,
        }
    )


def palette_variants(input: str, output_dir: str, variants: list[dict[str, Any]], name: str = "") -> dict[str, Any]:
    """Write named palette colorway PNGs plus a manifest and contact sheet."""
    command: dict[str, Any] = {
        "action": "palette.variants",
        "input": input,
        "output_dir": output_dir,
        "variants": variants,
    }
    if name:
        command["name"] = name
    return run_ide_command(command)


def sprite_edit(
    input: str,
    operations: list[dict[str, Any]],
    output: str = "",
    package_dir: str = "",
) -> dict[str, Any]:
    """Apply a JSON-ready sprite edit operation pipeline to one sprite."""
    command: dict[str, Any] = {"action": "sprite.edit", "input": input, "operations": operations}
    if output:
        command["output"] = output
    if package_dir:
        command["package_dir"] = package_dir
    return run_ide_command(command)


def sprite_batch_edit(inputs: list[str], output_dir: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the same sprite edit operation pipeline to multiple sprites."""
    return run_ide_command(
        {
            "action": "sprite.batch_edit",
            "inputs": inputs,
            "output_dir": output_dir,
            "operations": operations,
        }
    )


def autotile_generate(input: str, output_dir: str, name: str = "", engine: str = "generic") -> dict[str, Any]:
    """Generate a 16-mask cardinal autotile sheet and engine rule metadata."""
    command: dict[str, Any] = {
        "action": "autotile.generate",
        "input": input,
        "output_dir": output_dir,
        "engine": engine,
    }
    if name:
        command["name"] = name
    return run_ide_command(command)


def _default_fast_mcp_factory(*args: Any, **kwargs: Any) -> Any:
    from mcp.server.fastmcp import FastMCP

    return FastMCP(*args, **kwargs)


def build_mcp_server(fast_mcp_factory: Callable[..., Any] | None = None) -> Any:
    factory = fast_mcp_factory or _default_fast_mcp_factory
    mcp = factory("SpriteCut", json_response=True)
    for tool_function in [
        palette_extract,
        palette_swap,
        palette_hue_shift,
        palette_variants,
        sprite_edit,
        sprite_batch_edit,
        autotile_generate,
    ]:
        mcp.tool()(tool_function)
    return mcp


def main(fast_mcp_factory: Callable[..., Any] | None = None) -> int:
    try:
        server = build_mcp_server(fast_mcp_factory=fast_mcp_factory)
    except ImportError as exc:
        print(
            "SpriteCut MCP requires the optional MCP SDK. Install it with: "
            "pip install -r requirements-mcp.txt",
            file=sys.stderr,
        )
        print(f"Import error: {exc}", file=sys.stderr)
        return 1
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
