from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_animation_editor import (
    AnimationEditSession,
    AnimationFrameRef,
    normalize_frame_image,
    playback_next_frame,
    write_applied_animation,
)


class SpriteAnimationEditorTests(unittest.TestCase):
    def test_animation_session_loads_frames_and_steps_playback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "idle_001.png"
            second = root / "idle_002.png"
            Image.new("RGBA", (4, 6), (255, 0, 0, 255)).save(first)
            Image.new("RGBA", (6, 4), (0, 255, 0, 255)).save(second)
            session = AnimationEditSession.from_frame_refs(
                "idle",
                [
                    AnimationFrameRef("sprite_001", first, duration=0.1),
                    AnimationFrameRef("sprite_002", second, duration=0.1),
                ],
            )

            self.assertEqual(session.name, "idle")
            self.assertEqual(len(session.frames), 2)
            self.assertEqual(playback_next_frame(0, len(session.frames)), 1)
            self.assertEqual(playback_next_frame(1, len(session.frames)), 0)

    def test_normalize_frame_image_uses_bottom_center_anchor(self) -> None:
        image = Image.new("RGBA", (2, 4), (255, 0, 0, 255))

        normalized = normalize_frame_image(image, (8, 8), anchor="bottom-center")

        self.assertEqual(normalized.size, (8, 8))
        self.assertEqual(normalized.getpixel((3, 4)), (255, 0, 0, 255))

    def test_write_applied_animation_exports_frames_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "idle_001.png"
            second = root / "idle_002.png"
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(first)
            Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(second)
            session = AnimationEditSession.from_frame_refs(
                "idle",
                [AnimationFrameRef("sprite_001", first), AnimationFrameRef("sprite_002", second)],
            )

            result = write_applied_animation(session, root / "applied")

            self.assertTrue(Path(result["manifest"]).exists())
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["frames"]), 2)
            self.assertTrue(Path(manifest["frames"][0]["image"]).exists())


if __name__ == "__main__":
    unittest.main()
