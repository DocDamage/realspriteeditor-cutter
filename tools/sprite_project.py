from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


EDITABLE_FIELDS = {
    "display_name",
    "category",
    "bbox",
    "pivot",
    "review_status",
    "review_flags",
    "confidence",
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_project(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Project file must contain a JSON object.")
    if data.get("schema_version") != 1:
        raise ValueError(f"Unsupported project schema_version: {data.get('schema_version')}")
    if not isinstance(data.get("sprites"), list):
        raise ValueError("Project file must contain a sprites list.")
    return data


def save_project(project: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project, indent=2), encoding="utf-8")


def attach_sprite_edit_output(project: dict[str, object], sprite_id: str, applied_output_file: str) -> dict[str, object]:
    updated = copy.deepcopy(project)
    sprites = updated.get("sprites", [])
    if not isinstance(sprites, list):
        raise ValueError("Project sprites must be a list.")
    for sprite in sprites:
        if isinstance(sprite, dict) and sprite.get("id") == sprite_id:
            sprite["applied_output_file"] = applied_output_file
            sprite["review_status"] = "approved"
            flags = sprite.get("review_flags", [])
            sprite["review_flags"] = [flag for flag in flags if flag != "edited"] if isinstance(flags, list) else []
            return updated
    raise ValueError(f"Sprite not found: {sprite_id}")


def attach_animation_edit_output(project: dict[str, object], clip_name: str, manifest_path: str) -> dict[str, object]:
    updated = copy.deepcopy(project)
    clips = updated.get("animation_clips", [])
    if not isinstance(clips, list):
        raise ValueError("Project animation_clips must be a list.")
    for clip in clips:
        if isinstance(clip, dict) and clip.get("name") == clip_name:
            clip["applied_manifest"] = manifest_path
            return updated
    raise ValueError(f"Animation clip not found: {clip_name}")


def find_sprite(project: dict[str, Any], sprite_id: str) -> dict[str, Any]:
    sprites = project.get("sprites")
    if not isinstance(sprites, list):
        raise ValueError("Project file must contain a sprites list.")
    for sprite in sprites:
        if isinstance(sprite, dict) and sprite.get("id") == sprite_id:
            return sprite
    raise KeyError(f"Unknown sprite id: {sprite_id}")


def _sprites(project: dict[str, Any]) -> list[dict[str, Any]]:
    sprites = project.get("sprites")
    if not isinstance(sprites, list):
        raise ValueError("Project file must contain a sprites list.")
    return sprites


def _history(project: dict[str, Any]) -> list[dict[str, Any]]:
    history = project.setdefault("history", [])
    if not isinstance(history, list):
        raise ValueError("Project history must be a list when present.")
    return history


def _append_history(project: dict[str, Any], entry: dict[str, Any]) -> None:
    entry.setdefault("timestamp", _utc_timestamp())
    _history(project).append(entry)
    project["redo_stack"] = []


def _normalize_bbox(bbox: dict[str, Any]) -> dict[str, int]:
    required = ["x", "y", "width", "height"]
    missing = [field for field in required if field not in bbox]
    if missing:
        raise ValueError(f"Bbox missing field(s): {', '.join(missing)}")
    normalized = {field: int(bbox[field]) for field in required}
    if normalized["width"] <= 0 or normalized["height"] <= 0:
        raise ValueError("Bbox width and height must be positive.")
    return normalized


def _union_bbox(boxes: list[dict[str, Any]]) -> dict[str, int]:
    normalized = [_normalize_bbox(box) for box in boxes]
    left = min(box["x"] for box in normalized)
    top = min(box["y"] for box in normalized)
    right = max(box["x"] + box["width"] for box in normalized)
    bottom = max(box["y"] + box["height"] for box in normalized)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def _with_flag(sprite: dict[str, Any], flag: str) -> list[str]:
    flags = sprite.get("review_flags", [])
    if not isinstance(flags, list):
        flags = []
    next_flags = [str(item) for item in flags]
    if flag not in next_flags:
        next_flags.append(flag)
    return next_flags


def update_sprite(project: dict[str, Any], sprite_id: str, **changes: Any) -> dict[str, Any]:
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"Unsupported sprite edit field(s): {', '.join(sorted(unknown))}")

    sprite = find_sprite(project, sprite_id)
    before = copy.deepcopy({field: sprite.get(field) for field in EDITABLE_FIELDS if field in sprite})
    for field, value in changes.items():
        sprite[field] = value
    after = copy.deepcopy({field: sprite.get(field) for field in EDITABLE_FIELDS if field in sprite})

    _append_history(
        project,
        {
            "action": "update_sprite",
            "sprite_id": sprite_id,
            "before": before,
            "after": after,
        },
    )
    return sprite


def approve_sprite(project: dict[str, Any], sprite_id: str) -> dict[str, Any]:
    return update_sprite(
        project,
        sprite_id,
        review_status="approved",
        review_flags=[],
        confidence=1.0,
    )


def reject_sprite(project: dict[str, Any], sprite_id: str, reason: str = "rejected") -> dict[str, Any]:
    sprite = find_sprite(project, sprite_id)
    return update_sprite(
        project,
        sprite_id,
        review_status="rejected",
        review_flags=_with_flag(sprite, reason),
        confidence=0.0,
    )


def move_sprite_bbox(project: dict[str, Any], sprite_id: str, dx: int, dy: int) -> dict[str, Any]:
    sprite = find_sprite(project, sprite_id)
    bbox = _normalize_bbox(sprite.get("bbox", {}))
    moved = {"x": bbox["x"] + int(dx), "y": bbox["y"] + int(dy), "width": bbox["width"], "height": bbox["height"]}
    return update_sprite(
        project,
        sprite_id,
        bbox=moved,
        review_flags=_with_flag(sprite, "manual_bbox"),
        review_status="needs_review",
    )


def split_sprite(project: dict[str, Any], sprite_id: str, boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(boxes) < 2:
        raise ValueError("Splitting requires at least two boxes.")

    sprites = _sprites(project)
    original = find_sprite(project, sprite_id)
    before_original = copy.deepcopy(original)
    normalized_boxes = [_normalize_bbox(box) for box in boxes]
    children: list[dict[str, Any]] = []
    existing_ids = {str(sprite.get("id")) for sprite in sprites if isinstance(sprite, dict)}

    for index, bbox in enumerate(normalized_boxes, start=1):
        child_id = f"{sprite_id}_split_{index:02d}"
        if child_id in existing_ids:
            raise ValueError(f"Split sprite id already exists: {child_id}")
        child = copy.deepcopy(original)
        child["id"] = child_id
        child["display_name"] = child_id
        child["bbox"] = bbox
        child["atlas"] = None
        child["confidence"] = min(0.9, float(child.get("confidence", 0.75)))
        child["review_status"] = "needs_review"
        child["review_flags"] = ["manual_split"]
        children.append(child)
        sprites.append(child)

    original["review_status"] = "rejected"
    original["review_flags"] = _with_flag(original, "split_source")
    original["confidence"] = 0.0

    _append_history(
        project,
        {
            "action": "split_sprite",
            "sprite_id": sprite_id,
            "before": {"original": before_original},
            "after": {"original": copy.deepcopy(original), "children": copy.deepcopy(children)},
        },
    )
    return children


def merge_sprites(
    project: dict[str, Any],
    sprite_ids: list[str],
    merged_id: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    if len(sprite_ids) < 2:
        raise ValueError("Merging requires at least two sprites.")

    sprites = _sprites(project)
    existing_ids = {str(sprite.get("id")) for sprite in sprites if isinstance(sprite, dict)}
    if merged_id in existing_ids:
        raise ValueError(f"Merged sprite id already exists: {merged_id}")

    source_sprites = [find_sprite(project, sprite_id) for sprite_id in sprite_ids]
    before_sources = copy.deepcopy(source_sprites)
    merged = copy.deepcopy(source_sprites[0])
    merged["id"] = merged_id
    merged["display_name"] = display_name or merged_id
    merged["bbox"] = _union_bbox([sprite.get("bbox", {}) for sprite in source_sprites])
    merged["atlas"] = None
    merged["confidence"] = min(0.9, min(float(sprite.get("confidence", 0.75)) for sprite in source_sprites))
    merged["review_status"] = "needs_review"
    merged["review_flags"] = ["manual_merge"]
    merged["merged_from"] = list(sprite_ids)

    for sprite in source_sprites:
        sprite["review_status"] = "rejected"
        sprite["review_flags"] = _with_flag(sprite, f"merged_into:{merged_id}")
        sprite["confidence"] = 0.0
    sprites.append(merged)

    _append_history(
        project,
        {
            "action": "merge_sprites",
            "sprite_ids": list(sprite_ids),
            "sprite_id": merged_id,
            "before": {"sources": before_sources},
            "after": {"sources": copy.deepcopy(source_sprites), "merged": copy.deepcopy(merged)},
        },
    )
    return merged


def _apply_snapshot(sprite: dict[str, Any], snapshot: dict[str, Any]) -> None:
    for field in EDITABLE_FIELDS:
        if field in snapshot:
            sprite[field] = copy.deepcopy(snapshot[field])
        elif field in sprite:
            del sprite[field]


def _replace_or_append_sprite(project: dict[str, Any], snapshot: dict[str, Any]) -> None:
    sprites = _sprites(project)
    sprite_id = str(snapshot.get("id", ""))
    for index, sprite in enumerate(sprites):
        if isinstance(sprite, dict) and str(sprite.get("id", "")) == sprite_id:
            sprites[index] = copy.deepcopy(snapshot)
            return
    sprites.append(copy.deepcopy(snapshot))


def _remove_sprites(project: dict[str, Any], sprite_ids: set[str]) -> None:
    sprites = _sprites(project)
    sprites[:] = [sprite for sprite in sprites if not (isinstance(sprite, dict) and str(sprite.get("id", "")) in sprite_ids)]


def _undo_structural_edit(project: dict[str, Any], entry: dict[str, Any]) -> bool:
    action = entry.get("action")
    before = entry.get("before", {})
    after = entry.get("after", {})
    if action == "split_sprite" and isinstance(before, dict) and isinstance(after, dict):
        children = after.get("children", [])
        child_ids = {str(child.get("id", "")) for child in children if isinstance(child, dict)}
        _remove_sprites(project, child_ids)
        original = before.get("original")
        if isinstance(original, dict):
            _replace_or_append_sprite(project, original)
        return True
    if action == "merge_sprites" and isinstance(before, dict) and isinstance(after, dict):
        merged = after.get("merged")
        if isinstance(merged, dict):
            _remove_sprites(project, {str(merged.get("id", ""))})
        sources = before.get("sources", [])
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict):
                    _replace_or_append_sprite(project, source)
        return True
    return False


def _redo_structural_edit(project: dict[str, Any], entry: dict[str, Any]) -> bool:
    action = entry.get("action")
    after = entry.get("after", {})
    if action == "split_sprite" and isinstance(after, dict):
        original = after.get("original")
        if isinstance(original, dict):
            _replace_or_append_sprite(project, original)
        children = after.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    _replace_or_append_sprite(project, child)
        return True
    if action == "merge_sprites" and isinstance(after, dict):
        sources = after.get("sources", [])
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict):
                    _replace_or_append_sprite(project, source)
        merged = after.get("merged")
        if isinstance(merged, dict):
            _replace_or_append_sprite(project, merged)
        return True
    return False


def _structural_undo_result_sprite(project: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    try:
        return find_sprite(project, str(entry["sprite_id"]))
    except KeyError:
        before = entry.get("before", {})
        sources = before.get("sources", []) if isinstance(before, dict) else []
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and source.get("id"):
                    return find_sprite(project, str(source["id"]))
        raise


def undo_last_edit(project: dict[str, Any]) -> dict[str, Any]:
    history = project.get("history", [])
    if not isinstance(history, list):
        raise ValueError("Project history must be a list.")
    if not history:
        raise ValueError("No edits to undo.")

    entry = history.pop()
    structural = _undo_structural_edit(project, entry)
    if structural:
        sprite = _structural_undo_result_sprite(project, entry)
    else:
        sprite = find_sprite(project, str(entry["sprite_id"]))
        _apply_snapshot(sprite, entry.get("before", {}))

    redo_stack = project.setdefault("redo_stack", [])
    if not isinstance(redo_stack, list):
        raise ValueError("Project redo_stack must be a list when present.")
    redo_stack.append(entry)
    return sprite


def redo_last_edit(project: dict[str, Any]) -> dict[str, Any]:
    redo_stack = project.get("redo_stack", [])
    if not isinstance(redo_stack, list):
        raise ValueError("Project redo_stack must be a list.")
    if not redo_stack:
        raise ValueError("No edits to redo.")

    entry = redo_stack.pop()
    structural = _redo_structural_edit(project, entry)
    sprite = find_sprite(project, str(entry["sprite_id"]))
    if not structural:
        _apply_snapshot(sprite, entry.get("after", {}))

    history = project.setdefault("history", [])
    if not isinstance(history, list):
        raise ValueError("Project history must be a list when present.")
    history.append(entry)
    return sprite


def safe_file_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_.")
    return cleaned or "sprite"


def _resolve_project_path(path_text: str, project_path: Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else project_path.parent / path


def _clear_generated_child(output_root: Path, child_name: str) -> None:
    target = output_root / child_name
    if not target.exists():
        return
    resolved_root = output_root.resolve()
    resolved_target = target.resolve()
    if resolved_target.parent != resolved_root:
        raise ValueError(f"Refusing to clear unexpected output path: {target}")
    shutil.rmtree(target)


def _unique_output_path(path: Path, used_paths: set[Path]) -> Path:
    candidate = path
    index = 2
    while candidate in used_paths:
        candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
        index += 1
    used_paths.add(candidate)
    return candidate


def _clamp_bbox_to_image(sprite: dict[str, Any], bbox: dict[str, int], image_size: tuple[int, int]) -> dict[str, int]:
    image_width, image_height = image_size
    left = max(0, bbox["x"])
    top = max(0, bbox["y"])
    right = min(image_width, bbox["x"] + bbox["width"])
    bottom = min(image_height, bbox["y"] + bbox["height"])
    if right <= left or bottom <= top:
        raise ValueError(f"Bbox for {sprite.get('id', 'sprite')} does not overlap the source image.")
    clamped = {"x": left, "y": top, "width": right - left, "height": bottom - top}
    if clamped != bbox:
        sprite["bbox"] = clamped
        sprite["review_flags"] = _with_flag(sprite, "bbox_clamped")
    return clamped


def _active_project_sprites(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        sprite
        for sprite in _sprites(project)
        if isinstance(sprite, dict) and sprite.get("review_status") != "rejected"
    ]


def _project_engine_exports(project: dict[str, Any]) -> list[str]:
    settings = project.get("settings", {})
    raw_exports: Any = settings.get("engine_exports", []) if isinstance(settings, dict) else []
    raw_parts: list[str] = []
    if isinstance(raw_exports, str):
        raw_parts = raw_exports.split(",")
    elif isinstance(raw_exports, list):
        for item in raw_exports:
            raw_parts.extend(str(item).split(","))

    requested = [part.strip().lower() for part in raw_parts if part.strip()]
    if "all" in requested:
        return ["unity", "godot", "unreal"]

    allowed = {"unity", "godot", "unreal"}
    engines: list[str] = []
    for engine in requested:
        if engine in allowed and engine not in engines:
            engines.append(engine)
    return engines


def _project_pivot(sprite: dict[str, Any]) -> dict[str, Any]:
    pivot = sprite.get("pivot", {})
    if not isinstance(pivot, dict):
        pivot = {}
    return {
        "x": float(pivot.get("x", 0.5)),
        "y": float(pivot.get("y", 0.5)),
        "method": str(pivot.get("method", "manual")),
    }


def _sprite_export_entry(sprite: dict[str, Any]) -> dict[str, Any]:
    bbox = _normalize_bbox(sprite.get("bbox", {}))
    flags = sprite.get("review_flags", [])
    if not isinstance(flags, list):
        flags = []
    return {
        "name": str(sprite.get("id", "")),
        "display_name": str(sprite.get("display_name") or sprite.get("id") or ""),
        "kind": str(sprite.get("kind", "sprite")),
        "category": str(sprite.get("category", "sprites")),
        "sequence": sprite.get("sequence"),
        "frame": sprite.get("frame"),
        "source_file": str(sprite.get("applied_output_file") or sprite.get("output_file") or ""),
        "source_rect": bbox,
        "size": {"width": bbox["width"], "height": bbox["height"]},
        "pivot": _project_pivot(sprite),
        "atlas": None,
        "is_partial": bool(sprite.get("is_partial", False)),
        "confidence": float(sprite.get("confidence", 1.0)),
        "review_flags": [str(flag) for flag in flags],
        "review_status": str(sprite.get("review_status", "needs_review")),
    }


def _review_animation_clips(project: dict[str, Any], active_sprites: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    source_clips = project.get("animation_clips", [])
    if not isinstance(source_clips, list):
        return clips

    for clip in source_clips:
        if not isinstance(clip, dict):
            continue
        frames: list[dict[str, Any]] = []
        for frame in clip.get("frames", []):
            if not isinstance(frame, dict):
                continue
            sprite = active_sprites.get(str(frame.get("sprite", "")))
            if sprite is None:
                continue
            bbox = _normalize_bbox(sprite.get("bbox", {}))
            frames.append(
                {
                    "sprite": str(sprite.get("id", "")),
                    "display_name": str(sprite.get("display_name") or sprite.get("id") or ""),
                    "frame": frame.get("frame", sprite.get("frame")),
                    "source_file": str(sprite.get("applied_output_file") or sprite.get("output_file") or ""),
                    "duration": float(frame.get("duration", 1.0 / max(1, int(clip.get("frame_rate", 8))))),
                    "bbox": bbox,
                    "pivot": _project_pivot(sprite),
                    "atlas": None,
                    "review_status": str(sprite.get("review_status", "needs_review")),
                }
            )
        if not frames:
            continue
        clips.append(
            {
                "name": str(clip.get("name", "animation")),
                "source_sheet": str(clip.get("source_sheet", "")),
                "sequence": str(clip.get("sequence", "")),
                "frame_rate": int(clip.get("frame_rate", 8)),
                "loop": bool(clip.get("loop", True)),
                "frame_count": len(frames),
                "frames": frames,
            }
        )
    return clips


def _godot_animation_clips(animation_clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    animations: list[dict[str, Any]] = []
    for clip in animation_clips:
        animations.append(
            {
                "name": clip["name"],
                "speed_fps": clip["frame_rate"],
                "loop": clip["loop"],
                "frames": [
                    {
                        "sprite": frame["sprite"],
                        "source_file": frame["source_file"],
                        "duration": frame["duration"],
                        "atlas": frame["atlas"],
                    }
                    for frame in clip["frames"]
                ],
            }
        )
    return animations


def _unreal_flipbooks(animation_clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flipbooks: list[dict[str, Any]] = []
    for clip in animation_clips:
        frames = []
        for index, frame in enumerate(clip["frames"]):
            frames.append(
                {
                    "sprite": frame["sprite"],
                    "key_frame": index,
                    "duration": frame["duration"],
                    "source_file": frame["source_file"],
                    "atlas": frame["atlas"],
                }
            )
        flipbooks.append({"name": clip["name"], "frame_rate": clip["frame_rate"], "loop": clip["loop"], "frames": frames})
    return flipbooks


def _write_project_engine_exports(project: dict[str, Any], output_root: Path) -> list[str]:
    engines = _project_engine_exports(project)
    if not engines:
        return []

    active_sprites = {
        str(sprite.get("id")): sprite
        for sprite in _active_project_sprites(project)
        if isinstance(sprite, dict) and sprite.get("applied_output_file")
    }
    entries = [_sprite_export_entry(sprite) for sprite in active_sprites.values()]
    animation_clips = _review_animation_clips(project, active_sprites)
    exports_dir = output_root / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    import_settings = {
        "texture_type": "sprite",
        "sprite_mode": "multiple",
        "filter_mode": "point",
        "compression": "none",
        "alpha_is_transparency": True,
    }

    if "unity" in engines:
        with (exports_dir / "unity_sprites.json").open("w", encoding="utf-8") as handle:
            json.dump({"engine": "unity", "import_settings": import_settings, "sprites": entries, "animation_clips": animation_clips}, handle, indent=2)
        written.append("unity")

    if "godot" in engines:
        godot_entries = []
        for entry in entries:
            godot_entry = dict(entry)
            godot_entry["pivot_offset"] = {
                "x": round((float(entry["pivot"]["x"]) - 0.5) * float(entry["size"]["width"]), 4),
                "y": round((float(entry["pivot"]["y"]) - 0.5) * float(entry["size"]["height"]), 4),
            }
            godot_entries.append(godot_entry)
        with (exports_dir / "godot_sprites.json").open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "engine": "godot",
                    "import_settings": {"filter": False, "repeat": False, "mipmaps": False},
                    "sprites": godot_entries,
                    "animations": _godot_animation_clips(animation_clips),
                },
                handle,
                indent=2,
            )
        written.append("godot")

    if "unreal" in engines:
        unreal_entries = []
        for entry in entries:
            unreal_entry = dict(entry)
            unreal_entry["pivot"] = {"x": entry["pivot"]["x"], "y": round(1.0 - float(entry["pivot"]["y"]), 4), "method": entry["pivot"]["method"]}
            unreal_entries.append(unreal_entry)
        with (exports_dir / "unreal_sprites.json").open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "engine": "unreal",
                    "import_settings": {"texture_group": "2D Pixels", "compression": "UserInterface2D", "filter": "Nearest"},
                    "sprites": unreal_entries,
                    "flipbooks": _unreal_flipbooks(animation_clips),
                },
                handle,
                indent=2,
            )
        written.append("unreal")
    return written


def render_project_outputs(project: dict[str, Any], project_path: Path, out_dir: Path | None = None) -> dict[str, Any]:
    output_root = out_dir or (project_path.parent / "applied_project")
    output_root.mkdir(parents=True, exist_ok=True)
    _clear_generated_child(output_root, "sprites")
    _clear_generated_child(output_root, "exports")
    sprites_root = output_root / "sprites"
    manifest_dir = output_root / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    rendered = 0
    errors: list[dict[str, str]] = []
    used_output_paths: set[Path] = set()
    for sprite in _active_project_sprites(project):
        try:
            bbox = _normalize_bbox(sprite.get("bbox", {}))
            source_path = _resolve_project_path(str(sprite["source_file"]), project_path)
            category = safe_file_name(str(sprite.get("category", "sprites")))
            display_name = safe_file_name(str(sprite.get("display_name") or sprite.get("id") or "sprite"))
            output_path = _unique_output_path(sprites_root / category / f"{display_name}.png", used_output_paths)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source_path) as source_image:
                image = source_image.convert("RGBA")
                bbox = _clamp_bbox_to_image(sprite, bbox, image.size)
                crop = image.crop((bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]))
                crop.save(output_path)
            sprite["applied_output_file"] = str(output_path)
            rendered += 1
        except Exception as exc:
            errors.append({"sprite_id": str(sprite.get("id", "")), "error": f"{type(exc).__name__}: {exc}"})

    skipped_rejected = len([sprite for sprite in _sprites(project) if isinstance(sprite, dict) and sprite.get("review_status") == "rejected"])
    written_exports = _write_project_engine_exports(project, output_root)
    summary = {"rendered": rendered, "skipped_rejected": skipped_rejected, "errors": errors, "exports": written_exports, "output_dir": str(output_root)}
    with (manifest_dir / "project_sprites.json").open("w", encoding="utf-8") as handle:
        json.dump(project.get("sprites", []), handle, indent=2)
    with (manifest_dir / "review_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    save_project(project, project_path)
    return summary
