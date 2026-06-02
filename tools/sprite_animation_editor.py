from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from tools.sprite_editor import SpriteEditSession, write_edit_package


@dataclass(frozen=True)
class AnimationFrameRef:
    sprite_id: str
    path: Path
    duration: float = 0.0833


@dataclass
class AnimationEditSession:
    name: str
    frames: list[SpriteEditSession]
    frame_refs: list[AnimationFrameRef]
    fps: int = 12
    active_frame: int = 0
    frame_size: tuple[int, int] = (1, 1)

    @classmethod
    def from_frame_refs(cls, name: str, frame_refs: list[AnimationFrameRef], fps: int = 12) -> "AnimationEditSession":
        if not frame_refs:
            raise ValueError("Animation edit session requires at least one frame.")
        images: list[Image.Image] = []
        for ref in frame_refs:
            with Image.open(ref.path) as image:
                images.append(image.convert("RGBA").copy())
        frame_size = (max(image.width for image in images), max(image.height for image in images))
        frames = [
            SpriteEditSession.from_image(normalize_frame_image(image, frame_size), name=ref.sprite_id or ref.path.stem)
            for image, ref in zip(images, frame_refs)
        ]
        return cls(name=name, frames=frames, frame_refs=list(frame_refs), fps=max(1, int(fps)), frame_size=frame_size)


def normalize_frame_image(image: Image.Image, size: tuple[int, int], anchor: str = "bottom-center") -> Image.Image:
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    source = image.convert("RGBA")
    result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if anchor == "center":
        x = (width - source.width) // 2
        y = (height - source.height) // 2
    elif anchor == "top-left":
        x, y = 0, 0
    else:
        x = (width - source.width) // 2
        y = height - source.height
    result.alpha_composite(source, (x, y))
    return result


def playback_next_frame(current_index: int, frame_count: int) -> int:
    count = max(1, int(frame_count))
    return (int(current_index) + 1) % count


def write_applied_animation(session: AnimationEditSession, output_dir: Path | str) -> dict[str, Any]:
    output_dir = Path(output_dir) / session.name
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index, frame in enumerate(session.frames):
        frame_dir = output_dir / f"frame_{index + 1:03d}"
        package = write_edit_package(frame, frame_dir)
        duration = session.frame_refs[index].duration if index < len(session.frame_refs) else 1.0 / session.fps
        frames.append(
            {
                "index": index,
                "sprite": frame.name,
                "duration": duration,
                "image": package["image"],
                "manifest": package["manifest"],
            }
        )
    manifest_path = output_dir / "animation_edit_manifest.json"
    manifest = {
        "name": session.name,
        "fps": session.fps,
        "frame_size": {"width": session.frame_size[0], "height": session.frame_size[1]},
        "frames": frames,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest": manifest_path, "frames": frames}
