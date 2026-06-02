from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from tools.sprite_reports import write_html_report, write_visual_qa_report, write_visual_regression_report


def write_project_file(
    records: Sequence[Any],
    out_dir: Path,
    options: Any,
    sheets_processed: int,
    sheet_errors: Sequence[Any],
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
    records: Sequence[Any],
    manifest_dir: Path,
    sheets_processed: int,
    sheet_errors: Sequence[Any],
    options: Any | None = None,
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


