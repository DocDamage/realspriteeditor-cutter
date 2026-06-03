from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.sprite_source_learning import safe_name
from tools.sprite_vision_labeler import provider_from_name


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def _representative_file(group: dict[str, Any]) -> str:
    files = group.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"Learning group has no files: {group.get('group', '')}")
    middle = len(files) // 2
    return str(files[middle])


def _semantic_name_from_label(label: dict[str, Any], fallback: str) -> str:
    name = safe_name(str(label.get("display_name", "")).strip())
    return fallback if name in {"sprite", "unknown", "unknown_sprite"} else name


def enrich_source_learning_with_vision(
    index_path: Path,
    output_path: Path,
    *,
    provider_name: str = "gemini",
    model: str = "",
    checkpoint_interval: int = 25,
    limit: int = 0,
) -> dict[str, Any]:
    index = _load_json(index_path)
    source_root = Path(str(index.get("source_root", "")))
    groups = index.get("groups")
    if not source_root.exists():
        raise FileNotFoundError(f"Missing source_root from learning index: {source_root}")
    if not isinstance(groups, list):
        raise ValueError("Learning index must contain a groups list.")

    provider = provider_from_name(provider_name, model=model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = 0
    errors: list[dict[str, str]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        if limit and completed >= limit:
            break
        if isinstance(group.get("vision_label"), dict):
            completed += 1
            continue
        try:
            representative = _representative_file(group)
            image_path = source_root / representative
            sprite = {
                "id": str(group.get("group", "")),
                "display_name": str(group.get("semantic_base", "")),
                "category": str(group.get("suggested_category", "sprites")),
                "output_file": str(image_path),
            }
            label = provider.label_sprite(image_path, sprite)
            semantic_base = _semantic_name_from_label(label, str(group.get("semantic_base", "sprite")))
            group["vision_label"] = label
            group["vision_representative_file"] = representative
            group["vision_semantic_base"] = semantic_base
            if str(group.get("kind", "")) == "animation_sequence":
                group["vision_rename_pattern"] = f"{semantic_base}_frame_{{frame:03d}}"
            else:
                group["vision_rename_pattern"] = semantic_base
            completed += 1
            print(
                f"SOURCE_VISION provider={provider.name} completed={completed} "
                f"group={group.get('group', '')} semantic={semantic_base}",
                flush=True,
            )
            if checkpoint_interval > 0 and completed % checkpoint_interval == 0:
                index["vision_summary"] = _vision_summary(index, provider.name, errors)
                output_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        except Exception as exc:
            errors.append({"group": str(group.get("group", "")), "error": f"{type(exc).__name__}: {exc}"})

    index["vision_summary"] = _vision_summary(index, provider.name, errors)
    output_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {
        "ok": not errors,
        "output": str(output_path),
        "provider": provider.name,
        "groups": len(groups),
        "vision_labeled_groups": index["vision_summary"]["labeled_groups"],
        "missing_groups": index["vision_summary"]["missing_groups"],
        "errors": errors,
    }


def _vision_summary(index: dict[str, Any], provider: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    groups = index.get("groups", [])
    labeled = 0
    if isinstance(groups, list):
        labeled = sum(1 for group in groups if isinstance(group, dict) and isinstance(group.get("vision_label"), dict))
    total = len(groups) if isinstance(groups, list) else 0
    return {
        "provider": provider,
        "total_groups": total,
        "labeled_groups": labeled,
        "missing_groups": max(0, total - labeled),
        "errors": errors,
    }


def verify_source_vision(index_path: Path) -> dict[str, Any]:
    index = _load_json(index_path)
    summary = _vision_summary(index, str(index.get("vision_summary", {}).get("provider", "")), [])
    return {
        "ok": summary["missing_groups"] == 0,
        **summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Add representative vision labels to a source learning index.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    enrich = subparsers.add_parser("enrich")
    enrich.add_argument("index", type=Path)
    enrich.add_argument("--output", type=Path, required=True)
    enrich.add_argument("--provider", default="gemini")
    enrich.add_argument("--model", default="")
    enrich.add_argument("--checkpoint-interval", type=int, default=25)
    enrich.add_argument("--limit", type=int, default=0)

    verify = subparsers.add_parser("verify")
    verify.add_argument("index", type=Path)

    args = parser.parse_args()
    if args.action == "enrich":
        result = enrich_source_learning_with_vision(
            args.index,
            args.output,
            provider_name=args.provider,
            model=args.model,
            checkpoint_interval=args.checkpoint_interval,
            limit=args.limit,
        )
    else:
        result = verify_source_vision(args.index)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
