from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


NORTH = 1
EAST = 2
SOUTH = 4
WEST = 8
DIRECTIONS = {
    NORTH: "north",
    EAST: "east",
    SOUTH: "south",
    WEST: "west",
}


def _rgba(image: Image.Image) -> Image.Image:
    return image.convert("RGBA").copy()


def _edge_bytes(tile: Image.Image, side: str) -> bytes:
    image = tile.convert("RGBA")
    width, height = image.size
    if side == "north":
        pixels = [image.getpixel((x, 0)) for x in range(width)]
    elif side == "south":
        pixels = [image.getpixel((x, height - 1)) for x in range(width)]
    elif side == "east":
        pixels = [image.getpixel((width - 1, y)) for y in range(height)]
    elif side == "west":
        pixels = [image.getpixel((0, y)) for y in range(height)]
    else:
        raise ValueError(f"Unknown edge side: {side}")
    return b"".join(bytes(pixel) for pixel in pixels)


def tile_edge_signature(tile: Image.Image) -> dict[str, str]:
    return {
        side: hashlib.sha256(_edge_bytes(tile, side)).hexdigest()[:16]
        for side in ("north", "east", "south", "west")
    }


def _erase_missing_edges(tile: Image.Image, mask: int, edge_color: tuple[int, int, int, int], edge_width: int) -> Image.Image:
    output = _rgba(tile)
    draw = ImageDraw.Draw(output)
    width, height = output.size
    edge_width = max(1, int(edge_width))
    if not mask & NORTH:
        draw.rectangle((0, 0, width - 1, edge_width - 1), fill=edge_color)
    if not mask & SOUTH:
        draw.rectangle((0, height - edge_width, width - 1, height - 1), fill=edge_color)
    if not mask & WEST:
        draw.rectangle((0, 0, edge_width - 1, height - 1), fill=edge_color)
    if not mask & EAST:
        draw.rectangle((width - edge_width, 0, width - 1, height - 1), fill=edge_color)
    return output


def generate_cardinal_autotile_set(
    tile: Image.Image,
    *,
    edge_color: tuple[int, int, int, int] = (0, 0, 0, 0),
    edge_width: int | None = None,
) -> dict[int, Image.Image]:
    base = _rgba(tile)
    width, height = base.size
    width_guess = max(1, min(width, height) // 4)
    resolved_edge_width = edge_width if edge_width is not None else width_guess
    return {mask: _erase_missing_edges(base, mask, edge_color, resolved_edge_width) for mask in range(16)}


def _neighbors(mask: int) -> dict[str, bool]:
    return {name: bool(mask & bit) for bit, name in DIRECTIONS.items()}


def build_rule_tile_metadata(
    name: str,
    variants: dict[int, Image.Image],
    *,
    tile_size: int,
    engine: str = "generic",
) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for mask in sorted(variants):
        rules.append(
            {
            "tile": f"{name}_{mask:02d}",
            "bitmask": mask,
            "neighbors": _neighbors(mask),
            "atlas": {"x": mask % 4, "y": mask // 4, "width": 1, "height": 1},
            }
        )
    metadata: dict[str, Any] = {
        "name": name,
        "engine": engine,
        "mode": "cardinal_16",
        "bits": {"north": NORTH, "east": EAST, "south": SOUTH, "west": WEST},
        "tile_size": int(tile_size),
        "rules": rules,
    }
    if engine == "unity":
        metadata["import_hint"] = "Unity RuleTile compatible cardinal bitmask metadata"
    elif engine == "godot":
        metadata["import_hint"] = "Godot TileSet terrain/cardinal bitmask metadata"
    elif engine == "unreal":
        metadata["import_hint"] = "Unreal Paper2D tile map cardinal bitmask metadata"
    return metadata


def _sheet_from_variants(variants: dict[int, Image.Image]) -> Image.Image:
    first = next(iter(variants.values()))
    tile_width, tile_height = first.size
    sheet = Image.new("RGBA", (tile_width * 4, tile_height * 4), (0, 0, 0, 0))
    for mask, tile in variants.items():
        sheet.alpha_composite(tile.convert("RGBA"), ((mask % 4) * tile_width, (mask // 4) * tile_height))
    return sheet


def write_autotile_package(
    tile: Image.Image,
    output_dir: Path | str,
    *,
    name: str = "autotile",
    engine: str = "generic",
    edge_color: tuple[int, int, int, int] = (0, 0, 0, 0),
    edge_width: int | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = generate_cardinal_autotile_set(tile, edge_color=edge_color, edge_width=edge_width)
    sheet = _sheet_from_variants(variants)
    sheet_path = output_dir / f"{name}_autotile_16.png"
    rules_path = output_dir / f"{name}_autotile_rules.json"
    sheet.save(sheet_path)
    metadata = build_rule_tile_metadata(name, variants, tile_size=tile.size[0], engine=engine)
    metadata["source_edge_signature"] = tile_edge_signature(tile)
    rules_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {
        "sheet": str(sheet_path),
        "rules": str(rules_path),
        "variants": [f"{name}_{mask:02d}" for mask in sorted(variants)],
    }
