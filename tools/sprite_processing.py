from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class SheetProcessingHooks:
    sprite_record_cls: type[Any]
    safe_name: Callable[[str], str]
    detect_background: Callable[..., np.ndarray]
    grouped_components: Callable[..., tuple[np.ndarray, np.ndarray, int]]
    extract_detections: Callable[..., list[Any]]
    resolve_sheet_mode: Callable[[str, list[Any], int], str]
    classify_sprite: Callable[[str, int, int, int, int, int], str]
    should_use_full_alpha: Callable[[str, int, int, int], bool]
    analyze_sprite_pixels: Callable[[np.ndarray], tuple[float, float, list[str]]]
    detect_pivot: Callable[[np.ndarray, str], dict[str, float | str]]
    assess_sprite_quality: Callable[..., tuple[float, list[str], str]]
    save_pivot_debug: Callable[[np.ndarray, dict[str, float | str], Path], None]
    is_partial_detection: Callable[[Any, int, int], bool]
    make_contact_sheet: Callable[[list[Any], Path], None]
    cluster_animation_rows: Callable[[list[Any]], list[list[Any]]]


def make_masked_crop(
    rgba: np.ndarray,
    foreground: np.ndarray,
    labels: np.ndarray,
    detection: Any,
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
    detection: Any,
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
    detections: list[Any],
    out_dir: Path,
    preview_dir: Path,
    sheet_mode: str,
    options: Any,
    hooks: SheetProcessingHooks,
) -> list[Any]:
    records: list[Any] = []
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
        category = hooks.classify_sprite(source_stem, detection.x, detection.y, detection.width, detection.height, detection.foreground_pixels)
        counters[category] += 1
        sprite_id = f"{source_label}_{category}_{counters[category]:03d}"
        file_name = f"{sprite_id}.png"
        category_dir = out_dir / "sprites" / category
        category_dir.mkdir(parents=True, exist_ok=True)
        output_path = category_dir / file_name

        crop_rgba = rgba[detection.y : detection.bottom, detection.x : detection.right, :].copy()
        use_full_alpha = hooks.should_use_full_alpha(category, detection.width, detection.height, detection.foreground_pixels)
        if use_full_alpha:
            crop_rgba[:, :, 3] = 255
            alpha_mode = "full_bbox"
        else:
            crop_rgba = make_masked_crop(rgba, foreground, labels, detection)
            alpha_mode = "background_removed"

        Image.fromarray(crop_rgba, "RGBA").save(output_path)
        transparency_ratio, aspect_ratio, colors = hooks.analyze_sprite_pixels(crop_rgba)
        pivot = hooks.detect_pivot(crop_rgba, category)
        confidence, review_flags, review_status = hooks.assess_sprite_quality(
            detection,
            rgba.shape[1],
            rgba.shape[0],
            transparency_ratio,
            aspect_ratio,
        )
        if options.pivot_debug:
            hooks.save_pivot_debug(crop_rgba, pivot, preview_dir / "pivots" / f"{sprite_id}_pivot.png")

        record = hooks.sprite_record_cls(
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
            is_partial=hooks.is_partial_detection(detection, rgba.shape[1], rgba.shape[0]),
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
    hooks.make_contact_sheet(records, preview_dir / f"{source_label}_contact.png")
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
    detections: list[Any],
    out_dir: Path,
    preview_dir: Path,
    sheet_mode: str,
    options: Any,
    hooks: SheetProcessingHooks,
) -> list[Any]:
    rows = hooks.cluster_animation_rows(detections)
    if options.mode == "auto":
        rows = [row for row in rows if len(row) >= options.animation_min_frames]
    rows = [row for row in rows if row]

    records: list[Any] = []
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

        sequence_records: list[Any] = []
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
            transparency_ratio, aspect_ratio, colors = hooks.analyze_sprite_pixels(output_rgba)
            pivot = hooks.detect_pivot(output_rgba, "animation")
            confidence, review_flags, review_status = hooks.assess_sprite_quality(
                detection,
                rgba.shape[1],
                rgba.shape[0],
                transparency_ratio,
                aspect_ratio,
            )
            if options.pivot_debug:
                hooks.save_pivot_debug(output_rgba, pivot, preview_dir / "pivots" / f"{source_label}_{frame_name}_pivot.png")

            record = hooks.sprite_record_cls(
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
                is_partial=hooks.is_partial_detection(detection, rgba.shape[1], rgba.shape[0]),
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

        hooks.make_contact_sheet(sequence_records, preview_dir / f"{source_label}_{sequence_name}_contact.png")

    boxed.save(preview_dir / f"{source_label}_boxes.png")
    hooks.make_contact_sheet(records, preview_dir / f"{source_label}_contact.png")
    return records


def process_sheet(source_path: Path, out_dir: Path, preview_dir: Path, options: Any, hooks: SheetProcessingHooks) -> list[Any]:
    source_stem = hooks.safe_name(source_path.stem)
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

    background = hooks.detect_background(rgb, alpha, options.detection_settings)
    foreground = ~background
    labels, stats, num = hooks.grouped_components(foreground)
    detections = hooks.extract_detections(foreground, labels, stats, num, options.detection_settings)
    resolved_mode = hooks.resolve_sheet_mode(options.mode, detections, options.animation_min_frames)

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
            hooks,
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
            hooks,
        )

    rgba_image.close()
    return records


