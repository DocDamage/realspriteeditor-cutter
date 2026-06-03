from __future__ import annotations

import argparse
import json
import os
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Iterator


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "sprite"


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG file: {path}")
    return struct.unpack(">II", header[16:24])


def iter_cut_pngs(root: Path) -> Iterator[tuple[Path, str]]:
    for folder, kind in ((root / "sprites", "sprite"), (root / "animations", "animation_frame")):
        if not folder.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [name for name in dirnames if name != "__MACOSX" and not name.startswith("._")]
            for filename in filenames:
                if filename.lower().endswith(".png") and not filename.startswith("._"):
                    yield Path(dirpath) / filename, kind


def sprite_entry(root: Path, path: Path, kind: str, index: int) -> dict[str, object]:
    rel = path.relative_to(root)
    parts = rel.parts
    if kind == "animation_frame":
        category = "animation"
        sequence = safe_name("_".join(parts[1:-1])) if len(parts) > 2 else safe_name(path.parent.name)
        frame_match = re.search(r"(\d+)(?=\.png$)", path.name, re.I)
        frame = int(frame_match.group(1)) if frame_match else index
    else:
        category = safe_name(parts[1]) if len(parts) > 2 else "sprites"
        sequence = None
        frame = None

    width, height = png_size(path)
    stem = safe_name(path.stem)
    bbox = {"x": 0, "y": 0, "width": width, "height": height}
    return {
        "id": f"{kind}_{index:06d}_{stem}",
        "display_name": stem,
        "source_sheet": str(path),
        "kind": kind,
        "sheet_mode": "reconstructed_from_cut_png",
        "category": category,
        "sequence": sequence,
        "frame": frame,
        "source_file": str(path),
        "output_file": str(path),
        "bbox": bbox,
        "width": width,
        "height": height,
        "slot_width": width,
        "slot_height": height,
        "foreground_pixels": width * height,
        "alpha_mode": "preserved",
        "is_partial": False,
        "transparency_ratio": 0.0,
        "aspect_ratio": round(width / max(1, height), 4),
        "dominant_colors": [],
        "pivot": {"x": 0.5, "y": 0.5, "method": "reconstructed"},
        "confidence": 0.5,
        "review_flags": ["reconstructed_project"],
        "review_status": "needs_review",
        "atlas": None,
    }


def write_reconstructed_project(root: Path, project_path: Path, progress_interval: int = 50000) -> dict[str, object]:
    root = root.resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = project_path.with_suffix(project_path.suffix + ".tmp")
    counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    total = 0
    skipped: list[dict[str, str]] = []

    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write("{\n")
        handle.write('  "schema_version": 1,\n')
        handle.write('  "tool": "spritecut",\n')
        handle.write('  "settings": {"source": "reconstructed_from_cut_pngs", "pack_atlases": false, "vision_required": true},\n')
        handle.write('  "errors": [],\n')
        handle.write('  "history": [],\n')
        handle.write('  "redo_stack": [],\n')
        handle.write('  "animation_clips": [],\n')
        handle.write('  "sprites": [\n')
        first = True
        for path, kind in iter_cut_pngs(root):
            try:
                total += 1
                entry = sprite_entry(root, path, kind, total)
            except Exception as exc:
                skipped.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
                continue
            counts[str(entry["category"])] += 1
            kind_counts[kind] += 1
            if not first:
                handle.write(",\n")
            json.dump(entry, handle, ensure_ascii=False)
            first = False
            if progress_interval > 0 and total % progress_interval == 0:
                print(f"RECONSTRUCT_PROGRESS sprites={total}", flush=True)
        handle.write("\n  ],\n")
        handle.write('  "summary": ')
        json.dump(
            {
                "total_sprites": total - len(skipped),
                "sheets_processed": 0,
                "sheets_failed": len(skipped),
                "needs_review": total - len(skipped),
                "reconstructed": True,
                "by_category": dict(sorted(counts.items())),
                "by_kind": dict(sorted(kind_counts.items())),
            },
            handle,
            indent=2,
        )
        handle.write(",\n")
        handle.write('  "reconstruction_errors": ')
        json.dump(skipped, handle, indent=2)
        handle.write("\n}\n")

    tmp_path.replace(project_path)
    return {"ok": True, "project_path": str(project_path), "total_sprites": total - len(skipped), "skipped": len(skipped)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconstruct a SpriteCut project from already-cut PNG files.")
    parser.add_argument("root", type=Path, help="SpriteCut output root containing sprites/ and animations/.")
    parser.add_argument("--project-name", default="project.spritecut.vision.json", help="Project filename to write under root.")
    parser.add_argument("--progress-interval", type=int, default=50000)
    args = parser.parse_args()
    result = write_reconstructed_project(args.root, args.root / args.project_name, progress_interval=args.progress_interval)
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
