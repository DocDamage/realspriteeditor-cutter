from __future__ import annotations

import sys
import contextlib
import io
from pathlib import Path
from typing import Any, Callable

try:
    from tools.cut_tileset_sprites import run_cli
    from tools.golden_sprite_fixtures import create_golden_pack
    from tools.sprite_ide_api import run_ide_command
    from tools.sprite_project import load_project, render_project_outputs
    from tools.sprite_studio import build_engine_import_plans, build_review_dashboard, review_and_apply_project as run_review_and_apply_project
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.cut_tileset_sprites import run_cli
    from tools.golden_sprite_fixtures import create_golden_pack
    from tools.sprite_ide_api import run_ide_command
    from tools.sprite_project import load_project, render_project_outputs
    from tools.sprite_studio import build_engine_import_plans, build_review_dashboard, review_and_apply_project as run_review_and_apply_project


REPO_ROOT = Path(__file__).resolve().parents[1]


MCP_TOOL_NAMES = [
    "mcp_health_check",
    "mcp_client_config",
    "palette_extract",
    "palette_swap",
    "palette_hue_shift",
    "palette_variants",
    "sprite_edit",
    "sprite_batch_edit",
    "autotile_generate",
    "create_sample_pack",
    "process_sheets",
    "load_project_summary",
    "review_dashboard",
    "apply_project_outputs",
    "review_and_apply_project",
    "generate_import_plans",
]

RESOURCE_URIS = [
    "spritecut://actions",
    "spritecut://commands",
    "spritecut://quality-checklist",
    "spritecut://sample-pack",
]

PROMPT_NAMES = [
    "review_sprite_project",
    "plan_palette_variants",
    "generate_sprite_edit_request",
    "prepare_engine_handoff",
]


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def read_actions_resource() -> str:
    """Return the SpriteCut action catalog for agents."""
    return "\n".join(
        [
            "SpriteCut MCP actions:",
            "- palette.extract -> palette_extract",
            "- palette.swap -> palette_swap",
            "- palette.hue_shift -> palette_hue_shift",
            "- palette.variants -> palette_variants",
            "- sprite.edit -> sprite_edit",
            "- sprite.batch_edit -> sprite_batch_edit",
            "- autotile.generate -> autotile_generate",
            "- project processing -> process_sheets, review_dashboard, review_and_apply_project",
        ]
    )


def read_commands_resource() -> str:
    """Return the SpriteCut command reference markdown."""
    return _read_repo_text("skills/codex/spritecut-pipeline/references/spritecut-commands.md")


def read_quality_checklist_resource() -> str:
    """Return the SpriteCut production quality checklist markdown."""
    return _read_repo_text("skills/codex/spritecut-pipeline/references/spritecut-quality-checklist.md")


def read_sample_pack_resource() -> str:
    """Return a manifest-style description of bundled SpriteCut sample assets."""
    manifest_path = REPO_ROOT / "skills/codex/spritecut-pipeline/assets/sample-pack/sample_pack_manifest.json"
    if manifest_path.exists():
        return manifest_path.read_text(encoding="utf-8")
    return "Sample pack assets include misaligned_sheet.png, palette_swap_request.json, and autotile_request.json."


def review_sprite_project(project_path: str) -> str:
    """Prompt an agent to review a SpriteCut project file."""
    return (
        f"Review SpriteCut project `{project_path}`. Check status counts, low-confidence sprites, "
        "touches_edge/tiny_component/bbox_clamped flags, duplicate names, animation clips, and whether "
        "Review + Apply output is ready for handoff."
    )


def plan_palette_variants(input_path: str, base_color: str, theme: str = "cohesive game-ready colorways") -> str:
    """Prompt an agent to plan palette variant outputs."""
    return (
        f"Plan palette variants for `{input_path}` using base color `{base_color}`. "
        f"Create {theme}, extract the palette first, prefer exact swaps for pixel art, and produce a "
        "palette.variants request with named variants plus a contact sheet."
    )


def generate_sprite_edit_request(input_path: str, edit_goal: str) -> str:
    """Prompt an agent to generate a SpriteCut sprite.edit JSON request."""
    return (
        f"Generate a sprite.edit JSON request for `{input_path}` to accomplish `{edit_goal}`. "
        "Use supported operations such as replace_color, crop, resize, flip, rotate_90, draw_line, "
        "fill_rect, erase_rect, flood_fill, and hue_shift. Include output and package_dir paths."
    )


def prepare_engine_handoff(project_path: str, engine: str = "godot") -> str:
    """Prompt an agent to prepare engine import handoff."""
    return (
        f"Prepare `{project_path}` for {engine} handoff. Run review_dashboard, apply or review_and_apply "
        "if needed, confirm applied_project/import_plans contains the target engine metadata, and summarize "
        "sprites, animations, pivots, collision profiles, and remaining review blockers."
    )


def mcp_health_check() -> dict[str, Any]:
    """Return MCP setup and server health information."""
    command = [sys.executable, str(REPO_ROOT / "tools" / "sprite_mcp_server.py")]
    return {
        "ok": True,
        "server": "SpriteCut",
        "transport": "stdio",
        "repo_root": str(REPO_ROOT),
        "command": command,
        "tools": MCP_TOOL_NAMES,
        "resources": RESOURCE_URIS,
        "prompts": PROMPT_NAMES,
    }


def mcp_client_config(server_name: str = "SpriteCut", python_command: str = "python") -> dict[str, Any]:
    """Return a ready-to-copy stdio MCP client config object."""
    return {
        "mcpServers": {
            server_name: {
                "command": python_command,
                "args": ["tools\\sprite_mcp_server.py"],
                "cwd": str(REPO_ROOT),
            }
        }
    }


def create_sample_pack(output_dir: str) -> dict[str, Any]:
    """Create a small sample sprite pack for MCP smoke tests and demos."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    expected_path = create_golden_pack(root)
    alias_path = root / "expected.json"
    if expected_path != alias_path:
        alias_path.write_text(expected_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "ok": True,
        "output_dir": str(root),
        "expected": str(alias_path),
        "cases": ["transparent_animation_rows", "packed_props_dark_bg"],
    }


def _output_dir_from_stdout(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        if line.startswith("OUTPUT="):
            return Path(line.split("=", 1)[1].strip())
    return None


def process_sheets(
    input_path: str,
    out_name: str = "_organized_sprites",
    *,
    preset: str = "",
    auto_detect_all: bool = True,
    workers: int = 1,
    max_image_megapixels: float = 80.0,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the SpriteCut cutter on a folder or sheet and return generated paths."""
    argv = [input_path, "--out-name", out_name, "--workers", str(workers), "--max-image-megapixels", str(max_image_megapixels)]
    if preset:
        argv.extend(["--preset", preset])
    if auto_detect_all:
        argv.append("--auto-detect-all")
    if resume:
        argv.append("--resume")

    stdout = io.StringIO()
    stderr = io.StringIO()
    return_code = 0
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            return_code = int(run_cli(argv))
        except SystemExit as exc:
            return_code = int(exc.code) if isinstance(exc.code, int) else 1

    output_dir = _output_dir_from_stdout(stdout.getvalue())
    result: dict[str, Any] = {
        "ok": return_code == 0,
        "return_code": return_code,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
    }
    if output_dir is not None:
        result.update(
            {
                "output_dir": str(output_dir),
                "project_path": str(output_dir / "project.spritecut.json"),
                "report_path": str(output_dir / "manifest" / "report.html"),
                "visual_qa_path": str(output_dir / "manifest" / "visual_qa.html"),
            }
        )
    return result


def load_project_summary(project_path: str) -> dict[str, Any]:
    """Load a SpriteCut project and return a compact summary."""
    project = load_project(Path(project_path))
    sprites = project.get("sprites", [])
    clips = project.get("animation_clips", [])
    statuses: dict[str, int] = {}
    categories: dict[str, int] = {}
    if isinstance(sprites, list):
        for sprite in sprites:
            if not isinstance(sprite, dict):
                continue
            status = str(sprite.get("review_status", "needs_review"))
            category = str(sprite.get("category", "sprites"))
            statuses[status] = statuses.get(status, 0) + 1
            categories[category] = categories.get(category, 0) + 1
    return {
        "ok": True,
        "project_path": project_path,
        "sprite_count": len(sprites) if isinstance(sprites, list) else 0,
        "animation_clip_count": len(clips) if isinstance(clips, list) else 0,
        "statuses": statuses,
        "categories": categories,
        "settings": project.get("settings", {}),
    }


def review_dashboard(project_path: str, confidence_threshold: float = 0.85) -> dict[str, Any]:
    """Build the SpriteCut studio review dashboard for a project."""
    project = load_project(Path(project_path))
    return {
        "ok": True,
        "project_path": project_path,
        "dashboard": build_review_dashboard(project, confidence_threshold=confidence_threshold),
    }


def apply_project_outputs(project_path: str, output_dir: str = "") -> dict[str, Any]:
    """Render reviewed project crops and engine exports."""
    path = Path(project_path)
    project = load_project(path)
    summary = render_project_outputs(project, path, out_dir=Path(output_dir) if output_dir else None)
    return {"ok": True, "project_path": project_path, "summary": summary, "output_dir": summary["output_dir"]}


def review_and_apply_project(project_path: str, output_dir: str = "", naming_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the full SpriteCut studio review and apply pass."""
    path = Path(project_path)
    project = load_project(path)
    result = run_review_and_apply_project(
        project,
        path,
        output_dir=Path(output_dir) if output_dir else None,
        naming_rules=naming_rules,
    )
    return {"ok": True, "project_path": project_path, **result}


def generate_import_plans(project_path: str, engines: list[str] | None = None) -> dict[str, Any]:
    """Generate Unity, Godot, and/or Unreal import plans from a project."""
    project = load_project(Path(project_path))
    plans = build_engine_import_plans(project, engines=engines)
    return {"ok": True, "project_path": project_path, "plans": plans}


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
        mcp_health_check,
        mcp_client_config,
        palette_extract,
        palette_swap,
        palette_hue_shift,
        palette_variants,
        sprite_edit,
        sprite_batch_edit,
        autotile_generate,
        create_sample_pack,
        process_sheets,
        load_project_summary,
        review_dashboard,
        apply_project_outputs,
        review_and_apply_project,
        generate_import_plans,
    ]:
        mcp.tool()(tool_function)
    for uri, resource_function in [
        ("spritecut://actions", read_actions_resource),
        ("spritecut://commands", read_commands_resource),
        ("spritecut://quality-checklist", read_quality_checklist_resource),
        ("spritecut://sample-pack", read_sample_pack_resource),
    ]:
        mcp.resource(uri)(resource_function)
    for prompt_function in [
        review_sprite_project,
        plan_palette_variants,
        generate_sprite_edit_request,
        prepare_engine_handoff,
    ]:
        mcp.prompt()(prompt_function)
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
