from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

try:
    from tools.autotile_tools import write_autotile_package
    from tools.cut_tileset_sprites import BUILT_IN_PRESETS, DetectionSettings, detect_background, extract_detections, grouped_components, is_inside_spritecut_output
    from tools.sprite_editor import SpriteEditSession, apply_hue_shift, apply_palette_swap, color_wheel_palette, extract_palette, write_edit_package
    from tools.sprite_project import approve_sprite, load_project, merge_sprites, redo_last_edit, reject_sprite, render_project_outputs, save_project, split_sprite, undo_last_edit, update_sprite
    from tools.sprite_studio import apply_taxonomy_rules, asset_browser_index, batch_health_score, build_engine_import_plans, build_review_dashboard, diff_projects, generate_collision_profiles, review_and_apply_project, search_assets, train_preset_from_project
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.autotile_tools import write_autotile_package
    from tools.cut_tileset_sprites import BUILT_IN_PRESETS, DetectionSettings, detect_background, extract_detections, grouped_components, is_inside_spritecut_output
    from tools.sprite_editor import SpriteEditSession, apply_hue_shift, apply_palette_swap, color_wheel_palette, extract_palette, write_edit_package
    from tools.sprite_project import approve_sprite, load_project, merge_sprites, redo_last_edit, reject_sprite, render_project_outputs, save_project, split_sprite, undo_last_edit, update_sprite
    from tools.sprite_studio import apply_taxonomy_rules, asset_browser_index, batch_health_score, build_engine_import_plans, build_review_dashboard, diff_projects, generate_collision_profiles, review_and_apply_project, search_assets, train_preset_from_project


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SCRIPT_PATH = Path(__file__).with_name("cut_tileset_sprites.py")
PREVIEW_ACCESSIBILITY_MODES = ["normal", "grayscale", "protanopia", "deuteranopia", "tritanopia"]
TOOLTIP_TEXT: dict[str, str] = {
    "input_path": "Folder or image file to process. Folder scans skip prior SpriteCut output folders automatically.",
    "add_folder": "Choose a folder containing sprite sheets or nested asset folders.",
    "add_file": "Choose a single sprite sheet image when you want to process just one file.",
    "refresh_files": "Rescan the selected input path and rebuild the sheet list and preview.",
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
    "editor_hue_degrees": "Hue rotation in degrees for color-wheel style sprite recoloring.",
    "editor_hue_shift": "Apply hue, saturation, and value changes to the current sprite session.",
    "editor_color_wheel": "Preview color harmony suggestions such as complementary, analogous, triadic, or tetradic.",
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
    output_dir = Path(output_text)
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
        gray = rgba.convert("LA").convert("RGBA")
        return gray

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


def studio_asset_rows(
    project: dict[str, object],
    query: str = "",
    status_filter: str = "all",
    category_filter: str = "all",
) -> list[dict[str, object]]:
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


def editor_callable_actions() -> list[str]:
    return ["sprite.edit", "sprite.batch_edit", "palette.extract", "palette.swap", "palette.hue_shift", "palette.variants", "autotile.generate"]


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


def scale_bbox_for_canvas(
    bbox: dict[str, int],
    image_size: tuple[int, int],
    canvas_size: tuple[int, int],
) -> dict[str, object]:
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
    return tk.NORMAL if has_active_process else tk.DISABLED


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.after_id: str | None = None
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self._unschedule()
        self.after_id = self.widget.after(self.delay_ms, self._show)

    def _unschedule(self) -> None:
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def _show(self) -> None:
        if self.window is not None:
            return
        x, y = self.widget.winfo_pointerxy()
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x + 14}+{y + 18}")
        label = tk.Label(
            self.window,
            text=self.text,
            justify="left",
            wraplength=320,
            background="#111318",
            foreground="#e6e8ef",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=6,
        )
        label.pack()

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._unschedule()
        if self.window is not None:
            self.window.destroy()
            self.window = None


def attach_tooltip(widget: tk.Widget, key: str) -> tk.Widget:
    tooltip = ToolTip(widget, tooltip_text(key))
    setattr(widget, "_spritecut_tooltip", tooltip)
    return widget


class SpriteSheetToolUi(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Sprite Sheet Processor")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(bg="#17191d")

        self.input_path = tk.StringVar()
        self.auto_detect_all = tk.BooleanVar(value=True)
        self.out_name = tk.StringVar(value="_organized_sprites")
        self.mode = tk.StringVar(value="auto")
        self.animation_names = tk.StringVar()
        self.animation_frame_mode = tk.StringVar(value="fixed")
        self.animation_anchor = tk.StringVar(value="bottom-center")
        self.animation_min_frames = tk.IntVar(value=3)
        self.animation_fps = tk.IntVar(value=12)
        self.pivot_debug = tk.BooleanVar(value=False)
        self.pack_atlases = tk.BooleanVar(value=True)
        self.atlas_size = tk.IntVar(value=2048)
        self.atlas_padding = tk.IntVar(value=2)
        self.atlas_allow_rotation = tk.BooleanVar(value=False)
        self.export_unity = tk.BooleanVar(value=True)
        self.export_godot = tk.BooleanVar(value=True)
        self.export_unreal = tk.BooleanVar(value=True)
        self.alpha_threshold = tk.IntVar(value=10)
        self.white_threshold = tk.IntVar(value=250)
        self.white_tolerance = tk.IntVar(value=8)
        self.dark_artifact_threshold = tk.IntVar(value=45)
        self.min_sprite_pixels = tk.IntVar(value=24)
        self.min_sprite_width = tk.IntVar(value=3)
        self.min_sprite_height = tk.IntVar(value=3)
        self.crop_padding = tk.IntVar(value=1)
        self.on_error = tk.StringVar(value="skip")
        self.builtin_preset = tk.StringVar(value=builtin_preset_names()[0])
        self.preview_accessibility_mode = tk.StringVar(value="normal")

        self.sheet_files: list[Path] = []
        self.preview_image: ImageTk.PhotoImage | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.active_process: subprocess.Popen | None = None
        self.latest_output_dir: Path | None = None
        self.latest_report_path: Path | None = None
        self.latest_project_path: Path | None = None
        self.current_project: dict[str, object] | None = None
        self.current_project_path: Path | None = None
        self.project_sprite_rows_cache: list[dict[str, object]] = []
        self.review_image: ImageTk.PhotoImage | None = None
        self.review_source_canvas_image: ImageTk.PhotoImage | None = None
        self.review_canvas_scale: float = 1.0
        self.review_canvas_drag_start: tuple[int, int] | None = None
        self.review_canvas_bbox_start: dict[str, int] | None = None

        self.review_status_filter = tk.StringVar(value="all")
        self.review_query = tk.StringVar()
        self.review_name = tk.StringVar()
        self.review_category = tk.StringVar()
        self.review_bbox_x = tk.StringVar()
        self.review_bbox_y = tk.StringVar()
        self.review_bbox_width = tk.StringVar()
        self.review_bbox_height = tk.StringVar()
        self.review_pivot_x = tk.StringVar()
        self.review_pivot_y = tk.StringVar()
        self.review_status = tk.StringVar(value="needs_review")
        self.review_flags = tk.StringVar()
        self.review_split_boxes = tk.StringVar()
        self.review_animation_clip = tk.StringVar()
        self.review_animation_frame_index = 0
        self.review_animation_after_id: str | None = None
        self.studio_query = tk.StringVar()
        self.studio_status_filter = tk.StringVar(value="all")
        self.studio_taxonomy_pattern = tk.StringVar(value="{category}_{source_sheet}_{index:03d}")
        self.studio_asset_rows_cache: list[dict[str, object]] = []
        self.editor_session: SpriteEditSession | None = None
        self.editor_image: ImageTk.PhotoImage | None = None
        self.editor_source_color = tk.StringVar(value="#ff0000")
        self.editor_target_color = tk.StringVar(value="#00ffff")
        self.editor_hue_degrees = tk.StringVar(value="0")
        self.editor_harmony = tk.StringVar(value="complementary")
        self.editor_autotile_name = tk.StringVar(value="autotile")
        self.editor_engine = tk.StringVar(value="godot")

        self._style()
        self._build_layout()
        self.after(100, self._drain_log_queue)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#17191d")
        style.configure("Panel.TFrame", background="#20242b")
        style.configure("TLabel", background="#17191d", foreground="#e6e8ef")
        style.configure("Panel.TLabel", background="#20242b", foreground="#e6e8ef")
        style.configure("TButton", background="#2f6feb", foreground="#ffffff", padding=8)
        style.map("TButton", background=[("active", "#3b82f6")])
        style.configure("TCheckbutton", background="#20242b", foreground="#e6e8ef")
        style.configure("TRadiobutton", background="#20242b", foreground="#e6e8ef")
        style.configure("TEntry", fieldbackground="#111318", foreground="#e6e8ef")
        style.configure("TCombobox", fieldbackground="#111318", foreground="#e6e8ef")
        style.configure("Horizontal.TProgressbar", background="#2f6feb", troughcolor="#111318")

    def _build_layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="ns", padx=(10, 6), pady=10)
        left.columnconfigure(0, weight=1)

        center = ttk.Frame(self, style="Panel.TFrame", padding=12)
        center.grid(row=0, column=1, sticky="nsew", padx=6, pady=10)
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)

        right = ttk.Frame(self, style="Panel.TFrame", padding=12)
        right.grid(row=0, column=2, sticky="ns", padx=(6, 10), pady=10)

        self._build_left(left)
        self._build_center(center)
        self._build_right(right)

    def _grid_tip(self, widget: tk.Widget, tooltip_key: str, **grid_options: object) -> tk.Widget:
        widget.grid(**grid_options)
        attach_tooltip(widget, tooltip_key)
        return widget

    def _build_left(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Input", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self._grid_tip(ttk.Entry(parent, textvariable=self.input_path, width=34), "input_path", row=1, column=0, sticky="ew", pady=(8, 6))
        self._grid_tip(ttk.Button(parent, text="Add Folder", command=self.choose_folder), "add_folder", row=2, column=0, sticky="ew", pady=3)
        self._grid_tip(ttk.Button(parent, text="Add File", command=self.choose_file), "add_file", row=3, column=0, sticky="ew", pady=3)
        self._grid_tip(ttk.Button(parent, text="Refresh", command=self.refresh_files), "refresh_files", row=4, column=0, sticky="ew", pady=(3, 10))

        ttk.Label(parent, text="Sheets", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(row=5, column=0, sticky="w", pady=(8, 4))
        self.file_list = tk.Listbox(parent, width=38, height=24, bg="#111318", fg="#e6e8ef", selectbackground="#2f6feb", relief="flat")
        self.file_list.grid(row=6, column=0, sticky="nsew")
        attach_tooltip(self.file_list, "file_list")
        self.file_list.bind("<<ListboxSelect>>", lambda _event: self.update_preview())

    def _build_center(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Preview", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        preview_mode = ttk.Combobox(
            header,
            textvariable=self.preview_accessibility_mode,
            values=PREVIEW_ACCESSIBILITY_MODES,
            state="readonly",
            width=14,
        )
        self._grid_tip(preview_mode, "preview_accessibility", row=0, column=1, sticky="e")
        self.preview_accessibility_mode.trace_add("write", lambda *_args: self.update_preview())
        self.preview_label = ttk.Label(parent, text="Choose a folder or file to preview sheets.", style="Panel.TLabel", anchor="center")
        self.preview_label.grid(row=1, column=0, sticky="nsew", pady=(8, 10))

        bottom = ttk.Frame(parent, style="Panel.TFrame")
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._grid_tip(ttk.Button(bottom, text="Process", command=self.process), "process", row=0, column=1, padx=4)
        self._grid_tip(ttk.Button(bottom, text="Reset Log", command=self.clear_log), "reset_log", row=0, column=2, padx=(4, 0))
        self.cancel_button = ttk.Button(bottom, text="Cancel", command=self.cancel_process, state=tk.DISABLED)
        self._grid_tip(self.cancel_button, "cancel", row=0, column=3, padx=(4, 0))
        self.open_output_button = ttk.Button(bottom, text="Open Output", command=self.open_latest_output, state=tk.DISABLED)
        self._grid_tip(self.open_output_button, "open_output", row=1, column=1, sticky="ew", padx=4, pady=(8, 0))
        self.open_report_button = ttk.Button(bottom, text="Open Report", command=self.open_latest_report, state=tk.DISABLED)
        self._grid_tip(self.open_report_button, "open_report", row=1, column=2, sticky="ew", padx=(4, 0), pady=(8, 0))
        self.open_project_button = ttk.Button(bottom, text="Open Project", command=self.open_latest_project, state=tk.DISABLED)
        self._grid_tip(self.open_project_button, "open_project", row=1, column=3, sticky="ew", padx=(4, 0), pady=(8, 0))

        self.log = tk.Text(parent, height=10, bg="#111318", fg="#d7dde8", insertbackground="#d7dde8", relief="flat")
        self.log.grid(row=3, column=0, sticky="ew", pady=(10, 0))

    def _build_right(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        ttk.Label(parent, text="Settings", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        notebook = ttk.Notebook(parent)
        notebook.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        core = ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        detection = ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        output = ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        review = ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        studio = ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        editor = ttk.Frame(notebook, style="Panel.TFrame", padding=8)
        notebook.add(core, text="Core")
        notebook.add(detection, text="Detect")
        notebook.add(output, text="Output")
        notebook.add(review, text="Review")
        notebook.add(studio, text="Studio")
        notebook.add(editor, text="Editor")

        self._build_core_settings(core)
        self._build_detection_settings(detection)
        self._build_output_settings(output)
        self._build_review_settings(review)
        self._build_studio_settings(studio)
        self._build_editor_settings(editor)

    def _build_core_settings(self, parent: ttk.Frame) -> None:
        self._label(parent, "Output", 0)
        self._grid_tip(ttk.Entry(parent, textvariable=self.out_name, width=24), "out_name", row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._grid_tip(ttk.Checkbutton(parent, text="Auto detect all", variable=self.auto_detect_all), "auto_detect_all", row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._label(parent, "Built-In Preset", 3)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.builtin_preset, values=builtin_preset_names(), state="readonly", width=20), "builtin_preset", row=4, column=0, columnspan=2, sticky="ew")
        self._grid_tip(ttk.Button(parent, text="Apply Preset", command=self.apply_builtin_preset), "apply_preset", row=5, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        self._label(parent, "Mode", 6)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.mode, values=["auto", "tileset", "animation"], state="readonly", width=20), "mode", row=7, column=0, columnspan=2, sticky="ew")
        self._label(parent, "Animation Rows", 8)
        self._grid_tip(ttk.Entry(parent, textvariable=self.animation_names, width=24), "animation_names", row=9, column=0, columnspan=2, sticky="ew")
        self._label(parent, "Frame Mode", 10)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.animation_frame_mode, values=["fixed", "trimmed"], state="readonly", width=20), "animation_frame_mode", row=11, column=0, columnspan=2, sticky="ew")
        self._label(parent, "Anchor", 12)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.animation_anchor, values=["bottom-center", "center"], state="readonly", width=20), "animation_anchor", row=13, column=0, columnspan=2, sticky="ew")
        self._label(parent, "Min Frames", 14)
        self._grid_tip(ttk.Spinbox(parent, from_=1, to=24, textvariable=self.animation_min_frames, width=8), "animation_min_frames", row=15, column=0, sticky="w", pady=(0, 8))
        self._label(parent, "FPS", 16)
        self._grid_tip(ttk.Spinbox(parent, from_=1, to=60, textvariable=self.animation_fps, width=8), "animation_fps", row=17, column=0, sticky="w", pady=(0, 8))
        self._grid_tip(ttk.Checkbutton(parent, text="Pivot debug previews", variable=self.pivot_debug), "pivot_debug", row=18, column=0, columnspan=2, sticky="w", pady=3)

    def _build_detection_settings(self, parent: ttk.Frame) -> None:
        controls = [
            ("Alpha Threshold", self.alpha_threshold, 0, 255, "alpha_threshold"),
            ("White Threshold", self.white_threshold, 0, 255, "white_threshold"),
            ("White Tolerance", self.white_tolerance, 0, 64, "white_tolerance"),
            ("Dark Artifact", self.dark_artifact_threshold, 0, 255, "dark_artifact_threshold"),
            ("Min Pixels", self.min_sprite_pixels, 1, 10000, "min_sprite_pixels"),
            ("Min Width", self.min_sprite_width, 1, 512, "min_sprite_width"),
            ("Min Height", self.min_sprite_height, 1, 512, "min_sprite_height"),
            ("Crop Padding", self.crop_padding, 0, 64, "crop_padding"),
        ]
        for row, (label, variable, from_value, to_value, tooltip_key) in enumerate(controls):
            self._grid_tip(ttk.Label(parent, text=label, style="Panel.TLabel"), tooltip_key, row=row, column=0, sticky="w", pady=3)
            self._grid_tip(ttk.Spinbox(parent, from_=from_value, to=to_value, textvariable=variable, width=8), tooltip_key, row=row, column=1, sticky="e", pady=3)
        self._label(parent, "On Error", len(controls))
        self._grid_tip(ttk.Combobox(parent, textvariable=self.on_error, values=["skip", "fail"], state="readonly", width=10), "on_error", row=len(controls) + 1, column=0, columnspan=2, sticky="ew")

    def _build_output_settings(self, parent: ttk.Frame) -> None:
        self._grid_tip(ttk.Checkbutton(parent, text="Pack atlases", variable=self.pack_atlases), "pack_atlases", row=0, column=0, columnspan=2, sticky="w", pady=3)
        self._label(parent, "Atlas Size", 1)
        self._grid_tip(ttk.Entry(parent, textvariable=self.atlas_size, width=10), "atlas_size", row=2, column=0, sticky="w")
        self._label(parent, "Padding", 3)
        self._grid_tip(ttk.Entry(parent, textvariable=self.atlas_padding, width=10), "atlas_padding", row=4, column=0, sticky="w")
        self._grid_tip(ttk.Checkbutton(parent, text="Allow rotation", variable=self.atlas_allow_rotation), "atlas_allow_rotation", row=5, column=0, columnspan=2, sticky="w", pady=(3, 10))

        self._grid_tip(ttk.Label(parent, text="Exports", style="Panel.TLabel", font=("Segoe UI", 11, "bold")), "engine_exports", row=6, column=0, columnspan=2, sticky="w", pady=(8, 3))
        self._grid_tip(ttk.Checkbutton(parent, text="Unity", variable=self.export_unity), "export_unity", row=7, column=0, sticky="w")
        self._grid_tip(ttk.Checkbutton(parent, text="Godot", variable=self.export_godot), "export_godot", row=8, column=0, sticky="w")
        self._grid_tip(ttk.Checkbutton(parent, text="Unreal", variable=self.export_unreal), "export_unreal", row=9, column=0, sticky="w")
        self._grid_tip(ttk.Button(parent, text="Save Preset", command=self.save_preset), "save_preset", row=10, column=0, columnspan=2, sticky="ew", pady=(16, 3))
        self._grid_tip(ttk.Button(parent, text="Load Preset", command=self.load_preset), "load_preset", row=11, column=0, columnspan=2, sticky="ew", pady=3)

    def _build_review_settings(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        self._grid_tip(ttk.Button(parent, text="Load Project", command=self.load_project_dialog), "load_project", row=0, column=0, sticky="ew", pady=2, padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Save Project", command=self.save_project_dialog), "save_project", row=0, column=1, sticky="ew", pady=2, padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Undo", command=self.undo_project_edit), "undo", row=1, column=0, sticky="ew", pady=2, padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Redo", command=self.redo_project_edit), "redo", row=1, column=1, sticky="ew", pady=2, padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Apply Outputs", command=self.apply_project_outputs), "apply_outputs", row=2, column=0, columnspan=2, sticky="ew", pady=(6, 2))

        self._label(parent, "Filter", 3)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.review_status_filter, values=["all", "needs_review", "approved", "rejected"], state="readonly", width=16), "review_filter", row=4, column=0, sticky="ew", pady=(0, 4), padx=(0, 3))
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_query, width=16), "review_query", row=4, column=1, sticky="ew", pady=(0, 4), padx=(3, 0))
        self.review_status_filter.trace_add("write", lambda *_args: self.refresh_project_rows())
        self.review_query.trace_add("write", lambda *_args: self.refresh_project_rows())

        self.review_list = tk.Listbox(parent, width=34, height=9, bg="#111318", fg="#e6e8ef", selectbackground="#2f6feb", relief="flat", selectmode=tk.EXTENDED)
        self.review_list.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        attach_tooltip(self.review_list, "review_list")
        self.review_list.bind("<<ListboxSelect>>", lambda _event: self.populate_review_editor())

        self.review_image_label = ttk.Label(parent, text="Load a project to review sprites.", style="Panel.TLabel", anchor="center")
        self.review_image_label.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self.review_source_canvas = tk.Canvas(parent, width=220, height=140, bg="#111318", highlightthickness=0)
        self.review_source_canvas.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        attach_tooltip(self.review_source_canvas, "review_source_canvas")
        self.review_source_canvas.bind("<ButtonPress-1>", self._on_review_canvas_press)
        self.review_source_canvas.bind("<B1-Motion>", self._on_review_canvas_drag)
        self.review_source_canvas.bind("<ButtonRelease-1>", self._on_review_canvas_release)

        self._label(parent, "Animation Clip", 8)
        self.review_animation_combo = ttk.Combobox(parent, textvariable=self.review_animation_clip, values=[], state="readonly", width=24)
        self._grid_tip(self.review_animation_combo, "animation_clip", row=9, column=0, columnspan=2, sticky="ew")
        self._grid_tip(ttk.Button(parent, text="Play", command=self.play_review_animation), "play_animation", row=10, column=0, sticky="ew", pady=(4, 2), padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Stop", command=self.stop_review_animation), "stop_animation", row=10, column=1, sticky="ew", pady=(4, 2), padx=(3, 0))

        self._label(parent, "Name", 11)
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_name, width=24), "review_name", row=12, column=0, columnspan=2, sticky="ew")
        self._label(parent, "Category", 13)
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_category, width=24), "review_category", row=14, column=0, columnspan=2, sticky="ew")

        self._label(parent, "BBox x/y/w/h", 15)
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_bbox_x, width=6), "review_bbox", row=16, column=0, sticky="w")
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_bbox_y, width=6), "review_bbox", row=16, column=0)
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_bbox_width, width=6), "review_bbox", row=16, column=1, sticky="w")
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_bbox_height, width=6), "review_bbox", row=16, column=1, sticky="e")

        self._label(parent, "Pivot x/y", 17)
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_pivot_x, width=8), "review_pivot", row=18, column=0, sticky="w")
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_pivot_y, width=8), "review_pivot", row=18, column=1, sticky="w")

        self._label(parent, "Status / Flags", 19)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.review_status, values=["needs_review", "approved", "rejected"], state="readonly", width=14), "review_status", row=20, column=0, sticky="ew", padx=(0, 3))
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_flags, width=14), "review_flags", row=20, column=1, sticky="ew", padx=(3, 0))

        self._grid_tip(ttk.Button(parent, text="Apply Edit", command=self.apply_review_edit), "apply_edit", row=21, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        self._grid_tip(ttk.Button(parent, text="Approve", command=self.approve_review_sprite), "approve", row=22, column=0, sticky="ew", pady=2, padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Reject", command=self.reject_review_sprite), "reject", row=22, column=1, sticky="ew", pady=2, padx=(3, 0))

        self._label(parent, "Split boxes", 23)
        self._grid_tip(ttk.Entry(parent, textvariable=self.review_split_boxes, width=24), "split_boxes", row=24, column=0, columnspan=2, sticky="ew")
        self._grid_tip(ttk.Button(parent, text="Split Selected", command=self.split_review_sprite), "split_selected", row=25, column=0, sticky="ew", pady=(6, 2), padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Merge Selected", command=self.merge_review_sprites), "merge_selected", row=25, column=1, sticky="ew", pady=(6, 2), padx=(3, 0))

    def _build_studio_settings(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        self._grid_tip(ttk.Button(parent, text="Refresh", command=self.refresh_studio_panel), "studio_refresh", row=0, column=0, sticky="ew", pady=2, padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Review + Apply", command=self.review_apply_studio_project), "studio_review_apply", row=0, column=1, sticky="ew", pady=2, padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Auto Name", command=self.auto_name_studio_project), "studio_auto_name", row=1, column=0, sticky="ew", pady=2, padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Profiles", command=self.generate_studio_profiles), "studio_generate_profiles", row=1, column=1, sticky="ew", pady=2, padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Diff Project", command=self.diff_studio_project), "studio_diff_project", row=2, column=0, sticky="ew", pady=(2, 8), padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Train Preset", command=self.train_studio_preset), "studio_train_preset", row=2, column=1, sticky="ew", pady=(2, 8), padx=(3, 0))

        self._label(parent, "Taxonomy Pattern", 3)
        self._grid_tip(ttk.Entry(parent, textvariable=self.studio_taxonomy_pattern, width=28), "studio_taxonomy_pattern", row=4, column=0, columnspan=2, sticky="ew")

        self._label(parent, "Dashboard", 5)
        self.studio_dashboard_label = ttk.Label(parent, text="Load a project to build a studio dashboard.", style="Panel.TLabel", wraplength=260, justify="left")
        self.studio_dashboard_label.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        attach_tooltip(self.studio_dashboard_label, "studio_dashboard")

        self._label(parent, "Review Queue", 7)
        self.studio_queue_list = tk.Listbox(parent, width=34, height=6, bg="#111318", fg="#e6e8ef", selectbackground="#2f6feb", relief="flat")
        self.studio_queue_list.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        attach_tooltip(self.studio_queue_list, "studio_queue")

        self._label(parent, "Asset Browser", 9)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.studio_status_filter, values=["all", "needs_review", "approved", "rejected"], state="readonly", width=14), "studio_asset_query", row=10, column=0, sticky="ew", padx=(0, 3))
        self._grid_tip(ttk.Entry(parent, textvariable=self.studio_query, width=14), "studio_asset_query", row=10, column=1, sticky="ew", padx=(3, 0))
        self.studio_asset_list = tk.Listbox(parent, width=34, height=9, bg="#111318", fg="#e6e8ef", selectbackground="#2f6feb", relief="flat")
        self.studio_asset_list.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        attach_tooltip(self.studio_asset_list, "studio_asset_list")
        self.studio_status_filter.trace_add("write", lambda *_args: self.refresh_studio_panel())
        self.studio_query.trace_add("write", lambda *_args: self.refresh_studio_panel())

    def _build_editor_settings(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        self._grid_tip(ttk.Button(parent, text="Load Sprite", command=self.load_editor_sprite_dialog), "editor_load_sprite", row=0, column=0, sticky="ew", pady=2, padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Save Package", command=self.save_editor_package), "editor_save_package", row=0, column=1, sticky="ew", pady=2, padx=(3, 0))

        self.editor_preview_label = ttk.Label(parent, text="Load a sprite to edit.", style="Panel.TLabel", anchor="center")
        self.editor_preview_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 6))

        self.editor_palette_label = ttk.Label(parent, text="Palette: none", style="Panel.TLabel", wraplength=260, justify="left")
        self.editor_palette_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        attach_tooltip(self.editor_palette_label, "editor_palette_summary")

        self._label(parent, "Palette Swap", 3)
        self._grid_tip(ttk.Entry(parent, textvariable=self.editor_source_color, width=12), "editor_source_color", row=4, column=0, sticky="ew", padx=(0, 3))
        self._grid_tip(ttk.Entry(parent, textvariable=self.editor_target_color, width=12), "editor_target_color", row=4, column=1, sticky="ew", padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Swap", command=self.apply_editor_palette_swap), "editor_swap_colors", row=5, column=0, columnspan=2, sticky="ew", pady=(4, 8))

        self._label(parent, "Color Wheel", 6)
        self._grid_tip(ttk.Combobox(parent, textvariable=self.editor_harmony, values=["complementary", "analogous", "triadic", "tetradic"], state="readonly", width=14), "editor_color_wheel", row=7, column=0, sticky="ew", padx=(0, 3))
        self._grid_tip(ttk.Entry(parent, textvariable=self.editor_hue_degrees, width=12), "editor_hue_degrees", row=7, column=1, sticky="ew", padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Hue Shift", command=self.apply_editor_hue_shift), "editor_hue_shift", row=8, column=0, sticky="ew", pady=(4, 2), padx=(0, 3))
        self._grid_tip(ttk.Button(parent, text="Wheel", command=self.preview_editor_color_wheel), "editor_color_wheel", row=8, column=1, sticky="ew", pady=(4, 2), padx=(3, 0))

        self._label(parent, "Auto-Tile", 9)
        self._grid_tip(ttk.Entry(parent, textvariable=self.editor_autotile_name, width=14), "editor_autotile_name", row=10, column=0, sticky="ew", padx=(0, 3))
        self._grid_tip(ttk.Combobox(parent, textvariable=self.editor_engine, values=["generic", "unity", "godot", "unreal"], state="readonly", width=10), "engine_exports", row=10, column=1, sticky="ew", padx=(3, 0))
        self._grid_tip(ttk.Button(parent, text="Generate Auto-Tile", command=self.generate_editor_autotile), "editor_generate_autotile", row=11, column=0, columnspan=2, sticky="ew", pady=(4, 8))

        self._grid_tip(ttk.Button(parent, text="IDE Actions", command=self.show_editor_ide_actions), "editor_ide_api", row=12, column=0, columnspan=2, sticky="ew")

    def _label(self, parent: ttk.Frame, text: str, row: int) -> None:
        ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))

    def choose_folder(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self.input_path.set(path)
            self.refresh_files()

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"), ("All files", "*.*")])
        if path:
            self.input_path.set(path)
            self.refresh_files()

    def refresh_files(self) -> None:
        path_text = self.input_path.get().strip()
        self.file_list.delete(0, tk.END)
        self.sheet_files = []
        if not path_text:
            return

        root = Path(path_text)
        if not root.exists():
            self.append_log(f"Missing input: {root}")
            return

        self.sheet_files = discover_sheet_files(root)
        for path in self.sheet_files:
            self.file_list.insert(tk.END, path.name)
        if self.sheet_files:
            self.file_list.selection_set(0)
            self.update_preview()
        self.append_log(f"Loaded {len(self.sheet_files)} sheet(s).")

    def update_preview(self) -> None:
        selection = self.file_list.curselection()
        if not selection:
            return
        path = self.sheet_files[selection[0]]
        try:
            boxes = detect_preview_boxes(path, self.current_settings())
            preview = render_detection_preview(path, boxes, max_size=(760, 560))
            preview = apply_preview_accessibility_mode(preview, self.preview_accessibility_mode.get())
            self.preview_image = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_image, text="")
            self.append_log(f"Preview detected {len(boxes)} region(s) in {path.name}.")
        except Exception as exc:
            self.preview_label.configure(image="", text=f"Preview failed: {exc}")

    def current_settings(self) -> CutterUiSettings | None:
        path_text = self.input_path.get().strip()
        if not path_text:
            messagebox.showerror("Missing Input", "Choose a sprite sheet file or folder first.")
            return None

        exports = []
        if self.export_unity.get():
            exports.append("unity")
        if self.export_godot.get():
            exports.append("godot")
        if self.export_unreal.get():
            exports.append("unreal")

        return CutterUiSettings(
            input_path=Path(path_text),
            auto_detect_all=self.auto_detect_all.get(),
            out_name=self.out_name.get().strip() or "_organized_sprites",
            mode=self.mode.get(),
            animation_names=self.animation_names.get(),
            animation_frame_mode=self.animation_frame_mode.get(),
            animation_anchor=self.animation_anchor.get(),
            animation_min_frames=int(self.animation_min_frames.get()),
            animation_fps=int(self.animation_fps.get()),
            pivot_debug=self.pivot_debug.get(),
            pack_atlases=self.pack_atlases.get(),
            atlas_size=int(self.atlas_size.get()),
            atlas_padding=int(self.atlas_padding.get()),
            atlas_allow_rotation=self.atlas_allow_rotation.get(),
            engine_exports=exports,
            alpha_threshold=int(self.alpha_threshold.get()),
            white_threshold=int(self.white_threshold.get()),
            white_tolerance=int(self.white_tolerance.get()),
            dark_artifact_threshold=int(self.dark_artifact_threshold.get()),
            min_sprite_pixels=int(self.min_sprite_pixels.get()),
            min_sprite_width=int(self.min_sprite_width.get()),
            min_sprite_height=int(self.min_sprite_height.get()),
            crop_padding=int(self.crop_padding.get()),
            on_error=self.on_error.get(),
        )

    def apply_settings(self, settings: CutterUiSettings) -> None:
        self.auto_detect_all.set(settings.auto_detect_all)
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

    def apply_builtin_preset(self) -> None:
        input_path = Path(self.input_path.get().strip()) if self.input_path.get().strip() else Path(".")
        try:
            settings = settings_from_builtin_preset(self.builtin_preset.get(), input_path=input_path)
            self.apply_settings(settings)
            self.append_log(f"Applied built-in preset: {self.builtin_preset.get()}")
        except Exception as exc:
            messagebox.showerror("Built-In Preset", str(exc))

    def save_preset(self) -> None:
        settings = self.current_settings()
        if settings is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON preset", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            save_preset_file(settings, Path(path))
            self.append_log(f"Saved preset: {path}")
        except Exception as exc:
            messagebox.showerror("Save Preset", str(exc))

    def load_preset(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON preset", "*.json"), ("All files", "*.*")])
        if not path:
            return
        input_path = Path(self.input_path.get().strip()) if self.input_path.get().strip() else Path(".")
        try:
            settings = load_preset_file(Path(path), input_path=input_path)
            self.apply_settings(settings)
            self.append_log(f"Loaded preset: {path}")
        except Exception as exc:
            messagebox.showerror("Load Preset", str(exc))

    def load_project_dialog(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("SpriteCut project", "*.spritecut.json"), ("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self.load_project_file(Path(path))

    def load_project_file(self, path: Path) -> None:
        try:
            self.current_project = load_project(path)
            self.current_project_path = path
            self.append_log(f"Loaded project: {path}")
            self.refresh_project_rows()
            self.refresh_project_animation_clips()
        except Exception as exc:
            messagebox.showerror("Load Project", str(exc))

    def save_project_dialog(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Save Project", "Load a project before saving.")
            return
        path = self.current_project_path
        if path is None:
            selected = filedialog.asksaveasfilename(defaultextension=".spritecut.json", filetypes=[("SpriteCut project", "*.spritecut.json"), ("All files", "*.*")])
            if not selected:
                return
            path = Path(selected)
        try:
            save_project(self.current_project, path)
            self.current_project_path = path
            self.append_log(f"Saved project: {path}")
        except Exception as exc:
            messagebox.showerror("Save Project", str(exc))

    def apply_project_outputs(self) -> None:
        if self.current_project is None or self.current_project_path is None:
            messagebox.showinfo("Apply Outputs", "Load a project before applying outputs.")
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
            messagebox.showerror("Apply Outputs", str(exc))

    def load_editor_sprite_dialog(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp"), ("All files", "*.*")])
        if path:
            self.load_editor_sprite(Path(path))

    def load_editor_sprite(self, path: Path) -> None:
        try:
            self.editor_session = SpriteEditSession.open(path)
            self.editor_autotile_name.set(path.stem)
            self.append_log(f"Loaded editor sprite: {path}")
            self.refresh_editor_preview()
        except Exception as exc:
            messagebox.showerror("Load Sprite", str(exc))

    def refresh_editor_preview(self) -> None:
        if not hasattr(self, "editor_preview_label"):
            return
        if self.editor_session is None:
            self.editor_preview_label.configure(image="", text="Load a sprite to edit.")
            self.editor_palette_label.configure(text="Palette: none")
            return
        image = self.editor_session.composite()
        preview = image.copy()
        preview.thumbnail((180, 140), Image.Resampling.NEAREST)
        self.editor_image = ImageTk.PhotoImage(preview)
        self.editor_preview_label.configure(image=self.editor_image, text="")
        self.editor_palette_label.configure(text="Palette: " + editor_palette_summary(image, max_colors=8))

    def save_editor_package(self) -> None:
        if self.editor_session is None:
            messagebox.showinfo("Save Package", "Load a sprite before saving an edit package.")
            return
        selected = filedialog.askdirectory()
        if not selected:
            return
        try:
            result = write_edit_package(self.editor_session, Path(selected))
            self.append_log(f"Saved editor package: {result['image']}")
        except Exception as exc:
            messagebox.showerror("Save Package", str(exc))

    def apply_editor_palette_swap(self) -> None:
        if self.editor_session is None:
            messagebox.showinfo("Palette Swap", "Load a sprite before swapping colors.")
            return
        try:
            source = self.editor_source_color.get().strip()
            target = self.editor_target_color.get().strip()
            self.editor_session.replace_color(source, target)
            self.append_log(f"Palette swap: {source} -> {target}")
            self.refresh_editor_preview()
        except Exception as exc:
            messagebox.showerror("Palette Swap", str(exc))

    def apply_editor_hue_shift(self) -> None:
        if self.editor_session is None:
            messagebox.showinfo("Hue Shift", "Load a sprite before applying hue shifts.")
            return
        try:
            degrees = float(self.editor_hue_degrees.get())
            self.editor_session.hue_shift(degrees)
            self.append_log(f"Hue shift: {degrees:g} degrees")
            self.refresh_editor_preview()
        except Exception as exc:
            messagebox.showerror("Hue Shift", str(exc))

    def preview_editor_color_wheel(self) -> None:
        try:
            base = self.editor_target_color.get().strip() or "#ff0000"
            preview = editor_color_wheel_preview(base, self.editor_harmony.get())
            self.append_log(f"Color wheel: {preview}")
        except Exception as exc:
            messagebox.showerror("Color Wheel", str(exc))

    def generate_editor_autotile(self) -> None:
        if self.editor_session is None:
            messagebox.showinfo("Auto-Tile", "Load a sprite before generating an auto-tile.")
            return
        selected = filedialog.askdirectory()
        if not selected:
            return
        try:
            result = write_autotile_package(
                self.editor_session.composite(),
                Path(selected),
                name=self.editor_autotile_name.get().strip() or self.editor_session.name,
                engine=self.editor_engine.get(),
            )
            self.append_log(f"Generated auto-tile: {result['sheet']} rules={result['rules']}")
        except Exception as exc:
            messagebox.showerror("Auto-Tile", str(exc))

    def show_editor_ide_actions(self) -> None:
        actions = ", ".join(editor_callable_actions())
        messagebox.showinfo(
            "IDE API",
            "Use tools\\sprite_ide_api.py with --request request.json.\n\n"
            f"Actions: {actions}",
        )

    def refresh_studio_panel(self) -> None:
        if not hasattr(self, "studio_dashboard_label"):
            return
        self.studio_queue_list.delete(0, tk.END)
        self.studio_asset_list.delete(0, tk.END)
        self.studio_asset_rows_cache = []
        if self.current_project is None:
            self.studio_dashboard_label.configure(text="Load a project to build a studio dashboard.")
            return

        self.studio_dashboard_label.configure(text=studio_dashboard_text(self.current_project))
        for label in studio_queue_labels(self.current_project):
            self.studio_queue_list.insert(tk.END, label)

        rows = studio_asset_rows(self.current_project, self.studio_query.get(), self.studio_status_filter.get())
        self.studio_asset_rows_cache = rows
        for item in rows:
            self.studio_asset_list.insert(tk.END, studio_asset_label(item))

    def auto_name_studio_project(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Auto Name", "Load a project before applying taxonomy rules.")
            return
        try:
            result = apply_taxonomy_rules(self.current_project, studio_default_taxonomy_rules(self.studio_taxonomy_pattern.get()))  # type: ignore[arg-type]
            self.append_log(f"Auto-named project sprites: renamed={result['renamed']} pattern={result['pattern']}")
            self.refresh_project_rows()
            if self.current_project_path is not None:
                save_project(self.current_project, self.current_project_path)
        except Exception as exc:
            messagebox.showerror("Auto Name", str(exc))

    def generate_studio_profiles(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Profiles", "Load a project before generating profiles.")
            return
        try:
            profiles = generate_collision_profiles(self.current_project)  # type: ignore[arg-type]
            plans = build_engine_import_plans(self.current_project)  # type: ignore[arg-type]
            if self.current_project_path is not None:
                save_project(self.current_project, self.current_project_path)
            self.append_log(f"Generated studio profiles: sprites={len(profiles)} engines={','.join(plans) or 'none'}")
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror("Profiles", str(exc))

    def train_studio_preset(self) -> None:
        if self.current_project is None or self.current_project_path is None:
            messagebox.showinfo("Train Preset", "Load a saved project before training a preset.")
            return
        try:
            preset = train_preset_from_project(self.current_project)  # type: ignore[arg-type]
            output_path = self.current_project_path.parent / "trained_spritecut_preset.json"
            output_path.write_text(json.dumps(preset, indent=2), encoding="utf-8")
            self.append_log(f"Trained preset: {output_path}")
            self.refresh_studio_panel()
        except Exception as exc:
            messagebox.showerror("Train Preset", str(exc))

    def diff_studio_project(self) -> None:
        if self.current_project is None or self.current_project_path is None:
            messagebox.showinfo("Diff Project", "Load a project before comparing reruns.")
            return
        selected = filedialog.askopenfilename(filetypes=[("SpriteCut project", "*.spritecut.json"), ("JSON", "*.json"), ("All files", "*.*")])
        if not selected:
            return
        try:
            baseline_project = load_project(Path(selected))
            diff = diff_projects(baseline_project, self.current_project)  # type: ignore[arg-type]
            output_path = self.current_project_path.parent / "studio_diff.json"
            output_path.write_text(json.dumps(diff, indent=2), encoding="utf-8")
            self.append_log(f"{studio_project_diff_text(baseline_project, self.current_project)} -> {output_path}")
            self.refresh_studio_panel()
        except Exception as exc:
            messagebox.showerror("Diff Project", str(exc))

    def review_apply_studio_project(self) -> None:
        if self.current_project is None or self.current_project_path is None:
            messagebox.showinfo("Review + Apply", "Load a project before running the studio pass.")
            return
        try:
            result = review_and_apply_project(
                self.current_project,  # type: ignore[arg-type]
                self.current_project_path,
                naming_rules=studio_default_taxonomy_rules(self.studio_taxonomy_pattern.get()),
            )
            output_dir = Path(str(result["output_dir"]))
            self.latest_output_dir = output_dir
            self.open_output_button.configure(state=tk.NORMAL)
            self.append_log(
                "Review + Apply complete: "
                f"rendered={result['apply']['rendered']} "
                f"health={result['health']['grade']}:{result['health']['score']} "
                f"imports={','.join(result['import_plans']) or 'none'} "
                f"output={output_dir}"
            )
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror("Review + Apply", str(exc))

    def refresh_project_rows(self) -> None:
        self.review_list.delete(0, tk.END)
        self.project_sprite_rows_cache = []
        if self.current_project is None:
            self.refresh_studio_panel()
            return
        rows = project_sprite_rows(self.current_project, self.review_status_filter.get(), self.review_query.get())
        self.project_sprite_rows_cache = rows
        for sprite in rows:
            self.review_list.insert(tk.END, format_project_sprite_label(sprite))
        if rows:
            self.review_list.selection_set(0)
            self.populate_review_editor()
        self.refresh_studio_panel()

    def refresh_project_animation_clips(self) -> None:
        if self.current_project is None:
            clip_names: list[str] = []
        else:
            clip_names = project_animation_clip_names(self.current_project)
        self.review_animation_combo.configure(values=clip_names)
        if clip_names:
            self.review_animation_clip.set(clip_names[0])
            self.review_animation_frame_index = 0
        else:
            self.review_animation_clip.set("")

    def _selected_project_sprite(self) -> dict[str, object] | None:
        selection = self.review_list.curselection()
        if not selection or selection[0] >= len(self.project_sprite_rows_cache):
            return None
        return self.project_sprite_rows_cache[selection[0]]

    def _selected_project_sprite_ids(self) -> list[str]:
        ids: list[str] = []
        for index in self.review_list.curselection():
            if index < len(self.project_sprite_rows_cache):
                ids.append(str(self.project_sprite_rows_cache[index].get("id", "")))
        return [sprite_id for sprite_id in ids if sprite_id]

    def populate_review_editor(self) -> None:
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
            self.review_image_label.configure(image="", text="No output image for this sprite.")
            return
        path = self._resolve_project_path(output_file)
        if not path.exists():
            self.review_image_label.configure(image="", text=f"Missing sprite image: {path.name}")
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
            image.thumbnail((160, 110), Image.Resampling.NEAREST)
            self.review_image = ImageTk.PhotoImage(image.copy())
            image.close()
            self.review_image_label.configure(image=self.review_image, text="")
        except Exception as exc:
            self.review_image_label.configure(image="", text=f"Preview failed: {exc}")

    def _update_review_source_canvas(self, sprite: dict[str, object]) -> None:
        self.review_source_canvas.delete("all")
        source_file = sprite.get("source_file")
        bbox = sprite.get("bbox", {})
        if not source_file or not isinstance(bbox, dict):
            self.review_source_canvas.create_text(110, 70, text="No source box", fill="#e6e8ef")
            return
        path = self._resolve_project_path(str(source_file))
        if not path.exists():
            self.review_source_canvas.create_text(110, 70, text="Missing source", fill="#e6e8ef")
            return
        try:
            image = Image.open(path).convert("RGBA")
            canvas_size = (220, 140)
            scaled = scale_bbox_for_canvas(
                {"x": int(bbox["x"]), "y": int(bbox["y"]), "width": int(bbox["width"]), "height": int(bbox["height"])},
                image.size,
                canvas_size,
            )
            display_size = (int(round(image.width * float(scaled["scale"]))), int(round(image.height * float(scaled["scale"]))))
            image = image.resize(display_size, Image.Resampling.NEAREST)
            self.review_source_canvas_image = ImageTk.PhotoImage(image.copy())
            image.close()
            offset_x, offset_y = scaled["offset"]  # type: ignore[misc]
            self.review_canvas_scale = float(scaled["scale"])
            self.review_source_canvas.create_image(offset_x, offset_y, image=self.review_source_canvas_image, anchor="nw")
            self.review_source_canvas.create_rectangle(*scaled["rect"], outline="#ff5a3c", width=2, tags=("bbox",))
        except Exception as exc:
            self.review_source_canvas.create_text(110, 70, text=f"Canvas failed: {exc}", fill="#e6e8ef")

    def _current_bbox_fields(self) -> dict[str, int] | None:
        try:
            return parse_bbox_fields(self.review_bbox_x.get(), self.review_bbox_y.get(), self.review_bbox_width.get(), self.review_bbox_height.get())
        except Exception:
            return None

    def _on_review_canvas_press(self, event: tk.Event) -> None:
        bbox = self._current_bbox_fields()
        if bbox is None:
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            return
        source_file = sprite.get("source_file")
        if not source_file:
            return
        path = self._resolve_project_path(str(source_file))
        if not path.exists():
            return
        with Image.open(path) as image:
            scaled = scale_bbox_for_canvas(bbox, image.size, (220, 140))
        x0, y0, x1, y1 = scaled["rect"]  # type: ignore[misc]
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self.review_canvas_drag_start = (int(event.x), int(event.y))
            self.review_canvas_bbox_start = bbox

    def _on_review_canvas_drag(self, event: tk.Event) -> None:
        if self.review_canvas_drag_start is None or self.review_canvas_bbox_start is None:
            return
        dx = int(event.x) - self.review_canvas_drag_start[0]
        dy = int(event.y) - self.review_canvas_drag_start[1]
        bbox = translate_bbox_by_canvas_delta(self.review_canvas_bbox_start, dx, dy, self.review_canvas_scale)
        self.review_bbox_x.set(str(bbox["x"]))
        self.review_bbox_y.set(str(bbox["y"]))
        self.review_bbox_width.set(str(bbox["width"]))
        self.review_bbox_height.set(str(bbox["height"]))
        sprite = self._selected_project_sprite()
        if sprite is not None:
            preview_sprite = dict(sprite)
            preview_sprite["bbox"] = bbox
            self._update_review_source_canvas(preview_sprite)

    def _on_review_canvas_release(self, _event: tk.Event) -> None:
        self.review_canvas_drag_start = None
        self.review_canvas_bbox_start = None

    def play_review_animation(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Play Animation", "Load a project first.")
            return
        clip_name = self.review_animation_clip.get().strip()
        if not clip_name:
            messagebox.showinfo("Play Animation", "No animation clip is available.")
            return
        self.stop_review_animation()
        self.review_animation_frame_index = 0
        self._show_next_animation_frame()

    def stop_review_animation(self) -> None:
        if self.review_animation_after_id is not None:
            self.after_cancel(self.review_animation_after_id)
            self.review_animation_after_id = None

    def _show_next_animation_frame(self) -> None:
        if self.current_project is None:
            return
        clip_name = self.review_animation_clip.get().strip()
        frames = project_animation_clip_frames(self.current_project, clip_name)
        if not frames:
            return
        frame = frames[self.review_animation_frame_index % len(frames)]
        source_file = frame.get("source_file")
        if source_file:
            self._show_review_image_path(self._resolve_project_path(str(source_file)))
        duration = float(frame.get("duration", 0.125))
        self.review_animation_frame_index = (self.review_animation_frame_index + 1) % len(frames)
        self.review_animation_after_id = self.after(max(20, int(duration * 1000)), self._show_next_animation_frame)

    def apply_review_edit(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Apply Edit", "Load a project before editing.")
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            messagebox.showinfo("Apply Edit", "Select a sprite to edit.")
            return
        try:
            update_sprite(
                self.current_project,
                str(sprite["id"]),
                display_name=self.review_name.get().strip() or str(sprite["id"]),
                category=self.review_category.get().strip(),
                bbox=parse_bbox_fields(self.review_bbox_x.get(), self.review_bbox_y.get(), self.review_bbox_width.get(), self.review_bbox_height.get()),
                pivot=parse_pivot_fields(self.review_pivot_x.get(), self.review_pivot_y.get()),
                review_status=self.review_status.get(),
                review_flags=parse_flags_text(self.review_flags.get()),
            )
            self.append_log(f"Edited sprite: {sprite['id']}")
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror("Apply Edit", str(exc))

    def approve_review_sprite(self) -> None:
        self._apply_review_action("Approve", approve_sprite)

    def reject_review_sprite(self) -> None:
        self._apply_review_action("Reject", reject_sprite)

    def _apply_review_action(self, label: str, action: object) -> None:
        if self.current_project is None:
            messagebox.showinfo(label, "Load a project first.")
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            messagebox.showinfo(label, "Select a sprite first.")
            return
        try:
            action(self.current_project, str(sprite["id"]))  # type: ignore[operator]
            self.append_log(f"{label}: {sprite['id']}")
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror(label, str(exc))

    def undo_project_edit(self) -> None:
        self._apply_project_stack_action("Undo", undo_last_edit)

    def redo_project_edit(self) -> None:
        self._apply_project_stack_action("Redo", redo_last_edit)

    def _apply_project_stack_action(self, label: str, action: object) -> None:
        if self.current_project is None:
            messagebox.showinfo(label, "Load a project first.")
            return
        try:
            action(self.current_project)  # type: ignore[operator]
            self.append_log(f"{label} project edit")
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror(label, str(exc))

    def _parse_split_boxes(self) -> list[dict[str, int]]:
        boxes: list[dict[str, int]] = []
        for raw_box in self.review_split_boxes.get().split(";"):
            parts = [part.strip() for part in raw_box.split(",") if part.strip()]
            if not parts:
                continue
            if len(parts) != 4:
                raise ValueError("Split boxes use x,y,width,height; x,y,width,height.")
            boxes.append(parse_bbox_fields(parts[0], parts[1], parts[2], parts[3]))
        return boxes

    def split_review_sprite(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Split Sprite", "Load a project first.")
            return
        sprite = self._selected_project_sprite()
        if sprite is None:
            messagebox.showinfo("Split Sprite", "Select one sprite to split.")
            return
        try:
            split_sprite(self.current_project, str(sprite["id"]), self._parse_split_boxes())
            self.append_log(f"Split sprite: {sprite['id']}")
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror("Split Sprite", str(exc))

    def merge_review_sprites(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("Merge Sprites", "Load a project first.")
            return
        sprite_ids = self._selected_project_sprite_ids()
        if len(sprite_ids) < 2:
            messagebox.showinfo("Merge Sprites", "Select at least two sprites.")
            return
        merged_id = self.review_name.get().strip() or f"{sprite_ids[0]}_merged"
        try:
            merge_sprites(self.current_project, sprite_ids, merged_id=merged_id, display_name=merged_id)
            self.append_log(f"Merged sprites: {', '.join(sprite_ids)}")
            self.refresh_project_rows()
        except Exception as exc:
            messagebox.showerror("Merge Sprites", str(exc))

    def process(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Processing", "A processing run is already active.")
            return

        settings = self.current_settings()
        if settings is None:
            return

        command = build_cutter_command(settings)
        self._set_latest_run_targets(None)
        self.append_log("> " + " ".join(command))
        self.progress.start(12)
        self.cancel_button.configure(state=cancel_button_state(True))
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

    def cancel_process(self) -> None:
        process = self.active_process
        if process is None or process.poll() is not None:
            self.append_log("No active process to cancel.")
            self.cancel_button.configure(state=cancel_button_state(False))
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
                self.progress.stop()
                self.cancel_button.configure(state=cancel_button_state(False))
            else:
                targets = output_targets_from_cli_line(line)
                if targets is not None:
                    self._set_latest_run_targets(targets)
                self.append_log(line)
        self.after(100, self._drain_log_queue)

    def _set_latest_run_targets(self, targets: RunOutputTargets | None) -> None:
        self.latest_output_dir = targets.output_dir if targets is not None else None
        self.latest_report_path = targets.report_path if targets is not None else None
        self.latest_project_path = targets.project_path if targets is not None else None
        state = tk.NORMAL if targets is not None else tk.DISABLED
        self.open_output_button.configure(state=state)
        self.open_report_button.configure(state=state)
        self.open_project_button.configure(state=state)

    def open_latest_output(self) -> None:
        self._open_existing_path(self.latest_output_dir, "output folder")

    def open_latest_report(self) -> None:
        self._open_existing_path(self.latest_report_path, "HTML report")

    def open_latest_project(self) -> None:
        if self.latest_project_path is not None and self.latest_project_path.exists():
            self.load_project_file(self.latest_project_path)
            return
        self._open_existing_path(self.latest_project_path, "project file")

    def _open_existing_path(self, path: Path | None, label: str) -> None:
        if path is None:
            messagebox.showinfo("No Run Output", "Process a sheet before opening run output.")
            return
        if not path.exists():
            messagebox.showerror("Missing Output", f"The latest {label} does not exist:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Open Output", str(exc))

    def append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def clear_log(self) -> None:
        self.log.delete("1.0", tk.END)


def main() -> None:
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print("Sprite Sheet Processor UI")
        print("")
        print("Launches a desktop wrapper for tools/cut_tileset_sprites.py.")
        print("Run without arguments:")
        print("  python tools\\sprite_sheet_tool_ui.py")
        print("")
        print("The UI supports preview, cutter settings, review editing, Studio health/diff/search, sprite editing, auto-tiles, import plans, and live logs.")
        return

    app = SpriteSheetToolUi()
    app.mainloop()


if __name__ == "__main__":
    main()
