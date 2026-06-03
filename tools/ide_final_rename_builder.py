"""Build final rename manifest using existing vision data (no API calls)."""
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
    "sprite",
    "sprites",
    "image",
    "preview",
    "spritesheet",
    "sprite_sheet",
    "unknown",
    "unknown_sprite",
}


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _clean_category(value: Any) -> str:
    category = safe_name(str(value or "unknown"))
    return category if category in FINAL_CATEGORIES else "unknown"


def _clean_final_base(value: Any, fallback: str) -> str:
    candidate = safe_name(str(value or ""))
    return safe_name(fallback) if candidate in GENERIC_FINAL_NAMES else candidate


def _representative_file(group: dict[str, Any]) -> str:
    representative = str(group.get("vision_representative_file", "")).strip()
    if representative:
        return representative
    files = group.get("files")
    if isinstance(files, list) and files:
        return str(files[len(files) // 2])
    raise ValueError(f"Learning group has no representative file: {group.get('group', '')}")


def _frame_number(path: str, index: int) -> int:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path)
    return int(match.group(1)) if match else index + 1


def _planned_file_renames(group: dict[str, Any], final_label: dict[str, Any], used_paths: set[str]) -> list[dict[str, Any]]:
    files = group.get("files")
    if not isinstance(files, list):
        return []
    planned: list[dict[str, Any]] = []
    final_base = str(final_label["final_semantic_base"])
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


def build_manifest(index_path: Path, output_path: Path) -> dict[str, Any]:
    index = _load_json(index_path)
    source_root = Path(str(index.get("source_root", "")))
    groups = index.get("groups")
    if not source_root.exists():
        raise FileNotFoundError(f"Missing source_root from learning index: {source_root}")
    if not isinstance(groups, list):
        raise ValueError("Learning index must contain a groups list.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": 1,
        "kind": "sprite_source_final_rename_manifest",
        "source_root": str(source_root),
        "source_index": str(index_path),
        "provider": "ide",
        "groups": [],
        "file_renames": [],
    }
    completed_groups: set[str] = set()
    used_paths: set[str] = set()
    errors: list[dict[str, str]] = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group", ""))
        if group_name in completed_groups:
            continue
        try:
            # Use existing vision data as the "final name"
            vision_label = group.get("vision_label") if isinstance(group.get("vision_label"), dict) else {}
            fallback = str(group.get("semantic_base") or group.get("vision_semantic_base") or "sprite")
            vision_base = vision_label.get("display_name") or group.get("vision_semantic_base") or fallback
            confidence = _confidence(vision_label.get("confidence", 0))

            final_base = _clean_final_base(vision_base, fallback)
            if confidence < 0.45:
                final_base = safe_name(fallback)

            category = _clean_category(vision_label.get("category"))
            # Boost animation category for animation_sequence kinds if vision says otherwise
            if str(group.get("kind")) == "animation_sequence" and category not in {"animation", "effects_and_particles"}:
                # Keep vision category unless it's clearly wrong for animations
                pass

            pattern = f"{final_base}_frame_{{frame:03d}}" if str(group.get("kind")) == "animation_sequence" else final_base
            final_label = {
                "final_semantic_base": final_base,
                "final_rename_pattern": pattern,
                "category": category,
                "rename_confidence": confidence,
                "rationale": f"Derived from existing vision_label ({vision_label.get('description', '')[:80]}...)",
                "provider": "ide",
            }

            file_renames = _planned_file_renames(group, final_label, used_paths)
            entry = {
                "group": group_name,
                "relative_dir": group.get("relative_dir", ""),
                "kind": group.get("kind", ""),
                "representative_file": _representative_file(group),
                "path_semantic_base": group.get("semantic_base", ""),
                "gemini_semantic_base": group.get("vision_semantic_base", ""),
                **final_label,
                "file_count": len(file_renames),
            }
            manifest["groups"].append(entry)
            manifest["file_renames"].extend(file_renames)
            completed_groups.add(group_name)
        except Exception as exc:
            errors.append({"group": group_name, "error": str(exc)})

    finalized = len(manifest["groups"])
    manifest["summary"] = {
        "total_groups": len(groups),
        "finalized_groups": finalized,
        "missing_groups": max(0, len(groups) - finalized),
        "file_renames": len(manifest["file_renames"]),
        "errors": errors,
    }
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest["summary"]


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
    b = sub.add_parser("build")
    b.add_argument("index", type=Path)
    b.add_argument("--output", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.action == "build":
        result = build_manifest(args.index, args.output)
    else:
        result = verify_manifest(args.manifest)
    print(json.dumps(result, indent=2))
