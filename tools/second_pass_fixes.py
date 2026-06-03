"""Second-pass targeted corrections based on image inspection."""
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


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


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


# Targeted corrections: group_path -> (new_name, new_category)
CORRECTIONS = {
    "Legacy Collection/Assets/Gothicvania/Characters/Terrible Knight/Projectiles/dagger": ("throwing_dagger", "weapons_and_projectiles"),
    "Legacy Collection/Assets/Gothicvania/Misc/Dagger/dagger": ("dagger", "weapons_and_projectiles"),
    "Legacy Collection/Assets/Gothicvania/Environments/Day-Platformer/PNG/tileset": ("day_platformer_tileset", "tiles_and_terrain"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Old Version/layers/parallax_space_stars": ("parallax_space_stars", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Characters/death/Previews/death_lamp_rise": ("death_lamp_rise", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Environments/HauntedForest/Layers/water_tileset": ("water_tileset", "tiles_and_terrain"),
    "Legacy Collection/Assets/Gothicvania/Environments/Living-Tissue-Platform-Files/PNG/layers/tileset": ("living_tissue_tileset", "tiles_and_terrain"),
    "Legacy Collection/Assets/Gothicvania/Environments/country-platform-files/layers/country_platform_tileset": ("country_platform_tileset", "tiles_and_terrain"),
    "Legacy Collection/Assets/Gothicvania/Environments/grunge-tileset-files-web/grunge_tileset": ("grunge_tileset", "tiles_and_terrain"),
    "Legacy Collection/Assets/Gothicvania/Environments/night-town-background-files/layers/night_town_background_town": ("night_town_background", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Environments/treasure-hoard-platform/PNG/background": ("treasure_hoard_background", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Environments/treasure-hoard-platform/PNG/treasure_hoard_background_preview": ("treasure_hoard_background_preview", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Misc/fantasy weapons set/PNG/10": ("spear", "weapons_and_projectiles"),
    # Additional fixes from suspicious list
    "Legacy Collection/Assets/Gothicvania/Environments/country-platform-files/country_platform_preview": ("country_platform_preview", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Characters/Nightmare-Files/Sprites/Run/run": ("nightmare_run", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Characters/Ogre/Sprites/Attack/ogre_attack": ("ogre_attack", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Characters/Ogre/Sprites/idle-unarmed/ogre_idle_unarmed": ("ogre_idle_unarmed", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Characters/meerman/Sprites/meerman": ("meerman", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Characters/meerman/meerman": ("meerman", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Characters/meerman/preview": ("meerman_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Characters/mutant-toad/Sprites/jump/mutant_toad_jump": ("mutant_toad_jump", "characters_and_creatures"),
    "Legacy Collection/Assets/Gothicvania/Environments/lava-background/PNG/lava_tile": ("lava_tile", "tiles_and_terrain"),
    "Legacy Collection/Assets/Gothicvania/Environments/treasure-hoard-platform/PNG/tileset": ("treasure_hoard_tileset", "tiles_and_terrain"),
    "Legacy Collection/Assets/Gothicvania/Misc/fantasy weapons set/PNG/1": ("scimitar", "weapons_and_projectiles"),
    "Legacy Collection/Assets/Gothicvania/Misc/fantasy weapons set/PNG/4": ("katana", "weapons_and_projectiles"),
    "Legacy Collection/Assets/Gothicvania/Misc/fantasy weapons set/PNG/5": ("sword", "weapons_and_projectiles"),
    "Legacy Collection/Assets/Gothicvania/Misc/fantasy weapons set/PNG/6": ("scythe", "weapons_and_projectiles"),
    "Legacy Collection/Assets/Gothicvania/Misc/fantasy weapons set/PNG/9": ("lightsaber", "weapons_and_projectiles"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Living Pack 1/Ogre/ogre_preview": ("ogre_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Living Pack 1/Ogre/ogre_sheet": ("ogre_sheet", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Living Pack 1/Slime/slime_preview": ("slime_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Mechanic/drone": ("drone", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Mechanic/observer": ("observer", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Mechanic/steel_eagle": ("steel_eagle", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Monster Pack Files/Previews/jumping_demon": ("jumping_demon_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Monster Pack Files/Previews/vampire": ("vampire_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Battle Sprites/Monster Pack Files/static/jumping_demon": ("jumping_demon", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Top-Down-16-bit-fantasy/Characters pack 1/Blond_kid/aseprite": ("blond_kid", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Top-Down-16-bit-fantasy/Characters pack 1/Blond_kid/preview": ("blond_kid_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Top-Down-16-bit-fantasy/Characters pack 1/Guy/aseprite": ("guy", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Top-Down-16-bit-fantasy/Characters pack 1/Guy/preview": ("guy_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/Top-Down-16-bit-fantasy/Characters pack 1/PirateGirl/pirategirl": ("pirate_girl", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/top-down-dungeon-enemy-robot/Previews/robot_walk_back": ("robot_walk_back_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/top-down-dungeon-enemy-robot/Previews/robot_walk_front": ("robot_walk_front_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/TinyRPG/Characters/top-down-dungeon-enemy-robot/Previews/robot_walk_side": ("robot_walk_side_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/Previews/punch": ("cyberpunk_detective_punch", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/Previews/walk": ("cyberpunk_detective_walk", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/sprites/crouch/layer": ("cyberpunk_detective_crouch", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/sprites/shot/layer": ("cyberpunk_detective_shot", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/sprites/walk/layer": ("cyberpunk_detective_walk", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/spritesheets/draw_gun": ("cyberpunk_detective_draw_gun", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/cyberpunk-detective/spritesheets/walk": ("cyberpunk_detective_walk_sheet", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/mech-unit/spritesheet/mech_unit": ("mech_unit", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/space-marine-lite/Sprites/Die/sprites/die": ("space_marine_die", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/space-marine-lite/Sprites/Idle/idle": ("space_marine_idle", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/space-marine-lite/atlas": ("space_marine_atlas", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/spaceship-unit/Gifs Previews/ship_and_thrust": ("spaceship_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/spaceship-unit/Gifs Previews/thrust": ("spaceship_thrust_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/spaceship-unit/Sprites/Thrust/thrust": ("spaceship_thrust", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/spaceship-unit/Spritesheets/separated sprites/spaceship_unit": ("spaceship_unit", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/spaceship-unit/Spritesheets/separated sprites/thrust": ("spaceship_thrust_sprites", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/spaceship-unit/Spritesheets/spritesheets": ("spaceship_spritesheets", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/tank-unit/Preview/tank_unit": ("tank_unit_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-enemies/Previews/enemy_explosion": ("enemy_explosion_preview", "effects_and_particles"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/Previews/ship": ("top_down_ship_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/Previews/thrust/ship": ("ship_thrust_preview", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 01/0000_layer": ("top_down_ship_01", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 01/0001_layer": ("top_down_ship_01", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 01/0002_layer": ("top_down_ship_01", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 01/0003_layer": ("top_down_ship_01", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 01/0004_layer": ("top_down_ship_01", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 02/0001_layer": ("top_down_ship_02", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 02/0002_layer": ("top_down_ship_02", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 02/0003_layer": ("top_down_ship_02", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 02/0004_layer": ("top_down_ship_02", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 03/0000_layer": ("top_down_ship_03", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 03/0001_layer": ("top_down_ship_03", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 03/0002_layer": ("top_down_ship_03", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 03/0003_layer": ("top_down_ship_03", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 03/0004_layer": ("top_down_ship_03", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 04/0002_layer": ("top_down_ship_04", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 04/0003_layer": ("top_down_ship_04", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/sprites/ship 04/0004_layer": ("top_down_ship_04", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/spritesheets/red/ship": ("red_ship", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/spritesheets/thrust/ship": ("ship_thrust", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-ship/spritesheets/yellow/ship": ("yellow_ship", "characters_and_creatures"),
    # Background misclassifications
    "Legacy Collection/Assets/Gothicvania/Environments/forest-road-background/PNG/middle": ("forest_road_background", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Environments/mist-forest-background/layers/mist_forest_background_back_trees": ("mist_forest_background_trees", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Environments/mist-forest-background/layers/mist_forest_background_tree": ("mist_forest_background_tree", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Gothicvania/Environments/night-town-background-files/layers/night_town_background_far_buildings": ("night_town_background", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Blue Version/layered/asteroid": ("space_asteroid", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Blue Version/layered/blue_back": ("space_background_blue", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Blue Version/layered/blue_stars": ("blue_stars", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Blue Version/layered/prop_planet_big": ("space_planet_big", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Old Version/layers/parallax_space_backgound": ("parallax_space_background", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Old Version/layers/parallax_space_big_planet": ("parallax_space_big_planet", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Old Version/layers/parallax_space_far_planets": ("parallax_space_far_planets", "backgrounds_and_parallax"),
    "Legacy Collection/Assets/Warped/Environments/space_background_pack/Old Version/layers/parallax_space_ring_planet": ("parallax_space_ring_planet", "backgrounds_and_parallax"),
    # Misc fixes
    "Legacy Collection/Assets/Misc/Characters/sunny-bunny/Sprites/idle/0002_layer": ("sunny_bunny_idle", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/alien-walking-enemy/Sprites/walk/walk": ("alien_walk", "characters_and_creatures"),
    "Legacy Collection/Assets/Warped/Characters/top-down-shooter-enemies/sprites/enemy-01/0004": ("enemy_01", "characters_and_creatures"),
}


def apply_second_pass(manifest_path: Path, output_path: Path, index_path: Path | None = None) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    groups_data = manifest.get("groups", [])
    
    # Load learning index for file lists
    files_by_group: dict[str, list[str]] = {}
    if index_path and index_path.exists():
        index = _load_json(index_path)
        for g in index.get("groups", []):
            if isinstance(g, dict):
                files_by_group[str(g.get("group", ""))] = g.get("files", [])
    else:
        inferred = Path(str(manifest.get("source_index", "")))
        if inferred.exists():
            index = _load_json(inferred)
            for g in index.get("groups", []):
                if isinstance(g, dict):
                    files_by_group[str(g.get("group", ""))] = g.get("files", [])
    
    changes_log: list[dict[str, str]] = []
    fixed_groups: list[dict[str, Any]] = []
    
    for group in groups_data:
        if not isinstance(group, dict):
            continue
        group_name = group.get("group", "")
        
        if group_name in CORRECTIONS:
            new_name, new_cat = CORRECTIONS[group_name]
            old_name = group["final_semantic_base"]
            if old_name != new_name or group.get("category") != new_cat:
                changes_log.append({
                    "group": group_name,
                    "old": old_name,
                    "new": new_name,
                    "old_cat": group.get("category", ""),
                    "new_cat": new_cat,
                })
                group["final_semantic_base"] = new_name
                group["category"] = new_cat
                group["rename_confidence"] = 0.85
                group["rationale"] = f"Second-pass correction from '{old_name}' via image inspection."
        
        fixed_groups.append(group)
    
    # Rebuild file_renames
    used_paths: set[str] = set()
    file_renames: list[dict[str, Any]] = []
    for group in fixed_groups:
        group_name = group.get("group", "")
        group["files"] = files_by_group.get(group_name, [])
        file_renames.extend(_planned_file_renames(group, group["final_semantic_base"], used_paths))
        group.pop("files", None)
    
    manifest["groups"] = fixed_groups
    manifest["file_renames"] = file_renames
    
    summary = manifest.get("summary", {})
    summary["file_renames"] = len(file_renames)
    manifest["summary"] = summary
    
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    
    return {
        "total_groups": len(fixed_groups),
        "changes_made": len(changes_log),
        "sample_changes": changes_log[:20],
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
    a = sub.add_parser("apply")
    a.add_argument("manifest", type=Path)
    a.add_argument("--output", type=Path, required=True)
    a.add_argument("--index", type=Path, default=None)
    v = sub.add_parser("verify")
    v.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.action == "apply":
        result = apply_second_pass(args.manifest, args.output, index_path=args.index)
    else:
        result = verify_manifest(args.manifest)
    print(json.dumps(result, indent=2))
