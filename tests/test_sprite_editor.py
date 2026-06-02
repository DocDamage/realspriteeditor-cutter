from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_editor import (
    SpriteEditSession,
    apply_hue_shift,
    apply_edit_operations,
    apply_palette_swap,
    write_batch_edit_package,
    color_wheel_palette,
    extract_palette,
    write_palette_variant_package,
    write_edit_package,
)


def sample_image() -> Image.Image:
    image = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
    for x in range(3):
        for y in range(3):
            image.putpixel((x, y), (255, 0, 0, 255))
    for x in range(3, 6):
        for y in range(3):
            image.putpixel((x, y), (0, 255, 0, 255))
    return image


class SpriteEditorTests(unittest.TestCase):
    def test_edit_session_supports_layered_pixel_tools_and_undo_redo(self) -> None:
        session = SpriteEditSession.from_image(sample_image(), name="crate")

        session.add_layer("paint")
        session.draw_pixel(5, 5, (10, 20, 30, 255))
        session.draw_line((0, 5), (2, 5), (40, 50, 60, 255))
        session.fill_rect((3, 3, 2, 2), (80, 90, 100, 255))
        session.flood_fill((4, 0), (0, 120, 0, 255))
        edited = session.composite()

        self.assertEqual(edited.getpixel((5, 5)), (10, 20, 30, 255))
        self.assertEqual(edited.getpixel((1, 5)), (40, 50, 60, 255))
        self.assertEqual(edited.getpixel((3, 3)), (80, 90, 100, 255))
        self.assertEqual(edited.getpixel((4, 0)), (0, 120, 0, 255))

        session.undo()
        self.assertEqual(session.composite().getpixel((4, 0)), (0, 255, 0, 255))
        session.redo()
        self.assertEqual(session.composite().getpixel((4, 0)), (0, 120, 0, 255))

    def test_edit_session_transforms_crop_resize_flip_rotate_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            sample_image().save(source)
            session = SpriteEditSession.open(source)

            session.crop((0, 0, 4, 4))
            session.resize((8, 8))
            session.flip_horizontal()
            session.rotate_90(clockwise=True)
            output = root / "edited.png"
            session.save(output)

            self.assertEqual(session.size, (8, 8))
            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (8, 8))

    def test_palette_swap_extracts_palette_and_preserves_transparency(self) -> None:
        image = sample_image()

        palette = extract_palette(image, max_colors=4)
        swapped = apply_palette_swap(image, {"#ff0000": "#0000ff", "#00ff00": "#ffff00"})

        self.assertEqual(palette[0]["hex"], "#ff0000")
        self.assertEqual(swapped.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual(swapped.getpixel((4, 0)), (255, 255, 0, 255))
        self.assertEqual(swapped.getpixel((5, 5)), (0, 0, 0, 0))

    def test_hue_shift_and_color_wheel_generate_pixel_art_palettes(self) -> None:
        image = Image.new("RGBA", (1, 1), (255, 0, 0, 255))

        shifted = apply_hue_shift(image, degrees=120)
        wheel = color_wheel_palette("#ff0000", harmony="complementary", steps=5)

        shifted_pixel = shifted.getpixel((0, 0))
        self.assertGreater(shifted_pixel[1], 200)
        self.assertLess(shifted_pixel[0], 80)
        self.assertEqual(wheel["base"], "#ff0000")
        self.assertIn("#00ffff", wheel["colors"])
        self.assertEqual(len(wheel["ramp"]), 5)

    def test_write_edit_package_saves_png_manifest_and_palette(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = SpriteEditSession.from_image(sample_image(), name="crate")
            session.replace_color("#ff0000", "#0000ff")

            result = write_edit_package(session, root)

            self.assertTrue(Path(result["image"]).exists())
            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["palette"]).exists())
            self.assertEqual(result["operations"][-1]["action"], "replace_color")

    def test_apply_edit_operations_dispatches_json_ready_editor_pipeline(self) -> None:
        session = SpriteEditSession.from_image(sample_image(), name="crate")

        summary = apply_edit_operations(
            session,
            [
                {"tool": "add_layer", "name": "paint"},
                {"tool": "draw_pixel", "x": 5, "y": 5, "color": "#112233"},
                {"tool": "fill_rect", "rect": [0, 3, 2, 2], "color": "#445566"},
                {"tool": "crop", "rect": [0, 0, 6, 6]},
                {"tool": "resize", "size": [12, 12]},
                {"tool": "flip", "axis": "horizontal"},
                {"tool": "rotate_90", "clockwise": False},
            ],
        )

        self.assertEqual(summary["applied"], 7)
        self.assertEqual(summary["size"], {"width": 12, "height": 12})
        self.assertEqual(summary["layers"], ["base", "paint"])
        self.assertEqual(session.composite().size, (12, 12))

    def test_apply_edit_operations_rejects_unknown_tools(self) -> None:
        session = SpriteEditSession.from_image(sample_image(), name="crate")

        with self.assertRaises(ValueError):
            apply_edit_operations(session, [{"tool": "not_a_real_tool"}])

    def test_write_palette_variant_package_generates_named_colorways(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = write_palette_variant_package(
                sample_image(),
                root,
                name="crate",
                variants=[
                    {"name": "blue", "swaps": {"#ff0000": "#0000ff"}},
                    {"name": "lime_shift", "hue_shift": 120},
                ],
            )

            self.assertEqual([variant["name"] for variant in result["variants"]], ["blue", "lime_shift"])
            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["contact_sheet"]).exists())
            with Image.open(result["contact_sheet"]) as contact:
                self.assertEqual(contact.size, (12, 6))
            with Image.open(result["variants"][0]["image"]) as image:
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))

    def test_write_batch_edit_package_applies_one_pipeline_to_many_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.png"
            second = root / "second.png"
            sample_image().save(first)
            sample_image().save(second)

            result = write_batch_edit_package(
                [first, second],
                root / "batch",
                operations=[
                    {"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"},
                    {"tool": "crop", "rect": [0, 0, 4, 4]},
                ],
            )

            self.assertEqual(result["edited"], 2)
            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["contact_sheet"]).exists())
            with Image.open(result["contact_sheet"]) as contact:
                self.assertEqual(contact.size, (8, 4))
            for item in result["outputs"]:
                with Image.open(item["output"]) as image:
                    self.assertEqual(image.size, (4, 4))
                    self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))


if __name__ == "__main__":
    unittest.main()
