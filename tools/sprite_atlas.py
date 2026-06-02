from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from PIL import Image


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value).strip("_")


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


def pack_records_into_atlases(records: Sequence[Any], out_dir: Path, options: RunOptions) -> list[dict[str, object]]:
    atlas_dir = out_dir / "atlases"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Any]] = {}
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
            placements: list[tuple[Any, PackedRect]] = []
            still_pending: list[Any] = []

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


