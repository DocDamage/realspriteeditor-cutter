from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from tools.autotile_tools import write_autotile_package
    from tools.sprite_editor import SpriteEditSession, apply_edit_operations, apply_hue_shift, apply_palette_swap, extract_palette, write_batch_edit_package, write_edit_package, write_palette_variant_package
    from tools.sprite_project import attach_sprite_edit_output, load_project, save_project
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.autotile_tools import write_autotile_package
    from tools.sprite_editor import SpriteEditSession, apply_edit_operations, apply_hue_shift, apply_palette_swap, extract_palette, write_batch_edit_package, write_edit_package, write_palette_variant_package
    from tools.sprite_project import attach_sprite_edit_output, load_project, save_project


def _load_image(path: Path | str) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA").copy()


def _save_image(image: Image.Image, path: Path | str) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return str(path)


def _require_path(command: dict[str, Any], key: str) -> Path:
    value = str(command.get(key, "")).strip()
    if not value:
        raise ValueError(f"Missing required command field: {key}")
    return Path(value)


def _resolve_relative_request_paths(command: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(command)
    for key in ("input", "output", "output_dir", "package_dir", "project_path"):
        value = resolved.get(key)
        if isinstance(value, str) and value.strip():
            path = Path(value)
            if not path.is_absolute():
                resolved[key] = str(base_dir / path)
    inputs = resolved.get("inputs")
    if isinstance(inputs, list):
        resolved_inputs: list[Any] = []
        for value in inputs:
            if isinstance(value, str) and value.strip():
                path = Path(value)
                resolved_inputs.append(str(base_dir / path) if not path.is_absolute() else value)
            else:
                resolved_inputs.append(value)
        resolved["inputs"] = resolved_inputs
    return resolved


def run_ide_command(command: dict[str, Any]) -> dict[str, Any]:
    action = str(command.get("action", "")).strip()
    if not action:
        raise ValueError("Missing required command field: action")

    if action == "palette.extract":
        source = _require_path(command, "input")
        max_colors = int(command.get("max_colors", 32))
        palette = extract_palette(_load_image(source), max_colors=max_colors)
        result: dict[str, Any] = {"ok": True, "action": action, "input": str(source), "palette": palette}
        output = str(command.get("output", "")).strip()
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(result, indent=2), encoding="utf-8")
            result["output"] = output
        return result

    if action == "palette.swap":
        source = _require_path(command, "input")
        output = _require_path(command, "output")
        swaps = command.get("swaps", {})
        if not isinstance(swaps, dict) or not swaps:
            raise ValueError("palette.swap requires a non-empty swaps object.")
        tolerance = int(command.get("tolerance", 0))
        image = apply_palette_swap(_load_image(source), swaps, tolerance=tolerance)
        return {"ok": True, "action": action, "input": str(source), "output": _save_image(image, output), "swapped": len(swaps)}

    if action == "palette.hue_shift":
        source = _require_path(command, "input")
        output = _require_path(command, "output")
        degrees = float(command.get("degrees", 0))
        saturation = float(command.get("saturation", 1.0))
        value = float(command.get("value", 1.0))
        image = apply_hue_shift(_load_image(source), degrees=degrees, saturation=saturation, value=value)
        return {"ok": True, "action": action, "input": str(source), "output": _save_image(image, output), "degrees": degrees}

    if action == "sprite.edit":
        source = _require_path(command, "input")
        output_text = str(command.get("output", "")).strip()
        package_dir_text = str(command.get("package_dir", "")).strip()
        operations = command.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("sprite.edit requires operations to be a list.")
        session = SpriteEditSession.open(source)
        summary = apply_edit_operations(session, operations)
        result: dict[str, Any] = {"ok": True, "action": action, "input": str(source), "summary": summary}
        if output_text:
            output = Path(output_text)
            session.save(output)
            result["output"] = str(output)
        if package_dir_text:
            result["package"] = write_edit_package(session, Path(package_dir_text))
        return result

    if action == "sprite.batch_edit":
        inputs = command.get("inputs", [])
        if not isinstance(inputs, list) or not inputs:
            raise ValueError("sprite.batch_edit requires a non-empty inputs list.")
        output_dir = _require_path(command, "output_dir")
        operations = command.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("sprite.batch_edit requires operations to be a list.")
        package = write_batch_edit_package([Path(str(path)) for path in inputs], output_dir, operations=operations)
        return {"ok": True, "action": action, **package}

    if action == "sprite.save_to_project":
        project_path = _require_path(command, "project_path")
        source = _require_path(command, "input")
        sprite_id = str(command.get("sprite_id", "")).strip()
        if not sprite_id:
            raise ValueError("sprite.save_to_project requires sprite_id.")
        operations = command.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("sprite.save_to_project requires operations to be a list.")
        output_dir_text = str(command.get("output_dir", "")).strip()
        output_dir = Path(output_dir_text) if output_dir_text else project_path.parent / "applied_project" / "sprites" / "edited"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{sprite_id}.png"
        session = SpriteEditSession.open(source)
        summary = apply_edit_operations(session, operations)
        session.save(output_path)
        project = load_project(project_path)
        updated = attach_sprite_edit_output(project, sprite_id, str(output_path))
        save_project(updated, project_path)
        return {
            "ok": True,
            "action": action,
            "project_path": str(project_path),
            "sprite_id": sprite_id,
            "input": str(source),
            "output": str(output_path),
            "summary": summary,
        }

    if action == "palette.variants":
        source = _require_path(command, "input")
        output_dir = _require_path(command, "output_dir")
        variants = command.get("variants", [])
        if not isinstance(variants, list):
            raise ValueError("palette.variants requires variants to be a list.")
        package = write_palette_variant_package(
            _load_image(source),
            output_dir,
            name=str(command.get("name", source.stem)),
            variants=variants,
        )
        return {"ok": True, "action": action, "input": str(source), **package}

    if action == "autotile.generate":
        source = _require_path(command, "input")
        output_dir = _require_path(command, "output_dir")
        name = str(command.get("name", source.stem)).strip() or source.stem
        engine = str(command.get("engine", "generic")).strip() or "generic"
        package = write_autotile_package(_load_image(source), output_dir, name=name, engine=engine)
        return {"ok": True, "action": action, "input": str(source), **package}

    raise ValueError(f"Unsupported sprite IDE action: {action}")


def _load_request(args: argparse.Namespace) -> dict[str, Any]:
    if args.request:
        request_path = Path(args.request)
        data = json.loads(request_path.read_text(encoding="utf-8"))
    elif args.json:
        data = json.loads(args.json)
    else:
        data = json.loads(sys.stdin.read())
    if not isinstance(data, dict):
        raise ValueError("Sprite IDE request must be a JSON object.")
    if args.request:
        return _resolve_relative_request_paths(data, request_path.parent)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IDE-callable JSON API for SpriteCut editor, palette, and autotile operations.")
    parser.add_argument("--request", help="Path to a JSON request file.")
    parser.add_argument("--json", help="Inline JSON request.")
    args = parser.parse_args(argv)
    try:
        result = run_ide_command(_load_request(args))
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
