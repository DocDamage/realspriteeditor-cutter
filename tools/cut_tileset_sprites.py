from __future__ import annotations

import argparse
import colorsys
import csv
import hashlib
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


WHITE_THRESHOLD = 250
DARK_ARTIFACT_THRESHOLD = 45
MIN_GROUP_PIXELS = 24
MIN_WIDTH = 3
MIN_HEIGHT = 3
PADDING = 1
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
BUILT_IN_PRESETS: dict[str, dict[str, object]] = {
    "pixel_tileset_white_bg": {
        "mode": "tileset",
        "alpha_threshold": 10,
        "white_threshold": 248,
        "white_tolerance": 10,
        "min_sprite_pixels": 24,
        "crop_padding": 1,
        "pack_atlases": True,
        "atlas_padding": 2,
        "engine_exports": "unity,godot",
    },
    "transparent_animation_rows": {
        "mode": "animation",
        "animation_frame_mode": "fixed",
        "animation_anchor": "bottom-center",
        "animation_min_frames": 3,
        "animation_fps": 12,
        "alpha_threshold": 10,
        "min_sprite_pixels": 16,
        "crop_padding": 1,
        "engine_exports": "unity,godot,unreal",
    },
    "packed_props_dark_bg": {
        "mode": "tileset",
        "alpha_threshold": 10,
        "dark_artifact_threshold": 60,
        "min_sprite_pixels": 32,
        "crop_padding": 2,
        "pack_atlases": True,
        "atlas_padding": 3,
        "engine_exports": "unity,godot",
    },
    "rpgmaker_tiles": {
        "mode": "tileset",
        "alpha_threshold": 10,
        "white_threshold": 250,
        "white_tolerance": 8,
        "min_sprite_width": 4,
        "min_sprite_height": 4,
        "min_sprite_pixels": 16,
        "crop_padding": 0,
        "pack_atlases": True,
        "atlas_padding": 1,
        "engine_exports": "godot",
    },
}


@dataclass
class SpriteRecord:
    id: str
    display_name: str
    source_sheet: str
    source_file: str
    kind: str
    sheet_mode: str
    category: str
    sequence: str | None
    frame: int | None
    output_file: str
    bbox: dict[str, int]
    width: int
    height: int
    slot_width: int | None
    slot_height: int | None
    foreground_pixels: int
    alpha_mode: str
    is_partial: bool
    transparency_ratio: float
    aspect_ratio: float
    dominant_colors: list[str]
    pivot: dict[str, float | str]
    confidence: float
    review_flags: list[str]
    review_status: str
    atlas: dict[str, object] | None


@dataclass
class DetectedSprite:
    label: int
    x: int
    y: int
    width: int
    height: int
    foreground_pixels: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


@dataclass
class DetectionSettings:
    alpha_threshold: int = 10
    white_threshold: int = WHITE_THRESHOLD
    white_tolerance: int = 8
    dark_artifact_threshold: int = DARK_ARTIFACT_THRESHOLD
    min_sprite_pixels: int = MIN_GROUP_PIXELS
    min_sprite_width: int = MIN_WIDTH
    min_sprite_height: int = MIN_HEIGHT
    crop_padding: int = PADDING


@dataclass
class SheetError:
    source_file: str
    error: str


@dataclass
class RunOptions:
    mode: str
    animation_names: list[str]
    animation_frame_mode: str
    animation_anchor: str
    animation_min_frames: int
    animation_fps: int
    pivot_debug: bool
    pack_atlases: bool
    atlas_size: int
    atlas_padding: int
    atlas_allow_rotation: bool
    engine_exports: list[str]
    detection_settings: DetectionSettings
    on_error: str
    workers: int
    max_image_megapixels: float
    resume: bool
    auto_detect_all: bool
    auto_profile: dict[str, object]


@dataclass
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass
class PackedRect(Rect):
    source_id: str
    rotated: bool = False


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def unique_output_dir(root: Path, preferred_name: str) -> Path:
    candidate = root / preferred_name
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = root / f"{preferred_name}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def is_generated_output_path(path: Path) -> bool:
    return any(part.lower().startswith("_organized_sprites") for part in path.parts)


def is_inside_spritecut_output(path: Path, root: Path) -> bool:
    current = path if path.is_dir() else path.parent
    while True:
        if (current / "project.spritecut.json").exists() or (current / "manifest" / "sprites.json").exists():
            return True
        if current == root or current == current.parent:
            return False
        current = current.parent


def discover_sheet_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS else []

    sheets: list[Path] = []
    for path in input_path.rglob("*"):
        if is_generated_output_path(path) or is_inside_spritecut_output(path, input_path):
            continue
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            sheets.append(path)
    return sorted(sheets, key=lambda path: natural_key(str(path.relative_to(input_path))))


def load_config_defaults(config_path: Path | None, preset_name: str | None = None) -> dict[str, object]:
    defaults: dict[str, object] = {}
    if preset_name:
        if preset_name not in BUILT_IN_PRESETS:
            available = ", ".join(sorted(BUILT_IN_PRESETS))
            raise SystemExit(f"Unknown preset '{preset_name}'. Available presets: {available}")
        defaults.update(BUILT_IN_PRESETS[preset_name])

    if config_path is not None:
        with config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise SystemExit(f"Config file must contain a JSON object: {config_path}")
        defaults.update(raw)

    if isinstance(defaults.get("engine_exports"), list):
        defaults["engine_exports"] = ",".join(str(item) for item in defaults["engine_exports"])
    if isinstance(defaults.get("animation_names"), list):
        defaults["animation_names"] = ",".join(str(item) for item in defaults["animation_names"])
    return defaults


def detect_background(rgb: np.ndarray, alpha: np.ndarray, settings: DetectionSettings | None = None) -> np.ndarray:
    settings = settings or DetectionSettings()
    white = (
        (rgb[:, :, 0] >= settings.white_threshold)
        & (rgb[:, :, 1] >= settings.white_threshold)
        & (rgb[:, :, 2] >= settings.white_threshold)
        & ((rgb.max(axis=2) - rgb.min(axis=2)) <= settings.white_tolerance)
    )
    transparent = alpha <= settings.alpha_threshold

    dark_flat = (rgb.max(axis=2) <= settings.dark_artifact_threshold) & (alpha > settings.alpha_threshold)
    black_background = np.zeros(dark_flat.shape, dtype=bool)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(dark_flat.astype(np.uint8), 8)
    near_transparent = cv2.dilate(transparent.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
    for label in range(1, num):
        x, y, w, h, area = stats[label]
        fill = area / max(1, w * h)
        component = labels == label
        touches_edge = x == 0 or y == 0 or x + w == rgb.shape[1] or y + h == rgb.shape[0]
        touches_transparent = bool((component & near_transparent).any())
        if area >= 350 and (w >= 18 or h >= 18) and (fill >= 0.18 or area >= 900) and (touches_edge or touches_transparent):
            black_background[component] = True

    if black_background.any():
        expanded = cv2.dilate(black_background.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2).astype(bool)
        black_background = expanded & (alpha > settings.alpha_threshold) & (rgb.max(axis=2) <= 105)

    return white | transparent | black_background


def grouped_components(foreground: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    num, labels, stats, _ = cv2.connectedComponentsWithStats(foreground.astype(np.uint8), 8)
    return labels, stats, num


def extract_detections(
    foreground: np.ndarray,
    labels: np.ndarray,
    stats: np.ndarray,
    num: int,
    settings: DetectionSettings | None = None,
) -> list[DetectedSprite]:
    settings = settings or DetectionSettings()
    detections: list[DetectedSprite] = []
    height, width = foreground.shape
    for label in range(1, num):
        x, y, w, h, _area = stats[label]
        if w < settings.min_sprite_width or h < settings.min_sprite_height:
            continue

        component_region = labels[y : y + h, x : x + w] == label
        exact_foreground = foreground[y : y + h, x : x + w] & component_region
        foreground_pixels = int(exact_foreground.sum())
        if foreground_pixels < settings.min_sprite_pixels:
            continue

        x0 = max(0, int(x) - settings.crop_padding)
        y0 = max(0, int(y) - settings.crop_padding)
        x1 = min(width, int(x + w) + settings.crop_padding)
        y1 = min(height, int(y + h) + settings.crop_padding)
        detections.append(
            DetectedSprite(
                label=int(label),
                x=x0,
                y=y0,
                width=int(x1 - x0),
                height=int(y1 - y0),
                foreground_pixels=foreground_pixels,
            )
        )

    return sorted(detections, key=lambda item: (item.y, item.x))


def coefficient_of_variation(values: list[int]) -> float:
    if not values:
        return 0.0
    mean = float(np.mean(values))
    if mean == 0:
        return 0.0
    return float(np.std(values) / mean)


def cluster_animation_rows(detections: list[DetectedSprite]) -> list[list[DetectedSprite]]:
    if not detections:
        return []

    median_height = float(np.median([detection.height for detection in detections]))
    row_tolerance = max(8.0, median_height * 0.65)
    rows: list[list[DetectedSprite]] = []
    row_centers: list[float] = []

    for detection in sorted(detections, key=lambda item: (item.center_y, item.x)):
        best_index: int | None = None
        best_distance = row_tolerance + 1
        for index, center in enumerate(row_centers):
            distance = abs(detection.center_y - center)
            if distance <= row_tolerance and distance < best_distance:
                best_index = index
                best_distance = distance

        if best_index is None:
            rows.append([detection])
            row_centers.append(detection.center_y)
        else:
            rows[best_index].append(detection)
            row_centers[best_index] = float(np.mean([item.center_y for item in rows[best_index]]))

    rows.sort(key=lambda row: min(item.y for item in row))
    for row in rows:
        row.sort(key=lambda item: item.x)
    return rows


def row_is_animation_like(row: list[DetectedSprite]) -> bool:
    if len(row) < 2:
        return False
    widths = [item.width for item in row]
    heights = [item.height for item in row]
    width_cv = coefficient_of_variation(widths)
    height_cv = coefficient_of_variation(heights)
    return width_cv <= 0.38 and height_cv <= 0.38


def looks_like_animation_sheet(detections: list[DetectedSprite], min_frames: int) -> bool:
    if len(detections) < min_frames:
        return False

    rows = cluster_animation_rows(detections)
    candidate_rows = [row for row in rows if len(row) >= min_frames]
    if not candidate_rows:
        return False

    covered = sum(len(row) for row in candidate_rows) / max(1, len(detections))
    if covered < 0.7:
        return False

    similar_rows = [row for row in candidate_rows if row_is_animation_like(row)]
    if not similar_rows:
        return False

    if len(candidate_rows) == 1:
        return len(similar_rows[0]) >= min_frames and covered >= 0.85

    frame_counts = [len(row) for row in similar_rows]
    frame_count_cv = coefficient_of_variation(frame_counts)
    return len(similar_rows) == len(candidate_rows) and frame_count_cv <= 0.35


def resolve_sheet_mode(requested_mode: str, detections: list[DetectedSprite], min_frames: int) -> str:
    if requested_mode != "auto":
        return requested_mode
    return "animation" if looks_like_animation_sheet(detections, min_frames) else "tileset"


def parse_animation_names(value: str) -> list[str]:
    if not value:
        return []
    return [safe_name(part) for part in value.split(",") if safe_name(part)]


def parse_engine_exports(value: str) -> list[str]:
    if not value:
        return []
    names = [safe_name(part) for part in value.split(",") if safe_name(part)]
    if "all" in names:
        return ["unity", "godot", "unreal"]
    allowed = {"unity", "godot", "unreal"}
    return [name for name in names if name in allowed]


def _border_pixels(rgb: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if rgb.size == 0:
        return rgb.reshape(0, 3), alpha.reshape(0)
    top = rgb[0, :, :]
    bottom = rgb[-1, :, :]
    left = rgb[:, 0, :]
    right = rgb[:, -1, :]
    top_alpha = alpha[0, :]
    bottom_alpha = alpha[-1, :]
    left_alpha = alpha[:, 0]
    right_alpha = alpha[:, -1]
    return np.concatenate([top, bottom, left, right], axis=0), np.concatenate([top_alpha, bottom_alpha, left_alpha, right_alpha], axis=0)


def _auto_sheet_stats(sheet: Path) -> dict[str, object] | None:
    try:
        with Image.open(sheet) as image:
            image = image.convert("RGBA")
            image.thumbnail((1024, 1024), Image.Resampling.NEAREST)
            rgba = np.array(image)
    except Exception:
        return None

    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]
    border_rgb, border_alpha = _border_pixels(rgb, alpha)
    opaque_border = border_alpha > 10
    if opaque_border.any():
        opaque_rgb = border_rgb[opaque_border]
        white_border_ratio = float(
            np.mean(
                (opaque_rgb[:, 0] >= 245)
                & (opaque_rgb[:, 1] >= 245)
                & (opaque_rgb[:, 2] >= 245)
                & ((opaque_rgb.max(axis=1) - opaque_rgb.min(axis=1)) <= 14)
            )
        )
        dark_border_ratio = float(np.mean(opaque_rgb.max(axis=1) <= 64))
    else:
        white_border_ratio = 0.0
        dark_border_ratio = 0.0

    transparent_ratio = float(np.mean(alpha <= 10))
    settings = DetectionSettings(alpha_threshold=10, white_threshold=248, white_tolerance=12, dark_artifact_threshold=60, min_sprite_pixels=16, crop_padding=1)
    background = detect_background(rgb, alpha, settings)
    foreground = ~background
    labels, stats, num = grouped_components(foreground)
    detections = extract_detections(foreground, labels, stats, num, settings)
    return {
        "transparent_ratio": transparent_ratio,
        "white_border_ratio": white_border_ratio,
        "dark_border_ratio": dark_border_ratio,
        "animation_like": looks_like_animation_sheet(detections, min_frames=3),
        "detections": len(detections),
    }


def infer_auto_defaults(sheets: list[Path], sample_limit: int = 8) -> dict[str, object]:
    defaults: dict[str, object] = {
        "auto_detect_all": True,
        "mode": "auto",
        "animation_names": "",
        "animation_frame_mode": "fixed",
        "animation_anchor": "bottom-center",
        "animation_min_frames": 3,
        "animation_fps": 8,
        "pack_atlases": True,
        "atlas_padding": 2,
        "atlas_allow_rotation": False,
        "engine_exports": "all",
        "alpha_threshold": 10,
        "white_threshold": 250,
        "white_tolerance": 8,
        "dark_artifact_threshold": 45,
        "min_sprite_pixels": 24,
        "min_sprite_width": 3,
        "min_sprite_height": 3,
        "crop_padding": 1,
        "on_error": "skip",
        "workers": min(4, max(1, os.cpu_count() or 1)) if len(sheets) > 1 else 1,
    }

    stats = [stat for sheet in sheets[:sample_limit] if (stat := _auto_sheet_stats(sheet)) is not None]
    if not stats:
        return defaults

    transparent_ratio = float(np.mean([float(stat["transparent_ratio"]) for stat in stats]))
    white_border_ratio = float(np.mean([float(stat["white_border_ratio"]) for stat in stats]))
    dark_border_ratio = float(np.mean([float(stat["dark_border_ratio"]) for stat in stats]))
    animation_votes = sum(1 for stat in stats if stat["animation_like"])

    if transparent_ratio >= 0.18:
        defaults["min_sprite_pixels"] = 16
        defaults["crop_padding"] = 1

    if dark_border_ratio >= 0.35 and dark_border_ratio >= white_border_ratio:
        defaults["dark_artifact_threshold"] = 60
        defaults["crop_padding"] = 2
        defaults["atlas_padding"] = 3
        defaults["min_sprite_pixels"] = max(int(defaults["min_sprite_pixels"]), 32)
    elif white_border_ratio >= 0.35:
        defaults["white_threshold"] = 248
        defaults["white_tolerance"] = 12

    if animation_votes >= max(1, len(stats) // 2):
        defaults["animation_fps"] = 12
        defaults["min_sprite_pixels"] = min(int(defaults["min_sprite_pixels"]), 16)
    return defaults


def option_was_provided(argv: list[str], *names: str) -> bool:
    prefixes = tuple(f"{name}=" for name in names)
    return any(arg in names or arg.startswith(prefixes) for arg in argv)


AUTO_DEFAULT_FLAGS: dict[str, tuple[str, ...]] = {
    "mode": ("--mode",),
    "animation_names": ("--animation-names",),
    "animation_frame_mode": ("--animation-frame-mode",),
    "animation_anchor": ("--animation-anchor",),
    "animation_min_frames": ("--animation-min-frames",),
    "animation_fps": ("--animation-fps",),
    "pack_atlases": ("--pack-atlases", "--no-pack-atlases"),
    "atlas_padding": ("--atlas-padding",),
    "atlas_allow_rotation": ("--atlas-allow-rotation",),
    "engine_exports": ("--engine-exports", "--no-engine-exports"),
    "alpha_threshold": ("--alpha-threshold",),
    "white_threshold": ("--white-threshold",),
    "white_tolerance": ("--white-tolerance",),
    "dark_artifact_threshold": ("--dark-artifact-threshold",),
    "min_sprite_pixels": ("--min-sprite-pixels",),
    "min_sprite_width": ("--min-sprite-width",),
    "min_sprite_height": ("--min-sprite-height",),
    "crop_padding": ("--crop-padding",),
    "on_error": ("--on-error",),
    "workers": ("--workers",),
}


def apply_auto_defaults(args: argparse.Namespace, defaults: dict[str, object], config_defaults: dict[str, object], argv: list[str]) -> dict[str, object]:
    applied: dict[str, object] = {}
    for key, value in defaults.items():
        if key == "auto_detect_all":
            continue
        if key in config_defaults:
            continue
        if option_was_provided(argv, *AUTO_DEFAULT_FLAGS.get(key, ())):
            continue
        setattr(args, key, value)
        applied[key] = value
    return applied


def classify_sprite(sheet_stem: str, x: int, y: int, w: int, h: int, foreground_pixels: int) -> str:
    area = w * h
    fill = foreground_pixels / max(1, area)
    aspect = w / max(1, h)

    if (w >= 300 and h >= 160) or (h >= 300 and w >= 300):
        return "environment_and_large_composites"
    if w >= 110 and h <= 105:
        return "wide_cases_and_counters"
    if h >= 110 and w <= 100:
        return "tall_shelves_and_racks"
    if (w >= 135 and h >= 88) or area >= 18_000:
        return "large_fixtures"
    if 0.75 <= aspect <= 1.35 and 34 <= w <= 78 and 30 <= h <= 78 and fill >= 0.23:
        return "baskets_crates_and_bins"
    if w <= 52 and h <= 52:
        if y <= 150:
            return "signs_and_labels"
        return "small_goods_and_debris"
    if w <= 85 and h <= 80:
        return "medium_props"
    return "fixtures_and_displays"


def should_use_full_alpha(category: str, w: int, h: int, foreground_pixels: int) -> bool:
    fill = foreground_pixels / max(1, w * h)
    if category in {"environment_and_large_composites", "large_fixtures"}:
        return fill >= 0.18
    if category in {"wide_cases_and_counters", "tall_shelves_and_racks", "fixtures_and_displays"}:
        return fill >= 0.38
    return False


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value).strip("_")


def render_checker(size: tuple[int, int], cell: int = 8) -> Image.Image:
    width, height = size
    checker = Image.new("RGBA", size, (236, 236, 236, 255))
    draw = ImageDraw.Draw(checker)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(x + cell - 1, width), min(y + cell - 1, height)), fill=(210, 210, 210, 255))
    return checker


def is_partial_detection(detection: DetectedSprite, sheet_width: int, sheet_height: int) -> bool:
    return detection.x <= 0 or detection.y <= 0 or detection.right >= sheet_width or detection.bottom >= sheet_height


def dominant_colors(rgba: np.ndarray, max_colors: int = 5) -> list[str]:
    alpha = rgba[:, :, 3]
    visible = rgba[:, :, :3][alpha > 20]
    if visible.size == 0:
        return []

    quantized = (visible // 16) * 16
    colors, counts = np.unique(quantized.reshape(-1, 3), axis=0, return_counts=True)
    order = np.argsort(counts)[::-1][:max_colors]
    return [f"#{int(colors[index][0]):02x}{int(colors[index][1]):02x}{int(colors[index][2]):02x}" for index in order]


def analyze_sprite_pixels(rgba: np.ndarray) -> tuple[float, float, list[str]]:
    height, width = rgba.shape[:2]
    alpha = rgba[:, :, 3]
    transparency_ratio = 1.0 - float(np.count_nonzero(alpha > 20) / max(1, width * height))
    aspect_ratio = float(width / max(1, height))
    return round(transparency_ratio, 4), round(aspect_ratio, 4), dominant_colors(rgba)


def assess_sprite_quality(
    detection: DetectedSprite,
    sheet_width: int,
    sheet_height: int,
    transparency_ratio: float,
    aspect_ratio: float,
) -> tuple[float, list[str], str]:
    flags: list[str] = []
    score = 1.0

    if is_partial_detection(detection, sheet_width, sheet_height):
        flags.append("touches_edge")
        score -= 0.25
    if detection.foreground_pixels < 96 or detection.width < 8 or detection.height < 8:
        flags.append("tiny_component")
        score -= 0.2
    if transparency_ratio >= 0.78:
        flags.append("transparent_heavy")
        score -= 0.15
    if aspect_ratio < 0.25 or aspect_ratio > 4.0:
        flags.append("odd_aspect")
        score -= 0.15
    if detection.width >= sheet_width * 0.8 or detection.height >= sheet_height * 0.8:
        flags.append("large_region")
        score -= 0.1

    confidence = round(max(0.0, min(1.0, score)), 3)
    review_status = "needs_review" if flags else "approved"
    return confidence, flags, review_status


def detect_pivot_centroid(rgba: np.ndarray, category: str, bias_strength: float = 1.0) -> dict[str, float | str]:
    alpha = rgba[:, :, 3].astype(np.float32)
    mask = alpha > 20
    height, width = alpha.shape
    if not mask.any():
        return {"x": 0.5, "y": 0.5, "method": "centroid"}

    weights = alpha * mask
    ys, xs = np.indices(alpha.shape)
    total = float(weights.sum())
    pivot_x = float((xs * weights).sum() / total) / max(1, width - 1)
    pivot_y = float((ys * weights).sum() / total) / max(1, height - 1)

    bottom_categories = {"animation", "tall_shelves_and_racks", "wide_cases_and_counters", "large_fixtures", "fixtures_and_displays"}
    if category in bottom_categories:
        pivot_x = pivot_x * (1 - 0.35 * bias_strength) + 0.5 * (0.35 * bias_strength)
        pivot_y = pivot_y * (1 - 0.65 * bias_strength) + 0.88 * (0.65 * bias_strength)
    elif category in {"signs_and_labels"}:
        pivot_x = pivot_x * (1 - 0.25 * bias_strength) + 0.5 * (0.25 * bias_strength)
        pivot_y = pivot_y * (1 - 0.6 * bias_strength) + 0.2 * (0.6 * bias_strength)

    return {"x": round(max(0.05, min(0.95, pivot_x)), 4), "y": round(max(0.05, min(0.95, pivot_y)), 4), "method": "centroid"}


def detect_pivot_contour(rgba: np.ndarray, category: str, bias_strength: float = 1.0) -> dict[str, float | str]:
    alpha = rgba[:, :, 3]
    height, width = alpha.shape
    _, binary = cv2.threshold(alpha, 20, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return detect_pivot_centroid(rgba, category, bias_strength)

    contour = max(contours, key=cv2.contourArea)
    moments = cv2.moments(contour)
    if moments["m00"] > 0:
        pivot_x = float(moments["m10"] / moments["m00"]) / max(1, width - 1)
        pivot_y = float(moments["m01"] / moments["m00"]) / max(1, height - 1)
    else:
        x, y, w, h = cv2.boundingRect(contour)
        pivot_x = (x + w / 2) / max(1, width)
        pivot_y = (y + h / 2) / max(1, height)

    bottom_categories = {"animation", "tall_shelves_and_racks", "wide_cases_and_counters", "large_fixtures", "fixtures_and_displays"}
    if category in bottom_categories:
        bottom_y = float(contour[:, 0, 1].max()) / max(1, height - 1)
        pivot_x = pivot_x * (1 - 0.4 * bias_strength) + 0.5 * (0.4 * bias_strength)
        pivot_y = bottom_y * 0.96
    elif category in {"signs_and_labels"}:
        pivot_x = pivot_x * (1 - 0.25 * bias_strength) + 0.5 * (0.25 * bias_strength)
        pivot_y = 0.18

    return {"x": round(max(0.05, min(0.95, pivot_x)), 4), "y": round(max(0.05, min(0.95, pivot_y)), 4), "method": "contour"}


def detect_pivot(rgba: np.ndarray, category: str) -> dict[str, float | str]:
    contour = detect_pivot_contour(rgba, category)
    centroid = detect_pivot_centroid(rgba, category)
    contour_weight = 0.7
    pivot_x = float(contour["x"]) * contour_weight + float(centroid["x"]) * (1 - contour_weight)
    pivot_y = float(contour["y"]) * contour_weight + float(centroid["y"]) * (1 - contour_weight)
    return {"x": round(max(0.05, min(0.95, pivot_x)), 4), "y": round(max(0.05, min(0.95, pivot_y)), 4), "method": "hybrid"}


def save_pivot_debug(rgba: np.ndarray, pivot: dict[str, float | str], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(rgba, "RGBA")
    base = render_checker(image.size)
    base.alpha_composite(image)
    debug = np.array(base.convert("RGB"))

    alpha = rgba[:, :, 3]
    _, binary = cv2.threshold(alpha, 20, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(debug, contours, -1, (0, 210, 80), 1)

    debug_image = Image.fromarray(debug, "RGB")
    draw = ImageDraw.Draw(debug_image)
    px = int(float(pivot["x"]) * max(1, image.width - 1))
    py = int(float(pivot["y"]) * max(1, image.height - 1))
    size = 8
    draw.line((px - size, py, px + size, py), fill=(255, 0, 0), width=2)
    draw.line((px, py - size, px, py + size), fill=(255, 0, 0), width=2)
    debug_image.save(out_path)


def make_contact_sheet(records: list[SpriteRecord], out_path: Path, max_thumb: int = 96) -> None:
    if not records:
        return

    thumbs: list[tuple[SpriteRecord, Image.Image]] = []
    for record in records:
        image = Image.open(record.output_file).convert("RGBA")
        image.thumbnail((max_thumb, max_thumb), Image.Resampling.NEAREST)
        thumbs.append((record, image.copy()))
        image.close()

    columns = 6
    label_height = 28
    cell_w = max_thumb + 20
    cell_h = max_thumb + label_height + 18
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * cell_w, rows * cell_h), (248, 248, 248, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, (record, thumb) in enumerate(thumbs):
        col = index % columns
        row = index // columns
        x = col * cell_w
        y = row * cell_h
        checker = render_checker((max_thumb, max_thumb))
        sheet.alpha_composite(checker, (x + 10, y + 8))
        px = x + 10 + (max_thumb - thumb.width) // 2
        py = y + 8 + (max_thumb - thumb.height) // 2
        sheet.alpha_composite(thumb, (px, py))
        draw.text((x + 8, y + max_thumb + 12), record.id, fill=(24, 24, 24), font=font)

    sheet.convert("RGB").save(out_path)


def make_masked_crop(
    rgba: np.ndarray,
    foreground: np.ndarray,
    labels: np.ndarray,
    detection: DetectedSprite,
) -> np.ndarray:
    x0 = detection.x
    y0 = detection.y
    x1 = detection.right
    y1 = detection.bottom
    crop_rgba = rgba[y0:y1, x0:x1, :].copy()
    local_mask = labels[y0:y1, x0:x1] == detection.label
    local_foreground = foreground[y0:y1, x0:x1] & local_mask
    refined = cv2.morphologyEx(local_foreground.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)
    crop_rgba[:, :, 3] = (refined * 255).astype(np.uint8)
    return crop_rgba


def draw_detection_box(
    draw: ImageDraw.ImageDraw,
    detection: DetectedSprite,
    label: str,
    color: tuple[int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    x0 = detection.x
    y0 = detection.y
    x1 = detection.right
    y1 = detection.bottom
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=color, width=1)
    draw.text((x0 + 2, y0 + 2), label, fill=color, font=font)


def process_tileset_sheet(
    source_path: Path,
    source_label: str,
    source_stem: str,
    rgba: np.ndarray,
    rgba_image: Image.Image,
    foreground: np.ndarray,
    labels: np.ndarray,
    detections: list[DetectedSprite],
    out_dir: Path,
    preview_dir: Path,
    sheet_mode: str,
    options: RunOptions,
) -> list[SpriteRecord]:
    records: list[SpriteRecord] = []
    counters: Counter[str] = Counter()
    boxed = rgba_image.convert("RGB")
    draw = ImageDraw.Draw(boxed)
    font = ImageFont.load_default()
    colors = [
        (230, 80, 80),
        (40, 150, 220),
        (80, 170, 80),
        (220, 150, 40),
        (170, 90, 220),
        (60, 180, 180),
    ]

    for detection in detections:
        category = classify_sprite(source_stem, detection.x, detection.y, detection.width, detection.height, detection.foreground_pixels)
        counters[category] += 1
        sprite_id = f"{source_label}_{category}_{counters[category]:03d}"
        file_name = f"{sprite_id}.png"
        category_dir = out_dir / "sprites" / category
        category_dir.mkdir(parents=True, exist_ok=True)
        output_path = category_dir / file_name

        crop_rgba = rgba[detection.y : detection.bottom, detection.x : detection.right, :].copy()
        use_full_alpha = should_use_full_alpha(category, detection.width, detection.height, detection.foreground_pixels)
        if use_full_alpha:
            crop_rgba[:, :, 3] = 255
            alpha_mode = "full_bbox"
        else:
            crop_rgba = make_masked_crop(rgba, foreground, labels, detection)
            alpha_mode = "background_removed"

        Image.fromarray(crop_rgba, "RGBA").save(output_path)
        transparency_ratio, aspect_ratio, colors = analyze_sprite_pixels(crop_rgba)
        pivot = detect_pivot(crop_rgba, category)
        confidence, review_flags, review_status = assess_sprite_quality(
            detection,
            rgba.shape[1],
            rgba.shape[0],
            transparency_ratio,
            aspect_ratio,
        )
        if options.pivot_debug:
            save_pivot_debug(crop_rgba, pivot, preview_dir / "pivots" / f"{sprite_id}_pivot.png")

        record = SpriteRecord(
            id=sprite_id,
            display_name=sprite_id,
            source_sheet=source_label,
            source_file=str(source_path),
            kind="sprite",
            sheet_mode=sheet_mode,
            category=category,
            sequence=None,
            frame=None,
            output_file=str(output_path),
            bbox={"x": detection.x, "y": detection.y, "width": detection.width, "height": detection.height},
            width=detection.width,
            height=detection.height,
            slot_width=None,
            slot_height=None,
            foreground_pixels=detection.foreground_pixels,
            alpha_mode=alpha_mode,
            is_partial=is_partial_detection(detection, rgba.shape[1], rgba.shape[0]),
            transparency_ratio=transparency_ratio,
            aspect_ratio=aspect_ratio,
            dominant_colors=colors,
            pivot=pivot,
            confidence=confidence,
            review_flags=review_flags,
            review_status=review_status,
            atlas=None,
        )
        records.append(record)

        color = colors[(len(records) - 1) % len(colors)]
        draw_detection_box(draw, detection, str(len(records)), color, font)

    boxed.save(preview_dir / f"{source_label}_boxes.png")
    make_contact_sheet(records, preview_dir / f"{source_label}_contact.png")
    return records


def place_animation_frame(crop_rgba: np.ndarray, slot_width: int, slot_height: int, anchor: str) -> np.ndarray:
    if crop_rgba.shape[1] == slot_width and crop_rgba.shape[0] == slot_height:
        return crop_rgba

    frame = np.zeros((slot_height, slot_width, 4), dtype=np.uint8)
    if anchor == "center":
        dest_x = (slot_width - crop_rgba.shape[1]) // 2
        dest_y = (slot_height - crop_rgba.shape[0]) // 2
    else:
        dest_x = (slot_width - crop_rgba.shape[1]) // 2
        dest_y = slot_height - crop_rgba.shape[0]

    dest_x = max(0, dest_x)
    dest_y = max(0, dest_y)
    frame[dest_y : dest_y + crop_rgba.shape[0], dest_x : dest_x + crop_rgba.shape[1], :] = crop_rgba
    return frame


def process_animation_sheet(
    source_path: Path,
    source_label: str,
    rgba: np.ndarray,
    rgba_image: Image.Image,
    foreground: np.ndarray,
    labels: np.ndarray,
    detections: list[DetectedSprite],
    out_dir: Path,
    preview_dir: Path,
    sheet_mode: str,
    options: RunOptions,
) -> list[SpriteRecord]:
    rows = cluster_animation_rows(detections)
    if options.mode == "auto":
        rows = [row for row in rows if len(row) >= options.animation_min_frames]
    rows = [row for row in rows if row]

    records: list[SpriteRecord] = []
    boxed = rgba_image.convert("RGB")
    draw = ImageDraw.Draw(boxed)
    font = ImageFont.load_default()
    colors = [
        (230, 80, 80),
        (40, 150, 220),
        (80, 170, 80),
        (220, 150, 40),
        (170, 90, 220),
        (60, 180, 180),
    ]

    for row_index, row in enumerate(rows, start=1):
        sequence_name = options.animation_names[row_index - 1] if row_index <= len(options.animation_names) else f"row_{row_index:02d}"
        sequence_dir = out_dir / "animations" / source_label / sequence_name
        sequence_dir.mkdir(parents=True, exist_ok=True)
        slot_width = max(item.width for item in row)
        slot_height = max(item.height for item in row)

        sequence_records: list[SpriteRecord] = []
        for frame_index, detection in enumerate(row, start=1):
            frame_name = f"{sequence_name}_{frame_index:03d}"
            output_path = sequence_dir / f"{frame_name}.png"
            crop_rgba = make_masked_crop(rgba, foreground, labels, detection)
            if options.animation_frame_mode == "fixed":
                output_rgba = place_animation_frame(crop_rgba, slot_width, slot_height, options.animation_anchor)
                alpha_mode = f"animation_fixed_{options.animation_anchor}"
                output_width = slot_width
                output_height = slot_height
                output_slot_width: int | None = slot_width
                output_slot_height: int | None = slot_height
            else:
                output_rgba = crop_rgba
                alpha_mode = "background_removed"
                output_width = detection.width
                output_height = detection.height
                output_slot_width = None
                output_slot_height = None

            Image.fromarray(output_rgba, "RGBA").save(output_path)
            transparency_ratio, aspect_ratio, colors = analyze_sprite_pixels(output_rgba)
            pivot = detect_pivot(output_rgba, "animation")
            confidence, review_flags, review_status = assess_sprite_quality(
                detection,
                rgba.shape[1],
                rgba.shape[0],
                transparency_ratio,
                aspect_ratio,
            )
            if options.pivot_debug:
                save_pivot_debug(output_rgba, pivot, preview_dir / "pivots" / f"{source_label}_{frame_name}_pivot.png")

            record = SpriteRecord(
                id=frame_name,
                display_name=frame_name,
                source_sheet=source_label,
                source_file=str(source_path),
                kind="animation_frame",
                sheet_mode=sheet_mode,
                category="animation",
                sequence=sequence_name,
                frame=frame_index,
                output_file=str(output_path),
                bbox={"x": detection.x, "y": detection.y, "width": detection.width, "height": detection.height},
                width=output_width,
                height=output_height,
                slot_width=output_slot_width,
                slot_height=output_slot_height,
                foreground_pixels=detection.foreground_pixels,
                alpha_mode=alpha_mode,
                is_partial=is_partial_detection(detection, rgba.shape[1], rgba.shape[0]),
                transparency_ratio=transparency_ratio,
                aspect_ratio=aspect_ratio,
                dominant_colors=colors,
                pivot=pivot,
                confidence=confidence,
                review_flags=review_flags,
                review_status=review_status,
                atlas=None,
            )
            records.append(record)
            sequence_records.append(record)

            color = colors[(row_index - 1) % len(colors)]
            draw_detection_box(draw, detection, f"{row_index}.{frame_index}", color, font)

        make_contact_sheet(sequence_records, preview_dir / f"{source_label}_{sequence_name}_contact.png")

    boxed.save(preview_dir / f"{source_label}_boxes.png")
    make_contact_sheet(records, preview_dir / f"{source_label}_contact.png")
    return records


def process_sheet(source_path: Path, out_dir: Path, preview_dir: Path, options: RunOptions) -> list[SpriteRecord]:
    source_stem = safe_name(source_path.stem)
    source_label = f"sheet_{source_stem.zfill(2) if source_stem.isdigit() else source_stem}"
    source_image = Image.open(source_path)
    megapixels = (source_image.width * source_image.height) / 1_000_000
    if options.max_image_megapixels > 0 and megapixels > options.max_image_megapixels:
        source_image.close()
        raise ValueError(f"{source_path} is {megapixels:.3f} megapixels and exceeds max_image_megapixels={options.max_image_megapixels}")
    rgba_image = source_image.convert("RGBA")
    source_image.close()
    rgba = np.array(rgba_image)
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3]

    background = detect_background(rgb, alpha, options.detection_settings)
    foreground = ~background
    labels, stats, num = grouped_components(foreground)
    detections = extract_detections(foreground, labels, stats, num, options.detection_settings)
    resolved_mode = resolve_sheet_mode(options.mode, detections, options.animation_min_frames)

    if resolved_mode == "animation":
        records = process_animation_sheet(
            source_path,
            source_label,
            rgba,
            rgba_image,
            foreground,
            labels,
            detections,
            out_dir,
            preview_dir,
            resolved_mode,
            options,
        )
    else:
        records = process_tileset_sheet(
            source_path,
            source_label,
            source_stem,
            rgba,
            rgba_image,
            foreground,
            labels,
            detections,
            out_dir,
            preview_dir,
            resolved_mode,
            options,
        )

    rgba_image.close()
    return records


def rects_intersect(a: Rect, b: Rect) -> bool:
    return a.x < b.right and a.right > b.x and a.y < b.bottom and a.bottom > b.y


def rect_contains(a: Rect, b: Rect) -> bool:
    return b.x >= a.x and b.y >= a.y and b.right <= a.right and b.bottom <= a.bottom


class MaxRectsPacker:
    def __init__(self, width: int, height: int, padding: int = 2, allow_rotation: bool = False) -> None:
        self.width = width
        self.height = height
        self.padding = max(0, padding)
        self.allow_rotation = allow_rotation
        self.free_rects = [Rect(0, 0, width, height)]
        self.used_rects: list[Rect] = []

    def insert(self, source_id: str, width: int, height: int) -> PackedRect | None:
        candidates = [(width, height, False)]
        if self.allow_rotation and width != height:
            candidates.append((height, width, True))

        best_free: Rect | None = None
        best_size: tuple[int, int, bool] | None = None
        best_score: tuple[int, int] | None = None
        for candidate_width, candidate_height, rotated in candidates:
            packed_width = candidate_width + self.padding * 2
            packed_height = candidate_height + self.padding * 2
            for free in self.free_rects:
                if packed_width > free.width or packed_height > free.height:
                    continue
                leftover_width = free.width - packed_width
                leftover_height = free.height - packed_height
                score = (min(leftover_width, leftover_height), max(leftover_width, leftover_height))
                if best_score is None or score < best_score:
                    best_score = score
                    best_free = free
                    best_size = (candidate_width, candidate_height, rotated)

        if best_free is None or best_size is None:
            return None

        placed = PackedRect(
            x=best_free.x + self.padding,
            y=best_free.y + self.padding,
            width=best_size[0],
            height=best_size[1],
            source_id=source_id,
            rotated=best_size[2],
        )
        used_with_padding = Rect(best_free.x, best_free.y, placed.width + self.padding * 2, placed.height + self.padding * 2)
        self._split_free_rects(used_with_padding)
        self._prune_free_rects()
        self.used_rects.append(used_with_padding)
        return placed

    def _split_free_rects(self, used: Rect) -> None:
        next_free: list[Rect] = []
        for free in self.free_rects:
            if not rects_intersect(free, used):
                next_free.append(free)
                continue

            if used.x > free.x:
                next_free.append(Rect(free.x, free.y, used.x - free.x, free.height))
            if used.right < free.right:
                next_free.append(Rect(used.right, free.y, free.right - used.right, free.height))
            if used.y > free.y:
                next_free.append(Rect(free.x, free.y, free.width, used.y - free.y))
            if used.bottom < free.bottom:
                next_free.append(Rect(free.x, used.bottom, free.width, free.bottom - used.bottom))

        self.free_rects = [rect for rect in next_free if rect.width > 0 and rect.height > 0]

    def _prune_free_rects(self) -> None:
        pruned: list[Rect] = []
        for index, rect in enumerate(self.free_rects):
            contained = False
            for other_index, other in enumerate(self.free_rects):
                if index != other_index and rect_contains(other, rect):
                    contained = True
                    break
            if not contained:
                pruned.append(rect)
        self.free_rects = pruned


def pack_records_into_atlases(records: list[SpriteRecord], out_dir: Path, options: RunOptions) -> list[dict[str, object]]:
    atlas_dir = out_dir / "atlases"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[SpriteRecord]] = {}
    for record in records:
        groups.setdefault(record.category, []).append(record)

    atlas_summaries: list[dict[str, object]] = []
    for group_name, group_records in sorted(groups.items()):
        pending = sorted(group_records, key=lambda record: max(record.width, record.height), reverse=True)
        atlas_index = 1
        while pending:
            largest_width = max(record.width for record in pending) + options.atlas_padding * 2
            largest_height = max(record.height for record in pending) + options.atlas_padding * 2
            atlas_size = max(options.atlas_size, largest_width, largest_height)
            packer = MaxRectsPacker(atlas_size, atlas_size, options.atlas_padding, options.atlas_allow_rotation)
            placements: list[tuple[SpriteRecord, PackedRect]] = []
            still_pending: list[SpriteRecord] = []

            for record in pending:
                placed = packer.insert(record.id, record.width, record.height)
                if placed is None:
                    still_pending.append(record)
                else:
                    placements.append((record, placed))

            if not placements:
                raise SystemExit(f"Could not pack sprites in group {group_name}; atlas size is too small.")

            safe_group = safe_name(group_name) or "sprites"
            atlas_name = f"{safe_group}_atlas_{atlas_index:03d}"
            atlas_path = atlas_dir / f"{atlas_name}.png"
            atlas_json_path = atlas_dir / f"{atlas_name}.json"
            atlas_image = Image.new("RGBA", (atlas_size, atlas_size), (255, 255, 255, 0))
            frames: list[dict[str, object]] = []

            for record, placed in placements:
                sprite = Image.open(record.output_file).convert("RGBA")
                if placed.rotated:
                    sprite = sprite.rotate(90, expand=True)
                atlas_image.alpha_composite(sprite, (placed.x, placed.y))
                sprite.close()

                rect = {"x": placed.x, "y": placed.y, "width": placed.width, "height": placed.height}
                record.atlas = {
                    "atlas": atlas_path.name,
                    "atlas_file": str(atlas_path),
                    "group": group_name,
                    "rect": rect,
                    "rotated": placed.rotated,
                }
                frames.append(
                    {
                        "atlas": atlas_path.name,
                        "group": group_name,
                        "source_id": record.id,
                        "source_file": record.output_file,
                        "category": record.category,
                        "sequence": record.sequence,
                        "frame": record.frame,
                        "rect": rect,
                        "rotated": placed.rotated,
                        "pivot": record.pivot,
                        "is_partial": record.is_partial,
                    }
                )

            atlas_image.save(atlas_path)
            atlas_data = {
                "atlas": atlas_path.name,
                "atlas_file": str(atlas_path),
                "group": group_name,
                "width": atlas_size,
                "height": atlas_size,
                "padding": options.atlas_padding,
                "frames": frames,
            }
            with atlas_json_path.open("w", encoding="utf-8") as handle:
                json.dump(atlas_data, handle, indent=2)
            atlas_summaries.append(atlas_data)

            pending = still_pending
            atlas_index += 1

    manifest_dir = out_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    with (manifest_dir / "atlases.json").open("w", encoding="utf-8") as handle:
        json.dump({"atlases": atlas_summaries}, handle, indent=2)
    return atlas_summaries


def sprite_export_entry(record: SpriteRecord) -> dict[str, object]:
    return {
        "name": record.id,
        "display_name": record.display_name,
        "kind": record.kind,
        "category": record.category,
        "sequence": record.sequence,
        "frame": record.frame,
        "source_file": record.output_file,
        "source_rect": record.bbox,
        "size": {"width": record.width, "height": record.height},
        "pivot": record.pivot,
        "atlas": record.atlas,
        "is_partial": record.is_partial,
        "confidence": record.confidence,
        "review_flags": record.review_flags,
        "review_status": record.review_status,
    }


def build_animation_clips(records: list[SpriteRecord], frame_rate: int) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[SpriteRecord]] = {}
    for record in records:
        if record.kind != "animation_frame" or not record.sequence:
            continue
        grouped.setdefault((record.source_sheet, record.sequence), []).append(record)

    clips: list[dict[str, object]] = []
    duration = round(1.0 / max(1, frame_rate), 4)
    for (source_sheet, sequence), frames in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        ordered = sorted(frames, key=lambda record: record.frame if record.frame is not None else 0)
        clips.append(
            {
                "name": f"{source_sheet}_{sequence}",
                "source_sheet": source_sheet,
                "sequence": sequence,
                "frame_rate": max(1, frame_rate),
                "loop": True,
                "frame_count": len(ordered),
                "frames": [
                    {
                        "sprite": record.id,
                        "display_name": record.display_name,
                        "frame": record.frame,
                        "source_file": record.output_file,
                        "duration": duration,
                        "bbox": record.bbox,
                        "pivot": record.pivot,
                        "atlas": record.atlas,
                        "review_status": record.review_status,
                    }
                    for record in ordered
                ],
            }
        )
    return clips


def godot_animation_clips(animation_clips: list[dict[str, object]]) -> list[dict[str, object]]:
    animations: list[dict[str, object]] = []
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
                    for frame in clip["frames"]  # type: ignore[index]
                ],
            }
        )
    return animations


def unreal_flipbooks(animation_clips: list[dict[str, object]]) -> list[dict[str, object]]:
    flipbooks: list[dict[str, object]] = []
    for clip in animation_clips:
        frames = []
        for index, frame in enumerate(clip["frames"]):  # type: ignore[index]
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


def load_existing_records(manifest_dir: Path) -> list[SpriteRecord]:
    sprites_path = manifest_dir / "sprites.json"
    if not sprites_path.exists():
        return []
    data = json.loads(sprites_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    records: list[SpriteRecord] = []
    record_fields = set(SpriteRecord.__dataclass_fields__)
    for item in data:
        if isinstance(item, dict):
            records.append(SpriteRecord(**{key: value for key, value in item.items() if key in record_fields}))
    return records


def load_existing_errors(manifest_dir: Path) -> list[SheetError]:
    errors_path = manifest_dir / "errors.json"
    if not errors_path.exists():
        return []
    data = json.loads(errors_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [SheetError(**item) for item in data if isinstance(item, dict)]


def write_engine_exports(records: list[SpriteRecord], out_dir: Path, engines: list[str], animation_clips: list[dict[str, object]]) -> None:
    if not engines:
        return

    exports_dir = out_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    base_entries = [sprite_export_entry(record) for record in records]
    import_settings = {
        "texture_type": "sprite",
        "sprite_mode": "multiple",
        "filter_mode": "point",
        "compression": "none",
        "alpha_is_transparency": True,
    }

    if "unity" in engines:
        with (exports_dir / "unity_sprites.json").open("w", encoding="utf-8") as handle:
            json.dump({"engine": "unity", "import_settings": import_settings, "sprites": base_entries, "animation_clips": animation_clips}, handle, indent=2)

    if "godot" in engines:
        godot_entries = []
        for entry in base_entries:
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
                    "animations": godot_animation_clips(animation_clips),
                },
                handle,
                indent=2,
            )

    if "unreal" in engines:
        unreal_entries = []
        for entry in base_entries:
            unreal_entry = dict(entry)
            unreal_entry["pivot"] = {"x": entry["pivot"]["x"], "y": round(1.0 - float(entry["pivot"]["y"]), 4), "method": entry["pivot"]["method"]}
            unreal_entries.append(unreal_entry)
        with (exports_dir / "unreal_sprites.json").open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "engine": "unreal",
                    "import_settings": {"texture_group": "2D Pixels", "compression": "UserInterface2D", "filter": "Nearest"},
                    "sprites": unreal_entries,
                    "flipbooks": unreal_flipbooks(animation_clips),
                },
                handle,
                indent=2,
            )


def relative_link(from_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(Path(target).resolve(), start=from_dir.resolve())).as_posix()


def write_html_report(
    records: list[SpriteRecord],
    manifest_dir: Path,
    sheets_processed: int,
    sheet_errors: list[SheetError],
    animation_clips: list[dict[str, object]] | None = None,
) -> None:
    category_counts = Counter(record.category for record in records)
    kind_counts = Counter(record.kind for record in records)
    sheet_counts = Counter(record.source_sheet for record in records)
    flag_counts = Counter(flag for record in records for flag in record.review_flags)
    partial_count = sum(1 for record in records if record.is_partial)
    needs_review_count = sum(1 for record in records if record.review_status == "needs_review")
    atlased_count = sum(1 for record in records if record.atlas)
    atlas_names = sorted({str(record.atlas["atlas"]) for record in records if record.atlas})
    sample_records = records[:80]

    rows = []
    thumb_cards = []
    clip_cards = []
    for clip in animation_clips or []:
        frames_html = []
        frames = clip.get("frames", [])
        if isinstance(frames, list):
            for frame in frames:
                if not isinstance(frame, dict):
                    continue
                source_file = frame.get("source_file")
                if not source_file:
                    continue
                frame_link = html.escape(relative_link(manifest_dir, Path(str(source_file))))
                frames_html.append(
                    "<a class=\"clip-frame\" href=\"{href}\">"
                    "<img src=\"{href}\" loading=\"lazy\" alt=\"{alt}\">"
                    "<span>{label}</span>"
                    "</a>".format(
                        href=frame_link,
                        alt=html.escape(str(frame.get("sprite", "frame"))),
                        label=html.escape(str(frame.get("frame", frame.get("sprite", "")))),
                    )
                )
        clip_cards.append(
            "<section class=\"card clip-card\" data-clip=\"{clip_name}\">"
            "<h3>{clip_name}</h3>"
            "<p>{frame_count} frames | {frame_rate} fps | loop={loop}</p>"
            "<div class=\"clip-strip\">{frames}</div>"
            "</section>".format(
                clip_name=html.escape(str(clip.get("name", "clip"))),
                frame_count=html.escape(str(clip.get("frame_count", 0))),
                frame_rate=html.escape(str(clip.get("frame_rate", ""))),
                loop=html.escape(str(clip.get("loop", ""))),
                frames="".join(frames_html),
            )
        )
    for record in records:
        preview_link = html.escape(relative_link(manifest_dir, Path(record.output_file)))
        safe_id = html.escape(record.id)
        safe_category = html.escape(record.category)
        safe_flags = html.escape(" ".join(record.review_flags))
        safe_status = html.escape(record.review_status)
        atlas_name = html.escape(str(record.atlas.get("atlas", ""))) if record.atlas else ""
        thumb_cards.append(
            "<a class=\"thumb-card\" href=\"{href}\" data-status=\"{status}\" data-flags=\"{flags}\" data-category=\"{category}\">"
            "<span class=\"thumb-frame\"><img src=\"{href}\" loading=\"lazy\" alt=\"{alt}\"></span>"
            "<span class=\"thumb-name\">{name}</span>"
            "<span class=\"thumb-meta\">{category} | {width}x{height} | {status}</span>"
            "</a>".format(
                href=preview_link,
                alt=safe_id,
                name=html.escape(record.display_name),
                category=safe_category,
                flags=safe_flags,
                width=record.width,
                height=record.height,
                status=safe_status,
            )
        )

    for record in sample_records:
        preview_link = html.escape(relative_link(manifest_dir, Path(record.output_file)))
        safe_category = html.escape(record.category)
        atlas_name = html.escape(str(record.atlas.get("atlas", ""))) if record.atlas else ""
        rows.append(
            "<tr>"
            f"<td><a href=\"{preview_link}\">{html.escape(record.display_name)}</a></td>"
            f"<td>{safe_category}</td>"
            f"<td>{html.escape(record.kind)}</td>"
            f"<td>{record.width}x{record.height}</td>"
            f"<td>{html.escape(str(record.is_partial))}</td>"
            f"<td>{record.confidence:.3f}</td>"
            f"<td>{html.escape(', '.join(record.review_flags) or 'none')}</td>"
            f"<td>{html.escape(str(record.pivot.get('x', '')))}, {html.escape(str(record.pivot.get('y', '')))}</td>"
            f"<td>{atlas_name}</td>"
            "</tr>"
        )

    category_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(category_counts.items()))
    kind_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(kind_counts.items()))
    sheet_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(sheet_counts.items()))
    flag_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(flag_counts.items())) or "<li>None</li>"
    atlas_items = "".join(f"<li>{html.escape(name)}</li>" for name in atlas_names) or "<li>None</li>"
    error_items = (
        "".join(f"<li>{html.escape(Path(error.source_file).name)}: {html.escape(error.error)}</li>" for error in sheet_errors)
        or "<li>None</li>"
    )

    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sprite Sheet Processing Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #15171c; color: #e8ebf2; }}
    a {{ color: #80b7ff; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
    .card {{ background: #20242b; border: 1px solid #343a46; border-radius: 6px; padding: 14px; }}
    .filters {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 12px 0; }}
    .filters input, .filters select {{ background: #111318; color: #e8ebf2; border: 1px solid #343a46; border-radius: 4px; padding: 7px; }}
    .thumb-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin-top: 12px; }}
    .thumb-card {{ display: grid; gap: 7px; color: #e8ebf2; text-decoration: none; background: #20242b; border: 1px solid #343a46; border-radius: 6px; padding: 10px; min-width: 0; }}
    .thumb-card:hover {{ border-color: #80b7ff; }}
    .thumb-card.hidden {{ display: none; }}
    .thumb-frame {{ display: grid; place-items: center; height: 96px; border-radius: 4px; background-color: #2a2f39; background-image: linear-gradient(45deg, #39404c 25%, transparent 25%), linear-gradient(-45deg, #39404c 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #39404c 75%), linear-gradient(-45deg, transparent 75%, #39404c 75%); background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0; }}
    .thumb-frame img {{ max-width: 96%; max-height: 90px; image-rendering: pixelated; }}
    .thumb-name {{ overflow-wrap: anywhere; font-size: 12px; }}
    .thumb-meta {{ color: #aeb8cc; font-size: 12px; }}
    .clip-strip {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }}
    .clip-frame {{ display: grid; gap: 4px; min-width: 72px; color: #e8ebf2; text-decoration: none; text-align: center; font-size: 12px; }}
    .clip-frame img {{ max-width: 72px; max-height: 72px; image-rendering: pixelated; background: #2a2f39; border-radius: 4px; padding: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #343a46; padding: 8px; text-align: left; font-size: 13px; }}
    th {{ color: #aeb8cc; }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
  </style>
</head>
<body>
  <h1>Sprite Sheet Processing Report</h1>
  <div class="grid">
    <section class="card">
      <h2>Run Summary</h2>
      <p>total_sprites: {len(records)}</p>
      <p>sheets_processed: {sheets_processed}</p>
      <p>sheets_failed: {len(sheet_errors)}</p>
      <p>partial_sprites: {partial_count}</p>
      <p>needs_review: {needs_review_count}</p>
      <p>atlased_sprites: {atlased_count}</p>
      <p>atlases: {len(atlas_names)}</p>
      <p><a href="../project.spritecut.json">project.spritecut.json</a></p>
      <p><a href="settings.json">settings.json</a></p>
      <p><a href="visual_qa.html">visual_qa.html</a></p>
    </section>
    <section class="card"><h2>By Kind</h2><ul>{kind_items}</ul></section>
    <section class="card"><h2>By Category</h2><ul>{category_items}</ul></section>
    <section class="card"><h2>By Sheet</h2><ul>{sheet_items}</ul></section>
    <section class="card"><h2>Review Flags</h2><ul>{flag_items}</ul></section>
    <section class="card"><h2>Atlases</h2><ul>{atlas_items}</ul></section>
    <section class="card"><h2>Errors</h2><ul>{error_items}</ul></section>
  </div>
  <h2>Sprite Preview</h2>
  <section class="filters" aria-label="Review Filters">
    <strong>Review Filters</strong>
    <select id="statusFilter" onchange="filterSprites()">
      <option value="all">All statuses</option>
      <option value="needs_review">Needs review</option>
      <option value="approved">Approved</option>
    </select>
    <input id="flagFilter" type="search" placeholder="flag or category" oninput="filterSprites()">
  </section>
  <div class="thumb-grid">
    {''.join(thumb_cards)}
  </div>
  <h2>Animation Clips</h2>
  <div class="grid">
    {''.join(clip_cards) or '<section class="card"><p>No animation clips.</p></section>'}
  </div>
  <h2>Sample Records</h2>
  <table>
    <thead><tr><th>Name</th><th>Category</th><th>Kind</th><th>Size</th><th>Partial</th><th>Confidence</th><th>Flags</th><th>Pivot</th><th>Atlas</th></tr></thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <script>
    function filterSprites() {{
      const status = document.getElementById("statusFilter").value;
      const query = document.getElementById("flagFilter").value.trim().toLowerCase();
      for (const card of document.querySelectorAll(".thumb-card")) {{
        const statusOk = status === "all" || card.dataset.status === status;
        const haystack = `${{card.dataset.flags}} ${{card.dataset.category}} ${{card.textContent}}`.toLowerCase();
        const queryOk = !query || haystack.includes(query);
        card.classList.toggle("hidden", !(statusOk && queryOk));
      }}
    }}
  </script>
</body>
</html>
"""
    (manifest_dir / "report.html").write_text(report, encoding="utf-8")


def write_visual_regression_report(out_dir: Path, manifest_dir: Path) -> None:
    preview_dir = out_dir / "previews"
    artifacts: list[dict[str, object]] = []
    if preview_dir.exists():
        for path in sorted(preview_dir.rglob("*.png"), key=lambda item: item.as_posix().lower()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts.append(
                {
                    "file": relative_link(manifest_dir, path),
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                }
            )
    with (manifest_dir / "visual_regression.json").open("w", encoding="utf-8") as handle:
        json.dump({"preview_artifacts": artifacts}, handle, indent=2)


def _safe_open_sprite(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as image:
            return image.convert("RGBA").copy()
    except Exception:
        return None


def _hue_shift_preview(image: Image.Image, degrees: float) -> Image.Image:
    rgba = image.convert("RGBA")
    data = np.array(rgba, dtype=np.uint8)
    alpha = data[:, :, 3]
    height, width = alpha.shape
    shift = (degrees % 360.0) / 360.0
    for y in range(height):
        for x in range(width):
            if alpha[y, x] == 0:
                continue
            r, g, b = data[y, x, :3] / 255.0
            h, s, v = colorsys.rgb_to_hsv(float(r), float(g), float(b))
            nr, ng, nb = colorsys.hsv_to_rgb((h + shift) % 1.0, s, v)
            data[y, x, 0] = int(round(nr * 255))
            data[y, x, 1] = int(round(ng * 255))
            data[y, x, 2] = int(round(nb * 255))
    return Image.fromarray(data, "RGBA")


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    draw.text(xy, text, fill=(32, 34, 40), font=ImageFont.load_default())


def _write_palette_change_sample(record: SpriteRecord, out_path: Path) -> bool:
    source = _safe_open_sprite(record.output_file)
    if source is None:
        return False
    variants = [
        ("original", source),
        ("hue +90", _hue_shift_preview(source, 90)),
        ("hue +180", _hue_shift_preview(source, 180)),
    ]
    max_thumb = 72
    label_height = 18
    swatch_height = 20
    cell_w = max_thumb + 18
    cell_h = max_thumb + label_height + swatch_height + 18
    sheet = Image.new("RGBA", (cell_w * len(variants), cell_h), (248, 248, 248, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(variants):
        thumb = image.copy()
        thumb.thumbnail((max_thumb, max_thumb), Image.Resampling.NEAREST)
        x = index * cell_w
        checker = render_checker((max_thumb, max_thumb))
        sheet.alpha_composite(checker, (x + 9, 8))
        sheet.alpha_composite(thumb, (x + 9 + (max_thumb - thumb.width) // 2, 8 + (max_thumb - thumb.height) // 2))
        _draw_label(draw, (x + 8, max_thumb + 12), label)
        for color_index, color in enumerate(record.dominant_colors[:4]):
            sx = x + 8 + color_index * 16
            sy = max_thumb + label_height + 13
            draw.rectangle((sx, sy, sx + 12, sy + 12), fill=_parse_hex_color(color), outline=(48, 52, 60))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path)
    return True


def _erase_autotile_edges(tile: Image.Image, mask: int, edge_width: int) -> Image.Image:
    output = tile.convert("RGBA").copy()
    draw = ImageDraw.Draw(output)
    width, height = output.size
    edge_width = max(1, edge_width)
    transparent = (0, 0, 0, 0)
    if not mask & 1:
        draw.rectangle((0, 0, width - 1, edge_width - 1), fill=transparent)
    if not mask & 4:
        draw.rectangle((0, height - edge_width, width - 1, height - 1), fill=transparent)
    if not mask & 8:
        draw.rectangle((0, 0, edge_width - 1, height - 1), fill=transparent)
    if not mask & 2:
        draw.rectangle((width - edge_width, 0, width - 1, height - 1), fill=transparent)
    return output


def _write_autotile_variant_sample(record: SpriteRecord, out_path: Path) -> bool:
    source = _safe_open_sprite(record.output_file)
    if source is None:
        return False
    tile = source.copy()
    tile.thumbnail((32, 32), Image.Resampling.NEAREST)
    if tile.width == 0 or tile.height == 0:
        return False
    edge_width = max(1, min(tile.width, tile.height) // 4)
    cell_w = tile.width + 6
    cell_h = tile.height + 16
    sheet = Image.new("RGBA", (cell_w * 4, cell_h * 4), (248, 248, 248, 255))
    draw = ImageDraw.Draw(sheet)
    for mask in range(16):
        col = mask % 4
        row = mask // 4
        x = col * cell_w
        y = row * cell_h
        checker = render_checker(tile.size, cell=4)
        variant = _erase_autotile_edges(tile, mask, edge_width)
        sheet.alpha_composite(checker, (x + 3, y + 3))
        sheet.alpha_composite(variant, (x + 3, y + 3))
        _draw_label(draw, (x + 3, y + tile.height + 5), f"{mask:02d}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path)
    return True


def write_visual_qa_report(records: list[SpriteRecord], out_dir: Path, manifest_dir: Path) -> None:
    preview_dir = out_dir / "previews"
    qa_dir = preview_dir / "visual_qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    before_after_sheets: list[dict[str, str]] = []
    for sheet_name in sorted({record.source_sheet for record in records}):
        boxes = preview_dir / f"{sheet_name}_boxes.png"
        contact = preview_dir / f"{sheet_name}_contact.png"
        if boxes.exists() or contact.exists():
            before_after_sheets.append(
                {
                    "sheet": sheet_name,
                    "before": relative_link(manifest_dir, boxes) if boxes.exists() else "",
                    "after": relative_link(manifest_dir, contact) if contact.exists() else "",
                }
            )

    flagged_records = [record for record in records if record.review_status == "needs_review" or record.review_flags]
    flagged_crop_issues = [
        {
            "id": record.id,
            "category": record.category,
            "flags": record.review_flags,
            "confidence": record.confidence,
            "sprite": relative_link(manifest_dir, Path(record.output_file)),
            "source_sheet": record.source_sheet,
        }
        for record in flagged_records[:80]
    ]

    palette_change_samples: list[dict[str, str]] = []
    for record in records[:8]:
        sample_path = qa_dir / f"{safe_name(record.id)}_palette_changes.png"
        if _write_palette_change_sample(record, sample_path):
            palette_change_samples.append(
                {
                    "id": record.id,
                    "sample": relative_link(manifest_dir, sample_path),
                    "dominant_colors": ", ".join(record.dominant_colors),
                }
            )

    autotile_variant_samples: list[dict[str, str]] = []
    autotile_candidates = [record for record in records if record.kind == "sprite"][:4]
    for record in autotile_candidates:
        sample_path = qa_dir / f"{safe_name(record.id)}_autotile_16.png"
        if _write_autotile_variant_sample(record, sample_path):
            autotile_variant_samples.append(
                {
                    "id": record.id,
                    "sample": relative_link(manifest_dir, sample_path),
                    "mode": "cardinal_16",
                }
            )

    manifest = {
        "before_after_sheets": before_after_sheets,
        "flagged_crop_issues": flagged_crop_issues,
        "palette_change_samples": palette_change_samples,
        "autotile_variant_samples": autotile_variant_samples,
    }
    (manifest_dir / "visual_qa.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    before_after_cards = []
    for item in before_after_sheets:
        before = html.escape(item["before"])
        after = html.escape(item["after"])
        before_after_cards.append(
            "<section class=\"card before-after\">"
            f"<h3>{html.escape(item['sheet'])}</h3>"
            "<div class=\"pair\">"
            f"<a href=\"{before}\"><span>Before</span><img src=\"{before}\" loading=\"lazy\" alt=\"before boxes\"></a>"
            f"<a href=\"{after}\"><span>After</span><img src=\"{after}\" loading=\"lazy\" alt=\"after contact sheet\"></a>"
            "</div></section>"
        )

    flagged_rows = "".join(
        "<tr>"
        f"<td><a href=\"{html.escape(item['sprite'])}\">{html.escape(item['id'])}</a></td>"
        f"<td>{html.escape(item['category'])}</td>"
        f"<td>{html.escape(', '.join(item['flags']) or 'none')}</td>"
        f"<td>{html.escape(str(item['confidence']))}</td>"
        f"<td>{html.escape(item['source_sheet'])}</td>"
        "</tr>"
        for item in flagged_crop_issues
    )
    palette_cards = "".join(
        "<a class=\"sample-card\" href=\"{sample}\"><img src=\"{sample}\" loading=\"lazy\" alt=\"palette sample\"><span>{label}</span><small>{colors}</small></a>".format(
            sample=html.escape(item["sample"]),
            label=html.escape(item["id"]),
            colors=html.escape(item["dominant_colors"]),
        )
        for item in palette_change_samples
    )
    autotile_cards = "".join(
        "<a class=\"sample-card\" href=\"{sample}\"><img src=\"{sample}\" loading=\"lazy\" alt=\"autotile sample\"><span>{label}</span><small>{mode}</small></a>".format(
            sample=html.escape(item["sample"]),
            label=html.escape(item["id"]),
            mode=html.escape(item["mode"]),
        )
        for item in autotile_variant_samples
    )

    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Visual QA Review</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #15171c; color: #e8ebf2; }}
    a {{ color: #80b7ff; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
    .card, .sample-card {{ background: #20242b; border: 1px solid #343a46; border-radius: 6px; padding: 14px; color: #e8ebf2; text-decoration: none; }}
    .pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .pair a, .sample-card {{ display: grid; gap: 8px; min-width: 0; }}
    img {{ max-width: 100%; image-rendering: pixelated; background: #2a2f39; border-radius: 4px; }}
    .samples {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }}
    small {{ color: #aeb8cc; overflow-wrap: anywhere; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
    th, td {{ border-bottom: 1px solid #343a46; padding: 8px; text-align: left; font-size: 13px; }}
    th {{ color: #aeb8cc; }}
  </style>
</head>
<body>
  <h1>Visual QA Review</h1>
  <p><a href="report.html">Back to main report</a> | <a href="visual_qa.json">visual_qa.json</a></p>
  <h2>Before / After Crop Sheets</h2>
  <div class="grid">{''.join(before_after_cards) or '<section class="card"><p>No crop sheet previews found.</p></section>'}</div>
  <h2>Flagged Crop Issues</h2>
  <table>
    <thead><tr><th>Sprite</th><th>Category</th><th>Flags</th><th>Confidence</th><th>Source Sheet</th></tr></thead>
    <tbody>{flagged_rows or '<tr><td colspan="5">No flagged crop issues.</td></tr>'}</tbody>
  </table>
  <h2>Palette Change Samples</h2>
  <div class="samples">{palette_cards or '<section class="card"><p>No palette samples generated.</p></section>'}</div>
  <h2>Autotile Variant Samples</h2>
  <div class="samples">{autotile_cards or '<section class="card"><p>No autotile samples generated.</p></section>'}</div>
</body>
</html>
"""
    (manifest_dir / "visual_qa.html").write_text(report, encoding="utf-8")


def write_project_file(
    records: list[SpriteRecord],
    out_dir: Path,
    options: RunOptions,
    sheets_processed: int,
    sheet_errors: list[SheetError],
    animation_clips: list[dict[str, object]],
) -> None:
    project = {
        "schema_version": 1,
        "tool": "spritecut",
        "settings": asdict(options),
        "summary": {
            "total_sprites": len(records),
            "sheets_processed": sheets_processed,
            "sheets_failed": len(sheet_errors),
            "needs_review": sum(1 for record in records if record.review_status == "needs_review"),
        },
        "errors": [asdict(error) for error in sheet_errors],
        "history": [],
        "redo_stack": [],
        "animation_clips": animation_clips,
        "sprites": [asdict(record) for record in records],
    }
    with (out_dir / "project.spritecut.json").open("w", encoding="utf-8") as handle:
        json.dump(project, handle, indent=2)


def write_manifest(
    records: list[SpriteRecord],
    manifest_dir: Path,
    sheets_processed: int,
    sheet_errors: list[SheetError],
    options: RunOptions | None = None,
    animation_clips: list[dict[str, object]] | None = None,
) -> None:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    with (manifest_dir / "sprites.json").open("w", encoding="utf-8") as handle:
        json.dump([asdict(record) for record in records], handle, indent=2)
    with (manifest_dir / "errors.json").open("w", encoding="utf-8") as handle:
        json.dump([asdict(error) for error in sheet_errors], handle, indent=2)
    if animation_clips is not None:
        with (manifest_dir / "animation_clips.json").open("w", encoding="utf-8") as handle:
            json.dump({"animation_clips": animation_clips}, handle, indent=2)
    if options is not None:
        with (manifest_dir / "settings.json").open("w", encoding="utf-8") as handle:
            json.dump(asdict(options), handle, indent=2)

    with (manifest_dir / "sprites.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "display_name",
                "source_sheet",
                "kind",
                "sheet_mode",
                "category",
                "sequence",
                "frame",
                "output_file",
                "x",
                "y",
                "width",
                "height",
                "slot_width",
                "slot_height",
                "foreground_pixels",
                "alpha_mode",
                "is_partial",
                "transparency_ratio",
                "aspect_ratio",
                "dominant_colors",
                "pivot_x",
                "pivot_y",
                "pivot_method",
                "confidence",
                "review_flags",
                "review_status",
                "atlas_name",
                "atlas_x",
                "atlas_y",
                "atlas_width",
                "atlas_height",
                "atlas_rotated",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "id": record.id,
                    "display_name": record.display_name,
                    "source_sheet": record.source_sheet,
                    "kind": record.kind,
                    "sheet_mode": record.sheet_mode,
                    "category": record.category,
                    "sequence": record.sequence if record.sequence is not None else "",
                    "frame": record.frame if record.frame is not None else "",
                    "output_file": record.output_file,
                    "x": record.bbox["x"],
                    "y": record.bbox["y"],
                    "width": record.width,
                    "height": record.height,
                    "slot_width": record.slot_width if record.slot_width is not None else "",
                    "slot_height": record.slot_height if record.slot_height is not None else "",
                    "foreground_pixels": record.foreground_pixels,
                    "alpha_mode": record.alpha_mode,
                    "is_partial": record.is_partial,
                    "transparency_ratio": record.transparency_ratio,
                    "aspect_ratio": record.aspect_ratio,
                    "dominant_colors": "|".join(record.dominant_colors),
                    "pivot_x": record.pivot.get("x", ""),
                    "pivot_y": record.pivot.get("y", ""),
                    "pivot_method": record.pivot.get("method", ""),
                    "confidence": record.confidence,
                    "review_flags": "|".join(record.review_flags),
                    "review_status": record.review_status,
                    "atlas_name": record.atlas.get("atlas", "") if record.atlas else "",
                    "atlas_x": record.atlas.get("rect", {}).get("x", "") if record.atlas else "",
                    "atlas_y": record.atlas.get("rect", {}).get("y", "") if record.atlas else "",
                    "atlas_width": record.atlas.get("rect", {}).get("width", "") if record.atlas else "",
                    "atlas_height": record.atlas.get("rect", {}).get("height", "") if record.atlas else "",
                    "atlas_rotated": record.atlas.get("rotated", "") if record.atlas else "",
                }
            )

    category_counts = Counter(record.category for record in records)
    kind_counts = Counter(record.kind for record in records)
    sheet_counts = Counter(record.source_sheet for record in records)
    sequence_counts = Counter(record.sequence for record in records if record.sequence)
    partial_count = sum(1 for record in records if record.is_partial)
    needs_review_count = sum(1 for record in records if record.review_status == "needs_review")
    atlased_count = sum(1 for record in records if record.atlas)
    summary = [
        f"total_sprites={len(records)}",
        f"sheets_processed={sheets_processed}",
        f"sheets_failed={len(sheet_errors)}",
        f"partial_sprites={partial_count}",
        f"needs_review={needs_review_count}",
        f"atlased_sprites={atlased_count}",
        "",
        "by_kind:",
        *[f"{kind}={count}" for kind, count in sorted(kind_counts.items())],
        "",
        "by_category:",
        *[f"{category}={count}" for category, count in sorted(category_counts.items())],
        "",
        "by_sequence:",
        *[f"{sequence}={count}" for sequence, count in sorted(sequence_counts.items())],
        "",
        "by_sheet:",
        *[f"{sheet}={count}" for sheet, count in sorted(sheet_counts.items())],
    ]
    (manifest_dir / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    write_visual_qa_report(records, manifest_dir.parent, manifest_dir)
    write_visual_regression_report(manifest_dir.parent, manifest_dir)
    write_html_report(records, manifest_dir, sheets_processed, sheet_errors, animation_clips)


def main() -> None:
    raw_argv = sys.argv[1:]
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", type=Path, help="JSON config file containing default CLI options.")
    pre_parser.add_argument("--preset", choices=sorted(BUILT_IN_PRESETS), help="Built-in preset to use before optional --config overrides.")
    pre_parser.add_argument("--list-presets", action="store_true", help="Print built-in preset names and exit.")
    pre_args, _remaining = pre_parser.parse_known_args()
    if pre_args.list_presets:
        for name in sorted(BUILT_IN_PRESETS):
            print(name)
        return
    config_defaults = load_config_defaults(pre_args.config, pre_args.preset)

    parser = argparse.ArgumentParser(
        description="Cut packed tileset sheets or row-based animation sheets into organized sprite crops.",
        parents=[pre_parser],
    )
    parser.add_argument("root", type=Path, help="Image file or folder containing sprite sheets.")
    parser.add_argument(
        "--auto-detect-all",
        dest="auto_detect_all",
        action="store_true",
        default=bool(config_defaults.get("auto_detect_all", True)),
        help="Infer background, thresholds, atlas/export defaults, workers, and animation FPS from the input sheets.",
    )
    parser.add_argument(
        "--manual-defaults",
        dest="auto_detect_all",
        action="store_false",
        help="Use literal CLI/config defaults instead of auto-inferring a processing profile.",
    )
    parser.add_argument("--out-name", default=config_defaults.get("out_name", "_organized_sprites"), help="Name for the output folder created beside the input.")
    parser.add_argument(
        "--mode",
        choices=["auto", "tileset", "animation"],
        default=config_defaults.get("mode", "auto"),
        help="auto detects animation-like sheets; tileset forces category folders; animation forces row/frame folders.",
    )
    parser.add_argument(
        "--animation-names",
        default=config_defaults.get("animation_names", ""),
        help="Comma-separated sequence names for animation rows, for example idle,run,attack.",
    )
    parser.add_argument(
        "--animation-frame-mode",
        choices=["fixed", "trimmed"],
        default=config_defaults.get("animation_frame_mode", "fixed"),
        help="fixed keeps each row on same-sized canvases; trimmed exports tight crops.",
    )
    parser.add_argument(
        "--animation-anchor",
        choices=["bottom-center", "center"],
        default=config_defaults.get("animation_anchor", "bottom-center"),
        help="Anchor used when placing trimmed sprites on fixed animation canvases.",
    )
    parser.add_argument(
        "--animation-min-frames",
        type=int,
        default=config_defaults.get("animation_min_frames", 3),
        help="Minimum frames per row for auto animation detection.",
    )
    parser.add_argument(
        "--animation-fps",
        type=int,
        default=config_defaults.get("animation_fps", 8),
        help="Frame rate written into generated animation clip metadata.",
    )
    parser.add_argument(
        "--pivot-debug",
        action="store_true",
        default=bool(config_defaults.get("pivot_debug", False)),
        help="Save per-sprite debug previews with contours and pivot crosses.",
    )
    parser.add_argument(
        "--pack-atlases",
        dest="pack_atlases",
        action="store_true",
        default=bool(config_defaults.get("pack_atlases", False)),
        help="Pack extracted sprites into category atlases after cutting.",
    )
    parser.add_argument(
        "--no-pack-atlases",
        dest="pack_atlases",
        action="store_false",
        help="Disable atlas packing even when --auto-detect-all would enable it.",
    )
    parser.add_argument(
        "--atlas-size",
        type=int,
        default=config_defaults.get("atlas_size", 2048),
        help="Square atlas size used when --pack-atlases is enabled.",
    )
    parser.add_argument(
        "--atlas-padding",
        type=int,
        default=config_defaults.get("atlas_padding", 2),
        help="Padding in pixels around sprites in generated atlases.",
    )
    parser.add_argument(
        "--atlas-allow-rotation",
        action="store_true",
        default=bool(config_defaults.get("atlas_allow_rotation", False)),
        help="Allow 90-degree rotation while atlas packing.",
    )
    parser.add_argument(
        "--engine-exports",
        default=config_defaults.get("engine_exports", ""),
        help="Comma-separated export presets to write: unity,godot,unreal, or all.",
    )
    parser.add_argument(
        "--no-engine-exports",
        dest="engine_exports",
        action="store_const",
        const="",
        help="Disable engine export JSON even when --auto-detect-all would enable it.",
    )
    parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=config_defaults.get("alpha_threshold", 10),
        help="Alpha values at or below this are treated as transparent background.",
    )
    parser.add_argument(
        "--white-threshold",
        type=int,
        default=config_defaults.get("white_threshold", WHITE_THRESHOLD),
        help="RGB values at or above this can be treated as white background.",
    )
    parser.add_argument(
        "--white-tolerance",
        type=int,
        default=config_defaults.get("white_tolerance", 8),
        help="Allowed RGB channel spread for white-background detection.",
    )
    parser.add_argument(
        "--dark-artifact-threshold",
        type=int,
        default=config_defaults.get("dark_artifact_threshold", DARK_ARTIFACT_THRESHOLD),
        help="Dark matte artifact threshold for removing large black background chunks.",
    )
    parser.add_argument(
        "--min-sprite-pixels",
        type=int,
        default=config_defaults.get("min_sprite_pixels", MIN_GROUP_PIXELS),
        help="Minimum foreground pixels required to keep a detected component.",
    )
    parser.add_argument(
        "--min-sprite-width",
        type=int,
        default=config_defaults.get("min_sprite_width", MIN_WIDTH),
        help="Minimum detected component width.",
    )
    parser.add_argument(
        "--min-sprite-height",
        type=int,
        default=config_defaults.get("min_sprite_height", MIN_HEIGHT),
        help="Minimum detected component height.",
    )
    parser.add_argument(
        "--crop-padding",
        type=int,
        default=config_defaults.get("crop_padding", PADDING),
        help="Padding around each extracted sprite crop.",
    )
    parser.add_argument(
        "--on-error",
        choices=["skip", "fail"],
        default=config_defaults.get("on_error", "skip"),
        help="Skip unreadable/problematic sheets by default, or fail fast.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=config_defaults.get("workers", 1),
        help="Number of worker threads used for batch sheet processing.",
    )
    parser.add_argument(
        "--max-image-megapixels",
        type=float,
        default=config_defaults.get("max_image_megapixels", 0),
        help="Skip/fail sheets larger than this many megapixels; 0 disables the guard.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=bool(config_defaults.get("resume", False)),
        help="Reuse an existing --out-name folder and skip sheets already present in its manifest.",
    )
    args = parser.parse_args()

    input_path = args.root.resolve()
    if not input_path.exists():
        raise SystemExit(f"Missing input: {input_path}")

    sheets = discover_sheet_files(input_path)
    if not sheets:
        raise SystemExit(f"No supported image sheets found in {input_path}")

    auto_profile: dict[str, object] = {}
    if args.auto_detect_all:
        auto_profile = infer_auto_defaults(sheets)
        apply_auto_defaults(args, auto_profile, config_defaults, raw_argv)

    output_base = input_path.parent if input_path.is_file() else input_path
    preferred_out_dir = output_base / args.out_name
    out_dir = preferred_out_dir if args.resume and preferred_out_dir.exists() else unique_output_dir(output_base, args.out_name)
    preview_dir = out_dir / "previews"
    manifest_dir = out_dir / "manifest"
    preview_dir.mkdir(parents=True, exist_ok=True)
    options = RunOptions(
        mode=args.mode,
        animation_names=parse_animation_names(args.animation_names),
        animation_frame_mode=args.animation_frame_mode,
        animation_anchor=args.animation_anchor,
        animation_min_frames=max(1, args.animation_min_frames),
        animation_fps=max(1, args.animation_fps),
        pivot_debug=args.pivot_debug,
        pack_atlases=args.pack_atlases,
        atlas_size=max(16, args.atlas_size),
        atlas_padding=max(0, args.atlas_padding),
        atlas_allow_rotation=args.atlas_allow_rotation,
        engine_exports=parse_engine_exports(args.engine_exports),
        detection_settings=DetectionSettings(
            alpha_threshold=max(0, args.alpha_threshold),
            white_threshold=max(0, min(255, args.white_threshold)),
            white_tolerance=max(0, args.white_tolerance),
            dark_artifact_threshold=max(0, min(255, args.dark_artifact_threshold)),
            min_sprite_pixels=max(1, args.min_sprite_pixels),
            min_sprite_width=max(1, args.min_sprite_width),
            min_sprite_height=max(1, args.min_sprite_height),
            crop_padding=max(0, args.crop_padding),
        ),
        on_error=args.on_error,
        workers=max(1, args.workers),
        max_image_megapixels=max(0.0, float(args.max_image_megapixels)),
        resume=args.resume,
        auto_detect_all=args.auto_detect_all,
        auto_profile=auto_profile,
    )

    all_records: list[SpriteRecord] = load_existing_records(manifest_dir) if options.resume else []
    sheet_errors: list[SheetError] = load_existing_errors(manifest_dir) if options.resume else []
    processed_sources = {str(Path(record.source_file).resolve()) for record in all_records}
    sheets_to_process = [sheet for sheet in sheets if str(sheet.resolve()) not in processed_sources]
    sheets_processed = len({record.source_file for record in all_records})
    if options.workers == 1 or len(sheets) <= 1:
        for sheet in sheets_to_process:
            print(f"PROCESSING {sheet}")
            try:
                records = process_sheet(sheet, out_dir, preview_dir, options)
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if options.on_error == "fail":
                    raise SystemExit(f"Failed processing {sheet}: {message}") from exc
                sheet_errors.append(SheetError(source_file=str(sheet), error=message))
                print(f"SKIPPED {sheet}: {message}")
                continue
            all_records.extend(records)
            sheets_processed += 1
            print(f"DONE {sheet} sprites={len(records)}")
    else:
        records_by_sheet: dict[Path, list[SpriteRecord]] = {}
        with ThreadPoolExecutor(max_workers=options.workers) as executor:
            futures = {}
            for sheet in sheets_to_process:
                print(f"PROCESSING {sheet}")
                futures[executor.submit(process_sheet, sheet, out_dir, preview_dir, options)] = sheet
            for future in as_completed(futures):
                sheet = futures[future]
                try:
                    records = future.result()
                    records_by_sheet[sheet] = records
                    print(f"DONE {sheet} sprites={len(records)}")
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    if options.on_error == "fail":
                        raise SystemExit(f"Failed processing {sheet}: {message}") from exc
                    sheet_errors.append(SheetError(source_file=str(sheet), error=message))
                    print(f"SKIPPED {sheet}: {message}")
        for sheet in sheets_to_process:
            records = records_by_sheet.get(sheet)
            if records is not None:
                all_records.extend(records)
                sheets_processed += 1

    if options.pack_atlases:
        pack_records_into_atlases(all_records, out_dir, options)
    animation_clips = build_animation_clips(all_records, options.animation_fps)
    write_engine_exports(all_records, out_dir, options.engine_exports, animation_clips)
    write_project_file(all_records, out_dir, options, sheets_processed, sheet_errors, animation_clips)
    write_manifest(all_records, manifest_dir, sheets_processed, sheet_errors, options, animation_clips)

    print(f"OUTPUT={out_dir}")
    print(f"SPRITES={len(all_records)}")
    for kind, count in sorted(Counter(record.kind for record in all_records).items()):
        print(f"KIND {kind}={count}")
    for category, count in sorted(Counter(record.category for record in all_records).items()):
        print(f"CATEGORY {category}={count}")


if __name__ == "__main__":
    main()
