from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PIL import Image, ImageDraw

try:
    import dearpygui.dearpygui as dpg
except ModuleNotFoundError:  # Keep helper tests importable when the GUI dependency is not installed.
    dpg = None  # type: ignore[assignment]

try:
    from tools.autotile_tools import write_autotile_package
    from tools.cut_tileset_sprites import BUILT_IN_PRESETS, DetectionSettings, detect_background, extract_detections, grouped_components, is_inside_spritecut_output
    from tools.golden_sprite_fixtures import create_golden_pack
    from tools.sprite_editor import SpriteEditSession, color_wheel_palette, extract_palette, write_edit_package, write_palette_variant_package
    from tools.sprite_project import approve_sprite, load_project, merge_sprites, redo_last_edit, reject_sprite, render_project_outputs, save_project, split_sprite, undo_last_edit, update_sprite
    from tools.sprite_studio import apply_taxonomy_rules, asset_browser_index, batch_health_score, build_engine_import_plans, build_review_dashboard, diff_projects, generate_collision_profiles, review_and_apply_project, search_assets, train_preset_from_project
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.autotile_tools import write_autotile_package
    from tools.cut_tileset_sprites import BUILT_IN_PRESETS, DetectionSettings, detect_background, extract_detections, grouped_components, is_inside_spritecut_output
    from tools.golden_sprite_fixtures import create_golden_pack
    from tools.sprite_editor import SpriteEditSession, color_wheel_palette, extract_palette, write_edit_package, write_palette_variant_package
    from tools.sprite_project import approve_sprite, load_project, merge_sprites, redo_last_edit, reject_sprite, render_project_outputs, save_project, split_sprite, undo_last_edit, update_sprite
    from tools.sprite_studio import apply_taxonomy_rules, asset_browser_index, batch_health_score, build_engine_import_plans, build_review_dashboard, diff_projects, generate_collision_profiles, review_and_apply_project, search_assets, train_preset_from_project


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SCRIPT_PATH = Path(__file__).with_name("cut_tileset_sprites.py")
PREVIEW_ACCESSIBILITY_MODES = ["normal", "grayscale", "protanopia", "deuteranopia", "tritanopia"]
VIEWPORT_SIZE = (1320, 820)
LEFT_PANEL_WIDTH = 300
CENTER_PANEL_WIDTH = 660
RIGHT_PANEL_WIDTH = 340
PREVIEW_MAX_SIZE = (620, 480)
REVIEW_CANVAS_SIZE = (300, 180)
REVIEW_IMAGE_PREVIEW_SIZE = (190, 130)
TOOLTIP_TEXT: dict[str, str] = {
    "input_path": "Folder or image file to process. Folder scans skip prior SpriteCut output folders automatically.",
    "add_folder": "Choose a folder containing sprite sheets or nested asset folders.",
    "add_file": "Choose a single sprite sheet image when you want to process just one file.",
    "refresh_files": "Rescan the selected input path and rebuild the sheet list and preview.",
    "create_sample_pack": "Create a small repeatable sample sprite pack for first-run demos and cutter smoke tests.",
    "file_list": "Detected source sheets. Select a sheet to preview auto-detected sprite regions.",
    "preview_accessibility": "Preview the detection overlay in normal or color-vision simulation modes.",
    "process": "Run the cutter with the current settings and write sprites, manifests, reports, and project files.",
    "reset_log": "Clear the run log without changing settings or output files.",
    "cancel": "Stop the active processing run. Finished output from already completed sheets remains on disk.",
    "open_output": "Open the latest output folder created by the cutter.",
    "open_report": "Open the latest HTML report for visual review and filtering.",
    "open_project": "Load the latest generated project file into the Review tab.",
    "out_name": "Name of the output folder created next to the selected input.",
    "auto_detect_all": "Let the tool infer backgrounds, thresholds, atlases, exports, workers, and animation FPS from the source art.",
    "include_archives": "Process supported images found inside .zip asset packs. Extracted sources are kept inside the output folder for review.",
    "builtin_preset": "Optional fixed recipe for repeatable batches. Auto detect all is usually the best first pass.",
    "apply_preset": "Apply the selected preset to the visible settings controls.",
    "mode": "Auto chooses animation rows or tileset crops per sheet. Use fixed modes only for strict batches.",
    "animation_names": "Optional comma-separated names for animation rows, such as idle, run, attack.",
    "animation_frame_mode": "Fixed keeps each animation row on stable same-size canvases; trimmed exports tight crops.",
    "animation_anchor": "Anchor used when placing trimmed animation frames on fixed canvases.",
    "animation_min_frames": "Minimum detections in a row before auto mode treats it as an animation row.",
    "animation_fps": "Frame rate written to generated animation clip metadata.",
    "pivot_debug": "Write debug previews showing contours and pivot crosses for review.",
    "alpha_threshold": "Pixels at or below this alpha value are treated as transparent background.",
    "white_threshold": "RGB values at or above this level may be treated as white sheet background.",
    "white_tolerance": "Allowed channel spread when classifying near-white background pixels.",
    "dark_artifact_threshold": "Dark matte threshold used to remove black or dark sheet backgrounds.",
    "min_sprite_pixels": "Minimum foreground pixel count required to keep a detected component.",
    "min_sprite_width": "Minimum component width required before a detection becomes a sprite crop.",
    "min_sprite_height": "Minimum component height required before a detection becomes a sprite crop.",
    "crop_padding": "Extra pixels added around each detected sprite crop.",
    "on_error": "Skip bad sheets for production batches, or fail fast while tuning settings.",
    "pack_atlases": "Pack extracted sprites into texture atlases grouped by category.",
    "atlas_size": "Square atlas texture size used when packing sprites.",
    "atlas_padding": "Pixels of spacing around sprites in generated atlases.",
    "atlas_allow_rotation": "Allow atlas packing to rotate sprites when it improves fit.",
    "engine_exports": "Choose which engine handoff JSON files to generate.",
    "export_unity": "Generate Unity-oriented sprite import and clip metadata.",
    "export_godot": "Generate Godot-oriented sprite and animation metadata.",
    "export_unreal": "Generate Unreal-oriented sprite and flipbook metadata.",
    "save_preset": "Save the current visible settings as a reusable JSON preset.",
    "load_preset": "Load a JSON preset and apply it to the current controls.",
    "load_project": "Open a project.spritecut.json file for manual review and corrections.",
    "recent_projects": "Recently loaded SpriteCut project files that still exist on disk.",
    "save_project": "Save the current project edits without regenerating output images.",
    "undo": "Undo the last project edit, including structural split and merge edits.",
    "redo": "Redo the last project edit after an undo.",
    "apply_outputs": "Regenerate corrected crops and reviewed engine exports from the current project edits.",
    "review_filter": "Filter the project list by review status.",
    "review_query": "Search sprites by id, display name, category, or review flag.",
    "review_list": "Project sprites. Select one or more for editing, approval, split, or merge operations.",
    "review_source_canvas": "Source sheet preview with draggable bbox overlay for manual crop adjustment.",
    "animation_clip": "Animation clip generated from row-based sheets for playback review.",
    "play_animation": "Play the selected animation clip in the review preview.",
    "stop_animation": "Stop animation playback in the review preview.",
    "review_name": "Display name used for reviewed output files and engine metadata.",
    "review_category": "Folder/category used when applying reviewed sprite outputs.",
    "review_bbox": "Manual source rectangle as x, y, width, height.",
    "review_pivot": "Manual pivot coordinates from 0.0 to 1.0 in sprite-local space.",
    "review_status": "Review state used for filtering and apply-output behavior.",
    "review_flags": "Comma-separated review flags for audit notes and report filtering.",
    "apply_edit": "Apply the edited fields to the selected sprite in project memory.",
    "approve": "Mark the selected sprite approved and clear review flags.",
    "reject": "Mark the selected sprite rejected so Apply Outputs skips it.",
    "split_boxes": "Split boxes in x,y,width,height format separated by semicolons.",
    "split_selected": "Create child sprites from the split boxes and reject the original source sprite.",
    "merge_selected": "Merge selected sprites into one union bbox and reject the sources.",
    "studio_refresh": "Rebuild the studio dashboard, review queue, health score, and asset search rows from the loaded project.",
    "studio_review_apply": "Run the one-click studio pass: auto naming, collision profiles, reviewed crops, import plans, health, and dashboard files.",
    "studio_auto_name": "Apply the taxonomy naming pattern to active sprites and keep rejected sprites untouched.",
    "studio_train_preset": "Write a trained preset suggestion beside the loaded project using categories, settings, and review corrections.",
    "studio_diff_project": "Compare the loaded project against another project file and write a studio_diff.json rerun comparison.",
    "studio_generate_profiles": "Generate collision, anchor, pivot, atlas, and engine import plan metadata for the loaded project.",
    "studio_dashboard": "Current production readiness summary with health score, status counts, and review queue size.",
    "studio_queue": "Priority review queue sorted by low confidence, review flags, duplicate names, and needs-review status.",
    "studio_asset_query": "Search the asset browser by sprite name, category, source sheet, status, kind, or review flags.",
    "studio_asset_list": "Searchable asset browser rows for quickly finding sprites by taxonomy, status, and review notes.",
    "studio_taxonomy_pattern": "Naming template used by Auto Name and Review + Apply, such as category, source sheet, and index tokens.",
    "editor_load_sprite": "Load one sprite PNG into the non-destructive editor session for palette, color, and autotile operations.",
    "editor_save_package": "Save the edited sprite plus an edit manifest and extracted palette JSON package.",
    "editor_palette_summary": "Palette summary for the current edited sprite, sorted by dominant visible colors.",
    "editor_source_color": "Source color to replace, written as a hex color such as #ff0000.",
    "editor_target_color": "Target replacement color, written as a hex color such as #00ffff.",
    "editor_swap_colors": "Replace the source color with the target color while preserving transparent pixels.",
    "editor_undo": "Undo the most recent non-destructive sprite edit in the current editor session.",
    "editor_redo": "Redo the most recently undone sprite edit in the current editor session.",
    "editor_crop_rect": "Crop rectangle for the current sprite as x,y,width,height or four space-separated numbers.",
    "editor_resize_size": "Resize target for the current sprite as width x height or two comma-separated numbers.",
    "editor_flip_axis": "Flip the current sprite horizontally or vertically using nearest-neighbor pixel handling.",
    "editor_crop": "Apply the crop rectangle to all layers in the current editor session.",
    "editor_resize": "Resize all layers in the current editor session using nearest-neighbor pixel handling.",
    "editor_flip": "Flip all layers in the current editor session across the selected axis.",
    "editor_rotate": "Rotate all layers in the current editor session by 90 degrees.",
    "editor_hue_degrees": "Hue rotation in degrees for color-wheel style sprite recoloring.",
    "editor_hue_shift": "Apply hue, saturation, and value changes to the current sprite session.",
    "editor_color_wheel": "Preview color harmony suggestions such as complementary, analogous, triadic, or tetradic.",
    "editor_palette_variants": "Write colorway PNGs, manifest JSON, and contact sheet using the selected harmony colors.",
    "editor_autotile_name": "Name used when writing a 16-mask cardinal autotile sheet and rule metadata.",
    "editor_generate_autotile": "Generate a 16-variant autotile package from the current edited sprite.",
    "editor_ide_api": "Show IDE-callable JSON actions for scripts, editors, and external tools.",
}


def tooltip_text(key: str) -> str:
    return TOOLTIP_TEXT[key]


@dataclass
class CutterUiSettings:
    input_path: Path
    auto_detect_all: bool = True
    include_archives: bool = False
    out_name: str = "_organized_sprites"
    mode: str = "auto"
    animation_names: str = ""
    animation_frame_mode: str = "fixed"
    animation_anchor: str = "bottom-center"
    animation_min_frames: int = 3
    animation_fps: int = 12
    pivot_debug: bool = False
    pack_atlases: bool = True
    atlas_size: int = 2048
    atlas_padding: int = 2
    atlas_allow_rotation: bool = False
    engine_exports: list[str] = field(default_factory=lambda: ["unity", "godot", "unreal"])
    alpha_threshold: int = 10
    white_threshold: int = 250
    white_tolerance: int = 8
    dark_artifact_threshold: int = 45
    min_sprite_pixels: int = 24
    min_sprite_width: int = 3
    min_sprite_height: int = 3
    crop_padding: int = 1
    on_error: str = "skip"


@dataclass(frozen=True)
class RunOutputTargets:
    output_dir: Path
    report_path: Path
    project_path: Path


def discover_sheet_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS else []

    files: list[Path] = []
    for path in root.rglob("*"):
        if "_organized_sprites" in path.parts or is_inside_spritecut_output(path, root):
            continue
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            files.append(path)
    return sorted(files, key=lambda item: item.name.lower())


def build_cutter_command(settings: CutterUiSettings, python_executable: str = sys.executable) -> list[str]:
    command = [
        python_executable,
        str(SCRIPT_PATH),
        "--out-name",
        settings.out_name,
    ]

    if settings.auto_detect_all:
        command.append("--auto-detect-all")
        if settings.include_archives:
            command.append("--include-archives")
        if settings.animation_names.strip():
            command.extend(["--animation-names", settings.animation_names.strip()])
        command.append(str(settings.input_path))
        return command

    command.extend(
        [
            "--manual-defaults",
            "--mode",
            settings.mode,
            "--animation-frame-mode",
            settings.animation_frame_mode,
            "--animation-anchor",
            settings.animation_anchor,
            "--animation-min-frames",
            str(settings.animation_min_frames),
            "--animation-fps",
            str(settings.animation_fps),
            "--alpha-threshold",
            str(settings.alpha_threshold),
            "--white-threshold",
            str(settings.white_threshold),
            "--white-tolerance",
            str(settings.white_tolerance),
            "--dark-artifact-threshold",
            str(settings.dark_artifact_threshold),
            "--min-sprite-pixels",
            str(settings.min_sprite_pixels),
            "--min-sprite-width",
            str(settings.min_sprite_width),
            "--min-sprite-height",
            str(settings.min_sprite_height),
            "--crop-padding",
            str(settings.crop_padding),
            "--on-error",
            settings.on_error,
        ]
    )

    if settings.animation_names.strip():
        command.extend(["--animation-names", settings.animation_names.strip()])
    if settings.include_archives:
        command.append("--include-archives")
    if settings.pivot_debug:
        command.append("--pivot-debug")
    if settings.pack_atlases:
        command.extend(["--pack-atlases", "--atlas-size", str(settings.atlas_size), "--atlas-padding", str(settings.atlas_padding)])
        if settings.atlas_allow_rotation:
            command.append("--atlas-allow-rotation")
    if settings.engine_exports:
        command.extend(["--engine-exports", ",".join(settings.engine_exports)])

    command.append(str(settings.input_path))
    return command


def settings_to_preset_dict(settings: CutterUiSettings) -> dict[str, object]:
    return {
        "out_name": settings.out_name,
        "auto_detect_all": settings.auto_detect_all,
        "include_archives": settings.include_archives,
        "mode": settings.mode,
        "animation_names": settings.animation_names,
        "animation_frame_mode": settings.animation_frame_mode,
        "animation_anchor": settings.animation_anchor,
        "animation_min_frames": settings.animation_min_frames,
        "animation_fps": settings.animation_fps,
        "pivot_debug": settings.pivot_debug,
        "pack_atlases": settings.pack_atlases,
        "atlas_size": settings.atlas_size,
        "atlas_padding": settings.atlas_padding,
        "atlas_allow_rotation": settings.atlas_allow_rotation,
        "engine_exports": settings.engine_exports,
        "alpha_threshold": settings.alpha_threshold,
        "white_threshold": settings.white_threshold,
        "white_tolerance": settings.white_tolerance,
        "dark_artifact_threshold": settings.dark_artifact_threshold,
        "min_sprite_pixels": settings.min_sprite_pixels,
        "min_sprite_width": settings.min_sprite_width,
        "min_sprite_height": settings.min_sprite_height,
        "crop_padding": settings.crop_padding,
        "on_error": settings.on_error,
    }


def settings_from_preset_dict(data: dict[str, object], input_path: Path) -> CutterUiSettings:
    exports = data.get("engine_exports", [])
    if isinstance(exports, str):
        engine_exports = [part.strip() for part in exports.split(",") if part.strip()]
    elif isinstance(exports, list):
        engine_exports = [str(part) for part in exports]
    else:
        engine_exports = []

    return CutterUiSettings(
        input_path=input_path,
        auto_detect_all=bool(data.get("auto_detect_all", False)),
        include_archives=bool(data.get("include_archives", False)),
        out_name=str(data.get("out_name", "_organized_sprites")),
        mode=str(data.get("mode", "auto")),
        animation_names=str(data.get("animation_names", "")),
        animation_frame_mode=str(data.get("animation_frame_mode", "fixed")),
        animation_anchor=str(data.get("animation_anchor", "bottom-center")),
        animation_min_frames=int(data.get("animation_min_frames", 3)),
        animation_fps=int(data.get("animation_fps", 8)),
        pivot_debug=bool(data.get("pivot_debug", False)),
        pack_atlases=bool(data.get("pack_atlases", False)),
        atlas_size=int(data.get("atlas_size", 2048)),
        atlas_padding=int(data.get("atlas_padding", 2)),
        atlas_allow_rotation=bool(data.get("atlas_allow_rotation", False)),
        engine_exports=engine_exports,
        alpha_threshold=int(data.get("alpha_threshold", 10)),
        white_threshold=int(data.get("white_threshold", 250)),
        white_tolerance=int(data.get("white_tolerance", 8)),
        dark_artifact_threshold=int(data.get("dark_artifact_threshold", 45)),
        min_sprite_pixels=int(data.get("min_sprite_pixels", 24)),
        min_sprite_width=int(data.get("min_sprite_width", 3)),
        min_sprite_height=int(data.get("min_sprite_height", 3)),
        crop_padding=int(data.get("crop_padding", 1)),
        on_error=str(data.get("on_error", "skip")),
    )


def save_preset_file(settings: CutterUiSettings, path: Path) -> None:
    path.write_text(json.dumps(settings_to_preset_dict(settings), indent=2), encoding="utf-8")


def load_preset_file(path: Path, input_path: Path) -> CutterUiSettings:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Preset file must contain a JSON object.")
    return settings_from_preset_dict(data, input_path)


def builtin_preset_names() -> list[str]:
    return sorted(BUILT_IN_PRESETS)


def settings_from_builtin_preset(name: str, input_path: Path) -> CutterUiSettings:
    if name not in BUILT_IN_PRESETS:
        raise ValueError(f"Unknown built-in preset: {name}")
    return settings_from_preset_dict(dict(BUILT_IN_PRESETS[name]), input_path)


def output_targets_from_cli_line(line: str) -> RunOutputTargets | None:
    if not line.startswith("OUTPUT="):
        return None
    output_text = line.split("=", 1)[1].strip()
    if not output_text:
        return None
    output_dir = Path(output_text.replace("\\", "/"))
    return RunOutputTargets(
        output_dir=output_dir,
        report_path=output_dir / "manifest" / "report.html",
        project_path=output_dir / "project.spritecut.json",
    )


def summarize_cli_output_line(line: str) -> list[str]:
    targets = output_targets_from_cli_line(line)
    if targets is None:
        return [line]
    return [
        line,
        f"Report: {targets.report_path}",
        f"Open output folder: {targets.output_dir}",
    ]


def render_detection_preview(image_path: Path, boxes: list[tuple[int, int, int, int]], max_size: tuple[int, int] = (760, 620)) -> Image.Image:
    image = Image.open(image_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    for index, (x, y, width, height) in enumerate(boxes, start=1):
        draw.rectangle((x, y, x + width - 1, y + height - 1), outline=(255, 90, 60, 255), width=2)
        draw.text((x + 3, y + 3), str(index), fill=(255, 90, 60, 255))
    image.thumbnail(max_size, Image.Resampling.NEAREST)
    return image.copy()


def apply_preview_accessibility_mode(image: Image.Image, mode: str) -> Image.Image:
    if mode == "normal":
        return image.copy()

    rgba = image.convert("RGBA")
    if mode == "grayscale":
        return rgba.convert("LA").convert("RGBA")

    import numpy as np

    matrices = {
        "protanopia": np.array(
            [
                [0.567, 0.433, 0.000],
                [0.558, 0.442, 0.000],
                [0.000, 0.242, 0.758],
            ]
        ),
        "deuteranopia": np.array(
            [
                [0.625, 0.375, 0.000],
                [0.700, 0.300, 0.000],
                [0.000, 0.300, 0.700],
            ]
        ),
        "tritanopia": np.array(
            [
                [0.950, 0.050, 0.000],
                [0.000, 0.433, 0.567],
                [0.000, 0.475, 0.525],
            ]
        ),
    }
    matrix = matrices.get(mode)
    if matrix is None:
        return image.copy()

    pixels = np.array(rgba).astype(np.float32)
    rgb = pixels[:, :, :3]
    transformed = rgb @ matrix.T
    pixels[:, :, :3] = np.clip(transformed, 0, 255)
    return Image.fromarray(pixels.astype(np.uint8), "RGBA")


def detection_settings_from_ui(settings: CutterUiSettings | None) -> DetectionSettings:
    if settings is None:
        return DetectionSettings()
    return DetectionSettings(
        alpha_threshold=max(0, settings.alpha_threshold),
        white_threshold=max(0, min(255, settings.white_threshold)),
        white_tolerance=max(0, settings.white_tolerance),
        dark_artifact_threshold=max(0, settings.dark_artifact_threshold),
        min_sprite_pixels=max(1, settings.min_sprite_pixels),
        min_sprite_width=max(1, settings.min_sprite_width),
        min_sprite_height=max(1, settings.min_sprite_height),
        crop_padding=max(0, settings.crop_padding),
    )


def detect_preview_boxes(image_path: Path, settings: CutterUiSettings | None = None) -> list[tuple[int, int, int, int]]:
    import numpy as np

    image = Image.open(image_path).convert("RGBA")
    rgba = np.array(image)
    detection_settings = detection_settings_from_ui(settings)
    background = detect_background(rgba[:, :, :3], rgba[:, :, 3], detection_settings)
    foreground = ~background
    labels, stats, num = grouped_components(foreground)
    detections = extract_detections(foreground, labels, stats, num, detection_settings)
    return [(detection.x, detection.y, detection.width, detection.height) for detection in detections]


def parse_flags_text(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,|]", value) if part.strip()]


def parse_bbox_fields(x: str, y: str, width: str, height: str) -> dict[str, int]:
    bbox = {"x": int(x), "y": int(y), "width": int(width), "height": int(height)}
    if bbox["width"] <= 0 or bbox["height"] <= 0:
        raise ValueError("Bounding box width and height must be positive.")
    return bbox


def parse_pivot_fields(x: str, y: str) -> dict[str, float | str]:
    pivot_x = float(x)
    pivot_y = float(y)
    if not 0.0 <= pivot_x <= 1.0 or not 0.0 <= pivot_y <= 1.0:
        raise ValueError("Pivot x and y must be between 0.0 and 1.0.")
    return {"x": pivot_x, "y": pivot_y, "method": "manual"}


def format_project_sprite_label(sprite: dict[str, object]) -> str:
    display_name = str(sprite.get("display_name") or sprite.get("id") or "sprite")
    status = str(sprite.get("review_status", "unknown"))
    confidence = float(sprite.get("confidence", 0.0))
    flags = sprite.get("review_flags", [])
    flags_text = ",".join(str(flag) for flag in flags) if isinstance(flags, list) and flags else "none"
    return f"{display_name} | {status} | {confidence:.2f} | {flags_text}"


def project_sprite_preview_path_text(sprite: dict[str, object]) -> str:
    applied_output = str(sprite.get("applied_output_file") or "").strip()
    if applied_output:
        return applied_output
    return str(sprite.get("output_file") or "").strip()


def project_sprite_rows(project: dict[str, object], status_filter: str = "all", query: str = "") -> list[dict[str, object]]:
    sprites = project.get("sprites", [])
    if not isinstance(sprites, list):
        return []
    normalized_query = query.strip().lower()
    rows: list[dict[str, object]] = []
    for sprite in sprites:
        if not isinstance(sprite, dict):
            continue
        status = str(sprite.get("review_status", "unknown"))
        if status_filter != "all" and status != status_filter:
            continue
        haystack = " ".join(
            [
                str(sprite.get("id", "")),
                str(sprite.get("display_name", "")),
                str(sprite.get("category", "")),
                " ".join(str(flag) for flag in sprite.get("review_flags", []) if isinstance(flag, str)),
            ]
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        rows.append(sprite)
    return rows


def studio_default_taxonomy_rules(pattern: str) -> dict[str, object]:
    normalized = pattern.strip() or "{category}_{source_sheet}_{index:03d}"
    return {"display_name_pattern": normalized, "include_rejected": False}


def studio_project_diff_text(old_project: dict[str, object], new_project: dict[str, object]) -> str:
    diff = diff_projects(old_project, new_project)  # type: ignore[arg-type]
    summary = diff.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    return (
        "Diff "
        f"added={int(summary.get('added', 0))} "
        f"removed={int(summary.get('removed', 0))} "
        f"changed={int(summary.get('changed', 0))}"
    )


def studio_dashboard_text(project: dict[str, object]) -> str:
    health = batch_health_score(project)  # type: ignore[arg-type]
    dashboard = build_review_dashboard(project)  # type: ignore[arg-type]
    counts = health.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}
    return (
        f"Health {health['grade']} {health['score']}/100 | "
        f"queue={len(dashboard['queue'])} | "
        f"approved={int(counts.get('approved', 0))} | "
        f"needs_review={int(counts.get('needs_review', 0))} | "
        f"rejected={int(counts.get('rejected', 0))}"
    )


def studio_queue_labels(project: dict[str, object], limit: int = 50) -> list[str]:
    dashboard = build_review_dashboard(project)  # type: ignore[arg-type]
    labels: list[str] = []
    for item in dashboard.get("queue", [])[:limit]:
        if not isinstance(item, dict):
            continue
        reasons = item.get("reasons", [])
        reason_text = ", ".join(str(reason) for reason in reasons) if isinstance(reasons, list) else str(reasons)
        labels.append(f"{item.get('sprite_id', '')} | p{item.get('priority', 0)} | {reason_text}")
    return labels


def studio_asset_rows(project: dict[str, object], query: str = "", status_filter: str = "all", category_filter: str = "all") -> list[dict[str, object]]:
    status = None if status_filter == "all" else status_filter
    category = None if category_filter == "all" else category_filter
    index = asset_browser_index(project)  # type: ignore[arg-type]
    return search_assets(index, query, status=status, category=category)  # type: ignore[return-value]


def studio_asset_label(item: dict[str, object]) -> str:
    flags = item.get("flags", [])
    flags_text = ",".join(str(flag) for flag in flags) if isinstance(flags, list) and flags else "none"
    return (
        f"{item.get('display_name', item.get('sprite_id', 'sprite'))} | "
        f"{item.get('category', 'sprites')} | "
        f"{item.get('status', 'unknown')} | "
        f"{flags_text}"
    )


def editor_palette_summary(image: Image.Image, max_colors: int = 8) -> str:
    palette = extract_palette(image, max_colors=max_colors)
    colors = ", ".join(f"{entry['hex']}:{entry['count']}" for entry in palette[:max_colors])
    return f"colors={len(palette)} | {colors or 'empty'}"


def editor_color_wheel_preview(base: str, harmony: str = "complementary") -> str:
    wheel = color_wheel_palette(base, harmony=harmony, steps=5)
    return f"{wheel['harmony']} | colors={', '.join(wheel['colors'])} | ramp={', '.join(wheel['ramp'])}"


def _editor_numbers(text: str, expected: int, label: str) -> tuple[int, ...]:
    parts = [part for part in re.split(r"[,\sxX]+", text.strip()) if part]
    if len(parts) != expected:
        raise ValueError(f"{label} must contain {expected} numbers.")
    values = tuple(int(part) for part in parts)
    if any(value < 0 for value in values):
        raise ValueError(f"{label} cannot contain negative values.")
    return values


def editor_parse_rect_text(text: str) -> tuple[int, int, int, int]:
    x, y, width, height = _editor_numbers(text, 4, "Crop rectangle")
    if width < 1 or height < 1:
        raise ValueError("Crop rectangle width and height must be at least 1.")
    return x, y, width, height


def editor_parse_size_text(text: str) -> tuple[int, int]:
    width, height = _editor_numbers(text, 2, "Resize size")
    if width < 1 or height < 1:
        raise ValueError("Resize width and height must be at least 1.")
    return width, height


def editor_variant_package(
    session: SpriteEditSession,
    output_dir: Path,
    *,
    name: str,
    base_color: str,
    harmony: str,
) -> dict[str, Any]:
    wheel = color_wheel_palette(base_color, harmony=harmony, steps=5)
    colors = [str(color) for color in wheel.get("colors", [])]
    targets = colors[:2] if len(colors) >= 2 else colors
    variants = [
        {"name": f"{harmony}_{index + 1}", "swaps": {base_color: target}}
        for index, target in enumerate(targets)
    ]
    return write_palette_variant_package(session.composite(), output_dir, name=name, variants=variants)


def editor_callable_actions() -> list[str]:
    return ["sprite.edit", "sprite.batch_edit", "palette.extract", "palette.swap", "palette.hue_shift", "palette.variants", "autotile.generate"]


def default_recent_projects_state_path() -> Path:
    return Path.home() / ".spritecut" / "recent_projects.json"


def load_recent_projects(state_file: Path | None = None, *, limit: int = 8) -> list[Path]:
    state_path = state_file or default_recent_projects_state_path()
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_paths = data.get("projects", []) if isinstance(data, dict) else []
    if not isinstance(raw_paths, list):
        return []
    projects: list[Path] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        path = Path(str(raw_path))
        key = str(path.resolve()).lower() if path.exists() else str(path).lower()
        if key in seen or not path.exists():
            continue
        seen.add(key)
        projects.append(path)
        if len(projects) >= limit:
            break
    return projects


def remember_recent_project(state_file: Path | None, project_path: Path, *, limit: int = 8) -> list[Path]:
    state_path = state_file or default_recent_projects_state_path()
    project = project_path.resolve()
    existing = [path for path in load_recent_projects(state_path, limit=limit) if path.resolve() != project]
    projects = [project, *existing][:limit]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"projects": [str(path) for path in projects]}, indent=2), encoding="utf-8")
    return projects


def create_ui_sample_pack(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    expected_path = create_golden_pack(output_root)
    alias_path = output_root / "expected.json"
    if expected_path != alias_path:
        alias_path.write_text(expected_path.read_text(encoding="utf-8"), encoding="utf-8")
    return output_root


def project_animation_clip_names(project: dict[str, object]) -> list[str]:
    clips = project.get("animation_clips", [])
    if not isinstance(clips, list):
        return []
    names: list[str] = []
    for clip in clips:
        if isinstance(clip, dict) and clip.get("name"):
            names.append(str(clip["name"]))
    return names


def project_animation_clip_frames(project: dict[str, object], clip_name: str) -> list[dict[str, object]]:
    clips = project.get("animation_clips", [])
    if not isinstance(clips, list):
        return []
    for clip in clips:
        if isinstance(clip, dict) and clip.get("name") == clip_name:
            frames = clip.get("frames", [])
            return [frame for frame in frames if isinstance(frame, dict)] if isinstance(frames, list) else []
    return []


def scale_bbox_for_canvas(bbox: dict[str, int], image_size: tuple[int, int], canvas_size: tuple[int, int]) -> dict[str, object]:
    image_width, image_height = image_size
    canvas_width, canvas_height = canvas_size
    scale = min(canvas_width / max(1, image_width), canvas_height / max(1, image_height))
    display_width = int(round(image_width * scale))
    display_height = int(round(image_height * scale))
    offset_x = (canvas_width - display_width) // 2
    offset_y = (canvas_height - display_height) // 2
    x0 = int(round(offset_x + bbox["x"] * scale))
    y0 = int(round(offset_y + bbox["y"] * scale))
    x1 = int(round(offset_x + (bbox["x"] + bbox["width"]) * scale))
    y1 = int(round(offset_y + (bbox["y"] + bbox["height"]) * scale))
    return {"rect": (x0, y0, x1, y1), "scale": scale, "offset": (offset_x, offset_y)}


def translate_bbox_by_canvas_delta(bbox: dict[str, int], dx: int, dy: int, scale: float) -> dict[str, int]:
    safe_scale = scale if scale > 0 else 1.0
    return {
        "x": int(round(bbox["x"] + dx / safe_scale)),
        "y": int(round(bbox["y"] + dy / safe_scale)),
        "width": int(bbox["width"]),
        "height": int(bbox["height"]),
    }


def cancel_button_state(has_active_process: bool) -> str:
    return "normal" if has_active_process else "disabled"


class DpgValue:
    def __init__(self, value: Any = None) -> None:
        self._value = value
        self.tag: str | int | None = None
        self._callbacks: list[Callable[..., object]] = []

    def bind(self, tag: str | int) -> "DpgValue":
        self.tag = tag
        if dpg is not None and dpg.does_item_exist(tag):
            dpg.set_value(tag, self._value)
        return self

    def get(self) -> Any:
        if dpg is not None and self.tag is not None and dpg.does_item_exist(self.tag):
            self._value = dpg.get_value(self.tag)
        return self._value

    def set(self, value: Any) -> None:
        self._value = value
        if dpg is not None and self.tag is not None and dpg.does_item_exist(self.tag):
            dpg.set_value(self.tag, value)
        for callback in list(self._callbacks):
            callback(None, None, None)

    def trace_add(self, _mode: str, callback: Callable[..., object]) -> None:
        self._callbacks.append(callback)


class DpgSelectableList:
    def __init__(self, parent: str | int, *, multi: bool = False, on_select: Callable[[], object] | None = None) -> None:
        self.parent = parent
        self.multi = multi
        self.on_select = on_select
        self.labels: list[str] = []
        self.tags: list[str] = []
        self.selected: set[int] = set()

    def clear(self) -> None:
        self.labels = []
        self.tags = []
        self.selected = set()
        if dpg is not None and dpg.does_item_exist(self.parent):
            dpg.delete_item(self.parent, children_only=True)

    def set_items(self, labels: list[str], *, select_first: bool = False) -> None:
        self.clear()
        self.labels = labels
        if dpg is None or not dpg.does_item_exist(self.parent):
            return
        for index, label in enumerate(labels):
            tag = f"{self.parent}_item_{index}_{uuid4().hex}"
            self.tags.append(tag)
            dpg.add_selectable(
                label=label,
                tag=tag,
                parent=self.parent,
                callback=self._on_select,
                user_data=index,
                span_columns=True,
            )
        if select_first and labels:
            self.select(0)

    def _on_select(self, _sender: object, app_data: object, user_data: object) -> None:
        index = int(user_data)
        is_selected = bool(app_data)
        if self.multi:
            if is_selected:
                self.selected.add(index)
            else:
                self.selected.discard(index)
        else:
            self.selected = {index} if is_selected else set()
            if is_selected and dpg is not None:
                for other_index, tag in enumerate(self.tags):
                    if other_index != index and dpg.does_item_exist(tag):
                        dpg.set_value(tag, False)
        if self.on_select is not None:
            self.on_select()

    def select(self, index: int, *, additive: bool = False) -> None:
        if index < 0 or index >= len(self.labels):
            return
        if not self.multi or not additive:
            self.selected = {index}
            if dpg is not None:
                for other_index, tag in enumerate(self.tags):
                    if dpg.does_item_exist(tag):
                        dpg.set_value(tag, other_index == index)
        else:
            self.selected.add(index)
            if dpg is not None and index < len(self.tags) and dpg.does_item_exist(self.tags[index]):
                dpg.set_value(self.tags[index], True)

    def selected_indices(self) -> list[int]:
        return sorted(index for index in self.selected if 0 <= index < len(self.labels))


class ToolTip:
    def __init__(self, item: str | int, text: str) -> None:
        self.item = item
        self.text = text
        if dpg is not None and dpg.does_item_exist(item):
            with dpg.tooltip(item):
                dpg.add_text(text, wrap=320)


def attach_tooltip(item: str | int, key: str) -> str | int:
    ToolTip(item, tooltip_text(key))
    return item


def _require_dearpygui() -> None:
    if dpg is None:
        raise RuntimeError("Dear PyGUI is required for the desktop UI. Install it with: pip install dearpygui")


def _image_texture_data(image: Image.Image) -> tuple[int, int, list[float]]:
    import numpy as np

    rgba = image.convert("RGBA")
    data = (np.asarray(rgba, dtype=np.float32) / 255.0).ravel().tolist()
    return rgba.width, rgba.height, data


class SpriteToolPanel:
    def __init__(self, app: "SpriteSheetToolUi") -> None:
        self.app = app

    def build(self) -> None:
        raise NotImplementedError


class LeftInputPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        dpg.add_text("Input")
        app._add_input_text("##input_path", app.input_path, "input_path", "input_path", width=-1)
        app._add_button("Add Folder", app.choose_folder, "add_folder", width=-1)
        app._add_button("Add File", app.choose_file, "add_file", width=-1)
        app._add_button("Refresh", app.refresh_files, "refresh_files", width=-1)
        app._add_button("Sample Pack", app.create_sample_pack_dialog, "create_sample_pack", width=-1)
        dpg.add_spacer(height=8)
        dpg.add_text("Sheets")
        with dpg.child_window(tag="file_list_panel", width=-1, height=470, border=True):
            pass
        attach_tooltip("file_list_panel", "file_list")
        app.file_list = DpgSelectableList("file_list_panel", on_select=app.update_preview)


class CenterPreviewPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        with dpg.group(horizontal=True):
            dpg.add_text("Preview")
            dpg.add_spacer(width=330)
            app._add_combo("##preview_accessibility", app.preview_accessibility_mode, PREVIEW_ACCESSIBILITY_MODES, "preview_accessibility", width=150, callback=lambda *_args: app.update_preview())
        with dpg.child_window(tag="preview_panel", width=-1, height=520, border=True):
            dpg.add_text("Choose a folder or file to preview sheets.", tag="preview_placeholder", wrap=620)
        with dpg.group(horizontal=True):
            dpg.add_text("Idle", tag="progress_text")
            app._add_button("Process", app.process, "process", tag="process_button")
            app._add_button("Reset Log", app.clear_log, "reset_log")
            app._add_button("Cancel", app.cancel_process, "cancel", tag="cancel_button", enabled=False)
        with dpg.group(horizontal=True):
            app._add_button("Open Output", app.open_latest_output, "open_output", tag="open_output_button", enabled=False)
            app._add_button("Open Report", app.open_latest_report, "open_report", tag="open_report_button", enabled=False)
            app._add_button("Open Project", app.open_latest_project, "open_project", tag="open_project_button", enabled=False)
        dpg.add_input_text(tag="log_text", multiline=True, readonly=True, width=-1, height=150, default_value="")


class SettingsTabsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        dpg.add_text("Settings")
        with dpg.tab_bar(tag="settings_tabs"):
            with dpg.tab(label="Core"):
                RunSettingsPanel(app).build()
            with dpg.tab(label="Detect"):
                DetectionSettingsPanel(app).build()
            with dpg.tab(label="Output"):
                OutputSettingsPanel(app).build()
            with dpg.tab(label="Review"):
                ReviewSettingsPanel(app).build()
            with dpg.tab(label="Studio"):
                StudioSettingsPanel(app).build()
            with dpg.tab(label="Editor"):
                EditorSettingsPanel(app).build()


class RunSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        dpg.add_text("Output")
        app._add_input_text("##out_name", app.out_name, "out_name", "out_name", width=-1)
        app._add_checkbox("Auto detect all", app.auto_detect_all, "auto_detect_all")
        app._add_checkbox("Include ZIP archives", app.include_archives, "include_archives")
        dpg.add_text("Built-In Preset")
        app._add_combo("##builtin_preset", app.builtin_preset, builtin_preset_names(), "builtin_preset", width=-1)
        app._add_button("Apply Preset", app.apply_builtin_preset, "apply_preset", width=-1)
        dpg.add_text("Mode")
        app._add_combo("##mode", app.mode, ["auto", "tileset", "animation"], "mode", width=-1)
        dpg.add_text("Animation Rows")
        app._add_input_text("##animation_names", app.animation_names, "animation_names", "animation_names", width=-1)
        dpg.add_text("Frame Mode")
        app._add_combo("##animation_frame_mode", app.animation_frame_mode, ["fixed", "trimmed"], "animation_frame_mode", width=-1)
        dpg.add_text("Anchor")
        app._add_combo("##animation_anchor", app.animation_anchor, ["bottom-center", "center"], "animation_anchor", width=-1)
        app._add_input_int("Min Frames", app.animation_min_frames, "animation_min_frames", "animation_min_frames", min_value=1, max_value=24)
        app._add_input_int("FPS", app.animation_fps, "animation_fps", "animation_fps", min_value=1, max_value=60)
        app._add_checkbox("Pivot debug previews", app.pivot_debug, "pivot_debug")


class DetectionSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        controls = [
            ("Alpha Threshold", app.alpha_threshold, 0, 255, "alpha_threshold"),
            ("White Threshold", app.white_threshold, 0, 255, "white_threshold"),
            ("White Tolerance", app.white_tolerance, 0, 64, "white_tolerance"),
            ("Dark Artifact", app.dark_artifact_threshold, 0, 255, "dark_artifact_threshold"),
            ("Min Pixels", app.min_sprite_pixels, 1, 10000, "min_sprite_pixels"),
            ("Min Width", app.min_sprite_width, 1, 512, "min_sprite_width"),
            ("Min Height", app.min_sprite_height, 1, 512, "min_sprite_height"),
            ("Crop Padding", app.crop_padding, 0, 64, "crop_padding"),
        ]
        for label, variable, min_value, max_value, tooltip_key in controls:
            app._add_input_int(label, variable, tooltip_key, tooltip_key, min_value=min_value, max_value=max_value)
        dpg.add_text("On Error")
        app._add_combo("##on_error", app.on_error, ["skip", "fail"], "on_error", width=-1)


class OutputSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        app._add_checkbox("Pack atlases", app.pack_atlases, "pack_atlases")
        app._add_input_int("Atlas Size", app.atlas_size, "atlas_size", "atlas_size", min_value=64, max_value=16384)
        app._add_input_int("Padding", app.atlas_padding, "atlas_padding", "atlas_padding", min_value=0, max_value=128)
        app._add_checkbox("Allow rotation", app.atlas_allow_rotation, "atlas_allow_rotation")
        dpg.add_text("Exports")
        attach_tooltip(dpg.last_item(), "engine_exports")
        app._add_checkbox("Unity", app.export_unity, "export_unity")
        app._add_checkbox("Godot", app.export_godot, "export_godot")
        app._add_checkbox("Unreal", app.export_unreal, "export_unreal")
        dpg.add_spacer(height=10)
        app._add_button("Save Preset", app.save_preset, "save_preset", width=-1)
        app._add_button("Load Preset", app.load_preset, "load_preset", width=-1)


class ReviewSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        with dpg.group(horizontal=True):
            app._add_button("Load Project", app.load_project_dialog, "load_project")
            app._add_button("Save Project", app.save_project_dialog, "save_project")
        with dpg.group(horizontal=True):
            app._add_combo("##recent_project", app.recent_project, [str(path) for path in app.recent_projects], "recent_projects", tag="recent_project_combo", width=190)
            app._add_button("Open Recent", app.open_recent_project, "recent_projects")
        with dpg.group(horizontal=True):
            app._add_button("Undo", app.undo_project_edit, "undo")
            app._add_button("Redo", app.redo_project_edit, "redo")
        app._add_button("Apply Outputs", app.apply_project_outputs, "apply_outputs", width=-1)
        dpg.add_text("Filter")
        with dpg.group(horizontal=True):
            app._add_combo("##review_filter", app.review_status_filter, ["all", "needs_review", "approved", "rejected"], "review_filter", width=120, callback=lambda *_args: app.refresh_project_rows())
            app._add_input_text("##review_query", app.review_query, "review_query", "review_query", width=145, callback=lambda *_args: app.refresh_project_rows())
        with dpg.child_window(tag="review_list_panel", width=-1, height=130, border=True):
            pass
        attach_tooltip("review_list_panel", "review_list")
        app._review_list = DpgSelectableList("review_list_panel", multi=True, on_select=app.populate_review_editor)
        with dpg.child_window(tag="review_image_panel", width=-1, height=140, border=True):
            dpg.add_text("Load a project to review sprites.", wrap=260)
        with dpg.group(tag="review_source_canvas_frame"):
            dpg.add_drawlist(tag="review_source_canvas", width=REVIEW_CANVAS_SIZE[0], height=REVIEW_CANVAS_SIZE[1])
        attach_tooltip("review_source_canvas_frame", "review_source_canvas")
        with dpg.item_handler_registry(tag="review_canvas_handlers"):
            dpg.add_item_clicked_handler(callback=app._on_review_canvas_press)
        dpg.bind_item_handler_registry("review_source_canvas", "review_canvas_handlers")
        dpg.add_text("Animation Clip")
        app._add_combo("##animation_clip", app.review_animation_clip, [], "animation_clip", tag="review_animation_combo", width=-1)
        with dpg.group(horizontal=True):
            app._add_button("Play", app.play_review_animation, "play_animation")
            app._add_button("Stop", app.stop_review_animation, "stop_animation")
        dpg.add_text("Name")
        app._add_input_text("##review_name", app.review_name, "review_name", "review_name", width=-1)
        dpg.add_text("Category")
        app._add_input_text("##review_category", app.review_category, "review_category", "review_category", width=-1)
        dpg.add_text("BBox x/y/w/h")
        with dpg.group(horizontal=True):
            app._add_input_text("##review_bbox_x", app.review_bbox_x, "review_bbox_x", "review_bbox", width=58)
            app._add_input_text("##review_bbox_y", app.review_bbox_y, "review_bbox_y", "review_bbox", width=58)
            app._add_input_text("##review_bbox_width", app.review_bbox_width, "review_bbox_width", "review_bbox", width=58)
            app._add_input_text("##review_bbox_height", app.review_bbox_height, "review_bbox_height", "review_bbox", width=58)
        dpg.add_text("Pivot x/y")
        with dpg.group(horizontal=True):
            app._add_input_text("##review_pivot_x", app.review_pivot_x, "review_pivot_x", "review_pivot", width=100)
            app._add_input_text("##review_pivot_y", app.review_pivot_y, "review_pivot_y", "review_pivot", width=100)
        dpg.add_text("Status / Flags")
        with dpg.group(horizontal=True):
            app._add_combo("##review_status", app.review_status, ["needs_review", "approved", "rejected"], "review_status", width=120)
            app._add_input_text("##review_flags", app.review_flags, "review_flags", "review_flags", width=130)
        app._add_button("Apply Edit", app.apply_review_edit, "apply_edit", width=-1)
        with dpg.group(horizontal=True):
            app._add_button("Approve", app.approve_review_sprite, "approve")
            app._add_button("Reject", app.reject_review_sprite, "reject")
        dpg.add_text("Split boxes")
        app._add_input_text("##split_boxes", app.review_split_boxes, "split_boxes", "split_boxes", width=-1)
        with dpg.group(horizontal=True):
            app._add_button("Split Selected", app.split_review_sprite, "split_selected")
            app._add_button("Merge Selected", app.merge_review_sprites, "merge_selected")


class StudioSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        with dpg.group(horizontal=True):
            app._add_button("Refresh", app.refresh_studio_panel, "studio_refresh")
            app._add_button("Review + Apply", app.review_apply_studio_project, "studio_review_apply")
        with dpg.group(horizontal=True):
            app._add_button("Auto Name", app.auto_name_studio_project, "studio_auto_name")
            app._add_button("Profiles", app.generate_studio_profiles, "studio_generate_profiles")
        with dpg.group(horizontal=True):
            app._add_button("Diff Project", app.diff_studio_project, "studio_diff_project")
            app._add_button("Train Preset", app.train_studio_preset, "studio_train_preset")
        dpg.add_text("Taxonomy Pattern")
        app._add_input_text("##studio_taxonomy_pattern", app.studio_taxonomy_pattern, "studio_taxonomy_pattern", "studio_taxonomy_pattern", width=-1)
        dpg.add_text("Dashboard")
        dpg.add_text("Load a project to build a studio dashboard.", tag="studio_dashboard_label", wrap=260)
        attach_tooltip("studio_dashboard_label", "studio_dashboard")
        dpg.add_text("Review Queue")
        with dpg.child_window(tag="studio_queue_panel", width=-1, height=100, border=True):
            pass
        attach_tooltip("studio_queue_panel", "studio_queue")
        app._studio_queue_list = DpgSelectableList("studio_queue_panel")
        dpg.add_text("Asset Browser")
        with dpg.group(horizontal=True):
            app._add_combo("##studio_status_filter", app.studio_status_filter, ["all", "needs_review", "approved", "rejected"], "studio_asset_query", width=120, callback=lambda *_args: app.refresh_studio_panel())
            app._add_input_text("##studio_query", app.studio_query, "studio_query", "studio_asset_query", width=130, callback=lambda *_args: app.refresh_studio_panel())
        with dpg.child_window(tag="studio_asset_panel", width=-1, height=140, border=True):
            pass
        attach_tooltip("studio_asset_panel", "studio_asset_list")
        app._studio_asset_list = DpgSelectableList("studio_asset_panel")


class EditorSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        with dpg.group(horizontal=True):
            app._add_button("Load Sprite", app.load_editor_sprite_dialog, "editor_load_sprite")
            app._add_button("Save Package", app.save_editor_package, "editor_save_package")
        with dpg.group(horizontal=True):
            app._add_button("Undo", app.undo_editor_edit, "editor_undo")
            app._add_button("Redo", app.redo_editor_edit, "editor_redo")
        with dpg.child_window(tag="editor_preview_panel", width=-1, height=145, border=True):
            dpg.add_text("Load a sprite to edit.", wrap=260)
        dpg.add_text("Palette: none", tag="editor_palette_label", wrap=260)
        attach_tooltip("editor_palette_label", "editor_palette_summary")
        dpg.add_text("Transform")
        app._add_input_text("##editor_crop_rect", app.editor_crop_rect, "editor_crop_rect", "editor_crop_rect", width=-1)
        with dpg.group(horizontal=True):
            app._add_button("Crop", app.apply_editor_crop, "editor_crop")
            app._add_input_text("##editor_resize_size", app.editor_resize_size, "editor_resize_size", "editor_resize_size", width=110)
            app._add_button("Resize", app.apply_editor_resize, "editor_resize")
        with dpg.group(horizontal=True):
            app._add_combo("##editor_flip_axis", app.editor_flip_axis, ["horizontal", "vertical"], "editor_flip_axis", width=120)
            app._add_button("Flip", app.apply_editor_flip, "editor_flip")
            app._add_button("Rotate CW", lambda *_args: app.apply_editor_rotate(clockwise=True), "editor_rotate")
            app._add_button("Rotate CCW", lambda *_args: app.apply_editor_rotate(clockwise=False), "editor_rotate")
        dpg.add_text("Palette Swap")
        with dpg.group(horizontal=True):
            app._add_input_text("##editor_source_color", app.editor_source_color, "editor_source_color", "editor_source_color", width=120)
            app._add_input_text("##editor_target_color", app.editor_target_color, "editor_target_color", "editor_target_color", width=120)
        app._add_button("Swap", app.apply_editor_palette_swap, "editor_swap_colors", width=-1)
        dpg.add_text("Color Wheel")
        with dpg.group(horizontal=True):
            app._add_combo("##editor_harmony", app.editor_harmony, ["complementary", "analogous", "triadic", "tetradic"], "editor_color_wheel", width=135)
            app._add_input_text("##editor_hue_degrees", app.editor_hue_degrees, "editor_hue_degrees", "editor_hue_degrees", width=100)
        with dpg.group(horizontal=True):
            app._add_button("Hue Shift", app.apply_editor_hue_shift, "editor_hue_shift")
            app._add_button("Wheel", app.preview_editor_color_wheel, "editor_color_wheel")
        app._add_button("Palette Variants", app.generate_editor_palette_variants, "editor_palette_variants", width=-1)
        dpg.add_text("Auto-Tile")
        with dpg.group(horizontal=True):
            app._add_input_text("##editor_autotile_name", app.editor_autotile_name, "editor_autotile_name", "editor_autotile_name", width=135)
            app._add_combo("##editor_engine", app.editor_engine, ["generic", "unity", "godot", "unreal"], "engine_exports", width=100)
        app._add_button("Generate Auto-Tile", app.generate_editor_autotile, "editor_generate_autotile", width=-1)
        app._add_button("IDE Actions", app.show_editor_ide_actions, "editor_ide_api", width=-1)


class UiController:
    def __init__(self, app: "SpriteSheetToolUi") -> None:
        self.app = app


class ProcessingController(UiController):
    def process(self, *args: object) -> None:
        self.app._process_impl(*args)


class ReviewProjectController(UiController):
    def refresh_project_rows(self, *args: object) -> None:
        self.app._refresh_project_rows_impl(*args)


class StudioController(UiController):
    def refresh_studio_panel(self, *args: object) -> None:
        self.app._refresh_studio_panel_impl(*args)


class SpriteEditorController(UiController):
    def _load_editor_sprite_impl(self, path: Path) -> None:
        self.app._load_editor_sprite_impl(path)

    def apply_palette_swap(self, *args: object) -> None:
        self.app._apply_editor_palette_swap_impl(*args)

    def apply_hue_shift(self, *args: object) -> None:
        self.app._apply_editor_hue_shift_impl(*args)

    def apply_crop(self, *args: object) -> None:
        self.app._apply_editor_crop_impl(*args)

    def apply_resize(self, *args: object) -> None:
        self.app._apply_editor_resize_impl(*args)

    def apply_flip(self, *args: object) -> None:
        self.app._apply_editor_flip_impl(*args)

    def apply_rotate(self, *, clockwise: bool = True) -> None:
        self.app._apply_editor_rotate_impl(clockwise=clockwise)


class SpriteSheetToolUi:
    def __init__(self, *, build: bool = True) -> None:
        self.input_path = DpgValue("")
        self.auto_detect_all = DpgValue(True)
        self.include_archives = DpgValue(False)
        self.out_name = DpgValue("_organized_sprites")
        self.mode = DpgValue("auto")
        self.animation_names = DpgValue("")
        self.animation_frame_mode = DpgValue("fixed")
        self.animation_anchor = DpgValue("bottom-center")
        self.animation_min_frames = DpgValue(3)
        self.animation_fps = DpgValue(12)
        self.pivot_debug = DpgValue(False)
        self.pack_atlases = DpgValue(True)
        self.atlas_size = DpgValue(2048)
        self.atlas_padding = DpgValue(2)
        self.atlas_allow_rotation = DpgValue(False)
        self.export_unity = DpgValue(True)
        self.export_godot = DpgValue(True)
        self.export_unreal = DpgValue(True)
        self.alpha_threshold = DpgValue(10)
        self.white_threshold = DpgValue(250)
        self.white_tolerance = DpgValue(8)
        self.dark_artifact_threshold = DpgValue(45)
        self.min_sprite_pixels = DpgValue(24)
        self.min_sprite_width = DpgValue(3)
        self.min_sprite_height = DpgValue(3)
        self.crop_padding = DpgValue(1)
        self.on_error = DpgValue("skip")
        preset_names = builtin_preset_names()
        self.builtin_preset = DpgValue(preset_names[0] if preset_names else "")
        self.preview_accessibility_mode = DpgValue("normal")

        self.sheet_files: list[Path] = []
        self.file_list: DpgSelectableList | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.log_lines: list[str] = []
        self.last_message: tuple[str, str, str] | None = None
        self.worker: threading.Thread | None = None
        self.active_process: subprocess.Popen[str] | None = None
        self.latest_output_dir: Path | None = None
        self.latest_report_path: Path | None = None
        self.latest_project_path: Path | None = None
        self.current_project: dict[str, object] | None = None
        self.current_project_path: Path | None = None
        self.recent_projects_state_path = default_recent_projects_state_path()
        self.recent_projects = load_recent_projects(self.recent_projects_state_path)
        self.recent_project = DpgValue(str(self.recent_projects[0]) if self.recent_projects else "")
        self.project_sprite_rows_cache: list[dict[str, object]] = []
        self.review_canvas_scale: float = 1.0
        self.review_canvas_drag_start: tuple[int, int] | None = None
        self.review_canvas_bbox_start: dict[str, int] | None = None
        self.review_canvas_rect: tuple[int, int, int, int] | None = None
        self.review_canvas_drag_dirty = False

        self.review_status_filter = DpgValue("all")
        self.review_query = DpgValue("")
        self.review_name = DpgValue("")
        self.review_category = DpgValue("")
        self.review_bbox_x = DpgValue("")
        self.review_bbox_y = DpgValue("")
        self.review_bbox_width = DpgValue("")
        self.review_bbox_height = DpgValue("")
        self.review_pivot_x = DpgValue("")
        self.review_pivot_y = DpgValue("")
        self.review_status = DpgValue("needs_review")
        self.review_flags = DpgValue("")
        self.review_split_boxes = DpgValue("")
        self.review_animation_clip = DpgValue("")
        self.review_animation_frame_index = 0
        self.review_animation_active = False
        self.review_animation_next_time: float | None = None
        self.studio_query = DpgValue("")
        self.studio_status_filter = DpgValue("all")
        self.studio_taxonomy_pattern = DpgValue("{category}_{source_sheet}_{index:03d}")
        self.studio_asset_rows_cache: list[dict[str, object]] = []
        self.editor_session: SpriteEditSession | None = None
        self.editor_crop_rect = DpgValue("0,0,16,16")
        self.editor_resize_size = DpgValue("16x16")
        self.editor_flip_axis = DpgValue("horizontal")
        self.editor_source_color = DpgValue("#ff0000")
        self.editor_target_color = DpgValue("#00ffff")
        self.editor_hue_degrees = DpgValue("0")
        self.editor_harmony = DpgValue("complementary")
        self.editor_autotile_name = DpgValue("autotile")
        self.editor_engine = DpgValue("godot")

        self._built = False
        self._texture_tags: dict[str, str] = {}
        self._dialog_actions: dict[str, Callable[[Path], None]] = {}
        self._main_window = "spritecut_main_window"
        self._texture_registry = "spritecut_texture_registry"
        self._review_list: DpgSelectableList | None = None
        self._studio_queue_list: DpgSelectableList | None = None
        self._studio_asset_list: DpgSelectableList | None = None
        self.processing_controller = ProcessingController(self)
        self.review_controller = ReviewProjectController(self)
        self.studio_controller = StudioController(self)
        self.editor_controller = SpriteEditorController(self)

        if build and dpg is not None:
            self._build()

    def _build(self) -> None:
        _require_dearpygui()
        if self._built:
            return
        dpg.create_context()
        self._build_theme()
        with dpg.texture_registry(tag=self._texture_registry):
            pass
        self._build_file_dialogs()
        self._build_layout()
        self._built = True

    def _build_theme(self) -> None:
        if dpg is None:
            return
        with dpg.theme(tag="spritecut_dark_theme"):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (23, 25, 29, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (32, 36, 43, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (17, 19, 24, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (47, 111, 235, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (59, 130, 246, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Header, (47, 111, 235, 180))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (59, 130, 246, 210))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (230, 232, 239, 255))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 10, 10)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 6)
        dpg.bind_theme("spritecut_dark_theme")

    def _build_file_dialogs(self) -> None:
        if dpg is None:
            return
        with dpg.file_dialog(directory_selector=True, show=False, callback=self._choose_folder_callback, tag="folder_dialog", width=720, height=440):
            dpg.add_file_extension("", color=(150, 255, 150, 255))
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._choose_file_callback, tag="image_file_dialog", width=720, height=440):
            dpg.add_file_extension("Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp){.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp}")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._load_preset_callback, tag="load_preset_dialog", width=720, height=440):
            dpg.add_file_extension("JSON preset (*.json){.json}")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._save_preset_callback, tag="save_preset_dialog", width=720, height=440):
            dpg.add_file_extension("JSON preset (*.json){.json}")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._load_project_callback, tag="load_project_dialog", width=720, height=440):
            dpg.add_file_extension("SpriteCut project (*.spritecut.json){.json}")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._save_project_callback, tag="save_project_dialog", width=720, height=440):
            dpg.add_file_extension("SpriteCut project (*.spritecut.json){.json}")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._load_editor_sprite_callback, tag="editor_sprite_dialog", width=720, height=440):
            dpg.add_file_extension("Images (*.png *.jpg *.jpeg *.bmp *.webp){.png,.jpg,.jpeg,.bmp,.webp}")
            dpg.add_file_extension(".*")
        with dpg.file_dialog(directory_selector=True, show=False, callback=self._directory_action_callback, tag="directory_action_dialog", width=720, height=440):
            dpg.add_file_extension("", color=(150, 255, 150, 255))
        with dpg.file_dialog(directory_selector=False, show=False, callback=self._diff_project_callback, tag="diff_project_dialog", width=720, height=440):
            dpg.add_file_extension("SpriteCut project (*.spritecut.json){.json}")
            dpg.add_file_extension(".*")

    def _build_layout(self) -> None:
        if dpg is None:
            return
        left_panel, center_panel, settings_panel = self._panel_builders()
        with dpg.window(tag=self._main_window, label="Sprite Sheet Processor", no_title_bar=True):
            with dpg.group(horizontal=True):
                with dpg.child_window(width=LEFT_PANEL_WIDTH, height=-1, border=True):
                    left_panel.build()
                with dpg.child_window(width=CENTER_PANEL_WIDTH, height=-1, border=True):
                    center_panel.build()
                with dpg.child_window(width=RIGHT_PANEL_WIDTH, height=-1, border=True):
                    settings_panel.build()
        dpg.create_viewport(title="Sprite Sheet Processor", width=VIEWPORT_SIZE[0], height=VIEWPORT_SIZE[1])
        dpg.set_primary_window(self._main_window, True)
        with dpg.handler_registry(tag="spritecut_global_handlers"):
            dpg.add_mouse_drag_handler(button=dpg.mvMouseButton_Left, callback=self._on_review_canvas_drag)
            dpg.add_mouse_release_handler(button=dpg.mvMouseButton_Left, callback=self._on_review_canvas_release)

    def _panel_builders(self) -> list[SpriteToolPanel]:
        return [LeftInputPanel(self), CenterPreviewPanel(self), SettingsTabsPanel(self)]

    def _controllers(self) -> list[UiController]:
        return [self.processing_controller, self.review_controller, self.studio_controller, self.editor_controller]

    def process(self, *_args: object) -> None:
        self.processing_controller.process(*_args)

    def refresh_project_rows(self, *_args: object) -> None:
        self.review_controller.refresh_project_rows(*_args)

    def refresh_studio_panel(self, *_args: object) -> None:
        self.studio_controller.refresh_studio_panel(*_args)

    def load_editor_sprite(self, path: Path) -> None:
        self.editor_controller.load_editor_sprite(path)

    def apply_editor_palette_swap(self, *_args: object) -> None:
        self.editor_controller.apply_palette_swap(*_args)

    def apply_editor_hue_shift(self, *_args: object) -> None:
        self.editor_controller.apply_hue_shift(*_args)

    def apply_editor_crop(self, *_args: object) -> None:
        self.editor_controller.apply_crop(*_args)

    def apply_editor_resize(self, *_args: object) -> None:
        self.editor_controller.apply_resize(*_args)

    def apply_editor_flip(self, *_args: object) -> None:
        self.editor_controller.apply_flip(*_args)

    def apply_editor_rotate(self, *, clockwise: bool = True) -> None:
        self.editor_controller.apply_rotate(clockwise=clockwise)

    def _build_left_panel(self) -> None:
        LeftInputPanel(self).build()

    def _build_center_panel(self) -> None:
        CenterPreviewPanel(self).build()

    def _build_right_panel(self) -> None:
        SettingsTabsPanel(self).build()

    def _build_core_settings(self) -> None:
        RunSettingsPanel(self).build()

    def _build_detection_settings(self) -> None:
        DetectionSettingsPanel(self).build()

    def _build_output_settings(self) -> None:
        OutputSettingsPanel(self).build()

    def _build_review_settings(self) -> None:
        ReviewSettingsPanel(self).build()

    def _build_studio_settings(self) -> None:
        StudioSettingsPanel(self).build()

    def _build_editor_settings(self) -> None:
        EditorSettingsPanel(self).build()

    def _value_callback(self, _sender: object, app_data: object, user_data: object) -> None:
        if isinstance(user_data, DpgValue):
            user_data.set(app_data)

    def _add_button(self, label: str, callback: Callable[..., object], tooltip_key: str, *, tag: str | None = None, width: int = 0, enabled: bool = True) -> str:
        item = tag or f"button_{tooltip_key}_{uuid4().hex}"
        dpg.add_button(label=label, tag=item, callback=callback, width=width, enabled=enabled)
        attach_tooltip(item, tooltip_key)
        return item

    def _add_input_text(self, label: str, variable: DpgValue, tag: str, tooltip_key: str, *, width: int = 0, callback: Callable[..., object] | None = None) -> str:
        variable.bind(tag)
        def _callback(sender: object, app_data: object, user_data: object) -> None:
            self._value_callback(sender, app_data, user_data)
            if callback is not None:
                callback(sender, app_data, user_data)
        dpg.add_input_text(label=label, tag=tag, default_value=str(variable.get()), callback=_callback, user_data=variable, width=width)
        variable.bind(tag)
        attach_tooltip(tag, tooltip_key)
        return tag

    def _add_input_int(self, label: str, variable: DpgValue, tag: str, tooltip_key: str, *, min_value: int, max_value: int) -> str:
        variable.bind(tag)
        dpg.add_input_int(label=label, tag=tag, default_value=int(variable.get()), callback=self._value_callback, user_data=variable, width=110, min_value=min_value, max_value=max_value, min_clamped=True, max_clamped=True)
        variable.bind(tag)
        attach_tooltip(tag, tooltip_key)
        return tag

    def _add_checkbox(self, label: str, variable: DpgValue, tooltip_key: str, *, tag: str | None = None) -> str:
        item = tag or tooltip_key
        variable.bind(item)
        dpg.add_checkbox(label=label, tag=item, default_value=bool(variable.get()), callback=self._value_callback, user_data=variable)
        variable.bind(item)
        attach_tooltip(item, tooltip_key)
        return item

    def _add_combo(self, label: str, variable: DpgValue, values: list[str], tooltip_key: str, *, tag: str | None = None, width: int = 0, callback: Callable[..., object] | None = None) -> str:
        item = tag or tooltip_key
        variable.bind(item)
        def _callback(sender: object, app_data: object, user_data: object) -> None:
            self._value_callback(sender, app_data, user_data)
            if callback is not None:
                callback(sender, app_data, user_data)
        dpg.add_combo(values, label=label, tag=item, default_value=str(variable.get()), callback=_callback, user_data=variable, width=width)
        variable.bind(item)
        attach_tooltip(item, tooltip_key)
        return item

    def run(self) -> None:
        _require_dearpygui()
        if not self._built:
            self._build()
        dpg.setup_dearpygui()
        dpg.show_viewport()
        try:
            while dpg.is_dearpygui_running():
                self._drain_log_queue()
                self._tick_review_animation()
                dpg.render_dearpygui_frame()
        finally:
            dpg.destroy_context()
            self._built = False

    def mainloop(self) -> None:
        self.run()

    def _show_message(self, title: str, text: str, *, level: str = "info") -> None:
        self.last_message = (title, text, level)
        prefix = "Error" if level == "error" else "Info"
        self.append_log(f"{prefix} - {title}: {text}")
        if dpg is None or not self._built:
            print(f"{title}: {text}", file=sys.stderr)
            return
        tag = f"message_{uuid4().hex}"
        with dpg.window(label=title, tag=tag, modal=True, no_resize=True, width=520, height=190):
            dpg.add_text(text, wrap=480)
            dpg.add_spacer(height=8)
            dpg.add_button(label="OK", callback=lambda: dpg.delete_item(tag), width=90)

    def _show_info(self, title: str, text: str) -> None:
        self._show_message(title, text)

    def _show_error(self, title: str, text: str) -> None:
        self._show_message(title, text, level="error")

    def _dialog_path(self, app_data: object) -> Path | None:
        if not isinstance(app_data, dict):
            return None
        for key in ("file_path_name", "current_path"):
            value = app_data.get(key)
            if value:
                return Path(str(value))
        selections = app_data.get("selections")
        if isinstance(selections, dict) and selections:
            return Path(str(next(iter(selections.values()))))
        return None

    def choose_folder(self, *_args: object) -> None:
        if dpg is not None:
            dpg.show_item("folder_dialog")

    def _choose_folder_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        if path is not None:
            self.input_path.set(str(path))
            self.refresh_files()

    def choose_file(self, *_args: object) -> None:
        if dpg is not None:
            dpg.show_item("image_file_dialog")

    def _choose_file_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        if path is not None:
            self.input_path.set(str(path))
            self.refresh_files()

    def create_sample_pack_dialog(self, *_args: object) -> None:
        self._dialog_actions["directory_action_dialog"] = self._create_sample_pack_to
        if dpg is not None:
            dpg.show_item("directory_action_dialog")

    def _create_sample_pack_to(self, path: Path) -> None:
        try:
            output = create_ui_sample_pack(path / "spritecut_sample_pack")
            self.input_path.set(str(output))
            self.refresh_files()
            self.append_log(f"Created sample pack: {output}")
        except Exception as exc:
            self._show_error("Sample Pack", str(exc))

    def refresh_files(self, *_args: object) -> None:
        path_text = str(self.input_path.get()).strip()
        self.sheet_files = []
        if self.file_list is not None:
            self.file_list.clear()
        if not path_text:
            self._show_text_panel("preview_panel", "Choose a folder or file to preview sheets.")
            return

        root = Path(path_text)
        if not root.exists():
            self._show_text_panel("preview_panel", f"Missing input: {root}")
            self.append_log(f"Missing input: {root}")
            return

        self.sheet_files = discover_sheet_files(root)
        if self.file_list is not None:
            self.file_list.set_items([path.name for path in self.sheet_files], select_first=bool(self.sheet_files))
        if self.sheet_files:
            self.update_preview()
        else:
            self._show_text_panel("preview_panel", "No supported sheet images found.")
        self.append_log(f"Loaded {len(self.sheet_files)} sheet(s).")

    def update_preview(self, *_args: object) -> None:
        if self.file_list is None:
            return
        selection = self.file_list.selected_indices()
        if not selection:
            return
        path = self.sheet_files[selection[0]]
        try:
            boxes = detect_preview_boxes(path, self.current_settings(show_error=False))
            preview = render_detection_preview(path, boxes, max_size=PREVIEW_MAX_SIZE)
            preview = apply_preview_accessibility_mode(preview, str(self.preview_accessibility_mode.get()))
            self._show_image_in_panel("preview_panel", "preview", preview, fallback_text="")
            self.append_log(f"Preview detected {len(boxes)} region(s) in {path.name}.")
        except Exception as exc:
            self._show_text_panel("preview_panel", f"Preview failed: {exc}")
            self.append_log(f"Preview failed for {path.name}: {exc}")

    def current_settings(self, *, show_error: bool = True) -> CutterUiSettings | None:
        path_text = str(self.input_path.get()).strip()
        if not path_text:
            if show_error:
                self._show_error("Missing Input", "Choose a sprite sheet file or folder first.")
            return None

        exports = []
        if bool(self.export_unity.get()):
            exports.append("unity")
        if bool(self.export_godot.get()):
            exports.append("godot")
        if bool(self.export_unreal.get()):
            exports.append("unreal")

        return CutterUiSettings(
            input_path=Path(path_text),
            auto_detect_all=bool(self.auto_detect_all.get()),
            include_archives=bool(self.include_archives.get()),
            out_name=str(self.out_name.get()).strip() or "_organized_sprites",
            mode=str(self.mode.get()),
            animation_names=str(self.animation_names.get()),
            animation_frame_mode=str(self.animation_frame_mode.get()),
            animation_anchor=str(self.animation_anchor.get()),
            animation_min_frames=int(self.animation_min_frames.get()),
            animation_fps=int(self.animation_fps.get()),
            pivot_debug=bool(self.pivot_debug.get()),
            pack_atlases=bool(self.pack_atlases.get()),
            atlas_size=int(self.atlas_size.get()),
            atlas_padding=int(self.atlas_padding.get()),
            atlas_allow_rotation=bool(self.atlas_allow_rotation.get()),
            engine_exports=exports,
            alpha_threshold=int(self.alpha_threshold.get()),
            white_threshold=int(self.white_threshold.get()),
            white_tolerance=int(self.white_tolerance.get()),
            dark_artifact_threshold=int(self.dark_artifact_threshold.get()),
            min_sprite_pixels=int(self.min_sprite_pixels.get()),
            min_sprite_width=int(self.min_sprite_width.get()),
            min_sprite_height=int(self.min_sprite_height.get()),
            crop_padding=int(self.crop_padding.get()),
            on_error=str(self.on_error.get()),
        )

    def apply_settings(self, settings: CutterUiSettings) -> None:
        self.auto_detect_all.set(settings.auto_detect_all)
        self.include_archives.set(settings.include_archives)
        self.out_name.set(settings.out_name)
        self.mode.set(settings.mode)
        self.animation_names.set(settings.animation_names)
        self.animation_frame_mode.set(settings.animation_frame_mode)
        self.animation_anchor.set(settings.animation_anchor)
        self.animation_min_frames.set(settings.animation_min_frames)
        self.animation_fps.set(settings.animation_fps)
        self.pivot_debug.set(settings.pivot_debug)
        self.pack_atlases.set(settings.pack_atlases)
        self.atlas_size.set(settings.atlas_size)
        self.atlas_padding.set(settings.atlas_padding)
        self.atlas_allow_rotation.set(settings.atlas_allow_rotation)
        self.export_unity.set("unity" in settings.engine_exports)
        self.export_godot.set("godot" in settings.engine_exports)
        self.export_unreal.set("unreal" in settings.engine_exports)
        self.alpha_threshold.set(settings.alpha_threshold)
        self.white_threshold.set(settings.white_threshold)
        self.white_tolerance.set(settings.white_tolerance)
        self.dark_artifact_threshold.set(settings.dark_artifact_threshold)
        self.min_sprite_pixels.set(settings.min_sprite_pixels)
        self.min_sprite_width.set(settings.min_sprite_width)
        self.min_sprite_height.set(settings.min_sprite_height)
        self.crop_padding.set(settings.crop_padding)
        self.on_error.set(settings.on_error)

    def apply_builtin_preset(self, *_args: object) -> None:
        input_path = Path(str(self.input_path.get()).strip()) if str(self.input_path.get()).strip() else Path(".")
        try:
            settings = settings_from_builtin_preset(str(self.builtin_preset.get()), input_path=input_path)
            self.apply_settings(settings)
            self.append_log(f"Applied built-in preset: {self.builtin_preset.get()}")
        except Exception as exc:
            self._show_error("Built-In Preset", str(exc))

    def save_preset(self, *_args: object) -> None:
        if self.current_settings() is not None and dpg is not None:
            dpg.show_item("save_preset_dialog")

    def _save_preset_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        settings = self.current_settings()
        path = self._dialog_path(app_data)
        if settings is None or path is None:
            return
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            save_preset_file(settings, path)
            self.append_log(f"Saved preset: {path}")
        except Exception as exc:
            self._show_error("Save Preset", str(exc))

    def load_preset(self, *_args: object) -> None:
        if dpg is not None:
            dpg.show_item("load_preset_dialog")

    def _load_preset_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        if path is None:
            return
        input_path = Path(str(self.input_path.get()).strip()) if str(self.input_path.get()).strip() else Path(".")
        try:
            settings = load_preset_file(path, input_path=input_path)
            self.apply_settings(settings)
            self.append_log(f"Loaded preset: {path}")
        except Exception as exc:
            self._show_error("Load Preset", str(exc))

    def load_project_dialog(self, *_args: object) -> None:
        if dpg is not None:
            dpg.show_item("load_project_dialog")

    def _load_project_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        if path is not None:
            self.load_project_file(path)

    def load_project_file(self, path: Path) -> None:
        try:
            self.current_project = load_project(path)
            self.current_project_path = path
            self._remember_recent_project(path)
            self.append_log(f"Loaded project: {path}")
            self.refresh_project_rows()
            self.refresh_project_animation_clips()
        except Exception as exc:
            self._show_error("Load Project", str(exc))

    def _remember_recent_project(self, path: Path) -> None:
        self.recent_projects = remember_recent_project(self.recent_projects_state_path, path)
        self.recent_project.set(str(self.recent_projects[0]) if self.recent_projects else "")
        if dpg is not None and self._built and dpg.does_item_exist("recent_project_combo"):
            dpg.configure_item("recent_project_combo", items=[str(project) for project in self.recent_projects])

    def open_recent_project(self, *_args: object) -> None:
        selected = str(self.recent_project.get()).strip()
        if not selected:
            self._show_info("Open Recent", "No recent project is selected.")
            return
        path = Path(selected)
        if not path.exists():
            self.recent_projects = load_recent_projects(self.recent_projects_state_path)
            self._show_error("Open Recent", f"Recent project no longer exists:\n{path}")
            return
        self.load_project_file(path)

    def save_project_dialog(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Save Project", "Load a project before saving.")
            return
        if self.current_project_path is not None:
            self._save_project_to_path(self.current_project_path)
        elif dpg is not None:
            dpg.show_item("save_project_dialog")

    def _save_project_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        if path is None:
            return
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".spritecut.json")
        self._save_project_to_path(path)

    def _save_project_to_path(self, path: Path) -> None:
        if self.current_project is None:
            return
        try:
            save_project(self.current_project, path)
            self.current_project_path = path
            self.append_log(f"Saved project: {path}")
        except Exception as exc:
            self._show_error("Save Project", str(exc))

    def apply_project_outputs(self, *_args: object) -> None:
        if self.current_project is None or self.current_project_path is None:
            self._show_info("Apply Outputs", "Load a project before applying outputs.")
            return
        try:
            result = render_project_outputs(self.current_project, self.current_project_path)
            self.append_log(
                "Applied project outputs: "
                f"rendered={result['rendered']} "
                f"skipped_rejected={result['skipped_rejected']} "
                f"errors={len(result['errors'])} "
                f"output={result['output_dir']}"
            )
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error("Apply Outputs", str(exc))

    def load_editor_sprite_dialog(self, *_args: object) -> None:
        if dpg is not None:
            dpg.show_item("editor_sprite_dialog")

    def _load_editor_sprite_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        if path is not None:
            self.load_editor_sprite(path)

    def load_editor_sprite(self, path: Path) -> None:
        try:
            self.editor_session = SpriteEditSession.open(path)
            self.editor_autotile_name.set(path.stem)
            self.append_log(f"Loaded editor sprite: {path}")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Load Sprite", str(exc))

    def refresh_editor_preview(self) -> None:
        if self.editor_session is None:
            self._show_text_panel("editor_preview_panel", "Load a sprite to edit.")
            self._set_text("editor_palette_label", "Palette: none")
            return
        image = self.editor_session.composite()
        preview = image.copy()
        preview.thumbnail((180, 135), Image.Resampling.NEAREST)
        self._show_image_in_panel("editor_preview_panel", "editor", preview)
        self._set_text("editor_palette_label", "Palette: " + editor_palette_summary(image, max_colors=8))

    def save_editor_package(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Save Package", "Load a sprite before saving an edit package.")
            return
        self._dialog_actions["directory_action_dialog"] = self._write_editor_package_to
        if dpg is not None:
            dpg.show_item("directory_action_dialog")

    def _write_editor_package_to(self, path: Path) -> None:
        if self.editor_session is None:
            return
        try:
            result = write_edit_package(self.editor_session, path)
            self.append_log(f"Saved editor package: {result['image']}")
        except Exception as exc:
            self._show_error("Save Package", str(exc))

    def _directory_action_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        path = self._dialog_path(app_data)
        action = self._dialog_actions.pop("directory_action_dialog", None)
        if path is not None and action is not None:
            action(path)

    def _apply_editor_palette_swap_impl(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Palette Swap", "Load a sprite before swapping colors.")
            return
        try:
            source = str(self.editor_source_color.get()).strip()
            target = str(self.editor_target_color.get()).strip()
            self.editor_session.replace_color(source, target)
            self.append_log(f"Palette swap: {source} -> {target}")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Palette Swap", str(exc))

    def _apply_editor_hue_shift_impl(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Hue Shift", "Load a sprite before applying hue shifts.")
            return
        try:
            degrees = float(self.editor_hue_degrees.get())
            self.editor_session.hue_shift(degrees)
            self.append_log(f"Hue shift: {degrees:g} degrees")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Hue Shift", str(exc))

    def undo_editor_edit(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Undo", "Load a sprite before undoing editor operations.")
            return
        try:
            self.editor_session.undo()
            self.append_log("Undo editor operation")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Undo", str(exc))

    def redo_editor_edit(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Redo", "Load a sprite before redoing editor operations.")
            return
        try:
            self.editor_session.redo()
            self.append_log("Redo editor operation")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Redo", str(exc))

    def _apply_editor_crop_impl(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Crop", "Load a sprite before cropping.")
            return
        try:
            rect = editor_parse_rect_text(str(self.editor_crop_rect.get()))
            self.editor_session.crop(rect)
            self.append_log(f"Crop: {rect[0]},{rect[1]},{rect[2]},{rect[3]}")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Crop", str(exc))

    def _apply_editor_resize_impl(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Resize", "Load a sprite before resizing.")
            return
        try:
            size = editor_parse_size_text(str(self.editor_resize_size.get()))
            self.editor_session.resize(size)
            self.append_log(f"Resize: {size[0]}x{size[1]}")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Resize", str(exc))

    def _apply_editor_flip_impl(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Flip", "Load a sprite before flipping.")
            return
        try:
            axis = str(self.editor_flip_axis.get()).strip().lower()
            if axis == "horizontal":
                self.editor_session.flip_horizontal()
            elif axis == "vertical":
                self.editor_session.flip_vertical()
            else:
                raise ValueError(f"Unsupported flip axis: {axis}")
            self.append_log(f"Flip: {axis}")
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Flip", str(exc))

    def _apply_editor_rotate_impl(self, *, clockwise: bool = True) -> None:
        if self.editor_session is None:
            self._show_info("Rotate", "Load a sprite before rotating.")
            return
        try:
            self.editor_session.rotate_90(clockwise=clockwise)
            self.append_log("Rotate: 90 degrees " + ("clockwise" if clockwise else "counter-clockwise"))
            self.refresh_editor_preview()
        except Exception as exc:
            self._show_error("Rotate", str(exc))

    def preview_editor_color_wheel(self, *_args: object) -> None:
        try:
            base = str(self.editor_target_color.get()).strip() or "#ff0000"
            preview = editor_color_wheel_preview(base, str(self.editor_harmony.get()))
            self.append_log(f"Color wheel: {preview}")
        except Exception as exc:
            self._show_error("Color Wheel", str(exc))

    def generate_editor_palette_variants(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Palette Variants", "Load a sprite before generating palette variants.")
            return
        self._dialog_actions["directory_action_dialog"] = self._write_palette_variants_to
        if dpg is not None:
            dpg.show_item("directory_action_dialog")

    def _write_palette_variants_to(self, path: Path) -> None:
        if self.editor_session is None:
            return
        try:
            result = editor_variant_package(
                self.editor_session,
                path,
                name=self.editor_session.name,
                base_color=str(self.editor_source_color.get()).strip() or "#ff0000",
                harmony=str(self.editor_harmony.get()),
            )
            self.append_log(f"Generated palette variants: {result['contact_sheet']}")
        except Exception as exc:
            self._show_error("Palette Variants", str(exc))

    def generate_editor_autotile(self, *_args: object) -> None:
        if self.editor_session is None:
            self._show_info("Auto-Tile", "Load a sprite before generating an auto-tile.")
            return
        self._dialog_actions["directory_action_dialog"] = self._write_autotile_to
        if dpg is not None:
            dpg.show_item("directory_action_dialog")

    def _write_autotile_to(self, path: Path) -> None:
        if self.editor_session is None:
            return
        try:
            result = write_autotile_package(
                self.editor_session.composite(),
                path,
                name=str(self.editor_autotile_name.get()).strip() or self.editor_session.name,
                engine=str(self.editor_engine.get()),
            )
            self.append_log(f"Generated auto-tile: {result['sheet']} rules={result['rules']}")
        except Exception as exc:
            self._show_error("Auto-Tile", str(exc))

    def show_editor_ide_actions(self, *_args: object) -> None:
        actions = ", ".join(editor_callable_actions())
        self._show_info("IDE API", "Use tools\\sprite_ide_api.py with --request request.json.\n\n" f"Actions: {actions}")

    def _refresh_studio_panel_impl(self, *_args: object) -> None:
        if self._studio_queue_list is not None:
            self._studio_queue_list.clear()
        if self._studio_asset_list is not None:
            self._studio_asset_list.clear()
        self.studio_asset_rows_cache = []
        if self.current_project is None:
            self._set_text("studio_dashboard_label", "Load a project to build a studio dashboard.")
            return

        self._set_text("studio_dashboard_label", studio_dashboard_text(self.current_project))
        if self._studio_queue_list is not None:
            self._studio_queue_list.set_items(studio_queue_labels(self.current_project))
        rows = studio_asset_rows(self.current_project, str(self.studio_query.get()), str(self.studio_status_filter.get()))
        self.studio_asset_rows_cache = rows
        if self._studio_asset_list is not None:
            self._studio_asset_list.set_items([studio_asset_label(item) for item in rows])

    def auto_name_studio_project(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Auto Name", "Load a project before applying taxonomy rules.")
            return
        try:
            result = apply_taxonomy_rules(self.current_project, studio_default_taxonomy_rules(str(self.studio_taxonomy_pattern.get())))  # type: ignore[arg-type]
            self.append_log(f"Auto-named project sprites: renamed={result['renamed']} pattern={result['pattern']}")
            self.refresh_project_rows()
            if self.current_project_path is not None:
                save_project(self.current_project, self.current_project_path)
        except Exception as exc:
            self._show_error("Auto Name", str(exc))

    def generate_studio_profiles(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Profiles", "Load a project before generating profiles.")
            return
        try:
            profiles = generate_collision_profiles(self.current_project)  # type: ignore[arg-type]
            plans = build_engine_import_plans(self.current_project)  # type: ignore[arg-type]
            if self.current_project_path is not None:
                save_project(self.current_project, self.current_project_path)
            self.append_log(f"Generated studio profiles: sprites={len(profiles)} engines={','.join(plans) or 'none'}")
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error("Profiles", str(exc))

    def train_studio_preset(self, *_args: object) -> None:
        if self.current_project is None or self.current_project_path is None:
            self._show_info("Train Preset", "Load a saved project before training a preset.")
            return
        try:
            preset = train_preset_from_project(self.current_project)  # type: ignore[arg-type]
            output_path = self.current_project_path.parent / "trained_spritecut_preset.json"
            output_path.write_text(json.dumps(preset, indent=2), encoding="utf-8")
            self.append_log(f"Trained preset: {output_path}")
            self.refresh_studio_panel()
        except Exception as exc:
            self._show_error("Train Preset", str(exc))

    def diff_studio_project(self, *_args: object) -> None:
        if self.current_project is None or self.current_project_path is None:
            self._show_info("Diff Project", "Load a project before comparing reruns.")
            return
        if dpg is not None:
            dpg.show_item("diff_project_dialog")

    def _diff_project_callback(self, _sender: object, app_data: object, _user_data: object = None) -> None:
        selected = self._dialog_path(app_data)
        if selected is None or self.current_project is None or self.current_project_path is None:
            return
        try:
            baseline_project = load_project(selected)
            diff = diff_projects(baseline_project, self.current_project)  # type: ignore[arg-type]
            output_path = self.current_project_path.parent / "studio_diff.json"
            output_path.write_text(json.dumps(diff, indent=2), encoding="utf-8")
            self.append_log(f"{studio_project_diff_text(baseline_project, self.current_project)} -> {output_path}")
            self.refresh_studio_panel()
        except Exception as exc:
            self._show_error("Diff Project", str(exc))

    def review_apply_studio_project(self, *_args: object) -> None:
        if self.current_project is None or self.current_project_path is None:
            self._show_info("Review + Apply", "Load a project before running the studio pass.")
            return
        try:
            result = review_and_apply_project(
                self.current_project,  # type: ignore[arg-type]
                self.current_project_path,
                naming_rules=studio_default_taxonomy_rules(str(self.studio_taxonomy_pattern.get())),
            )
            output_dir = Path(str(result["output_dir"]))
            self._set_latest_run_targets(
                RunOutputTargets(
                    output_dir=output_dir,
                    report_path=output_dir / "manifest" / "report.html",
                    project_path=self.current_project_path,
                )
            )
            self.append_log(
                "Review + Apply complete: "
                f"rendered={result['apply']['rendered']} "
                f"health={result['health']['grade']}:{result['health']['score']} "
                f"imports={','.join(result['import_plans']) or 'none'} "
                f"output={output_dir}"
            )
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error("Review + Apply", str(exc))

    def _refresh_project_rows_impl(self, *_args: object) -> None:
        if self._review_list is not None:
            self._review_list.clear()
        self.project_sprite_rows_cache = []
        if self.current_project is None:
            self._clear_review_editor("Load a project to review sprites.")
            self.refresh_studio_panel()
            return
        rows = project_sprite_rows(self.current_project, str(self.review_status_filter.get()), str(self.review_query.get()))
        self.project_sprite_rows_cache = rows
        if self._review_list is not None:
            self._review_list.set_items([format_project_sprite_label(sprite) for sprite in rows], select_first=bool(rows))
        if rows:
            self.populate_review_editor()
        else:
            self._clear_review_editor("No sprites match the current review filter.")
        self.refresh_studio_panel()

    def _clear_review_editor(self, message: str) -> None:
        self.review_animation_active = False
        self.review_animation_next_time = None
        self.review_name.set("")
        self.review_category.set("")
        self.review_bbox_x.set("")
        self.review_bbox_y.set("")
        self.review_bbox_width.set("")
        self.review_bbox_height.set("")
        self.review_pivot_x.set("")
        self.review_pivot_y.set("")
        self.review_status.set("needs_review")
        self.review_flags.set("")
        self.review_split_boxes.set("")
        self._show_text_panel("review_image_panel", message)
        self._clear_item_children("review_source_canvas")
        self._draw_canvas_text(message)

    def refresh_project_animation_clips(self) -> None:
        clip_names = project_animation_clip_names(self.current_project) if self.current_project is not None else []
        if dpg is not None and dpg.does_item_exist("review_animation_combo"):
            dpg.configure_item("review_animation_combo", items=clip_names)
        if clip_names:
            self.review_animation_clip.set(clip_names[0])
            self.review_animation_frame_index = 0
        else:
            self.review_animation_clip.set("")

    def _selected_project_sprite(self) -> dict[str, object] | None:
        if self._review_list is None:
            return None
        selection = self._review_list.selected_indices()
        if not selection or selection[0] >= len(self.project_sprite_rows_cache):
            return None
        return self.project_sprite_rows_cache[selection[0]]

    def _selected_project_sprite_ids(self) -> list[str]:
        if self._review_list is None:
            return []
        ids: list[str] = []
        for index in self._review_list.selected_indices():
            if index < len(self.project_sprite_rows_cache):
                ids.append(str(self.project_sprite_rows_cache[index].get("id", "")))
        return [sprite_id for sprite_id in ids if sprite_id]

    def populate_review_editor(self, *_args: object) -> None:
        sprite = self._selected_project_sprite()
        if sprite is None:
            return

        bbox = sprite.get("bbox", {})
        pivot = sprite.get("pivot", {})
        self.review_name.set(str(sprite.get("display_name") or sprite.get("id") or ""))
        self.review_category.set(str(sprite.get("category", "")))
        if isinstance(bbox, dict):
            self.review_bbox_x.set(str(bbox.get("x", "")))
            self.review_bbox_y.set(str(bbox.get("y", "")))
            self.review_bbox_width.set(str(bbox.get("width", "")))
            self.review_bbox_height.set(str(bbox.get("height", "")))
        if isinstance(pivot, dict):
            self.review_pivot_x.set(str(pivot.get("x", "")))
            self.review_pivot_y.set(str(pivot.get("y", "")))
        self.review_status.set(str(sprite.get("review_status", "needs_review")))
        flags = sprite.get("review_flags", [])
        self.review_flags.set(", ".join(str(flag) for flag in flags) if isinstance(flags, list) else "")
        self._update_review_image(sprite)
        self._update_review_source_canvas(sprite)

    def _update_review_image(self, sprite: dict[str, object]) -> None:
        output_file = project_sprite_preview_path_text(sprite)
        if not output_file:
            self._show_text_panel("review_image_panel", "No output image for this sprite.")
            return
        path = self._resolve_project_path(output_file)
        if not path.exists():
            self._show_text_panel("review_image_panel", f"Missing sprite image: {path.name}")
            return
        self._show_review_image_path(path)

    def _resolve_project_path(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute() or self.current_project_path is None:
            return path
        return self.current_project_path.parent / path

    def _show_review_image_path(self, path: Path) -> None:
        try:
            image = Image.open(path).convert("RGBA")
            image.thumbnail(REVIEW_IMAGE_PREVIEW_SIZE, Image.Resampling.NEAREST)
            self._show_image_in_panel("review_image_panel", "review", image.copy())
            image.close()
        except Exception as exc:
            self._show_text_panel("review_image_panel", f"Preview failed: {exc}")

    def _update_review_source_canvas(self, sprite: dict[str, object]) -> None:
        self._clear_item_children("review_source_canvas")
        source_file = sprite.get("source_file")
        bbox = sprite.get("bbox", {})
        if not source_file or not isinstance(bbox, dict):
            self._draw_canvas_text("No source box")
            return
        path = self._resolve_project_path(str(source_file))
        if not path.exists():
            self._draw_canvas_text("Missing source")
            return
        try:
            image = Image.open(path).convert("RGBA")
            canvas_size = REVIEW_CANVAS_SIZE
            int_bbox = {"x": int(bbox["x"]), "y": int(bbox["y"]), "width": int(bbox["width"]), "height": int(bbox["height"])}
            scaled = scale_bbox_for_canvas(int_bbox, image.size, canvas_size)
            display_size = (int(round(image.width * float(scaled["scale"]))), int(round(image.height * float(scaled["scale"]))))
            image = image.resize(display_size, Image.Resampling.NEAREST)
            texture = self._make_texture("review_source", image.copy())
            image.close()
            offset_x, offset_y = scaled["offset"]  # type: ignore[misc]
            self.review_canvas_scale = float(scaled["scale"])
            self.review_canvas_rect = scaled["rect"]  # type: ignore[assignment]
            if dpg is not None and dpg.does_item_exist("review_source_canvas"):
                dpg.draw_image(texture, (int(offset_x), int(offset_y)), (int(offset_x) + display_size[0], int(offset_y) + display_size[1]), parent="review_source_canvas")
                x0, y0, x1, y1 = scaled["rect"]  # type: ignore[misc]
                dpg.draw_rectangle((int(x0), int(y0)), (int(x1), int(y1)), color=(255, 90, 60, 255), thickness=2, parent="review_source_canvas")
        except Exception as exc:
            self._draw_canvas_text(f"Canvas failed: {exc}")

    def _draw_canvas_text(self, text: str) -> None:
        if dpg is not None and dpg.does_item_exist("review_source_canvas"):
            dpg.draw_text((12, 62), text, color=(230, 232, 239, 255), parent="review_source_canvas", size=14)

    def _current_bbox_fields(self) -> dict[str, int] | None:
        try:
            return parse_bbox_fields(str(self.review_bbox_x.get()), str(self.review_bbox_y.get()), str(self.review_bbox_width.get()), str(self.review_bbox_height.get()))
        except Exception:
            return None

    def _review_canvas_mouse_pos(self) -> tuple[int, int] | None:
        if dpg is None or not dpg.does_item_exist("review_source_canvas"):
            return None
        try:
            mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
            rect_min = dpg.get_item_rect_min("review_source_canvas")
            return int(mouse_x - rect_min[0]), int(mouse_y - rect_min[1])
        except Exception:
            return None

    def _on_review_canvas_press(self, *_args: object) -> None:
        bbox = self._current_bbox_fields()
        pos = self._review_canvas_mouse_pos()
        if bbox is None or pos is None or self.review_canvas_rect is None:
            return
        x0, y0, x1, y1 = self.review_canvas_rect
        if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
            self.review_canvas_drag_start = pos
            self.review_canvas_bbox_start = bbox
            self.review_canvas_drag_dirty = False

    def _on_review_canvas_drag(self, *_args: object) -> None:
        if self.review_canvas_drag_start is None or self.review_canvas_bbox_start is None:
            return
        pos = self._review_canvas_mouse_pos()
        if pos is None:
            return
        dx = pos[0] - self.review_canvas_drag_start[0]
        dy = pos[1] - self.review_canvas_drag_start[1]
        bbox = translate_bbox_by_canvas_delta(self.review_canvas_bbox_start, dx, dy, self.review_canvas_scale)
        self.review_bbox_x.set(str(bbox["x"]))
        self.review_bbox_y.set(str(bbox["y"]))
        self.review_bbox_width.set(str(bbox["width"]))
        self.review_bbox_height.set(str(bbox["height"]))
        self.review_canvas_drag_dirty = True
        sprite = self._selected_project_sprite()
        if sprite is not None:
            preview_sprite = dict(sprite)
            preview_sprite["bbox"] = bbox
            self._update_review_source_canvas(preview_sprite)

    def _on_review_canvas_release(self, *_args: object) -> None:
        if self.review_canvas_drag_dirty:
            bbox = self._current_bbox_fields()
            if bbox is not None:
                self.append_log(f"BBox draft updated: {bbox['x']},{bbox['y']},{bbox['width']},{bbox['height']}")
        self.review_canvas_drag_start = None
        self.review_canvas_bbox_start = None
        self.review_canvas_drag_dirty = False

    def play_review_animation(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Play Animation", "Load a project first.")
            return
        clip_name = str(self.review_animation_clip.get()).strip()
        if not clip_name:
            self._show_info("Play Animation", "No animation clip is available.")
            return
        self.stop_review_animation()
        self.review_animation_frame_index = 0
        self.review_animation_active = True
        self.review_animation_next_time = 0.0

    def stop_review_animation(self, *_args: object) -> None:
        self.review_animation_active = False
        self.review_animation_next_time = None

    def _tick_review_animation(self) -> None:
        if not self.review_animation_active:
            return
        if self.review_animation_next_time is not None and time.monotonic() < self.review_animation_next_time:
            return
        duration = self._show_next_animation_frame()
        self.review_animation_next_time = time.monotonic() + duration

    def _show_next_animation_frame(self) -> float:
        if self.current_project is None:
            return 0.125
        clip_name = str(self.review_animation_clip.get()).strip()
        frames = project_animation_clip_frames(self.current_project, clip_name)
        if not frames:
            return 0.125
        frame = frames[self.review_animation_frame_index % len(frames)]
        source_file = frame.get("source_file")
        if source_file:
            self._show_review_image_path(self._resolve_project_path(str(source_file)))
        duration = max(0.02, float(frame.get("duration", 0.125)))
        self.review_animation_frame_index = (self.review_animation_frame_index + 1) % len(frames)
        return duration

    def apply_review_edit(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Apply Edit", "Load a project before editing.")
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            self._show_info("Apply Edit", "Select a sprite to edit.")
            return
        try:
            update_sprite(
                self.current_project,
                str(sprite["id"]),
                display_name=str(self.review_name.get()).strip() or str(sprite["id"]),
                category=str(self.review_category.get()).strip(),
                bbox=parse_bbox_fields(str(self.review_bbox_x.get()), str(self.review_bbox_y.get()), str(self.review_bbox_width.get()), str(self.review_bbox_height.get())),
                pivot=parse_pivot_fields(str(self.review_pivot_x.get()), str(self.review_pivot_y.get())),
                review_status=str(self.review_status.get()),
                review_flags=parse_flags_text(str(self.review_flags.get())),
            )
            self.append_log(f"Edited sprite: {sprite['id']}")
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error("Apply Edit", str(exc))

    def approve_review_sprite(self, *_args: object) -> None:
        self._apply_review_action("Approve", approve_sprite)

    def reject_review_sprite(self, *_args: object) -> None:
        self._apply_review_action("Reject", reject_sprite)

    def _apply_review_action(self, label: str, action: object) -> None:
        if self.current_project is None:
            self._show_info(label, "Load a project first.")
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            self._show_info(label, "Select a sprite first.")
            return
        try:
            action(self.current_project, str(sprite["id"]))  # type: ignore[operator]
            self.append_log(f"{label}: {sprite['id']}")
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error(label, str(exc))

    def undo_project_edit(self, *_args: object) -> None:
        self._apply_project_stack_action("Undo", undo_last_edit)

    def redo_project_edit(self, *_args: object) -> None:
        self._apply_project_stack_action("Redo", redo_last_edit)

    def _apply_project_stack_action(self, label: str, action: object) -> None:
        if self.current_project is None:
            self._show_info(label, "Load a project first.")
            return
        try:
            action(self.current_project)  # type: ignore[operator]
            self.append_log(f"{label} project edit")
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error(label, str(exc))

    def _parse_split_boxes(self) -> list[dict[str, int]]:
        boxes: list[dict[str, int]] = []
        for raw_box in str(self.review_split_boxes.get()).split(";"):
            parts = [part.strip() for part in raw_box.split(",") if part.strip()]
            if not parts:
                continue
            if len(parts) != 4:
                raise ValueError("Split boxes use x,y,width,height; x,y,width,height.")
            boxes.append(parse_bbox_fields(parts[0], parts[1], parts[2], parts[3]))
        return boxes

    def split_review_sprite(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Split Sprite", "Load a project first.")
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            self._show_info("Split Sprite", "Select one sprite to split.")
            return
        try:
            split_sprite(self.current_project, str(sprite["id"]), self._parse_split_boxes())
            self.append_log(f"Split sprite: {sprite['id']}")
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error("Split Sprite", str(exc))

    def merge_review_sprites(self, *_args: object) -> None:
        if self.current_project is None:
            self._show_info("Merge Sprites", "Load a project first.")
            return
        sprite_ids = self._selected_project_sprite_ids()
        if len(sprite_ids) < 2:
            self._show_info("Merge Sprites", "Select at least two sprites.")
            return
        merged_id = str(self.review_name.get()).strip() or f"{sprite_ids[0]}_merged"
        try:
            merge_sprites(self.current_project, sprite_ids, merged_id=merged_id, display_name=merged_id)
            self.append_log(f"Merged sprites: {', '.join(sprite_ids)}")
            self.refresh_project_rows()
        except Exception as exc:
            self._show_error("Merge Sprites", str(exc))

    def _process_impl(self, *_args: object) -> None:
        if self.worker and self.worker.is_alive():
            self._show_info("Processing", "A processing run is already active.")
            return

        settings = self.current_settings()
        if settings is None:
            return

        command = build_cutter_command(settings)
        self._set_latest_run_targets(None)
        self.append_log("> " + " ".join(command))
        self._set_processing(True)
        self.worker = threading.Thread(target=self._run_process, args=(command,), daemon=True)
        self.worker.start()

    def _run_process(self, command: list[str]) -> None:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.active_process = process
            assert process.stdout is not None
            for line in process.stdout:
                for summary_line in summarize_cli_output_line(line.rstrip()):
                    self.log_queue.put(summary_line)
            return_code = process.wait()
            self.log_queue.put(f"Process exited with code {return_code}")
        except Exception as exc:
            self.log_queue.put(f"Process failed: {exc}")
        finally:
            self.active_process = None
            self.log_queue.put("__STOP_PROGRESS__")

    def cancel_process(self, *_args: object) -> None:
        process = self.active_process
        if process is None or process.poll() is not None:
            self.append_log("No active process to cancel.")
            self._set_processing(False)
            return
        self.append_log("Cancel requested.")
        process.terminate()

    def _drain_log_queue(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if line == "__STOP_PROGRESS__":
                self._set_processing(False)
            else:
                targets = output_targets_from_cli_line(line)
                if targets is not None:
                    self._set_latest_run_targets(targets)
                self.append_log(line)

    def _set_processing(self, active: bool) -> None:
        self._set_text("progress_text", "Processing..." if active else "Idle")
        self._set_button_enabled("process_button", not active)
        self._set_button_enabled("cancel_button", active)

    def _set_latest_run_targets(self, targets: RunOutputTargets | None) -> None:
        self.latest_output_dir = targets.output_dir if targets is not None else None
        self.latest_report_path = targets.report_path if targets is not None else None
        self.latest_project_path = targets.project_path if targets is not None else None
        enabled = targets is not None
        self._set_button_enabled("open_output_button", enabled)
        self._set_button_enabled("open_report_button", enabled)
        self._set_button_enabled("open_project_button", enabled)

    def open_latest_output(self, *_args: object) -> None:
        self._open_existing_path(self.latest_output_dir, "output folder")

    def open_latest_report(self, *_args: object) -> None:
        self._open_existing_path(self.latest_report_path, "HTML report")

    def open_latest_project(self, *_args: object) -> None:
        if self.latest_project_path is not None and self.latest_project_path.exists():
            self.load_project_file(self.latest_project_path)
            return
        self._open_existing_path(self.latest_project_path, "project file")

    def _open_existing_path(self, path: Path | None, label: str) -> None:
        if path is None:
            self._show_info("No Run Output", "Process a sheet before opening run output.")
            return
        if not path.exists():
            self._show_error("Missing Output", f"The latest {label} does not exist:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            self._show_error("Open Output", str(exc))

    def append_log(self, text: str) -> None:
        self.log_lines.append(text)
        if len(self.log_lines) > 1000:
            self.log_lines = self.log_lines[-1000:]
        self._set_text("log_text", "\n".join(self.log_lines))

    def clear_log(self, *_args: object) -> None:
        self.log_lines = []
        self._set_text("log_text", "")

    def _set_button_enabled(self, tag: str, enabled: bool) -> None:
        if dpg is not None and self._built and dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=enabled)

    def _set_text(self, tag: str, text: str) -> None:
        if dpg is not None and self._built and dpg.does_item_exist(tag):
            dpg.set_value(tag, text)

    def _clear_item_children(self, tag: str) -> None:
        if dpg is not None and self._built and dpg.does_item_exist(tag):
            dpg.delete_item(tag, children_only=True)

    def _show_text_panel(self, panel_tag: str, text: str) -> None:
        if dpg is None or not self._built or not dpg.does_item_exist(panel_tag):
            return
        dpg.delete_item(panel_tag, children_only=True)
        dpg.add_text(text, parent=panel_tag, wrap=520)

    def _make_texture(self, key: str, image: Image.Image) -> str:
        if dpg is None:
            raise RuntimeError("Dear PyGUI is not available.")
        existing = self._texture_tags.get(key)
        if existing and dpg.does_item_exist(existing):
            dpg.delete_item(existing)
        width, height, data = _image_texture_data(image)
        tag = f"texture_{key}_{uuid4().hex}"
        dpg.add_static_texture(width=width, height=height, default_value=data, tag=tag, parent=self._texture_registry)
        self._texture_tags[key] = tag
        return tag

    def _show_image_in_panel(self, panel_tag: str, key: str, image: Image.Image, *, fallback_text: str = "") -> None:
        if dpg is None or not self._built or not dpg.does_item_exist(panel_tag):
            return
        dpg.delete_item(panel_tag, children_only=True)
        texture = self._make_texture(key, image)
        dpg.add_image(texture, parent=panel_tag)
        if fallback_text:
            dpg.add_text(fallback_text, parent=panel_tag, wrap=520)


def main() -> None:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print("Sprite Sheet Processor UI")
        print("")
        print("Launches a Dear PyGUI desktop wrapper for tools/cut_tileset_sprites.py.")
        print("Run without arguments:")
        print("  python tools\\sprite_sheet_tool_ui.py")
        print("")
        print("The UI supports preview, cutter settings, review editing, Studio health/diff/search, sprite editing, auto-tiles, import plans, and live logs.")
        return

    try:
        app = SpriteSheetToolUi()
        app.run()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
