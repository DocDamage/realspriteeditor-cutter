from __future__ import annotations

import colorsys
import copy
import json
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageColor, ImageDraw


ColorInput = str | tuple[int, int, int] | tuple[int, int, int, int]


def parse_color(value: ColorInput) -> tuple[int, int, int, int]:
    if isinstance(value, str):
        parsed = ImageColor.getcolor(value, "RGBA")
        return (int(parsed[0]), int(parsed[1]), int(parsed[2]), int(parsed[3]))
    if len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]), 255)
    return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))


def color_to_hex(color: ColorInput, include_alpha: bool = False) -> str:
    rgba = parse_color(color)
    if include_alpha and rgba[3] != 255:
        return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}{rgba[3]:02x}"
    return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"


def _image_copy(image: Image.Image) -> Image.Image:
    return image.convert("RGBA").copy()


def _pixel_data(image: Image.Image) -> list[tuple[int, int, int, int]]:
    rgba = image.convert("RGBA")
    if hasattr(rgba, "get_flattened_data"):
        return list(rgba.get_flattened_data())  # type: ignore[attr-defined]
    return [rgba.getpixel((x, y)) for y in range(rgba.height) for x in range(rgba.width)]


def _within_tolerance(left: tuple[int, int, int, int], right: tuple[int, int, int, int], tolerance: int) -> bool:
    if left[3] == 0 and right[3] == 0:
        return True
    return all(abs(int(left[index]) - int(right[index])) <= tolerance for index in range(4))


def extract_palette(image: Image.Image, max_colors: int = 32, include_transparent: bool = False) -> list[dict[str, Any]]:
    counter: Counter[tuple[int, int, int, int]] = Counter()
    for pixel in _pixel_data(image):
        if pixel[3] == 0 and not include_transparent:
            continue
        counter[pixel] += 1
    entries: list[dict[str, Any]] = []
    for color, count in counter.most_common(max_colors):
        entries.append({"rgba": list(color), "hex": color_to_hex(color), "count": count})
    return entries


def apply_palette_swap(image: Image.Image, swaps: dict[str, str] | dict[ColorInput, ColorInput], tolerance: int = 0) -> Image.Image:
    source = image.convert("RGBA")
    normalized = [(parse_color(source_color), parse_color(target_color)) for source_color, target_color in swaps.items()]
    output = Image.new("RGBA", source.size)
    pixels = []
    for pixel in _pixel_data(source):
        next_pixel = pixel
        for source_color, target_color in normalized:
            if _within_tolerance(pixel, source_color, tolerance):
                next_pixel = (target_color[0], target_color[1], target_color[2], pixel[3] if target_color[3] == 255 else target_color[3])
                break
        pixels.append(next_pixel)
    output.putdata(pixels)
    return output


def apply_hue_shift(
    image: Image.Image,
    degrees: float,
    saturation: float = 1.0,
    value: float = 1.0,
) -> Image.Image:
    output = Image.new("RGBA", image.size)
    shifted = []
    for red, green, blue, alpha in _pixel_data(image):
        if alpha == 0:
            shifted.append((red, green, blue, alpha))
            continue
        hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
        hue = (hue + degrees / 360.0) % 1.0
        sat = max(0.0, min(1.0, sat * saturation))
        val = max(0.0, min(1.0, val * value))
        out_red, out_green, out_blue = colorsys.hsv_to_rgb(hue, sat, val)
        shifted.append((int(round(out_red * 255)), int(round(out_green * 255)), int(round(out_blue * 255)), alpha))
    output.putdata(shifted)
    return output


def _adjust_value(color: tuple[int, int, int, int], factor: float) -> str:
    hue, sat, val = colorsys.rgb_to_hsv(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)
    val = max(0.0, min(1.0, val * factor))
    red, green, blue = colorsys.hsv_to_rgb(hue, sat, val)
    return color_to_hex((int(round(red * 255)), int(round(green * 255)), int(round(blue * 255)), color[3]))


def color_wheel_palette(base: ColorInput, harmony: str = "complementary", steps: int = 5) -> dict[str, Any]:
    base_rgba = parse_color(base)
    hue, sat, val = colorsys.rgb_to_hsv(base_rgba[0] / 255.0, base_rgba[1] / 255.0, base_rgba[2] / 255.0)
    offsets = {
        "complementary": [0.0, 0.5],
        "analogous": [0.0, 1.0 / 12.0, -1.0 / 12.0],
        "triadic": [0.0, 1.0 / 3.0, 2.0 / 3.0],
        "tetradic": [0.0, 0.25, 0.5, 0.75],
    }.get(harmony, [0.0, 0.5])
    colors: list[str] = []
    for offset in offsets:
        red, green, blue = colorsys.hsv_to_rgb((hue + offset) % 1.0, sat, val)
        colors.append(color_to_hex((int(round(red * 255)), int(round(green * 255)), int(round(blue * 255)), base_rgba[3])))
    ramp_steps = max(1, int(steps))
    if ramp_steps == 1:
        ramp = [color_to_hex(base_rgba)]
    else:
        ramp = [_adjust_value(base_rgba, 0.45 + (1.15 * index / (ramp_steps - 1))) for index in range(ramp_steps)]
    return {"base": color_to_hex(base_rgba), "harmony": harmony, "colors": colors, "ramp": ramp}


@dataclass
class SpriteLayer:
    name: str
    image: Image.Image
    visible: bool = True
    opacity: float = 1.0


@dataclass
class SpriteEditSession:
    name: str
    layers: list[SpriteLayer]
    active_layer: int = 0
    operations: list[dict[str, Any]] = field(default_factory=list)
    _undo_stack: list[list[SpriteLayer]] = field(default_factory=list, repr=False)
    _redo_stack: list[list[SpriteLayer]] = field(default_factory=list, repr=False)

    @classmethod
    def from_image(cls, image: Image.Image, name: str = "sprite") -> "SpriteEditSession":
        return cls(name=name, layers=[SpriteLayer("base", _image_copy(image))])

    @classmethod
    def open(cls, path: Path | str) -> "SpriteEditSession":
        path = Path(path)
        with Image.open(path) as image:
            return cls.from_image(image, name=path.stem)

    @property
    def size(self) -> tuple[int, int]:
        if not self.layers:
            return (0, 0)
        return self.layers[0].image.size

    def _snapshot(self) -> list[SpriteLayer]:
        return [SpriteLayer(layer.name, layer.image.copy(), layer.visible, layer.opacity) for layer in self.layers]

    def _restore(self, snapshot: list[SpriteLayer]) -> None:
        self.layers = [SpriteLayer(layer.name, layer.image.copy(), layer.visible, layer.opacity) for layer in snapshot]
        self.active_layer = min(self.active_layer, max(0, len(self.layers) - 1))

    def _record(self, action: str, **data: Any) -> None:
        self._undo_stack.append(self._snapshot())
        self._redo_stack = []
        self.operations.append({"action": action, **copy.deepcopy(data)})

    def _layer(self) -> SpriteLayer:
        if not self.layers:
            raise ValueError("Sprite edit session has no layers.")
        return self.layers[self.active_layer]

    def add_layer(self, name: str, image: Image.Image | None = None, visible: bool = True, opacity: float = 1.0) -> None:
        self._record("add_layer", name=name)
        layer_image = _image_copy(image) if image is not None else Image.new("RGBA", self.size, (0, 0, 0, 0))
        if layer_image.size != self.size:
            layer_image = layer_image.resize(self.size, Image.Resampling.NEAREST)
        self.layers.append(SpriteLayer(name, layer_image, visible, max(0.0, min(1.0, float(opacity)))))
        self.active_layer = len(self.layers) - 1

    def _require_layer_index(self, index: int) -> int:
        index = int(index)
        if index < 0 or index >= len(self.layers):
            raise ValueError(f"Layer index out of range: {index}")
        return index

    def select_layer(self, index: int) -> None:
        self.active_layer = self._require_layer_index(index)

    def rename_layer(self, index: int, name: str) -> None:
        index = self._require_layer_index(index)
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("Layer name cannot be empty.")
        self._record("rename_layer", index=index, name=clean_name)
        self.layers[index].name = clean_name

    def duplicate_layer(self, index: int, name: str | None = None) -> None:
        index = self._require_layer_index(index)
        source = self.layers[index]
        next_name = str(name).strip() if name else f"{source.name}_copy"
        self._record("duplicate_layer", index=index, name=next_name)
        self.layers.insert(index + 1, SpriteLayer(next_name, source.image.copy(), source.visible, source.opacity))
        self.active_layer = index + 1

    def delete_layer(self, index: int) -> None:
        index = self._require_layer_index(index)
        if len(self.layers) <= 1:
            raise ValueError("Cannot delete the only layer.")
        self._record("delete_layer", index=index)
        del self.layers[index]
        self.active_layer = min(self.active_layer, len(self.layers) - 1)

    def reorder_layer(self, from_index: int, to_index: int) -> None:
        from_index = self._require_layer_index(from_index)
        to_index = max(0, min(len(self.layers) - 1, int(to_index)))
        self._record("reorder_layer", from_index=from_index, to_index=to_index)
        layer = self.layers.pop(from_index)
        self.layers.insert(to_index, layer)
        self.active_layer = to_index

    def set_layer_visibility(self, index: int, visible: bool) -> None:
        index = self._require_layer_index(index)
        self._record("set_layer_visibility", index=index, visible=bool(visible))
        self.layers[index].visible = bool(visible)

    def set_layer_opacity(self, index: int, opacity: float) -> None:
        index = self._require_layer_index(index)
        next_opacity = max(0.0, min(1.0, float(opacity)))
        self._record("set_layer_opacity", index=index, opacity=next_opacity)
        self.layers[index].opacity = next_opacity

    def composite(self) -> Image.Image:
        if not self.layers:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        result = Image.new("RGBA", self.size, (0, 0, 0, 0))
        for layer in self.layers:
            if not layer.visible:
                continue
            layer_image = layer.image.convert("RGBA")
            if layer.opacity < 1.0:
                alpha = layer_image.getchannel("A")
                alpha = alpha.point(lambda value: int(value * layer.opacity))
                layer_image = layer_image.copy()
                layer_image.putalpha(alpha)
            result.alpha_composite(layer_image)
        return result

    def draw_pixel(self, x: int, y: int, color: ColorInput) -> None:
        self._record("draw_pixel", x=int(x), y=int(y), color=color_to_hex(color, include_alpha=True))
        if 0 <= int(x) < self.size[0] and 0 <= int(y) < self.size[1]:
            self._layer().image.putpixel((int(x), int(y)), parse_color(color))

    def draw_line(self, start: tuple[int, int], end: tuple[int, int], color: ColorInput, width: int = 1) -> None:
        self._record("draw_line", start=list(start), end=list(end), color=color_to_hex(color, include_alpha=True), width=int(width))
        draw = ImageDraw.Draw(self._layer().image)
        draw.line((tuple(start), tuple(end)), fill=parse_color(color), width=max(1, int(width)))

    def fill_rect(self, rect: tuple[int, int, int, int], color: ColorInput) -> None:
        x, y, width, height = [int(part) for part in rect]
        self._record("fill_rect", rect=[x, y, width, height], color=color_to_hex(color, include_alpha=True))
        draw = ImageDraw.Draw(self._layer().image)
        draw.rectangle((x, y, x + max(1, width) - 1, y + max(1, height) - 1), fill=parse_color(color))

    def erase_rect(self, rect: tuple[int, int, int, int]) -> None:
        self.fill_rect(rect, (0, 0, 0, 0))
        self.operations[-1]["action"] = "erase_rect"

    def flood_fill(self, point: tuple[int, int], color: ColorInput, tolerance: int = 0) -> None:
        x, y = int(point[0]), int(point[1])
        if not (0 <= x < self.size[0] and 0 <= y < self.size[1]):
            return
        layer = self._layer().image
        target = layer.getpixel((x, y))
        replacement = parse_color(color)
        if _within_tolerance(target, replacement, 0):
            return
        self._record("flood_fill", point=[x, y], color=color_to_hex(color, include_alpha=True), tolerance=int(tolerance))
        queue: deque[tuple[int, int]] = deque([(x, y)])
        visited: set[tuple[int, int]] = set()
        while queue:
            cx, cy = queue.popleft()
            if (cx, cy) in visited or not (0 <= cx < self.size[0] and 0 <= cy < self.size[1]):
                continue
            visited.add((cx, cy))
            if not _within_tolerance(layer.getpixel((cx, cy)), target, int(tolerance)):
                continue
            layer.putpixel((cx, cy), replacement)
            queue.extend([(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)])

    def replace_color(self, source: ColorInput, target: ColorInput, tolerance: int = 0) -> None:
        self._record("replace_color", source=color_to_hex(source), target=color_to_hex(target), tolerance=int(tolerance))
        self._layer().image = apply_palette_swap(self._layer().image, {source: target}, tolerance=tolerance)

    def hue_shift(self, degrees: float, saturation: float = 1.0, value: float = 1.0) -> None:
        self._record("hue_shift", degrees=float(degrees), saturation=float(saturation), value=float(value))
        self._layer().image = apply_hue_shift(self._layer().image, degrees=degrees, saturation=saturation, value=value)

    def crop(self, rect: tuple[int, int, int, int]) -> None:
        x, y, width, height = [int(part) for part in rect]
        self._record("crop", rect=[x, y, width, height])
        crop_box = (x, y, x + max(1, width), y + max(1, height))
        for layer in self.layers:
            layer.image = layer.image.crop(crop_box)

    def resize(self, size: tuple[int, int]) -> None:
        width, height = max(1, int(size[0])), max(1, int(size[1]))
        self._record("resize", size=[width, height])
        for layer in self.layers:
            layer.image = layer.image.resize((width, height), Image.Resampling.NEAREST)

    def flip_horizontal(self) -> None:
        self._record("flip_horizontal")
        for layer in self.layers:
            layer.image = layer.image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    def flip_vertical(self) -> None:
        self._record("flip_vertical")
        for layer in self.layers:
            layer.image = layer.image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def rotate_90(self, clockwise: bool = True) -> None:
        self._record("rotate_90", clockwise=bool(clockwise))
        method = Image.Transpose.ROTATE_270 if clockwise else Image.Transpose.ROTATE_90
        for layer in self.layers:
            layer.image = layer.image.transpose(method)

    def undo(self) -> None:
        if not self._undo_stack:
            raise ValueError("No sprite edit operations to undo.")
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())

    def redo(self) -> None:
        if not self._redo_stack:
            raise ValueError("No sprite edit operations to redo.")
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.composite().save(path)


def _operation_tuple(value: Any, length: int, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ValueError(f"Editor operation field {field_name} must contain {length} numbers.")
    return tuple(int(part) for part in value)


def apply_edit_operations(session: SpriteEditSession, operations: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(operations, list):
        raise ValueError("Editor operations must be a list.")

    applied_tools: list[str] = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Each editor operation must be a JSON object.")
        tool = str(operation.get("tool") or operation.get("action") or "").strip()
        if not tool:
            raise ValueError("Editor operation is missing a tool field.")

        if tool == "add_layer":
            session.add_layer(
                str(operation.get("name", f"layer_{len(session.layers) + 1}")),
                visible=bool(operation.get("visible", True)),
                opacity=float(operation.get("opacity", 1.0)),
            )
        elif tool == "select_layer":
            session.select_layer(int(operation.get("index", 0)))
        elif tool == "rename_layer":
            session.rename_layer(int(operation.get("index", session.active_layer)), str(operation.get("name", "")).strip())
        elif tool == "duplicate_layer":
            name = operation.get("name")
            session.duplicate_layer(int(operation.get("index", session.active_layer)), str(name).strip() if name else None)
        elif tool == "delete_layer":
            session.delete_layer(int(operation.get("index", session.active_layer)))
        elif tool == "reorder_layer":
            session.reorder_layer(int(operation.get("from_index", session.active_layer)), int(operation.get("to_index", session.active_layer)))
        elif tool == "set_layer_visibility":
            session.set_layer_visibility(int(operation.get("index", session.active_layer)), bool(operation.get("visible", True)))
        elif tool == "set_layer_opacity":
            session.set_layer_opacity(int(operation.get("index", session.active_layer)), float(operation.get("opacity", 1.0)))
        elif tool == "draw_pixel":
            session.draw_pixel(int(operation["x"]), int(operation["y"]), operation.get("color", "#000000"))
        elif tool == "draw_line":
            session.draw_line(
                _operation_tuple(operation.get("start"), 2, "start"),  # type: ignore[arg-type]
                _operation_tuple(operation.get("end"), 2, "end"),  # type: ignore[arg-type]
                operation.get("color", "#000000"),
                width=int(operation.get("width", 1)),
            )
        elif tool == "fill_rect":
            session.fill_rect(_operation_tuple(operation.get("rect"), 4, "rect"), operation.get("color", "#000000"))  # type: ignore[arg-type]
        elif tool == "erase_rect":
            session.erase_rect(_operation_tuple(operation.get("rect"), 4, "rect"))  # type: ignore[arg-type]
        elif tool == "flood_fill":
            session.flood_fill(
                _operation_tuple(operation.get("point"), 2, "point"),  # type: ignore[arg-type]
                operation.get("color", "#000000"),
                tolerance=int(operation.get("tolerance", 0)),
            )
        elif tool == "replace_color":
            session.replace_color(operation.get("source", "#000000"), operation.get("target", "#000000"), tolerance=int(operation.get("tolerance", 0)))
        elif tool == "hue_shift":
            session.hue_shift(float(operation.get("degrees", 0)), saturation=float(operation.get("saturation", 1.0)), value=float(operation.get("value", 1.0)))
        elif tool == "crop":
            session.crop(_operation_tuple(operation.get("rect"), 4, "rect"))  # type: ignore[arg-type]
        elif tool == "resize":
            session.resize(_operation_tuple(operation.get("size"), 2, "size"))  # type: ignore[arg-type]
        elif tool == "flip":
            axis = str(operation.get("axis", "horizontal")).strip().lower()
            if axis in {"horizontal", "x"}:
                session.flip_horizontal()
            elif axis in {"vertical", "y"}:
                session.flip_vertical()
            else:
                raise ValueError(f"Unsupported flip axis: {axis}")
        elif tool == "rotate_90":
            session.rotate_90(clockwise=bool(operation.get("clockwise", True)))
        else:
            raise ValueError(f"Unsupported editor tool: {tool}")
        applied_tools.append(tool)

    return {
        "applied": len(applied_tools),
        "tools": applied_tools,
        "size": {"width": session.size[0], "height": session.size[1]},
        "layers": [layer.name for layer in session.layers],
        "operation_count": len(session.operations),
    }


def write_edit_package(session: SpriteEditSession, output_dir: Path | str) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{session.name}_edited.png"
    manifest_path = output_dir / f"{session.name}_edit_manifest.json"
    palette_path = output_dir / f"{session.name}_palette.json"
    session.save(image_path)
    palette = extract_palette(session.composite(), max_colors=64)
    manifest = {
        "name": session.name,
        "size": {"width": session.size[0], "height": session.size[1]},
        "layers": [{"name": layer.name, "visible": layer.visible, "opacity": layer.opacity} for layer in session.layers],
        "operations": session.operations,
        "image": str(image_path),
        "palette": str(palette_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    palette_path.write_text(json.dumps({"colors": palette}, indent=2), encoding="utf-8")
    return {
        "image": str(image_path),
        "manifest": str(manifest_path),
        "palette": str(palette_path),
        "operations": copy.deepcopy(session.operations),
    }


def _safe_variant_name(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "variant"


def render_contact_sheet(images: list[Image.Image], columns: int | None = None, background: ColorInput = (0, 0, 0, 0)) -> Image.Image:
    if not images:
        raise ValueError("Contact sheet requires at least one image.")
    rgba_images = [image.convert("RGBA").copy() for image in images]
    tile_width = max(image.width for image in rgba_images)
    tile_height = max(image.height for image in rgba_images)
    resolved_columns = int(columns or len(rgba_images))
    resolved_columns = max(1, min(resolved_columns, len(rgba_images)))
    rows = (len(rgba_images) + resolved_columns - 1) // resolved_columns
    sheet = Image.new("RGBA", (tile_width * resolved_columns, tile_height * rows), parse_color(background))
    for index, image in enumerate(rgba_images):
        x = (index % resolved_columns) * tile_width + (tile_width - image.width) // 2
        y = (index // resolved_columns) * tile_height + (tile_height - image.height) // 2
        sheet.alpha_composite(image, (x, y))
    return sheet


def _apply_variant(image: Image.Image, variant: dict[str, Any]) -> Image.Image:
    result = image.convert("RGBA").copy()
    swaps = variant.get("swaps", {})
    if isinstance(swaps, dict) and swaps:
        result = apply_palette_swap(result, swaps, tolerance=int(variant.get("tolerance", 0)))
    if "hue_shift" in variant:
        result = apply_hue_shift(
            result,
            degrees=float(variant.get("hue_shift", 0)),
            saturation=float(variant.get("saturation", 1.0)),
            value=float(variant.get("value", 1.0)),
        )
    return result


def write_palette_variant_package(
    image: Image.Image,
    output_dir: Path | str,
    *,
    name: str = "sprite",
    variants: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(variants, list) or not variants:
        raise ValueError("Palette variant package requires a non-empty variants list.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = _safe_variant_name(name)
    written: list[dict[str, Any]] = []
    rendered_images: list[Image.Image] = []
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            raise ValueError("Each palette variant must be a JSON object.")
        variant_name = _safe_variant_name(str(variant.get("name", f"variant_{index:02d}")))
        output_path = output_dir / f"{base_name}_{variant_name}.png"
        variant_image = _apply_variant(image, variant)
        variant_image.save(output_path)
        rendered_images.append(variant_image)
        written.append(
            {
                "name": variant_name,
                "image": str(output_path),
                "palette": extract_palette(variant_image, max_colors=64),
                "recipe": copy.deepcopy(variant),
            }
        )
    contact_sheet_path = output_dir / f"{base_name}_palette_variants_contact.png"
    render_contact_sheet(rendered_images).save(contact_sheet_path)
    manifest_path = output_dir / f"{base_name}_palette_variants.json"
    manifest = {"name": base_name, "variants": written, "contact_sheet": str(contact_sheet_path)}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"manifest": str(manifest_path), "contact_sheet": str(contact_sheet_path), "variants": written}


def write_batch_edit_package(
    inputs: list[Path | str],
    output_dir: Path | str,
    *,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("Batch edit package requires a non-empty inputs list.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[dict[str, Any]] = []
    rendered_images: list[Image.Image] = []
    for input_path in inputs:
        source = Path(input_path)
        session = SpriteEditSession.open(source)
        summary = apply_edit_operations(session, operations)
        output_path = output_dir / f"{_safe_variant_name(source.stem)}_edited.png"
        session.save(output_path)
        rendered_images.append(session.composite())
        outputs.append({"input": str(source), "output": str(output_path), "summary": summary})
    contact_sheet_path = output_dir / "batch_edit_contact.png"
    render_contact_sheet(rendered_images).save(contact_sheet_path)
    manifest_path = output_dir / "batch_edit_manifest.json"
    manifest = {"edited": len(outputs), "operations": copy.deepcopy(operations), "outputs": outputs, "contact_sheet": str(contact_sheet_path)}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"edited": len(outputs), "manifest": str(manifest_path), "contact_sheet": str(contact_sheet_path), "outputs": outputs}
