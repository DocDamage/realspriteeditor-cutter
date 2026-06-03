from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
GENERIC_STEMS = {"frame", "frames", "sprite", "sprites", "spritesheet", "sprite_sheet", "image", "img"}

CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("ui_icons_and_fonts", "ui icon icons font fonts hud menu button cursor"),
    ("weapons_and_projectiles", "weapon weapons projectile projectiles rocket bullet arrow missile"),
    ("vegetation_and_trees", "tree trees plant plants grass bush vegetation"),
    ("characters_and_creatures", "character characters creature creatures enemy enemies hero player npc"),
    ("signs_and_labels", "sign signs label labels text billboard poster"),
    ("tiles_and_terrain", "tile tiles terrain ground platform wall floor"),
    ("backgrounds_and_parallax", "background backgrounds parallax sky clouds"),
    ("animation", "animation animations anim frame frames sprite sprites explosion explosions magic effect effects death idle run walk jump attack"),
    ("props_and_items", "item items prop props crate crates coin coins key potion gem gems"),
)


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value).strip("_") or "sprite"


def _is_metadata_path(path: Path) -> bool:
    return any(part == "__MACOSX" or part.startswith("._") for part in path.parts)


def iter_source_images(source_root: Path) -> Iterable[Path]:
    for path in source_root.rglob("*"):
        if not path.is_file() or _is_metadata_path(path):
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def _semantic_base(stem: str) -> str:
    base = re.sub(r"(?i)(?:^|[_\-\s])spritesheet$", "", stem).strip("_- ")
    base = re.sub(r"(?i)(?:^|[_\-\s])sprite[_\-\s]*sheet$", "", base).strip("_- ")
    base = re.sub(r"[_\-\s]*\d+$", "", base).strip("_- ")
    return safe_name(base or stem)


def _frame_number(stem: str) -> int | None:
    match = re.search(r"(\d+)$", stem)
    return int(match.group(1)) if match else None


def _tokens_for_path(path: Path, source_root: Path) -> list[str]:
    rel = path.relative_to(source_root)
    raw_parts = list(rel.parts[:-1]) + [path.stem]
    tokens: list[str] = []
    for part in raw_parts:
        tokens.extend(token for token in safe_name(part).split("_") if token and not token.isdigit())
    return tokens


def suggest_category(tokens: Iterable[str]) -> str:
    token_set = set(tokens)
    best_category = "props_and_items"
    best_score = 0
    for category, keywords in CATEGORY_KEYWORDS:
        score = len(token_set.intersection(keywords.split()))
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def _group_key(path: Path, source_root: Path) -> str:
    rel_parent = path.parent.relative_to(source_root)
    base = _semantic_base(path.stem)
    if base in GENERIC_STEMS or path.stem.lower() in {"spritesheet", "sprite_sheet"}:
        for parent in reversed(path.parent.relative_to(source_root).parts):
            parent_base = safe_name(parent)
            if parent_base not in GENERIC_STEMS:
                base = parent_base
                break
    return str(rel_parent / base).replace("\\", "/")


def build_source_learning_index(source_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in iter_source_images(source_root):
        groups[_group_key(path, source_root)].append(path)

    learned_groups: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for key, files in sorted(groups.items()):
        files = sorted(files)
        tokens = Counter(token for file in files for token in _tokens_for_path(file, source_root))
        first = files[0]
        semantic_base = safe_name(Path(key).name)
        category = suggest_category(tokens)
        category_counts[category] += len(files)
        frames = [_frame_number(file.stem) for file in files]
        has_frames = any(frame is not None for frame in frames) or len(files) > 1
        learned_groups.append(
            {
                "group": key,
                "relative_dir": str(first.parent.relative_to(source_root)).replace("\\", "/"),
                "semantic_base": semantic_base,
                "suggested_category": category,
                "kind": "animation_sequence" if has_frames else "single_sprite",
                "file_count": len(files),
                "frame_count": len(files) if has_frames else 0,
                "rename_pattern": f"{semantic_base}_frame_{{frame:03d}}" if has_frames else semantic_base,
                "terms": [term for term, _count in tokens.most_common(12)],
                "files": [str(file.relative_to(source_root)).replace("\\", "/") for file in files],
            }
        )

    return {
        "schema_version": 1,
        "kind": "sprite_source_learning_index",
        "source_root": str(source_root),
        "source_name": source_root.name,
        "total_images": sum(group["file_count"] for group in learned_groups),
        "group_count": len(learned_groups),
        "category_counts": dict(sorted(category_counts.items())),
        "rules": {
            "sequence_naming": "{semantic_base}_frame_{frame:03d}",
            "single_sprite_naming": "{semantic_base}",
            "category_source": "path_keyword_rules",
        },
        "groups": learned_groups,
    }


def write_source_learning_index(source_root: Path, output_path: Path) -> dict[str, Any]:
    index = build_source_learning_index(source_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {"ok": True, "output": str(output_path), "total_images": index["total_images"], "group_count": index["group_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a compact SpriteCut learning index from a source asset folder.")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = write_source_learning_index(args.source_root, args.output)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
