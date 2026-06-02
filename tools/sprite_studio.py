from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.sprite_project import render_project_outputs, safe_file_name


SEVERE_FLAGS = {
    "bbox_clamped",
    "touches_edge",
    "tiny_component",
    "odd_aspect",
    "large_region",
    "manual_split",
    "manual_merge",
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sprites(project: dict[str, Any]) -> list[dict[str, Any]]:
    sprites = project.get("sprites", [])
    if not isinstance(sprites, list):
        raise ValueError("Project file must contain a sprites list.")
    return [sprite for sprite in sprites if isinstance(sprite, dict)]


def _active_sprites(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [sprite for sprite in _sprites(project) if str(sprite.get("review_status", "needs_review")) != "rejected"]


def _flags(sprite: dict[str, Any]) -> list[str]:
    flags = sprite.get("review_flags", [])
    if not isinstance(flags, list):
        return []
    return [str(flag) for flag in flags]


def _append_flag(sprite: dict[str, Any], flag: str) -> None:
    flags = _flags(sprite)
    if flag not in flags:
        flags.append(flag)
    sprite["review_flags"] = flags


def _bbox(sprite: dict[str, Any]) -> dict[str, int]:
    raw = sprite.get("bbox", {})
    if not isinstance(raw, dict):
        return {"x": 0, "y": 0, "width": 1, "height": 1}
    return {
        "x": int(raw.get("x", 0)),
        "y": int(raw.get("y", 0)),
        "width": max(1, int(raw.get("width", 1))),
        "height": max(1, int(raw.get("height", 1))),
    }


def _source_sheet(sprite: dict[str, Any]) -> str:
    explicit = str(sprite.get("source_sheet", "")).strip()
    if explicit:
        return safe_file_name(explicit)
    source_file = str(sprite.get("source_file", "")).strip()
    if not source_file:
        return "sheet"
    stem = Path(source_file).stem or "sheet"
    return safe_file_name(stem)


def _display_name(sprite: dict[str, Any]) -> str:
    return str(sprite.get("display_name") or sprite.get("id") or "sprite")


def _duplicate_display_names(sprites: list[dict[str, Any]]) -> set[str]:
    counts = Counter(safe_file_name(_display_name(sprite)) for sprite in sprites)
    return {name for name, count in counts.items() if name and count > 1}


def _confidence(sprite: dict[str, Any]) -> float:
    try:
        return float(sprite.get("confidence", 1.0))
    except (TypeError, ValueError):
        return 0.0


def _has_vision_label(sprite: dict[str, Any]) -> bool:
    label = sprite.get("vision_label")
    return isinstance(label, dict) and bool(str(label.get("display_name", "")).strip())


def _vision_counts(active_sprites: list[dict[str, Any]]) -> dict[str, int]:
    labeled = sum(1 for sprite in active_sprites if _has_vision_label(sprite))
    missing = len(active_sprites) - labeled
    low_confidence = sum(1 for sprite in active_sprites if "vision_low_confidence" in _flags(sprite))
    return {"labeled": labeled, "missing": missing, "low_confidence": low_confidence}


def _status(sprite: dict[str, Any]) -> str:
    return str(sprite.get("review_status", "needs_review"))


def _sprite_id(sprite: dict[str, Any]) -> str:
    return str(sprite.get("id") or _display_name(sprite))


def _asset_entry(sprite: dict[str, Any]) -> dict[str, Any]:
    bbox = _bbox(sprite)
    return {
        "sprite_id": _sprite_id(sprite),
        "display_name": _display_name(sprite),
        "category": str(sprite.get("category", "sprites")),
        "kind": str(sprite.get("kind", "sprite")),
        "status": _status(sprite),
        "flags": _flags(sprite),
        "confidence": _confidence(sprite),
        "source_sheet": _source_sheet(sprite),
        "bbox": bbox,
        "size": {"width": bbox["width"], "height": bbox["height"]},
    }


def build_review_dashboard(project: dict[str, Any], confidence_threshold: float = 0.85) -> dict[str, Any]:
    sprites = _sprites(project)
    active = _active_sprites(project)
    duplicate_names = _duplicate_display_names(active)
    counts = Counter(_status(sprite) for sprite in sprites)
    flag_counts = Counter(flag for sprite in sprites for flag in _flags(sprite))
    confidence_buckets = Counter(
        "high" if _confidence(sprite) >= confidence_threshold else "low" if _confidence(sprite) < 0.5 else "medium"
        for sprite in active
    )

    queue: list[dict[str, Any]] = []
    for sprite in active:
        reasons: list[str] = []
        priority = 0
        status = _status(sprite)
        confidence = _confidence(sprite)
        flags = _flags(sprite)
        display_name = safe_file_name(_display_name(sprite))

        if status == "needs_review":
            reasons.append("needs_review")
            priority += 100
        if confidence < confidence_threshold:
            reasons.append("low_confidence")
            priority += int((confidence_threshold - confidence) * 50) + 20
        severe = [flag for flag in flags if flag in SEVERE_FLAGS]
        if severe:
            reasons.extend(severe)
            priority += 12 * len(severe)
        if not _has_vision_label(sprite):
            reasons.append("missing_vision_labels")
            priority += 25
        if display_name in duplicate_names:
            reasons.append("duplicate_display_name")
            priority += 15

        if reasons:
            entry = _asset_entry(sprite)
            entry["priority"] = priority
            entry["reasons"] = reasons
            queue.append(entry)

    queue.sort(key=lambda item: (-int(item["priority"]), str(item["display_name"]).lower()))
    return {
        "generated_at": _utc_timestamp(),
        "total_sprites": len(sprites),
        "active_sprites": len(active),
        "counts": dict(counts),
        "flag_counts": dict(flag_counts),
        "confidence_buckets": dict(confidence_buckets),
        "vision": _vision_counts(active),
        "duplicate_display_names": sorted(duplicate_names),
        "queue": queue,
    }


def _format_taxonomy_name(sprite: dict[str, Any], pattern: str, index: int) -> str:
    bbox = _bbox(sprite)
    values = {
        "id": _sprite_id(sprite),
        "display_name": _display_name(sprite),
        "category": safe_file_name(str(sprite.get("category", "sprites"))),
        "source_sheet": _source_sheet(sprite),
        "sequence": safe_file_name(str(sprite.get("sequence", ""))) or "sprite",
        "frame": int(sprite.get("frame", index) or index),
        "index": index,
        "kind": safe_file_name(str(sprite.get("kind", "sprite"))),
        "status": safe_file_name(_status(sprite)),
        "width": bbox["width"],
        "height": bbox["height"],
    }
    try:
        rendered = pattern.format(**values)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid taxonomy display_name_pattern: {exc}") from exc
    return safe_file_name(rendered)


def apply_taxonomy_rules(project: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = rules or {}
    pattern = str(rules.get("display_name_pattern", "{category}_{source_sheet}_{index:03d}"))
    include_rejected = bool(rules.get("include_rejected", False))
    category_map = rules.get("category_map", {})
    if not isinstance(category_map, dict):
        category_map = {}

    targets = _sprites(project) if include_rejected else _active_sprites(project)
    used_names: Counter[str] = Counter()
    changes: list[dict[str, str]] = []

    for index, sprite in enumerate(targets, start=1):
        old_name = _display_name(sprite)
        old_category = str(sprite.get("category", "sprites"))
        if old_category in category_map:
            sprite["category"] = str(category_map[old_category])

        base_name = _format_taxonomy_name(sprite, pattern, index)
        used_names[base_name] += 1
        new_name = base_name if used_names[base_name] == 1 else f"{base_name}_{used_names[base_name]:02d}"
        sprite["display_name"] = new_name
        _append_flag(sprite, "auto_named")
        if old_name != new_name or old_category != str(sprite.get("category", "sprites")):
            changes.append({"sprite_id": _sprite_id(sprite), "before": old_name, "after": new_name})

    history = project.setdefault("history", [])
    if isinstance(history, list):
        history.append(
            {
                "action": "apply_taxonomy_rules",
                "timestamp": _utc_timestamp(),
                "rules": copy.deepcopy(rules),
                "changes": copy.deepcopy(changes),
            }
        )
        project["redo_stack"] = []

    return {"renamed": len(changes), "pattern": pattern, "changes": changes}


def diff_projects(old_project: dict[str, Any], new_project: dict[str, Any]) -> dict[str, Any]:
    old_by_id = {_sprite_id(sprite): sprite for sprite in _sprites(old_project)}
    new_by_id = {_sprite_id(sprite): sprite for sprite in _sprites(new_project)}
    added_ids = sorted(set(new_by_id) - set(old_by_id))
    removed_ids = sorted(set(old_by_id) - set(new_by_id))
    comparable_fields = ["bbox", "display_name", "category", "kind", "source_file", "sequence", "frame", "review_status", "review_flags", "confidence"]

    changed: list[dict[str, Any]] = []
    for sprite_id in sorted(set(old_by_id) & set(new_by_id)):
        old_sprite = old_by_id[sprite_id]
        new_sprite = new_by_id[sprite_id]
        changed_fields = [field for field in comparable_fields if old_sprite.get(field) != new_sprite.get(field)]
        if changed_fields:
            changed.append(
                {
                    "sprite_id": sprite_id,
                    "changed_fields": changed_fields,
                    "before": {field: copy.deepcopy(old_sprite.get(field)) for field in changed_fields},
                    "after": {field: copy.deepcopy(new_sprite.get(field)) for field in changed_fields},
                }
            )

    return {
        "added": [_asset_entry(new_by_id[sprite_id]) for sprite_id in added_ids],
        "removed": [_asset_entry(old_by_id[sprite_id]) for sprite_id in removed_ids],
        "changed": changed,
        "summary": {"added": len(added_ids), "removed": len(removed_ids), "changed": len(changed)},
    }


def _profile_for_sprite(sprite: dict[str, Any]) -> dict[str, Any]:
    bbox = _bbox(sprite)
    category = str(sprite.get("category", "")).lower()
    kind = str(sprite.get("kind", "")).lower()
    sequence = str(sprite.get("sequence", "")).lower()

    if any(token in category for token in ("floor", "wall", "tile")):
        shape = "box"
        anchor_preset = "center"
    elif any(token in category for token in ("shelf", "shelv", "rack", "counter", "door")):
        shape = "box"
        anchor_preset = "bottom_center"
    elif kind == "animation_frame" or sequence:
        shape = "tight_rect"
        anchor_preset = "bottom_center"
    else:
        shape = "tight_rect"
        anchor_preset = "center"

    pivot = sprite.get("pivot", {})
    if not isinstance(pivot, dict):
        pivot = {}
    pivot_x = float(pivot.get("x", 0.5))
    pivot_y = float(pivot.get("y", 1.0 if anchor_preset == "bottom_center" else 0.5))

    return {
        "collision": {
            "shape": shape,
            "x": 0,
            "y": 0,
            "width": bbox["width"],
            "height": bbox["height"],
        },
        "anchor": {
            "preset": anchor_preset,
            "x": pivot_x,
            "y": pivot_y,
        },
        "pivot_profile": {
            "preset": anchor_preset,
            "x": pivot_x,
            "y": pivot_y,
            "method": str(pivot.get("method", "profiled")),
        },
    }


def generate_collision_profiles(project: dict[str, Any], profile_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    category_overrides = (profile_rules or {}).get("categories", {}) if isinstance(profile_rules, dict) else {}
    if not isinstance(category_overrides, dict):
        category_overrides = {}

    for sprite in _active_sprites(project):
        profile = _profile_for_sprite(sprite)
        override = category_overrides.get(str(sprite.get("category", "")), {})
        if isinstance(override, dict):
            profile["collision"].update(override.get("collision", {}) if isinstance(override.get("collision", {}), dict) else {})
            profile["anchor"].update(override.get("anchor", {}) if isinstance(override.get("anchor", {}), dict) else {})
            profile["pivot_profile"].update(override.get("pivot_profile", {}) if isinstance(override.get("pivot_profile", {}), dict) else {})
        sprite["collision"] = copy.deepcopy(profile["collision"])
        sprite["anchor"] = copy.deepcopy(profile["anchor"])
        sprite["pivot_profile"] = copy.deepcopy(profile["pivot_profile"])
        profiles[_sprite_id(sprite)] = profile
    return profiles


def _engine_list(project: dict[str, Any], engines: list[str] | None = None) -> list[str]:
    if engines is None:
        settings = project.get("settings", {})
        raw = settings.get("engine_exports", ["unity", "godot", "unreal"]) if isinstance(settings, dict) else []
        if isinstance(raw, str):
            engines = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(raw, list):
            engines = [str(part).strip() for part in raw if str(part).strip()]
        else:
            engines = []
    normalized = [engine.lower() for engine in engines]
    if "all" in normalized:
        normalized = ["unity", "godot", "unreal"]
    return [engine for engine in ["unity", "godot", "unreal"] if engine in normalized]


def _import_sprite_entry(sprite: dict[str, Any]) -> dict[str, Any]:
    entry = _asset_entry(sprite)
    entry["name"] = entry["display_name"]
    entry["source_file"] = str(sprite.get("applied_output_file") or sprite.get("output_file") or sprite.get("source_file") or "")
    entry["source_rect"] = entry.pop("bbox")
    entry["pivot"] = copy.deepcopy(sprite.get("pivot_profile") or sprite.get("pivot") or {"x": 0.5, "y": 0.5, "method": "manual"})
    entry["collision"] = copy.deepcopy(sprite.get("collision") or _profile_for_sprite(sprite)["collision"])
    entry["anchor"] = copy.deepcopy(sprite.get("anchor") or _profile_for_sprite(sprite)["anchor"])
    entry["sequence"] = sprite.get("sequence")
    entry["frame"] = sprite.get("frame")
    return entry


def _active_animation_clips(project: dict[str, Any], active_ids: set[str]) -> list[dict[str, Any]]:
    clips = project.get("animation_clips", [])
    if not isinstance(clips, list):
        return []
    active_clips: list[dict[str, Any]] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        frames = []
        for frame in clip.get("frames", []):
            if isinstance(frame, dict) and str(frame.get("sprite", "")) in active_ids:
                frames.append(copy.deepcopy(frame))
        if frames:
            next_clip = copy.deepcopy(clip)
            next_clip["frames"] = frames
            next_clip["frame_count"] = len(frames)
            active_clips.append(next_clip)
    return active_clips


def build_engine_import_plans(project: dict[str, Any], engines: list[str] | None = None) -> dict[str, Any]:
    active = _active_sprites(project)
    if active and not active[0].get("collision"):
        generate_collision_profiles(project)
    sprites = [_import_sprite_entry(sprite) for sprite in active]
    clips = _active_animation_clips(project, {_sprite_id(sprite) for sprite in active})
    plans: dict[str, Any] = {}

    for engine in _engine_list(project, engines):
        if engine == "unity":
            plans["unity"] = {
                "engine": "unity",
                "unity_importer_settings": {
                    "texture_type": "Sprite",
                    "sprite_mode": "Multiple",
                    "filter_mode": "Point",
                    "compression": "None",
                    "alpha_is_transparency": True,
                    "pixels_per_unit": 100,
                },
                "sprites": sprites,
                "animation_clips": clips,
            }
        elif engine == "godot":
            plans["godot"] = {
                "engine": "godot",
                "texture_import": {"filter": False, "repeat": False, "mipmaps": False, "compress_mode": "lossless"},
                "sprites": [
                    {
                        **sprite,
                        "pivot_offset": {
                            "x": round((float(sprite["pivot"].get("x", 0.5)) - 0.5) * float(sprite["size"]["width"]), 4),
                            "y": round((float(sprite["pivot"].get("y", 0.5)) - 0.5) * float(sprite["size"]["height"]), 4),
                        },
                    }
                    for sprite in sprites
                ],
                "animations": clips,
            }
        elif engine == "unreal":
            plans["unreal"] = {
                "engine": "unreal",
                "import_pipeline": "Paper2D Sprite and Flipbook import",
                "texture_settings": {"compression": "UserInterface2D", "texture_group": "2D Pixels", "filter": "Nearest"},
                "sprites": [
                    {
                        **sprite,
                        "pivot": {
                            **sprite["pivot"],
                            "y": round(1.0 - float(sprite["pivot"].get("y", 0.5)), 4),
                        },
                    }
                    for sprite in sprites
                ],
                "flipbooks": clips,
            }
    return plans


def build_atlas_upgrade_plan(
    project: dict[str, Any],
    max_size: int | None = None,
    extrusion_pixels: int = 1,
    power_of_two: bool = True,
) -> dict[str, Any]:
    settings = project.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    atlas_size = int(max_size or settings.get("atlas_size", 2048))
    atlas_padding = int(settings.get("atlas_padding", 2))
    groups: dict[str, Any] = {}

    for sprite in _active_sprites(project):
        category_key = f"category:{safe_file_name(str(sprite.get('category', 'sprites')))}"
        category_group = groups.setdefault(category_key, {"strategy": "category", "keep_together": False, "sprites": []})
        category_group["sprites"].append(_sprite_id(sprite))

        sequence = str(sprite.get("sequence", "")).strip()
        if sequence:
            sequence_key = f"sequence:{safe_file_name(sequence)}"
            sequence_group = groups.setdefault(sequence_key, {"strategy": "animation_sequence", "keep_together": True, "sprites": []})
            sequence_group["sprites"].append(_sprite_id(sprite))

    return {
        "settings": {
            "max_size": atlas_size,
            "padding": atlas_padding,
            "extrusion_pixels": int(extrusion_pixels),
            "power_of_two": bool(power_of_two),
            "allow_rotation": bool(settings.get("atlas_allow_rotation", False)),
        },
        "policy": {
            "pack_order": "animation_sequences_first",
            "bleed_protection": "extrude_edge_pixels",
            "stable_group_names": True,
        },
        "groups": groups,
    }


def batch_health_score(project: dict[str, Any], confidence_threshold: float = 0.85) -> dict[str, Any]:
    sprites = _sprites(project)
    active = _active_sprites(project)
    counts = Counter(_status(sprite) for sprite in sprites)
    flag_counts = Counter(flag for sprite in sprites for flag in _flags(sprite))
    duplicate_names = _duplicate_display_names(active)
    low_confidence = [sprite for sprite in active if _confidence(sprite) < confidence_threshold]
    errors = project.get("errors", [])
    error_count = len(errors) if isinstance(errors, list) else 0
    vision = _vision_counts(active)

    blockers: list[str] = []
    warnings: list[str] = []
    if counts.get("needs_review", 0):
        blockers.append("needs_review_sprites")
    if error_count:
        blockers.append("processing_errors")
    if vision["missing"]:
        blockers.append("missing_vision_labels")
    if duplicate_names:
        warnings.append("duplicate_display_names")
    if counts.get("rejected", 0):
        warnings.append("rejected_sprites")
    if low_confidence:
        warnings.append("low_confidence_sprites")

    severe_flag_count = sum(count for flag, count in flag_counts.items() if flag in SEVERE_FLAGS)
    score = 100
    score -= counts.get("needs_review", 0) * 12
    score -= counts.get("rejected", 0) * 4
    score -= len(duplicate_names) * 8
    score -= len(low_confidence) * 7
    score -= vision["missing"] * 5
    score -= severe_flag_count * 3
    score -= error_count * 20
    score = max(0, min(100, score))
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 65 else "D" if score >= 50 else "F"

    return {
        "score": score,
        "grade": grade,
        "counts": dict(counts),
        "ready_count": counts.get("approved", 0),
        "review_count": counts.get("needs_review", 0),
        "rejected_count": counts.get("rejected", 0),
        "flag_counts": dict(flag_counts),
        "vision": vision,
        "duplicate_display_names": sorted(duplicate_names),
        "blockers": blockers,
        "warnings": warnings,
    }


def train_preset_from_project(project: dict[str, Any]) -> dict[str, Any]:
    settings = project.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    active = _active_sprites(project)
    category_counts = Counter(str(sprite.get("category", "sprites")) for sprite in active)
    common_flags = Counter(flag for sprite in _sprites(project) for flag in _flags(sprite))
    source_sheets = sorted({_source_sheet(sprite) for sprite in _sprites(project)})

    return {
        "name": "trained_spritecut_preset",
        "mode": str(settings.get("mode", "auto")),
        "detection": {
            "min_sprite_pixels": int(settings.get("min_sprite_pixels", 24)),
            "crop_padding": int(settings.get("crop_padding", 1)),
            "confidence_threshold": 0.85,
        },
        "atlas": {
            "enabled": bool(settings.get("pack_atlases", True)),
            "size": int(settings.get("atlas_size", 2048)),
            "padding": int(settings.get("atlas_padding", 2)),
            "allow_rotation": bool(settings.get("atlas_allow_rotation", False)),
        },
        "engine_exports": _engine_list(project),
        "taxonomy": {
            "display_name_pattern": "{category}_{source_sheet}_{index:03d}",
            "category_counts": dict(category_counts),
            "source_sheets": source_sheets,
        },
        "review_learning": {
            "common_flags": sorted(common_flags),
            "needs_review_rate": round(float(Counter(_status(sprite) for sprite in _sprites(project)).get("needs_review", 0)) / max(1, len(_sprites(project))), 4),
            "most_common_flags": common_flags.most_common(8),
        },
    }


def asset_browser_index(project: dict[str, Any]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for sprite in _sprites(project):
        entry = _asset_entry(sprite)
        text_parts = [
            entry["sprite_id"],
            entry["display_name"],
            entry["category"],
            entry["kind"],
            entry["status"],
            entry["source_sheet"],
            str(sprite.get("source_file", "")),
            " ".join(entry["flags"]),
        ]
        entry["search_text"] = " ".join(str(part).lower() for part in text_parts if str(part).strip())
        index.append(entry)
    return index


def search_assets(
    index: list[dict[str, Any]],
    query: str = "",
    *,
    status: str | None = None,
    category: str | None = None,
    flag: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    terms = [term.lower() for term in query.split() if term.strip()]
    results: list[dict[str, Any]] = []
    for item in index:
        if status is not None and str(item.get("status", "")) != status:
            continue
        if category is not None and str(item.get("category", "")) != category:
            continue
        if kind is not None and str(item.get("kind", "")) != kind:
            continue
        if flag is not None and flag not in item.get("flags", []):
            continue
        search_text = str(item.get("search_text", "")).lower()
        if terms and not all(term in search_text for term in terms):
            continue
        results.append(item)
    return results


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_import_plans(output_dir: Path, plans: dict[str, Any]) -> list[str]:
    names = {
        "unity": "unity_importer_settings.json",
        "godot": "godot_import_plan.json",
        "unreal": "unreal_paper2d_import_plan.json",
    }
    written: list[str] = []
    for engine, plan in plans.items():
        file_name = names.get(engine, f"{safe_file_name(engine)}_import_plan.json")
        _write_json(output_dir / "import_plans" / file_name, plan)
        written.append(engine)
    return written


def review_and_apply_project(
    project: dict[str, Any],
    project_path: Path,
    *,
    output_dir: Path | None = None,
    naming_rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if naming_rules is not None:
        naming = apply_taxonomy_rules(project, naming_rules)
    else:
        naming = {"renamed": 0, "pattern": None, "changes": []}

    collision_profiles = generate_collision_profiles(project)
    apply_summary = render_project_outputs(project, project_path, out_dir=output_dir)
    resolved_output = Path(apply_summary["output_dir"])

    dashboard = build_review_dashboard(project)
    health = batch_health_score(project)
    atlas_plan = build_atlas_upgrade_plan(project)
    preset = train_preset_from_project(project)
    browser_index = asset_browser_index(project)
    import_plans = build_engine_import_plans(project)

    _write_json(resolved_output / "studio" / "review_dashboard.json", dashboard)
    _write_json(resolved_output / "studio" / "batch_health.json", health)
    _write_json(resolved_output / "studio" / "atlas_upgrade_plan.json", atlas_plan)
    _write_json(resolved_output / "studio" / "trained_preset.json", preset)
    _write_json(resolved_output / "studio" / "asset_browser_index.json", browser_index)
    written_import_plans = _write_import_plans(resolved_output, import_plans)

    return {
        "naming": naming,
        "collision_profiles": collision_profiles,
        "apply": apply_summary,
        "dashboard": dashboard,
        "health": health,
        "atlas_plan": atlas_plan,
        "preset": preset,
        "asset_browser_index": browser_index,
        "import_plans": written_import_plans,
        "output_dir": str(resolved_output),
    }
