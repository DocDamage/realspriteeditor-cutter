from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.autotile_tools import (
    build_rule_tile_metadata,
    generate_cardinal_autotile_set,
    tile_edge_signature,
    write_autotile_package,
)


def solid_tile(color: tuple[int, int, int, int] = (100, 140, 80, 255)) -> Image.Image:
    return Image.new("RGBA", (8, 8), color)


class AutotileToolsTests(unittest.TestCase):
    def test_tile_edge_signature_describes_pixel_edges(self) -> None:
        tile = solid_tile()
        tile.putpixel((0, 0), (255, 0, 0, 255))

        signature = tile_edge_signature(tile)

        self.assertIn("north", signature)
        self.assertIn("west", signature)
        self.assertNotEqual(signature["north"], signature["south"])

    def test_generate_cardinal_autotile_set_writes_16_bitmask_variants(self) -> None:
        tile = solid_tile()

        variants = generate_cardinal_autotile_set(tile, edge_color=(0, 0, 0, 0), edge_width=2)

        self.assertEqual(sorted(variants), list(range(16)))
        self.assertEqual(variants[15].getpixel((0, 0)), (100, 140, 80, 255))
        self.assertEqual(variants[0].getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(variants[1].getpixel((3, 0)), (100, 140, 80, 255))
        self.assertEqual(variants[1].getpixel((0, 3)), (0, 0, 0, 0))

    def test_build_rule_tile_metadata_uses_engine_ready_bitmasks(self) -> None:
        variants = generate_cardinal_autotile_set(solid_tile())

        unity = build_rule_tile_metadata("grass", variants, tile_size=8, engine="unity")
        godot = build_rule_tile_metadata("grass", variants, tile_size=8, engine="godot")

        self.assertEqual(unity["engine"], "unity")
        self.assertEqual(godot["engine"], "godot")
        self.assertEqual(unity["rules"][15]["neighbors"], {"north": True, "east": True, "south": True, "west": True})
        self.assertEqual(godot["rules"][0]["bitmask"], 0)

    def test_write_autotile_package_saves_sheet_variants_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = write_autotile_package(solid_tile(), root, name="grass", engine="unity")

            self.assertTrue(Path(result["sheet"]).exists())
            self.assertTrue(Path(result["rules"]).exists())
            self.assertEqual(len(result["variants"]), 16)
            with Image.open(result["sheet"]) as sheet:
                self.assertEqual(sheet.size, (32, 32))
            rules = json.loads(Path(result["rules"]).read_text(encoding="utf-8"))
            self.assertEqual(rules["name"], "grass")
            self.assertEqual(rules["rules"][15]["tile"], "grass_15")


if __name__ == "__main__":
    unittest.main()
