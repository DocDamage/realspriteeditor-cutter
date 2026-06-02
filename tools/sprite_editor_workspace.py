from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from PIL import Image

from tools.sprite_editor import SpriteEditSession, extract_palette


class EditorTool(str, Enum):
    PENCIL = "pencil"
    ERASER = "eraser"
    EYEDROPPER = "eyedropper"
    FILL = "fill"
    LINE = "line"
    RECT_FILL = "rect_fill"
    RECT_OUTLINE = "rect_outline"
    SELECT_MOVE = "select_move"
    CROP = "crop"
    PAN = "pan"
    ZOOM = "zoom"
    PALETTE_SWAP = "palette_swap"
    HUE_SHIFT = "hue_shift"
    PALETTE_VARIANTS = "palette_variants"
    FLIP = "flip"
    ROTATE = "rotate"
    RESIZE = "resize"


class ToolScope(str, Enum):
    ACTIVE_LAYER = "active_layer"
    SELECTED_REGION = "selected_region"
    CURRENT_FRAME = "current_frame"
    SELECTED_FRAMES = "selected_frames"
    ALL_FRAMES = "all_frames"


@dataclass(frozen=True)
class EditorToolMetadata:
    label: str
    shortcut: str
    tooltip: str
    help_text: str


@dataclass(frozen=True)
class EditorWorkspaceState:
    fullscreen: bool = False
    active_tool: EditorTool = EditorTool.PENCIL
    foreground_color: str = "#ffffff"
    background_color: str = "#00000000"
    zoom: float = 8.0
    show_grid: bool = True
    tool_scope: ToolScope = ToolScope.ACTIVE_LAYER
    selected_frame_indices: tuple[int, ...] = ()
    active_layer_index: int = 0
    active_frame_index: int = 0
    selected_region: tuple[int, int, int, int] | None = None

    def with_tool(self, tool: EditorTool) -> "EditorWorkspaceState":
        return replace(self, active_tool=tool)

    def with_fullscreen(self, fullscreen: bool) -> "EditorWorkspaceState":
        return replace(self, fullscreen=bool(fullscreen))

    def with_scope(self, scope: ToolScope) -> "EditorWorkspaceState":
        return replace(self, tool_scope=scope)

    def with_zoom(self, zoom: float) -> "EditorWorkspaceState":
        return replace(self, zoom=max(1.0, min(64.0, float(zoom))))


EDITOR_TOOLS: dict[EditorTool, EditorToolMetadata] = {
    EditorTool.PENCIL: EditorToolMetadata("Pencil", "B", "Draw single-pixel strokes with the foreground color.", "Mouse: left-drag to draw. Shift: constrain straight strokes."),
    EditorTool.ERASER: EditorToolMetadata("Eraser", "E", "Erase pixels on the active layer.", "Mouse: left-drag to erase pixels to transparent."),
    EditorTool.EYEDROPPER: EditorToolMetadata("Eyedropper", "I", "Pick a visible color from the canvas.", "Mouse: left-click a pixel to set the foreground color."),
    EditorTool.FILL: EditorToolMetadata("Fill", "G", "Flood fill connected pixels that match the clicked color.", "Mouse: left-click inside a region. Tolerance controls near-color matching."),
    EditorTool.LINE: EditorToolMetadata("Line", "L", "Draw a straight line.", "Mouse: drag from start to end, release to commit."),
    EditorTool.RECT_FILL: EditorToolMetadata("Filled Rect", "R", "Draw a filled rectangle.", "Mouse: drag a rectangle, release to fill it."),
    EditorTool.RECT_OUTLINE: EditorToolMetadata("Rect Outline", "Shift+R", "Draw a rectangle outline.", "Mouse: drag a rectangle, release to draw the outline."),
    EditorTool.SELECT_MOVE: EditorToolMetadata("Select/Move", "M", "Select pixels or move the current selection.", "Mouse: drag to select. Drag an existing selection to move it."),
    EditorTool.CROP: EditorToolMetadata("Crop", "C", "Crop the sprite or current frame.", "Mouse: drag the crop area, release to preview, confirm to commit."),
    EditorTool.PAN: EditorToolMetadata("Pan", "H", "Move around the canvas without editing pixels.", "Mouse: drag to pan. Space-drag also pans."),
    EditorTool.ZOOM: EditorToolMetadata("Zoom", "Z", "Zoom in or out around the cursor.", "Mouse: wheel over canvas or click to zoom in. Alt-click zooms out."),
    EditorTool.PALETTE_SWAP: EditorToolMetadata("Palette Swap", "", "Replace one color with another.", "Mouse: use eyedropper/color fields, then apply to the chosen scope."),
    EditorTool.HUE_SHIFT: EditorToolMetadata("Hue Shift", "", "Shift hue, saturation, and value.", "Mouse: adjust fields, then apply to the chosen scope."),
    EditorTool.PALETTE_VARIANTS: EditorToolMetadata("Palette Variants", "", "Generate preview colorways.", "Mouse: choose harmony and generate variants for review."),
    EditorTool.FLIP: EditorToolMetadata("Flip", "", "Flip the current scope horizontally or vertically.", "Mouse: choose axis and apply."),
    EditorTool.ROTATE: EditorToolMetadata("Rotate", "", "Rotate the current scope by 90 degrees.", "Mouse: choose clockwise or counterclockwise and apply."),
    EditorTool.RESIZE: EditorToolMetadata("Resize", "", "Resize the current sprite or frame.", "Mouse: enter target size and apply with nearest-neighbor scaling."),
}

EDITOR_SHORTCUTS: dict[str, str] = {
    "B": "tool:pencil",
    "E": "tool:eraser",
    "I": "tool:eyedropper",
    "G": "tool:fill",
    "L": "tool:line",
    "R": "tool:rect_fill",
    "Shift+R": "tool:rect_outline",
    "M": "tool:select_move",
    "C": "tool:crop",
    "H": "tool:pan",
    "Z": "tool:zoom",
    "Ctrl+Z": "command:undo",
    "Ctrl+Y": "command:redo",
    "Ctrl+Shift+Z": "command:redo",
    "Ctrl+S": "command:save",
    "+": "command:zoom_in",
    "-": "command:zoom_out",
    "0": "command:fit",
    "1": "command:actual_size",
    "Space": "command:play_pause",
}


def _normalize_shortcut(value: str) -> str:
    parts = [part for part in value.replace(" ", "").split("+") if part]
    if not parts:
        return ""
    modifiers = [part.capitalize() for part in parts[:-1]]
    key = parts[-1]
    key = key.upper() if len(key) == 1 else key.capitalize()
    return "+".join([*modifiers, key])


def shortcut_action_for_key(value: str) -> str | None:
    return EDITOR_SHORTCUTS.get(_normalize_shortcut(value))


def tool_help_text(tool: EditorTool) -> str:
    return EDITOR_TOOLS[tool].help_text


@dataclass(frozen=True)
class CanvasView:
    sprite_size: tuple[int, int]
    panel_size: tuple[int, int]
    zoom: float = 8.0
    pan: tuple[int, int] = (0, 0)

    @classmethod
    def fit(cls, sprite_size: tuple[int, int], panel_size: tuple[int, int]) -> "CanvasView":
        sprite_width, sprite_height = max(1, sprite_size[0]), max(1, sprite_size[1])
        panel_width, panel_height = max(1, panel_size[0]), max(1, panel_size[1])
        zoom = max(1.0, min(8.0, panel_width / sprite_width, panel_height / sprite_height))
        zoom = float(int(zoom))
        canvas_width = int(sprite_width * zoom)
        canvas_height = int(sprite_height * zoom)
        pan = ((panel_width - canvas_width) // 2, (panel_height - canvas_height) // 2)
        return cls(sprite_size=(sprite_width, sprite_height), panel_size=(panel_width, panel_height), zoom=zoom, pan=pan)

    def sprite_to_screen(self, point: tuple[int, int]) -> tuple[int, int]:
        return (int(self.pan[0] + int(point[0]) * self.zoom), int(self.pan[1] + int(point[1]) * self.zoom))

    def screen_to_sprite(self, point: tuple[int, int]) -> tuple[int, int]:
        x = int((int(point[0]) - self.pan[0]) // self.zoom)
        y = int((int(point[1]) - self.pan[1]) // self.zoom)
        return (max(0, min(self.sprite_size[0] - 1, x)), max(0, min(self.sprite_size[1] - 1, y)))

    def panned(self, delta: tuple[int, int]) -> "CanvasView":
        return replace(self, pan=(self.pan[0] + int(delta[0]), self.pan[1] + int(delta[1])))

    def zoom_around_cursor(self, cursor: tuple[int, int], factor: float) -> "CanvasView":
        before = self.screen_to_sprite(cursor)
        next_zoom = max(1.0, min(64.0, self.zoom * float(factor)))
        next_pan = (int(cursor[0] - before[0] * next_zoom), int(cursor[1] - before[1] * next_zoom))
        return replace(self, zoom=next_zoom, pan=next_pan)


def checkerboard_image(size: tuple[int, int], cell_size: int = 8) -> Image.Image:
    width, height = max(1, int(size[0])), max(1, int(size[1]))
    cell = max(1, int(cell_size))
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    light = (198, 202, 210, 255)
    dark = (140, 146, 156, 255)
    for y in range(height):
        for x in range(width):
            image.putpixel((x, y), light if ((x // cell) + (y // cell)) % 2 == 0 else dark)
    return image


def canvas_status_text(cursor: tuple[int, int] | None, color_hex: str | None, zoom: float, layer_index: int, frame_index: int) -> str:
    cursor_text = f"x={cursor[0]} y={cursor[1]}" if cursor is not None else "x=- y=-"
    color_text = color_hex or "#--------"
    return f"{cursor_text} color={color_text} zoom={zoom:.1f}x layer={layer_index + 1} frame={frame_index + 1}"


@dataclass(frozen=True)
class MouseGesture:
    kind: str
    start: tuple[int, int]
    end: tuple[int, int] | None = None
    button: str = "left"
    wheel_delta: int = 0


@dataclass(frozen=True)
class MouseToolResult:
    sampled_color: str | None = None
    crop_rect: tuple[int, int, int, int] | None = None
    selected_region: tuple[int, int, int, int] | None = None
    pan_delta: tuple[int, int] | None = None
    zoom_factor: float | None = None


def _rect_from_points(start: tuple[int, int], end: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, x1 = sorted((int(start[0]), int(end[0])))
    y0, y1 = sorted((int(start[1]), int(end[1])))
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def apply_mouse_tool(session: SpriteEditSession, state: EditorWorkspaceState, gesture: MouseGesture) -> MouseToolResult:
    end = gesture.end or gesture.start
    if state.active_tool == EditorTool.PENCIL:
        if gesture.kind == "drag" and gesture.end is not None:
            session.draw_line(gesture.start, gesture.end, state.foreground_color)
        else:
            session.draw_pixel(gesture.start[0], gesture.start[1], state.foreground_color)
        return MouseToolResult()
    if state.active_tool == EditorTool.ERASER:
        if gesture.kind == "drag" and gesture.end is not None:
            session.draw_line(gesture.start, gesture.end, state.background_color)
        else:
            session.draw_pixel(gesture.start[0], gesture.start[1], state.background_color)
        return MouseToolResult()
    if state.active_tool == EditorTool.EYEDROPPER:
        color = session.composite().getpixel(gesture.start)
        suffix = f"{color[3]:02x}" if color[3] != 255 else ""
        return MouseToolResult(sampled_color=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}{suffix}")
    if state.active_tool == EditorTool.FILL:
        session.flood_fill(gesture.start, state.foreground_color)
        return MouseToolResult()
    if state.active_tool == EditorTool.LINE:
        session.draw_line(gesture.start, end, state.foreground_color)
        return MouseToolResult()
    if state.active_tool == EditorTool.RECT_FILL:
        session.fill_rect(_rect_from_points(gesture.start, end), state.foreground_color)
        return MouseToolResult()
    if state.active_tool == EditorTool.RECT_OUTLINE:
        x, y, width, height = _rect_from_points(gesture.start, end)
        session.draw_line((x, y), (x + width - 1, y), state.foreground_color)
        session.draw_line((x, y), (x, y + height - 1), state.foreground_color)
        session.draw_line((x + width - 1, y), (x + width - 1, y + height - 1), state.foreground_color)
        session.draw_line((x, y + height - 1), (x + width - 1, y + height - 1), state.foreground_color)
        return MouseToolResult()
    if state.active_tool == EditorTool.SELECT_MOVE:
        return MouseToolResult(selected_region=_rect_from_points(gesture.start, end))
    if state.active_tool == EditorTool.CROP:
        return MouseToolResult(crop_rect=_rect_from_points(gesture.start, end))
    if state.active_tool == EditorTool.PAN:
        return MouseToolResult(pan_delta=(int(end[0]) - int(gesture.start[0]), int(end[1]) - int(gesture.start[1])))
    if state.active_tool == EditorTool.ZOOM:
        return MouseToolResult(zoom_factor=1.25 if int(gesture.wheel_delta) >= 0 else 0.8)
    return MouseToolResult()


def apply_shortcut_action(state: EditorWorkspaceState, action: str) -> tuple[EditorWorkspaceState, str | None]:
    if action.startswith("tool:"):
        return (state.with_tool(EditorTool(action.split(":", 1)[1])), None)
    if action == "command:zoom_in":
        return (state.with_zoom(state.zoom * 1.25), None)
    if action == "command:zoom_out":
        return (state.with_zoom(state.zoom * 0.8), None)
    if action == "command:actual_size":
        return (state.with_zoom(1.0), None)
    if action.startswith("command:"):
        return (state, action.split(":", 1)[1])
    return (state, None)


def state_help_text(state: EditorWorkspaceState) -> str:
    metadata = EDITOR_TOOLS[state.active_tool]
    shortcut = metadata.shortcut or "no shortcut"
    return f"{metadata.label} ({shortcut})\nScope: {state.tool_scope.value}\n{metadata.help_text}"


@dataclass(frozen=True)
class PaletteOperationPlan:
    operation: str
    source_color: str
    target_color: str
    tolerance: int = 0
    scope: ToolScope = ToolScope.ACTIVE_LAYER

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "source_color": self.source_color,
            "target_color": self.target_color,
            "tolerance": int(self.tolerance),
            "scope": self.scope.value,
        }


def palette_swatch_rows(image: Image.Image, active_color: str = "", max_colors: int = 32) -> list[str]:
    rows: list[str] = []
    for entry in extract_palette(image, max_colors=max_colors):
        marker = "*" if str(entry["hex"]).lower() == active_color.lower() else " "
        rows.append(f"{marker} {entry['hex']} count={entry['count']}")
    return rows


def scoped_frame_indices(state: EditorWorkspaceState, frame_count: int) -> list[int]:
    count = max(0, int(frame_count))
    if count == 0:
        return []
    if state.tool_scope == ToolScope.ALL_FRAMES:
        return list(range(count))
    if state.tool_scope == ToolScope.SELECTED_FRAMES and state.selected_frame_indices:
        return [index for index in state.selected_frame_indices if 0 <= index < count]
    return [max(0, min(count - 1, int(state.active_frame_index)))]
