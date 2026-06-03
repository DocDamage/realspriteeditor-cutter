"""Conservative manifest name fixer: only corrects clear misidentifications and strips redundant suffixes."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    from tools.sprite_source_learning import safe_name
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from tools.sprite_source_learning import safe_name

FINAL_CATEGORIES = {
    "characters_and_creatures",
    "vegetation_and_trees",
    "tiles_and_terrain",
    "props_and_items",
    "weapons_and_projectiles",
    "ui_icons_and_fonts",
    "portraits_and_faces",
    "backgrounds_and_parallax",
    "effects_and_particles",
    "animation",
    "signs_and_labels",
    "unknown",
}

GENERIC_FINAL_NAMES = {
    "sprite", "sprites", "image", "preview", "spritesheet", "sprite_sheet",
    "unknown", "unknown_sprite",
}

# Pop-culture / trademarked names that shouldn't be used
BLOCKLIST = {
    "sephiroth", "alucard", "crisbell", "miriam", "kael", "thor", "akuma",
    "zangetsu", "astaroth", "judgement", "samus_aran", "samus", "captain_commando",
    "guntz", "stoker", "typhon", "metatran", "bombier", "garegga", "maw", "shyguy",
    "metroid_larva", "conker", "klonoa", "nutty", "chip", "mellow", "popcorn",
    "nessie", "antlion", "octorok", "gremlin", "concierge", "ettin", "malboro",
    "barghest",
}

# Names that are definite visual misidentifications
KNOWN_BAD = {
    "volcano", "magma_sprite", "blue_smiley_face_sprite", "blue_circle_sprite",
    "forest_sprite", "tree_sprite", "blue_dot", "air_effect", "loading_arc",
    "collectible_star", "pixel_coin", "dust_cloud_particle", "magic_light_fountain",
    "coin", "spark_particles", "stylized_eye_sprites", "orange_pixel_particles",
    "generic_collectible_token", "generic_particle", "pig_snout", "bubble", "bubble_sprite",
    "ui_compass_icon", "blue_pixel_gem", "water_splash_particle", "bullet_projectile",
    "ui_button_dot", "blue_energy_ball", "pink_blob_monster", "pink_skull_icon",
    "pink_magic_puff", "speech_or_sound_indicator", "ice_element_orb", "speed_boost_icon",
    "targeting_reticle", "crosshairs_icon", "simple_dot_particle", "ui_refresh_icon",
    "ui_indicator_ring", "loading_spinner_icon", "energy_projectile", "light_effects_sprite_sheet",
    "stone_resource", "snowflake_particle", "blue_magic_projectile", "energy_blast_animation",
    "elemental_swirl_animation", "magic_sprout_icon", "leaf_blower_projectile",
    "blue_gem", "ui_brackets", "light_blue_octagon_particle", "glowing_ring_outline",
    "pixel_water_swirl", "sparkle_particles", "empty_sprite", "energy_ring",
    "golden_outline_ring", "smiling_blue_blob", "golden_robot_king", "armored_robot",
    "golden_robot", "robot_enemy", "captain_commando", "golden_mech", "spectre_armor_set",
    "golden_power_armor", "drill_bot", "golden_fighter_jet", "automated_turret",
    "blue_gems", "blue_crystal", "abstract_spirit_creature", "cyan_particle_effect",
    "water_particle", "red_armored_soldier", "icicle_set", "yellow_mech_suit",
    "collectible_orb", "hopper", "mellow", "popcorn", "magic_energy_projectile",
    "blue_tear", "energy_glow_effect", "hovering_mechanical_beetle", "sci_fi_hovercraft",
    "glowing_blob_monster", "red_pudding", "small_alien_bug", "maggot", "metroid_larva",
    "mini_tank_enemy", "maw", "shyguy", "tower", "skeleton", "blueberry",
    "fireball_effect",
}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _clean_category(value: Any) -> str:
    category = safe_name(str(value or "unknown"))
    return category if category in FINAL_CATEGORIES else "unknown"


def _frame_number(path: str, index: int) -> int:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path)
    return int(match.group(1)) if match else index + 1


def _planned_file_renames(group: dict[str, Any], final_base: str, used_paths: set[str]) -> list[dict[str, Any]]:
    files = group.get("files")
    if not isinstance(files, list):
        return []
    planned: list[dict[str, Any]] = []
    is_sequence = str(group.get("kind")) == "animation_sequence"
    for index, rel_path_raw in enumerate(files):
        rel_path = str(rel_path_raw)
        old = Path(rel_path)
        suffix = old.suffix.lower()
        if is_sequence:
            stem = f"{final_base}_frame_{_frame_number(rel_path, index):03d}"
        else:
            stem = final_base
        target = str(old.with_name(stem + suffix)).replace("\\", "/")
        collision_index = 2
        unique_target = target
        while unique_target.lower() in used_paths:
            unique_target = str(old.with_name(f"{stem}_{collision_index:02d}{suffix}")).replace("\\", "/")
            collision_index += 1
        used_paths.add(unique_target.lower())
        planned.append({"source": rel_path, "target": unique_target})
    return planned


def _get_path_hint(group: dict[str, Any]) -> str:
    """Relevant path snippet for keyword matching (avoids top-level collection names)."""
    group_name = str(group.get("group", "")).lower()
    parts = group_name.split("/")
    return "/".join(parts[-4:]) if len(parts) > 4 else group_name


def _needs_fix(name: str, group: dict[str, Any]) -> bool:
    """Conservative check: only flag clearly wrong names."""
    path_hint = _get_path_hint(group)
    category = group.get("category", "unknown")
    
    if name in KNOWN_BAD or name in BLOCKLIST:
        return True
    
    # Robot in path but not in name
    if "robot" in path_hint and not any(x in name for x in ("robot", "mech", "machine", "drone", "bot", "android", "cyborg", "tank")):
        return True
    
    # Ship in path but categorized as character without ship/craft hint
    if "ship" in path_hint and category == "characters_and_creatures" and not any(x in name for x in ("ship", "craft", "vessel", "shuttle", "fighter", "drone", "mech", "robot")):
        return True
    
    # Explosion in actual asset folder name (not just parent collection)
    if "/explosion" in path_hint or "explosion-" in path_hint or "explosion_" in path_hint:
        if not any(x in name for x in ("explosion", "burst", "blast", "boom", "detonation", "effect")):
            return True
    
    # Thrust effects
    if "thrust" in path_hint and not any(x in name for x in ("thrust", "engine", "exhaust", "flame", "fire", "jet", "boost", "effect")):
        return True
    
    return False


def _smart_fallback(group: dict[str, Any]) -> tuple[str, str]:
    """Pick the best available fallback name from path/vision data."""
    # Priority 1: path semantic_base (usually the folder/file name)
    path_base = safe_name(str(group.get("semantic_base") or ""))
    
    # Priority 2: the group name itself (last path component) if semantic_base is generic
    if path_base in GENERIC_FINAL_NAMES or not path_base:
        group_name = str(group.get("group", ""))
        parts = [p for p in group_name.replace("\\", "/").split("/") if p]
        if parts:
            candidate = safe_name(parts[-1])
            # If the leaf is a generic numbered layer, use the parent folder instead
            if re.match(r"^\d+_layer$", candidate):
                if len(parts) >= 2:
                    parent = safe_name(parts[-2])
                    if parent and parent not in GENERIC_FINAL_NAMES:
                        candidate = parent
            if candidate and candidate not in GENERIC_FINAL_NAMES:
                path_base = candidate
    
    # Priority 3: vision semantic_base if still generic
    if path_base in GENERIC_FINAL_NAMES or not path_base:
        vision_base = safe_name(str(group.get("vision_semantic_base") or ""))
        if vision_base and vision_base not in GENERIC_FINAL_NAMES and vision_base not in KNOWN_BAD and vision_base not in BLOCKLIST:
            path_base = vision_base
    
    # Priority 4: derive from relative_dir if still generic
    if path_base in GENERIC_FINAL_NAMES or not path_base:
        rel_dir = str(group.get("relative_dir", ""))
        parts = [p for p in rel_dir.replace("\\", "/").split("/") if p]
        for part in reversed(parts):
            candidate = safe_name(part)
            if candidate and candidate not in GENERIC_FINAL_NAMES and candidate not in {"sprites", "spritesheets", "png", "layers", "gif", "preview", "assets", "collection", "previews", "separated sprites"}:
                path_base = candidate
                break
    
    # If still nothing, use "asset" as absolute last resort
    if not path_base or path_base in GENERIC_FINAL_NAMES:
        path_base = "asset"
    
    # Determine sensible category
    path_hint = _get_path_hint(group)
    category = group.get("suggested_category", "unknown")
    
    if "background" in path_hint or "parallax" in path_hint:
        category = "backgrounds_and_parallax"
    elif "/explosion" in path_hint or "explosion-" in path_hint or "explosion_" in path_hint or "fx" in path_hint or "effect" in path_hint:
        category = "effects_and_particles"
    elif "tileset" in path_hint or "tiles" in path_hint:
        category = "tiles_and_terrain"
    elif "weapon" in path_hint:
        category = "weapons_and_projectiles"
    elif "prop" in path_hint:
        category = "props_and_items"
    elif "ship" in path_hint or "vehicle" in path_hint:
        category = "characters_and_creatures"
    elif "character" in path_hint or "enemy" in path_hint or "boss" in path_hint:
        category = "characters_and_creatures"
    
    return path_base, _clean_category(category)


def _strip_suffix(name: str) -> str:
    """Strip redundant _sprite / _character suffixes if result stays meaningful."""
    original = name
    for suffix in ("_sprite", "_character"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    if name.endswith("_sprite_sheet"):
        name = name[:-len("_sprite_sheet")] + "_sheet"
    # Don't allow stripping to make it generic
    if name in GENERIC_FINAL_NAMES or not name:
        return original
    return name


def fix_manifest(manifest_path: Path, output_path: Path, index_path: Path | None = None) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    groups_data = manifest.get("groups", [])
    
    # Load learning index to get file lists for rebuilding renames
    files_by_group: dict[str, list[str]] = {}
    if index_path and index_path.exists():
        index = _load_json(index_path)
        for g in index.get("groups", []):
            if isinstance(g, dict):
                files_by_group[str(g.get("group", ""))] = g.get("files", [])
    else:
        # Fallback: try to infer index path from manifest
        inferred = Path(str(manifest.get("source_index", "")))
        if inferred.exists():
            index = _load_json(inferred)
            for g in index.get("groups", []):
                if isinstance(g, dict):
                    files_by_group[str(g.get("group", ""))] = g.get("files", [])
    
    fixed_groups: list[dict[str, Any]] = []
    used_paths: set[str] = set()
    changes_log: list[dict[str, str]] = []
    
    for group in groups_data:
        if not isinstance(group, dict):
            continue
        
        original_name = group["final_semantic_base"]
        category = group.get("category", "unknown")
        confidence = float(group.get("rename_confidence", 0))
        
        name = original_name
        new_category = category
        
        # Conservative fix 1: strip redundant suffixes
        stripped = _strip_suffix(name)
        if stripped != name:
            name = stripped
        
        # Conservative fix 2: only replace clearly bad names
        if _needs_fix(name, group):
            fallback_name, fallback_cat = _smart_fallback(group)
            if fallback_name != name:
                changes_log.append({
                    "group": group.get("group", ""),
                    "old": original_name,
                    "new": fallback_name,
                    "reason": "vision_misidentification"
                })
                name = fallback_name
                new_category = fallback_cat
                confidence = max(confidence, 0.6)
        elif name in BLOCKLIST:
            fallback_name, fallback_cat = _smart_fallback(group)
            if fallback_name != name:
                changes_log.append({
                    "group": group.get("group", ""),
                    "old": original_name,
                    "new": fallback_name,
                    "reason": "pop_culture_blocklist"
                })
                name = fallback_name
                new_category = fallback_cat
                confidence = max(confidence, 0.6)
        
        group["final_semantic_base"] = name
        group["category"] = new_category
        group["rename_confidence"] = round(confidence, 2)
        
        if name != original_name:
            group["rationale"] = f"Corrected from '{original_name}' via path fallback."
        
        fixed_groups.append(group)
    
    # Rebuild file_renames with collision detection using learning index file lists
    file_renames: list[dict[str, Any]] = []
    for group in fixed_groups:
        group_name = group.get("group", "")
        # Inject files from learning index so renames can be rebuilt
        group["files"] = files_by_group.get(group_name, [])
        file_renames.extend(_planned_file_renames(group, group["final_semantic_base"], used_paths))
        # Clean up injected key so output matches expected schema
        group.pop("files", None)
    
    manifest["groups"] = fixed_groups
    manifest["file_renames"] = file_renames
    manifest["provider"] = "ide_corrected"
    
    summary = manifest.get("summary", {})
    summary["file_renames"] = len(file_renames)
    manifest["summary"] = summary
    
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    return {
        "total_groups": len(fixed_groups),
        "changes_made": len(changes_log),
        "sample_changes": changes_log[:30],
    }


def verify_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("Final rename manifest is missing summary.")
    targets = [
        str(item.get("target", "")).lower()
        for item in manifest.get("file_renames", [])
        if isinstance(item, dict) and item.get("target")
    ]
    duplicates = sorted({target for target in targets if targets.count(target) > 1})
    return {
        "ok": int(summary.get("missing_groups", 1)) == 0 and not duplicates,
        **summary,
        "duplicate_targets": duplicates,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    f = sub.add_parser("fix")
    f.add_argument("manifest", type=Path)
    f.add_argument("--output", type=Path, required=True)
    f.add_argument("--index", type=Path, default=None)
    v = sub.add_parser("verify")
    v.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.action == "fix":
        result = fix_manifest(args.manifest, args.output, index_path=args.index)
    else:
        result = verify_manifest(args.manifest)
    print(json.dumps(result, indent=2))
