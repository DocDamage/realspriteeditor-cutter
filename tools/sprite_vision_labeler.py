from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from tools.sprite_project import load_project, safe_file_name, save_project


VISION_CATEGORIES = [
    "characters_and_creatures",
    "vegetation_and_trees",
    "tiles_and_terrain",
    "props_and_items",
    "weapons_and_projectiles",
    "ui_icons_and_fonts",
    "portraits_and_faces",
    "backgrounds_and_parallax",
    "effects_and_particles",
    "unknown",
]


class VisionProvider(Protocol):
    name: str

    def label_sprite(self, image_path: Path, sprite: dict[str, Any]) -> dict[str, Any]:
        ...


def _image_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_sprite_image(project_path: Path, sprite: dict[str, Any]) -> Path:
    for key in ("applied_output_file", "output_file", "source_file"):
        value = str(sprite.get(key, "")).strip()
        if value:
            path = Path(value)
            return path if path.is_absolute() else project_path.parent / path
    raise ValueError(f"Sprite {sprite.get('id', '')} has no image path for vision labeling.")


def _flags(sprite: dict[str, Any]) -> list[str]:
    values = sprite.get("review_flags", [])
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _add_flag(flags: list[str], flag: str) -> list[str]:
    return flags if flag in flags else [*flags, flag]


def _clean_display_name(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    cleaned = safe_file_name(text)
    return cleaned if cleaned != "sprite" else safe_file_name(fallback)


def _clean_category(value: Any) -> str:
    category = safe_file_name(str(value or "unknown"))
    return category if category in VISION_CATEGORIES else "unknown"


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_label(raw: dict[str, Any], provider_name: str) -> dict[str, Any]:
    label = {
        "display_name": _clean_display_name(raw.get("display_name"), "sprite"),
        "category": _clean_category(raw.get("category")),
        "description": str(raw.get("description", "")).strip(),
        "confidence": _confidence(raw.get("confidence")),
        "provider": provider_name,
    }
    return label


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "labels": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"schema_version": 1, "labels": {}}
    labels = data.get("labels")
    if not isinstance(labels, dict):
        data["labels"] = {}
    data.setdefault("schema_version", 1)
    return data


def _write_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _apply_label(sprite: dict[str, Any], label: dict[str, Any], min_confidence: float) -> bool:
    confidence = _confidence(label.get("confidence"))
    sprite["vision_label"] = dict(label)
    sprite["confidence"] = confidence
    flags = [flag for flag in _flags(sprite) if flag not in {"auto_named", "vision_low_confidence"}]
    flags = _add_flag(flags, "vision_labeled")
    if confidence >= min_confidence:
        sprite["display_name"] = _clean_display_name(label.get("display_name"), str(sprite.get("id", "sprite")))
        sprite["category"] = _clean_category(label.get("category"))
        sprite["review_status"] = "approved"
        sprite["review_flags"] = flags
        return True
    sprite["review_status"] = "needs_review"
    sprite["review_flags"] = _add_flag(flags, "vision_low_confidence")
    return False


class FixtureVisionProvider:
    name = "fixture"

    def __init__(self, labels: dict[str, dict[str, Any]]) -> None:
        self.labels = labels

    def label_sprite(self, image_path: Path, sprite: dict[str, Any]) -> dict[str, Any]:
        sprite_id = str(sprite.get("id", ""))
        if sprite_id not in self.labels:
            raise ValueError(f"Missing fixture vision label for sprite: {sprite_id}")
        return _normalize_label(self.labels[sprite_id], self.name)


class OpenAIVisionProvider:
    name = "openai"

    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for provider='openai'.")
        from openai import OpenAI

        self.client = OpenAI()
        self.model = model

    def label_sprite(self, image_path: Path, sprite: dict[str, Any]) -> dict[str, Any]:
        data_url = "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "Identify this isolated 2D game sprite. Return only JSON with keys display_name, "
            "category, description, confidence. Use snake_case display_name. Category must be one of: "
            f"{', '.join(VISION_CATEGORIES)}. Confidence must be 0 to 1."
        )
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
        text = str(getattr(response, "output_text", "")).strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match is None:
            raise ValueError(f"OpenAI vision response did not contain JSON: {text[:200]}")
        return _normalize_label(json.loads(match.group(0)), self.name)


class GeminiVisionProvider:
    name = "gemini"

    def __init__(self, model: str = "gemini-2.5-flash") -> None:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required for provider='gemini'.")
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def label_sprite(self, image_path: Path, sprite: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "Identify this isolated 2D game sprite. Return only JSON with keys display_name, "
            "category, description, confidence. Use snake_case display_name. Category must be one of: "
            f"{', '.join(VISION_CATEGORIES)}. Confidence must be 0 to 1."
        )
        with Image.open(image_path) as image:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, image.convert("RGBA")],
            )
        text = str(getattr(response, "text", "")).strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match is None:
            raise ValueError(f"Gemini vision response did not contain JSON: {text[:200]}")
        return _normalize_label(json.loads(match.group(0)), self.name)


def provider_from_name(name: str, *, fixture_labels: dict[str, dict[str, Any]] | None = None, model: str = "") -> VisionProvider:
    provider_name = name.strip().lower() or "openai"
    if provider_name == "fixture":
        return FixtureVisionProvider(fixture_labels or {})
    if provider_name == "openai":
        return OpenAIVisionProvider(model=model or "gpt-4.1-mini")
    if provider_name in {"gemini", "nano_banana", "nano-banana"}:
        return GeminiVisionProvider(model=model or "gemini-2.5-flash")
    raise ValueError(f"Unsupported vision provider: {name}")


def label_project_with_vision(
    project_path: Path | str,
    *,
    provider: VisionProvider,
    min_confidence: float = 0.8,
    cache_path: Path | str | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    path = Path(project_path)
    project = load_project(path)
    cache_file = Path(cache_path) if cache_path else path.parent / "manifest" / "vision_label_cache.json"
    cache = _load_cache(cache_file)
    cached_labels: dict[str, Any] = cache["labels"]
    labeled = 0
    approved = 0
    low_confidence = 0
    cached = 0
    errors: list[dict[str, str]] = []

    sprites = project.get("sprites", [])
    for sprite in sprites:
        if not isinstance(sprite, dict) or (limit and labeled >= limit):
            continue
        try:
            image_path = _resolve_sprite_image(path, sprite)
            image_hash = _image_sha256(image_path)
            cache_key = f"{provider.name}:{image_hash}"
            if cache_key in cached_labels:
                label = dict(cached_labels[cache_key])
                cached += 1
            else:
                label = provider.label_sprite(image_path, sprite)
                cached_labels[cache_key] = dict(label)
            labeled += 1
            if _apply_label(sprite, label, min_confidence):
                approved += 1
            else:
                low_confidence += 1
        except Exception as exc:
            errors.append({"sprite_id": str(sprite.get("id", "")), "error": f"{type(exc).__name__}: {exc}"})

    _write_cache(cache_file, cache)
    save_project(project, path)
    return {
        "ok": not errors,
        "project_path": str(path),
        "cache_path": str(cache_file),
        "provider": provider.name,
        "labeled": labeled,
        "approved": approved,
        "low_confidence": low_confidence,
        "cached": cached,
        "errors": errors,
    }
