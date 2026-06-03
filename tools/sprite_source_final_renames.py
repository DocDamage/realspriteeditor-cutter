from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Protocol

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


class RenameProvider(Protocol):
    name: str

    def final_name(self, image_path: Path, context: dict[str, Any]) -> dict[str, Any]:
        ...


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _mime_type(path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "image/png"


def _extract_json(text: str, provider: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text.strip(), flags=re.S)
    if match is None:
        raise ValueError(f"{provider} response did not contain JSON: {text[:200]}")
    raw = json.loads(match.group(0))
    if not isinstance(raw, dict):
        raise ValueError(f"{provider} response JSON was not an object.")
    return raw


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


def _provider_context(group: dict[str, Any]) -> dict[str, Any]:
    vision_label = group.get("vision_label") if isinstance(group.get("vision_label"), dict) else {}
    return {
        "source_group": group.get("group", ""),
        "relative_dir": group.get("relative_dir", ""),
        "kind": group.get("kind", ""),
        "file_count": group.get("file_count", 0),
        "path_semantic_base": group.get("semantic_base", ""),
        "path_rename_pattern": group.get("rename_pattern", ""),
        "path_category": group.get("suggested_category", ""),
        "path_terms": group.get("terms", []),
        "gemini_semantic_base": group.get("vision_semantic_base", ""),
        "gemini_rename_pattern": group.get("vision_rename_pattern", ""),
        "gemini_category": vision_label.get("category", ""),
        "gemini_description": vision_label.get("description", ""),
        "gemini_confidence": vision_label.get("confidence", 0),
    }


class FixtureRenameProvider:
    name = "fixture"

    def __init__(self, labels: dict[str, dict[str, Any]]) -> None:
        self.labels = labels

    def final_name(self, image_path: Path, context: dict[str, Any]) -> dict[str, Any]:
        key = str(context.get("source_group", ""))
        if key not in self.labels:
            raise ValueError(f"Missing fixture final rename for group: {key}")
        return dict(self.labels[key])


class KimiRenameProvider:
    name = "kimi"

    def __init__(self, model: str = "moonshot-v1-8k-vision-preview", timeout_seconds: float = 45.0) -> None:
        api_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
        if not api_key:
            raise RuntimeError("KIMI_API_KEY or MOONSHOT_API_KEY is required for provider='kimi'.")
        from openai import OpenAI

        is_kimi_code_key = api_key.startswith("sk-kimi-")
        base_url = os.environ.get("KIMI_BASE_URL") or os.environ.get("MOONSHOT_BASE_URL")
        if not base_url:
            base_url = "https://api.kimi.com/coding/v1" if is_kimi_code_key else "https://api.moonshot.ai/v1"
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self.model = model or ("kimi-for-coding" if is_kimi_code_key else "moonshot-v1-8k-vision-preview")

    def final_name(self, image_path: Path, context: dict[str, Any]) -> dict[str, Any]:
        mime = _mime_type(image_path)
        data_url = f"data:{mime};base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "You are finalizing production-safe names for a 2D game asset library. "
            "Look at the representative image and the source metadata. Choose a concise snake_case "
            "final_semantic_base that preserves the original pack meaning when the path is more reliable "
            "than the visual label, but corrects vague or misleading names. Do not use preview, sprite, "
            "image, or spritesheet as the final base unless that is truly the asset type. "
            "Return only JSON with keys final_semantic_base, category, rename_confidence, rationale. "
            "category must be one of: "
            f"{', '.join(sorted(FINAL_CATEGORIES))}. rename_confidence must be 0 to 1.\n\n"
            f"Metadata:\n{json.dumps(context, ensure_ascii=True)}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        )
        text = str(response.choices[0].message.content or "")
        return _extract_json(text, self.name)


def provider_from_name(name: str, *, fixture_labels: dict[str, dict[str, Any]] | None = None, model: str = "") -> RenameProvider:
    provider_name = name.strip().lower() or "kimi"
    if provider_name == "fixture":
        return FixtureRenameProvider(fixture_labels or {})
    if provider_name in {"kimi", "moonshot"}:
        return KimiRenameProvider(model=model)
    raise ValueError(f"Unsupported final rename provider: {name}")


def _normalize_final_label(raw: dict[str, Any], group: dict[str, Any], provider_name: str) -> dict[str, Any]:
    fallback = str(group.get("semantic_base") or group.get("vision_semantic_base") or "sprite")
    final_base = _clean_final_base(raw.get("final_semantic_base"), fallback)
    confidence = _confidence(raw.get("rename_confidence"))
    if confidence < 0.45:
        final_base = safe_name(fallback)
    pattern = f"{final_base}_frame_{{frame:03d}}" if str(group.get("kind")) == "animation_sequence" else final_base
    return {
        "final_semantic_base": final_base,
        "final_rename_pattern": pattern,
        "category": _clean_category(raw.get("category")),
        "rename_confidence": confidence,
        "rationale": str(raw.get("rationale", "")).strip(),
        "provider": provider_name,
    }


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


def build_final_rename_manifest(
    index_path: Path,
    output_path: Path,
    *,
    provider_name: str = "kimi",
    model: str = "",
    checkpoint_interval: int = 25,
    limit: int = 0,
    max_errors: int = 10,
    fixture_labels: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    index = _load_json(index_path)
    source_root = Path(str(index.get("source_root", "")))
    groups = index.get("groups")
    if not source_root.exists():
        raise FileNotFoundError(f"Missing source_root from learning index: {source_root}")
    if not isinstance(groups, list):
        raise ValueError("Learning index must contain a groups list.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        manifest = _load_json(output_path)
        completed_groups = {str(group.get("group", "")) for group in manifest.get("groups", []) if isinstance(group, dict)}
        used_paths = {str(item.get("target", "")).lower() for item in manifest.get("file_renames", []) if isinstance(item, dict)}
    else:
        manifest = {
            "schema_version": 1,
            "kind": "sprite_source_final_rename_manifest",
            "source_root": str(source_root),
            "source_index": str(index_path),
            "provider": provider_name,
            "groups": [],
            "file_renames": [],
        }
        completed_groups = set()
        used_paths = set()

    provider = provider_from_name(provider_name, fixture_labels=fixture_labels, model=model)
    errors: list[dict[str, str]] = []
    newly_completed = 0
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group", ""))
        if group_name in completed_groups:
            continue
        if limit and newly_completed >= limit:
            break
        try:
            representative = _representative_file(group)
            image_path = source_root / representative
            raw_label = provider.final_name(image_path, _provider_context(group))
            final_label = _normalize_final_label(raw_label, group, provider.name)
            file_renames = _planned_file_renames(group, final_label, used_paths)
            entry = {
                "group": group_name,
                "relative_dir": group.get("relative_dir", ""),
                "kind": group.get("kind", ""),
                "representative_file": representative,
                "path_semantic_base": group.get("semantic_base", ""),
                "gemini_semantic_base": group.get("vision_semantic_base", ""),
                **final_label,
                "file_count": len(file_renames),
            }
            manifest["groups"].append(entry)
            manifest["file_renames"].extend(file_renames)
            completed_groups.add(group_name)
            newly_completed += 1
            print(
                f"FINAL_RENAME provider={provider.name} completed={len(completed_groups)} "
                f"group={group_name} final={final_label['final_semantic_base']}",
                flush=True,
            )
            if checkpoint_interval > 0 and newly_completed % checkpoint_interval == 0:
                _write_manifest(manifest, output_path, len(groups), errors)
        except Exception as exc:
            errors.append({"group": group_name, "error": f"{type(exc).__name__}: {exc}"})
            if max_errors and len(errors) >= max_errors:
                break

    _write_manifest(manifest, output_path, len(groups), errors)
    return {
        "ok": not errors and len(completed_groups) == len(groups),
        "output": str(output_path),
        "provider": provider.name,
        "total_groups": len(groups),
        "finalized_groups": len(completed_groups),
        "missing_groups": max(0, len(groups) - len(completed_groups)),
        "file_renames": len(manifest.get("file_renames", [])),
        "errors": errors,
    }


def _write_manifest(manifest: dict[str, Any], output_path: Path, total_groups: int, errors: list[dict[str, str]]) -> None:
    finalized = len(manifest.get("groups", []))
    manifest["summary"] = {
        "total_groups": total_groups,
        "finalized_groups": finalized,
        "missing_groups": max(0, total_groups - finalized),
        "file_renames": len(manifest.get("file_renames", [])),
        "errors": errors,
    }
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def verify_final_rename_manifest(manifest_path: Path) -> dict[str, Any]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Kimi-finalized, collision-checked source rename manifest.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("index", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--provider", default="kimi")
    build.add_argument("--model", default="")
    build.add_argument("--checkpoint-interval", type=int, default=25)
    build.add_argument("--limit", type=int, default=0)
    build.add_argument("--max-errors", type=int, default=10)

    verify = subparsers.add_parser("verify")
    verify.add_argument("manifest", type=Path)

    args = parser.parse_args()
    if args.action == "build":
        result = build_final_rename_manifest(
            args.index,
            args.output,
            provider_name=args.provider,
            model=args.model,
            checkpoint_interval=args.checkpoint_interval,
            limit=args.limit,
            max_errors=args.max_errors,
        )
    else:
        result = verify_final_rename_manifest(args.manifest)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
