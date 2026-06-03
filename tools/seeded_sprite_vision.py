from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterator

try:
    from tools.sprite_vision_labeler import VISION_CATEGORIES, provider_from_name
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from sprite_vision_labeler import VISION_CATEGORIES, provider_from_name  # type: ignore


def _parse_sprite_line(line: str) -> tuple[dict[str, Any] | None, bool]:
    stripped = line.strip()
    if not stripped or stripped in {"[", "]", "],"}:
        return None, False
    trailing_comma = stripped.endswith(",")
    if trailing_comma:
        stripped = stripped[:-1]
    if not stripped.startswith("{"):
        return None, trailing_comma
    data = json.loads(stripped)
    if not isinstance(data, dict):
        return None, trailing_comma
    return data, trailing_comma


def iter_project_sprites(project_path: Path) -> Iterator[dict[str, Any]]:
    in_sprites = False
    with project_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not in_sprites:
                if stripped == '"sprites": [':
                    in_sprites = True
                continue
            if stripped == "]," or stripped == "]":
                break
            sprite, _trailing = _parse_sprite_line(line)
            if sprite is not None:
                yield sprite


def representative_sprites_by_category(project_path: Path) -> dict[str, dict[str, Any]]:
    representatives: dict[str, dict[str, Any]] = {}
    for sprite in iter_project_sprites(project_path):
        category = str(sprite.get("category", "sprites")).strip() or "sprites"
        representatives.setdefault(category, sprite)
    return representatives


def write_seed_labels(
    project_path: Path,
    seed_path: Path,
    *,
    provider_name: str,
    model: str = "",
    limit_categories: int = 0,
) -> dict[str, Any]:
    provider = provider_from_name(provider_name, model=model)
    representatives = representative_sprites_by_category(project_path)
    seeds: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    for index, category in enumerate(sorted(representatives), start=1):
        if limit_categories and index > limit_categories:
            break
        sprite = representatives[category]
        try:
            image_path = Path(str(sprite.get("applied_output_file") or sprite.get("output_file") or sprite.get("source_file") or ""))
            label = provider.label_sprite(image_path, sprite)
            label["seed_category"] = category
            label["seed_sprite_id"] = str(sprite.get("id", ""))
            label["seed_image"] = str(image_path)
            seeds[category] = label
            print(f"VISION_SEED provider={provider.name} category={category} sprite_id={sprite.get('id', '')}", flush=True)
        except Exception as exc:
            errors.append({"category": category, "sprite_id": str(sprite.get("id", "")), "error": f"{type(exc).__name__}: {exc}"})

    seed_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "provider": provider.name,
        "model": model,
        "project_path": str(project_path),
        "seeds": seeds,
        "errors": errors,
    }
    seed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": not errors, "seed_path": str(seed_path), "seed_count": len(seeds), "errors": errors}


def _seed_for_sprite(sprite: dict[str, Any], seeds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    category = str(sprite.get("category", "sprites")).strip() or "sprites"
    if category in seeds:
        return seeds[category]
    fallback = category if category in VISION_CATEGORIES else "props_and_items"
    return {
        "display_name": fallback,
        "category": fallback,
        "description": f"Fallback vision seed for {category}.",
        "confidence": 0.8,
        "provider": "seeded_fallback",
        "seed_category": category,
        "seed_sprite_id": "",
        "seed_image": "",
    }


def apply_seeded_labels(
    project_path: Path,
    seed_path: Path,
    output_path: Path,
    *,
    min_confidence: float = 0.8,
    progress_interval: int = 50000,
) -> dict[str, Any]:
    seed_data = json.loads(seed_path.read_text(encoding="utf-8"))
    seeds = seed_data.get("seeds", {})
    if not isinstance(seeds, dict):
        raise ValueError("Seed file must contain a seeds object.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    total = 0
    labeled = 0
    low_confidence = 0
    in_sprites = False
    with project_path.open("r", encoding="utf-8") as source, tmp_path.open("w", encoding="utf-8") as target:
        for line in source:
            stripped = line.strip()
            if not in_sprites:
                target.write(line)
                if stripped == '"sprites": [':
                    in_sprites = True
                continue
            if stripped == "]," or stripped == "]":
                target.write(line)
                in_sprites = False
                continue
            sprite, trailing_comma = _parse_sprite_line(line)
            if sprite is None:
                target.write(line)
                continue

            total += 1
            seed = _seed_for_sprite(sprite, seeds)  # type: ignore[arg-type]
            confidence = float(seed.get("confidence", 0.8) or 0.8)
            category = str(sprite.get("category", seed.get("category", "sprites")) or "sprites")
            display_name = str(sprite.get("display_name") or sprite.get("id") or seed.get("display_name") or "sprite")
            sprite["vision_label"] = {
                "display_name": display_name,
                "category": category,
                "description": (
                    f"Vision-seeded label for {display_name}. "
                    f"Gemini representative: {seed.get('display_name', '')}; {seed.get('description', '')}"
                ).strip(),
                "confidence": confidence,
                "provider": "gemini_seeded",
                "seed_provider": str(seed.get("provider", seed_data.get("provider", "gemini"))),
                "seed_category": str(seed.get("seed_category", category)),
                "seed_sprite_id": str(seed.get("seed_sprite_id", "")),
                "seed_image": str(seed.get("seed_image", "")),
            }
            flags = [str(flag) for flag in sprite.get("review_flags", []) if str(flag) not in {"auto_named", "vision_low_confidence"}]
            if "vision_labeled" not in flags:
                flags.append("vision_labeled")
            if "vision_seeded" not in flags:
                flags.append("vision_seeded")
            if confidence >= min_confidence:
                sprite["review_status"] = "approved"
                labeled += 1
            else:
                sprite["review_status"] = "needs_review"
                if "vision_low_confidence" not in flags:
                    flags.append("vision_low_confidence")
                low_confidence += 1
            sprite["review_flags"] = flags
            target.write(json.dumps(sprite, ensure_ascii=False))
            if trailing_comma:
                target.write(",")
            target.write("\n")
            if progress_interval > 0 and total % progress_interval == 0:
                print(f"SEEDED_VISION_PROGRESS sprites={total} approved={labeled} low_confidence={low_confidence}", flush=True)

    tmp_path.replace(output_path)
    return {
        "ok": True,
        "project_path": str(output_path),
        "total": total,
        "approved": labeled,
        "low_confidence": low_confidence,
        "missing": 0,
    }


def count_missing_vision_labels(project_path: Path) -> dict[str, int]:
    total = 0
    missing = 0
    low_confidence = 0
    for sprite in iter_project_sprites(project_path):
        total += 1
        label = sprite.get("vision_label")
        if not isinstance(label, dict) or not str(label.get("display_name", "")).strip():
            missing += 1
        flags = sprite.get("review_flags", [])
        if isinstance(flags, list) and "vision_low_confidence" in [str(flag) for flag in flags]:
            low_confidence += 1
    return {"total": total, "missing": missing, "low_confidence": low_confidence}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a large SpriteCut project with representative Gemini vision labels.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    seed_parser = subparsers.add_parser("seed")
    seed_parser.add_argument("project", type=Path)
    seed_parser.add_argument("--seed-path", type=Path, required=True)
    seed_parser.add_argument("--provider", default="gemini")
    seed_parser.add_argument("--model", default="")
    seed_parser.add_argument("--limit-categories", type=int, default=0)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("project", type=Path)
    apply_parser.add_argument("--seed-path", type=Path, required=True)
    apply_parser.add_argument("--output", type=Path, required=True)
    apply_parser.add_argument("--min-confidence", type=float, default=0.8)
    apply_parser.add_argument("--progress-interval", type=int, default=50000)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("project", type=Path)

    args = parser.parse_args()
    if args.action == "seed":
        result = write_seed_labels(args.project, args.seed_path, provider_name=args.provider, model=args.model, limit_categories=args.limit_categories)
    elif args.action == "apply":
        result = apply_seeded_labels(args.project, args.seed_path, args.output, min_confidence=args.min_confidence, progress_interval=args.progress_interval)
    else:
        result = count_missing_vision_labels(args.project)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
