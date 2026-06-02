# Editor Workspace Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the existing SpriteCut Editor tab into an embedded/fullscreen sprite editing workspace with mouse tools, keyboard shortcuts, layers, palette controls, animation frame editing, contextual help, and project round-trip saves.

**Architecture:** Keep `tools.sprite_editor` as the edit-session backend and keep `tools.sprite_sheet_tool_ui` as the Dear PyGUI shell. Add pure helper modules for editor workspace state, canvas math, tool dispatch, help/shortcut metadata, and animation/project save helpers so most behavior is testable without Dear PyGUI.

**Tech Stack:** Python unittest, Pillow, Dear PyGUI optional desktop UI runtime, existing SpriteCut project/edit modules, JSON manifests, stdlib dataclasses/enums.

---

## Scope And File Structure

This plan intentionally ships the editor in phases. Each task should leave the app usable and should commit a coherent slice of behavior.

Files to create:

- `tools/sprite_editor_workspace.py`: pure editor workspace state, tool metadata, shortcut mapping, canvas coordinate conversion, mouse gesture helpers, contextual help text, and non-UI tool dispatch into `SpriteEditSession`.
- `tools/sprite_animation_editor.py`: pure animation frame/session helpers, frame strip model, playback timing, frame normalization, anchor placement, and applied animation export.
- `tests/test_sprite_editor_workspace.py`: unit tests for tools, shortcuts, canvas math, mouse gestures, layer helper behavior, and help metadata.
- `tests/test_sprite_animation_editor.py`: unit tests for animation frame loading, playback stepping, normalization, scoped frame edits, and applied animation export.

Files to modify:

- `tools/sprite_editor.py`: add focused layer management methods missing from the current backend: duplicate, delete, rename, reorder, visibility, opacity, and active-layer selection.
- `tools/sprite_sheet_tool_ui.py`: replace the compact Editor tab with the workspace shell, fullscreen state, canvas drawing, event handlers, panels, timeline controls, Review/Studio open-in-editor hooks, save-back actions, and complete tooltips.
- `tools/sprite_project.py`: add small project metadata helpers if needed for attaching edited sprite/animation outputs without duplicating JSON mutation in the UI.
- `tools/sprite_mcp_server.py`: keep existing MCP editor wrappers working; only extend if project-attached editor saves need an MCP wrapper.
- `tools/sprite_ide_api.py`: keep existing IDE actions compatible; only extend if a new action is required for project-attached saves.
- `README.md`, `docs/sprite_tool_aaa_guide.md`, `skills/codex/spritecut-pipeline/references/spritecut-commands.md`, `.claude/skills/spritecut-pipeline/references/spritecut-commands.md`: update after behavior exists.

Primary verification commands:

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py tools\sprite_mcp_server.py tools\sprite_editor_workspace.py tools\sprite_animation_editor.py
```

---

### Task 1: Workspace State, Tool Metadata, Shortcuts, And Help

**Files:**
- Create: `tools/sprite_editor_workspace.py`
- Create: `tests/test_sprite_editor_workspace.py`
- Modify: `tools/sprite_sheet_tool_ui.py`

- [ ] **Step 1: Write failing tests for workspace state, tool metadata, shortcuts, and help**

Create `tests/test_sprite_editor_workspace.py` with these tests:

```python
from __future__ import annotations

import unittest

from tools.sprite_editor_workspace import (
    EDITOR_SHORTCUTS,
    EDITOR_TOOLS,
    EditorTool,
    EditorWorkspaceState,
    ToolScope,
    shortcut_action_for_key,
    tool_help_text,
)


class SpriteEditorWorkspaceTests(unittest.TestCase):
    def test_workspace_state_defaults_to_friendly_embedded_editor(self) -> None:
        state = EditorWorkspaceState()

        self.assertFalse(state.fullscreen)
        self.assertEqual(state.active_tool, EditorTool.PENCIL)
        self.assertEqual(state.zoom, 8.0)
        self.assertTrue(state.show_grid)
        self.assertEqual(state.foreground_color, "#ffffff")
        self.assertEqual(state.background_color, "#00000000")
        self.assertEqual(state.tool_scope, ToolScope.ACTIVE_LAYER)

    def test_tool_metadata_covers_required_tools_with_help_and_shortcuts(self) -> None:
        required = {
            EditorTool.PENCIL,
            EditorTool.ERASER,
            EditorTool.EYEDROPPER,
            EditorTool.FILL,
            EditorTool.LINE,
            EditorTool.RECT_FILL,
            EditorTool.RECT_OUTLINE,
            EditorTool.SELECT_MOVE,
            EditorTool.CROP,
            EditorTool.PAN,
            EditorTool.ZOOM,
            EditorTool.PALETTE_SWAP,
            EditorTool.HUE_SHIFT,
            EditorTool.PALETTE_VARIANTS,
            EditorTool.FLIP,
            EditorTool.ROTATE,
            EditorTool.RESIZE,
        }

        self.assertEqual(set(EDITOR_TOOLS), required)
        for tool in required:
            with self.subTest(tool=tool):
                metadata = EDITOR_TOOLS[tool]
                self.assertTrue(metadata.label)
                self.assertTrue(metadata.tooltip)
                self.assertIn("Mouse", tool_help_text(tool))

    def test_shortcuts_map_to_tools_and_common_commands(self) -> None:
        self.assertEqual(shortcut_action_for_key("B"), "tool:pencil")
        self.assertEqual(shortcut_action_for_key("ctrl+z"), "command:undo")
        self.assertEqual(shortcut_action_for_key("Ctrl+Shift+Z"), "command:redo")
        self.assertEqual(shortcut_action_for_key("0"), "command:fit")
        self.assertEqual(shortcut_action_for_key("Space"), "command:play_pause")
        self.assertIn("Ctrl+S", EDITOR_SHORTCUTS)

    def test_state_switches_tools_fullscreen_and_scope_without_losing_context(self) -> None:
        state = EditorWorkspaceState(active_tool=EditorTool.PENCIL, selected_frame_indices=(0, 2))

        state = state.with_tool(EditorTool.FILL)
        state = state.with_fullscreen(True)
        state = state.with_scope(ToolScope.ALL_FRAMES)

        self.assertEqual(state.active_tool, EditorTool.FILL)
        self.assertTrue(state.fullscreen)
        self.assertEqual(state.tool_scope, ToolScope.ALL_FRAMES)
        self.assertEqual(state.selected_frame_indices, (0, 2))
```

- [ ] **Step 2: Run the new workspace tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.sprite_editor_workspace'`.

- [ ] **Step 3: Implement workspace state, tool metadata, shortcuts, and help**

Create `tools/sprite_editor_workspace.py` with this starting implementation:

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


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
```

- [ ] **Step 4: Run the workspace tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace -v
```

Expected: all tests pass.

- [ ] **Step 5: Add fullscreen state fields to the existing UI app**

Modify `tools/sprite_sheet_tool_ui.py` imports to include the new module:

```python
from tools.sprite_editor_workspace import EditorTool, EditorWorkspaceState, ToolScope, EDITOR_TOOLS, EDITOR_SHORTCUTS, tool_help_text
```

In the `except ModuleNotFoundError` import fallback, add the same import from `tools.sprite_editor_workspace`.

In `SpriteSheetToolUi.__init__`, add:

```python
self.editor_workspace = EditorWorkspaceState()
self.editor_fullscreen = DpgValue(False)
self.editor_active_tool = DpgValue(self.editor_workspace.active_tool.value)
self.editor_tool_scope = DpgValue(self.editor_workspace.tool_scope.value)
```

Add helper methods:

```python
def set_editor_fullscreen(self, enabled: bool) -> None:
    self.editor_workspace = self.editor_workspace.with_fullscreen(enabled)
    self.editor_fullscreen.set(enabled)

def set_editor_tool(self, tool_value: str) -> None:
    tool = EditorTool(tool_value)
    self.editor_workspace = self.editor_workspace.with_tool(tool)
    self.editor_active_tool.set(tool.value)
    self._update_editor_help_panel()

def set_editor_tool_scope(self, scope_value: str) -> None:
    scope = ToolScope(scope_value)
    self.editor_workspace = self.editor_workspace.with_scope(scope)
    self.editor_tool_scope.set(scope.value)
```

- [ ] **Step 6: Add UI tests for fullscreen/tool helper methods**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_workspace_state_methods_update_fullscreen_tool_and_scope(self) -> None:
    app = SpriteSheetToolUi(build=False)

    app.set_editor_fullscreen(True)
    app.set_editor_tool("fill")
    app.set_editor_tool_scope("all_frames")

    self.assertTrue(app.editor_workspace.fullscreen)
    self.assertEqual(str(app.editor_fullscreen.get()), "True")
    self.assertEqual(str(app.editor_active_tool.get()), "fill")
    self.assertEqual(str(app.editor_tool_scope.get()), "all_frames")
```

- [ ] **Step 7: Run UI helper tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 1**

Run:

```powershell
git add tools\sprite_editor_workspace.py tools\sprite_sheet_tool_ui.py tests\test_sprite_editor_workspace.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add editor workspace state model"
```

Expected: commit succeeds.

---

### Task 2: Canvas View Model, Checkerboard, Grid, Zoom, Pan, And Status

**Files:**
- Modify: `tools/sprite_editor_workspace.py`
- Modify: `tests/test_sprite_editor_workspace.py`
- Modify: `tools/sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add failing tests for canvas coordinate conversion and zoom/pan**

Append to `tests/test_sprite_editor_workspace.py`:

```python
from PIL import Image

from tools.sprite_editor_workspace import CanvasView, checkerboard_image, canvas_status_text


class SpriteEditorCanvasTests(unittest.TestCase):
    def test_canvas_view_converts_screen_and_sprite_coordinates(self) -> None:
        view = CanvasView(sprite_size=(16, 12), panel_size=(200, 160), zoom=4.0, pan=(20, 12))

        self.assertEqual(view.sprite_to_screen((2, 3)), (28, 24))
        self.assertEqual(view.screen_to_sprite((28, 24)), (2, 3))
        self.assertEqual(view.screen_to_sprite((27, 23)), (1, 2))

    def test_canvas_view_fit_and_zoom_around_cursor_are_stable(self) -> None:
        fitted = CanvasView.fit(sprite_size=(32, 16), panel_size=(320, 200))
        self.assertEqual(fitted.zoom, 8.0)

        zoomed = fitted.zoom_around_cursor((80, 80), factor=2.0)

        self.assertEqual(zoomed.zoom, 16.0)
        self.assertEqual(zoomed.screen_to_sprite((80, 80)), fitted.screen_to_sprite((80, 80)))

    def test_checkerboard_image_and_status_text_are_useful(self) -> None:
        image = checkerboard_image((8, 8), cell_size=2)

        self.assertEqual(image.mode, "RGBA")
        self.assertNotEqual(image.getpixel((0, 0)), image.getpixel((2, 0)))
        self.assertIn("zoom=4.0x", canvas_status_text((3, 4), "#ff0000", 4.0, 1, 2))
```

- [ ] **Step 2: Run canvas tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorCanvasTests -v
```

Expected: FAIL because `CanvasView`, `checkerboard_image`, and `canvas_status_text` do not exist.

- [ ] **Step 3: Implement canvas helpers**

Add to `tools/sprite_editor_workspace.py`:

```python
from PIL import Image


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
        zoom = max(1.0, min(panel_width / sprite_width, panel_height / sprite_height))
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
        next_pan = (
            int(cursor[0] - before[0] * next_zoom),
            int(cursor[1] - before[1] * next_zoom),
        )
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
```

- [ ] **Step 4: Run canvas tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorCanvasTests -v
```

Expected: all canvas tests pass.

- [ ] **Step 5: Wire canvas state and status fields into the UI app**

Modify `tools/sprite_sheet_tool_ui.py` imports to include:

```python
CanvasView, canvas_status_text, checkerboard_image
```

In `SpriteSheetToolUi.__init__`, add:

```python
self.editor_canvas_view = CanvasView(sprite_size=(1, 1), panel_size=(640, 420))
self.editor_cursor = DpgValue("")
self.editor_status = DpgValue("x=- y=- color=#-------- zoom=8.0x layer=1 frame=1")
self.editor_show_grid = DpgValue(True)
```

Add helper:

```python
def _refresh_editor_status(self, cursor: tuple[int, int] | None = None, color_hex: str | None = None) -> None:
    self.editor_status.set(
        canvas_status_text(
            cursor,
            color_hex,
            self.editor_canvas_view.zoom,
            self.editor_workspace.active_layer_index,
            self.editor_workspace.active_frame_index,
        )
    )
```

- [ ] **Step 6: Add UI helper test for status refresh**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_status_uses_canvas_workspace_context(self) -> None:
    app = SpriteSheetToolUi(build=False)

    app._refresh_editor_status((2, 3), "#00ff00")

    self.assertIn("x=2 y=3", str(app.editor_status.get()))
    self.assertIn("#00ff00", str(app.editor_status.get()))
    self.assertIn("zoom=", str(app.editor_status.get()))
```

- [ ] **Step 7: Run UI tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

Run:

```powershell
git add tools\sprite_editor_workspace.py tools\sprite_sheet_tool_ui.py tests\test_sprite_editor_workspace.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add editor canvas view model"
```

Expected: commit succeeds.

---

### Task 3: Mouse Tool Dispatch For Pixel, Fill, Line, Rectangle, Selection, Crop, Pan, And Zoom

**Files:**
- Modify: `tools/sprite_editor_workspace.py`
- Modify: `tests/test_sprite_editor_workspace.py`
- Modify: `tools/sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add failing tests for mouse gesture dispatch**

Append to `tests/test_sprite_editor_workspace.py`:

```python
from PIL import Image

from tools.sprite_editor import SpriteEditSession
from tools.sprite_editor_workspace import MouseGesture, apply_mouse_tool


class SpriteEditorMouseToolTests(unittest.TestCase):
    def test_mouse_pencil_eraser_eyedropper_and_fill_tools(self) -> None:
        session = SpriteEditSession.from_image(Image.new("RGBA", (6, 6), (0, 0, 0, 0)), name="mouse")
        state = EditorWorkspaceState(foreground_color="#ff0000", active_tool=EditorTool.PENCIL)

        result = apply_mouse_tool(session, state, MouseGesture("click", (2, 2)))
        self.assertEqual(session.composite().getpixel((2, 2)), (255, 0, 0, 255))
        self.assertIsNone(result.sampled_color)

        state = state.with_tool(EditorTool.EYEDROPPER)
        result = apply_mouse_tool(session, state, MouseGesture("click", (2, 2)))
        self.assertEqual(result.sampled_color, "#ff0000")

        state = state.with_tool(EditorTool.ERASER)
        apply_mouse_tool(session, state, MouseGesture("drag", (2, 2), (2, 2)))
        self.assertEqual(session.composite().getpixel((2, 2)), (0, 0, 0, 0))

        state = state.with_tool(EditorTool.FILL)
        apply_mouse_tool(session, state, MouseGesture("click", (0, 0)))
        self.assertEqual(session.composite().getpixel((5, 5)), (255, 0, 0, 255))

    def test_mouse_line_rectangle_crop_pan_and_zoom_tools(self) -> None:
        session = SpriteEditSession.from_image(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), name="mouse")
        state = EditorWorkspaceState(foreground_color="#00ff00", active_tool=EditorTool.LINE)

        apply_mouse_tool(session, state, MouseGesture("drag", (0, 0), (3, 0)))
        self.assertEqual(session.composite().getpixel((2, 0)), (0, 255, 0, 255))

        state = state.with_tool(EditorTool.RECT_FILL)
        apply_mouse_tool(session, state, MouseGesture("drag", (1, 1), (2, 2)))
        self.assertEqual(session.composite().getpixel((2, 2)), (0, 255, 0, 255))

        state = state.with_tool(EditorTool.CROP)
        result = apply_mouse_tool(session, state, MouseGesture("drag", (0, 0), (3, 3)))
        self.assertEqual(result.crop_rect, (0, 0, 4, 4))

        state = state.with_tool(EditorTool.PAN)
        result = apply_mouse_tool(session, state, MouseGesture("drag", (4, 4), (7, 8)))
        self.assertEqual(result.pan_delta, (3, 4))

        state = state.with_tool(EditorTool.ZOOM)
        result = apply_mouse_tool(session, state, MouseGesture("wheel", (4, 4), wheel_delta=1))
        self.assertEqual(result.zoom_factor, 1.25)
```

- [ ] **Step 2: Run mouse tool tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorMouseToolTests -v
```

Expected: FAIL because `MouseGesture` and `apply_mouse_tool` do not exist.

- [ ] **Step 3: Implement mouse gesture dispatch**

Add to `tools/sprite_editor_workspace.py`:

```python
from tools.sprite_editor import SpriteEditSession


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
        return MouseToolResult(sampled_color=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}" if color[3] == 255 else f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}{color[3]:02x}")

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
        factor = 1.25 if int(gesture.wheel_delta) >= 0 else 0.8
        return MouseToolResult(zoom_factor=factor)

    return MouseToolResult()
```

- [ ] **Step 4: Run mouse tool tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorMouseToolTests -v
```

Expected: all mouse tool tests pass.

- [ ] **Step 5: Wire UI event-handler wrappers**

In `tools/sprite_sheet_tool_ui.py`, import `MouseGesture` and `apply_mouse_tool`.

Add methods:

```python
def _editor_canvas_sprite_point_from_mouse(self) -> tuple[int, int] | None:
    if dpg is None or not dpg.does_item_exist("editor_canvas"):
        return None
    mouse = dpg.get_mouse_pos(local=False)
    rect_min = dpg.get_item_rect_min("editor_canvas")
    local = (int(mouse[0] - rect_min[0]), int(mouse[1] - rect_min[1]))
    return self.editor_canvas_view.screen_to_sprite(local)

def _apply_editor_mouse_gesture(self, gesture: MouseGesture) -> None:
    if self.editor_session is None:
        self._show_info("Editor", "Load a sprite or open one from Review to begin editing.")
        return
    result = apply_mouse_tool(self.editor_session, self.editor_workspace, gesture)
    if result.sampled_color is not None:
        self.editor_source_color.set(result.sampled_color)
        self.editor_workspace = self.editor_workspace.with_tool(EditorTool.PENCIL)
    if result.crop_rect is not None:
        self.editor_crop_rect.set(",".join(str(part) for part in result.crop_rect))
    if result.selected_region is not None:
        self.editor_workspace = replace(self.editor_workspace, selected_region=result.selected_region)
    if result.pan_delta is not None:
        self.editor_canvas_view = self.editor_canvas_view.panned(result.pan_delta)
    if result.zoom_factor is not None:
        self.editor_canvas_view = self.editor_canvas_view.zoom_around_cursor(gesture.start, result.zoom_factor)
    self._refresh_editor_preview()
    self._refresh_editor_status(gesture.end or gesture.start)
```

If `replace` is not already imported in `tools/sprite_sheet_tool_ui.py`, import it from `dataclasses`.

- [ ] **Step 6: Add UI test for mouse gesture wrapper**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_mouse_gesture_applies_tool_to_loaded_session(self) -> None:
    app = SpriteSheetToolUi(build=False)
    app.editor_session = ui_module.SpriteEditSession.from_image(Image.new("RGBA", (4, 4), (0, 0, 0, 0)), name="sample")
    app.editor_workspace = app.editor_workspace.with_tool(ui_module.EditorTool.PENCIL)
    app.editor_workspace = ui_module.replace(app.editor_workspace, foreground_color="#ff0000")

    app._apply_editor_mouse_gesture(ui_module.MouseGesture("click", (1, 1)))

    self.assertEqual(app.editor_session.composite().getpixel((1, 1)), (255, 0, 0, 255))
```

- [ ] **Step 7: Run targeted UI and workspace tests**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

Run:

```powershell
git add tools\sprite_editor_workspace.py tools\sprite_sheet_tool_ui.py tests\test_sprite_editor_workspace.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add editor mouse tool dispatch"
```

Expected: commit succeeds.

---

### Task 4: Fullscreen Editor Shell And Canvas UI

**Files:**
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add tests for fullscreen layout state and panel visibility decisions**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_fullscreen_visibility_plan_hides_non_editor_panels(self) -> None:
    app = SpriteSheetToolUi(build=False)

    embedded = app.editor_visibility_plan()
    app.set_editor_fullscreen(True)
    fullscreen = app.editor_visibility_plan()

    self.assertTrue(embedded["main_panels"])
    self.assertTrue(embedded["editor_panel"])
    self.assertFalse(fullscreen["main_panels"])
    self.assertTrue(fullscreen["editor_panel"])
    self.assertTrue(fullscreen["timeline_panel"])
```

- [ ] **Step 2: Run UI tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui.SpriteSheetToolUiTests.test_editor_fullscreen_visibility_plan_hides_non_editor_panels -v
```

Expected: FAIL because `editor_visibility_plan` does not exist.

- [ ] **Step 3: Implement visibility planning helper**

Add to `SpriteSheetToolUi`:

```python
def editor_visibility_plan(self) -> dict[str, bool]:
    fullscreen = bool(self.editor_workspace.fullscreen)
    return {
        "main_panels": not fullscreen,
        "editor_panel": True,
        "timeline_panel": fullscreen or self.editor_animation_frames_loaded(),
        "log_panel": not fullscreen,
    }

def editor_animation_frames_loaded(self) -> bool:
    return bool(getattr(self, "editor_animation_frames", []))
```

- [ ] **Step 4: Run visibility test and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui.SpriteSheetToolUiTests.test_editor_fullscreen_visibility_plan_hides_non_editor_panels -v
```

Expected: test passes.

- [ ] **Step 5: Replace `EditorSettingsPanel.build` with a workspace layout**

Modify `EditorSettingsPanel.build` in `tools/sprite_sheet_tool_ui.py` to build:

```python
class EditorSettingsPanel(SpriteToolPanel):
    def build(self) -> None:
        app = self.app
        with dpg.group(horizontal=True):
            app._add_button("Fullscreen Editor", lambda *_args: app.set_editor_fullscreen(not bool(app.editor_workspace.fullscreen)), "editor_fullscreen")
            app._add_button("Load Sprite", app.load_editor_sprite_dialog, "editor_load_sprite")
            app._add_button("Save Package", app.save_editor_package, "editor_save_package")
            app._add_button("Save To Project", app.save_editor_to_project, "editor_save_project")
        with dpg.group(horizontal=True):
            with dpg.child_window(tag="editor_tool_rail", width=130, height=520, border=True):
                app._build_editor_tool_rail()
            with dpg.child_window(tag="editor_canvas", width=520, height=520, border=True):
                app._build_editor_canvas_panel()
            with dpg.child_window(tag="editor_side_panel", width=300, height=520, border=True):
                app._build_editor_side_panel()
        with dpg.child_window(tag="editor_timeline_panel", width=-1, height=130, border=True):
            app._build_editor_timeline_panel()
        dpg.add_text(str(app.editor_status.get()), tag="editor_status_text", wrap=920)
```

Add `TOOLTIP_TEXT` entries for:

```python
"editor_fullscreen": "Expand the Editor into a focused workspace inside the app window.",
"editor_save_project": "Save the current edited sprite or animation frames back into the loaded SpriteCut project outputs.",
"editor_canvas": "Edit pixels with the active tool. Mouse wheel zooms, space-drag pans, and the status bar shows cursor details.",
"editor_tool_scope": "Choose whether an edit affects the active layer, selected region, current frame, selected frames, or all frames.",
```

- [ ] **Step 6: Add panel builder methods**

Add methods to `SpriteSheetToolUi`:

```python
def _build_editor_tool_rail(self) -> None:
    for tool, metadata in EDITOR_TOOLS.items():
        self._add_button(metadata.label, lambda _s=None, _a=None, value=tool.value: self.set_editor_tool(value), f"editor_tool_{tool.value}", width=-1)
    self._add_combo("##editor_tool_scope", self.editor_tool_scope, [scope.value for scope in ToolScope], "editor_tool_scope", width=-1, callback=lambda *_args: self.set_editor_tool_scope(str(self.editor_tool_scope.get())))

def _build_editor_canvas_panel(self) -> None:
    if self.editor_session is None:
        dpg.add_text("Load a sprite or open one from Review to begin editing.", wrap=480)
        return
    self._refresh_editor_preview()

def _build_editor_side_panel(self) -> None:
    dpg.add_text("Layers")
    with dpg.child_window(tag="editor_layers_panel", width=-1, height=130, border=True):
        self._build_editor_layers_panel()
    dpg.add_text("Palette")
    with dpg.child_window(tag="editor_palette_panel", width=-1, height=150, border=True):
        self._build_editor_palette_panel()
    dpg.add_text("Tool Help")
    with dpg.child_window(tag="editor_help_panel", width=-1, height=190, border=True):
        self._build_editor_help_panel()

def _build_editor_timeline_panel(self) -> None:
    dpg.add_text("No animation loaded.", wrap=760)
```

The layer/palette/help methods can initially render the current compact controls and will be expanded in later tasks.

- [ ] **Step 7: Add smoke tests for tooltip coverage**

Extend the existing tooltip coverage test in `tests/test_sprite_sheet_tool_ui.py` to require:

```python
"editor_fullscreen",
"editor_save_project",
"editor_canvas",
"editor_tool_scope",
```

- [ ] **Step 8: Run UI tests and compile check**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui -v
python -m py_compile tools\sprite_sheet_tool_ui.py
```

Expected: tests pass and compile exits 0.

- [ ] **Step 9: Commit Task 4**

Run:

```powershell
git add tools\sprite_sheet_tool_ui.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add fullscreen editor workspace shell"
```

Expected: commit succeeds.

---

### Task 5: Keyboard Shortcuts And Contextual Help

**Files:**
- Modify: `tools/sprite_editor_workspace.py`
- Modify: `tests/test_sprite_editor_workspace.py`
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add failing tests for shortcut command dispatch**

Append to `tests/test_sprite_editor_workspace.py`:

```python
from tools.sprite_editor_workspace import apply_shortcut_action


class SpriteEditorShortcutTests(unittest.TestCase):
    def test_apply_shortcut_action_updates_state_for_tools_and_zoom(self) -> None:
        state = EditorWorkspaceState()

        state, command = apply_shortcut_action(state, "tool:fill")
        self.assertEqual(state.active_tool, EditorTool.FILL)
        self.assertIsNone(command)

        state, command = apply_shortcut_action(state, "command:zoom_in")
        self.assertEqual(state.zoom, 10.0)
        self.assertIsNone(command)

        state, command = apply_shortcut_action(state, "command:save")
        self.assertEqual(command, "save")

    def test_help_text_lists_shortcuts_and_current_scope(self) -> None:
        state = EditorWorkspaceState(active_tool=EditorTool.PENCIL, tool_scope=ToolScope.ALL_FRAMES)

        text = state_help_text(state)

        self.assertIn("Pencil", text)
        self.assertIn("B", text)
        self.assertIn("all_frames", text)
```

- [ ] **Step 2: Run shortcut tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorShortcutTests -v
```

Expected: FAIL because `apply_shortcut_action` and `state_help_text` do not exist.

- [ ] **Step 3: Implement shortcut state updates and help text**

Add to `tools/sprite_editor_workspace.py`:

```python
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
```

- [ ] **Step 4: Run shortcut tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorShortcutTests -v
```

Expected: shortcut tests pass.

- [ ] **Step 5: Wire UI shortcut handler**

In `tools/sprite_sheet_tool_ui.py`, import `apply_shortcut_action`, `shortcut_action_for_key`, and `state_help_text`.

Add:

```python
def handle_editor_shortcut(self, shortcut: str) -> bool:
    action = shortcut_action_for_key(shortcut)
    if action is None:
        return False
    self.editor_workspace, command = apply_shortcut_action(self.editor_workspace, action)
    self.editor_active_tool.set(self.editor_workspace.active_tool.value)
    self._update_editor_help_panel()
    if command == "undo":
        self.undo_editor_edit()
    elif command == "redo":
        self.redo_editor_edit()
    elif command == "save":
        self.save_editor_package()
    elif command == "fit":
        self.editor_canvas_view = CanvasView.fit(self.editor_canvas_view.sprite_size, self.editor_canvas_view.panel_size)
    elif command == "actual_size":
        self.editor_canvas_view = self.editor_canvas_view.zoom_around_cursor((0, 0), 1.0 / max(1.0, self.editor_canvas_view.zoom))
    elif command == "play_pause":
        self.toggle_editor_animation_playback()
    self._refresh_editor_status()
    return True

def _update_editor_help_panel(self) -> None:
    text = state_help_text(self.editor_workspace)
    if dpg is not None and dpg.does_item_exist("editor_help_text"):
        dpg.set_value("editor_help_text", text)
```

- [ ] **Step 6: Add UI shortcut tests**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_shortcut_handler_updates_tool_and_returns_handled_state(self) -> None:
    app = SpriteSheetToolUi(build=False)

    handled = app.handle_editor_shortcut("G")

    self.assertTrue(handled)
    self.assertEqual(str(app.editor_active_tool.get()), "fill")
    self.assertFalse(app.handle_editor_shortcut("unknown"))
```

- [ ] **Step 7: Run targeted tests**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 5**

Run:

```powershell
git add tools\sprite_editor_workspace.py tools\sprite_sheet_tool_ui.py tests\test_sprite_editor_workspace.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add editor shortcuts and contextual help"
```

Expected: commit succeeds.

---

### Task 6: Layer Management Backend And UI Panel

**Files:**
- Modify: `tools/sprite_editor.py`
- Modify: `tests/test_sprite_editor.py`
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add failing backend tests for layer operations**

Append to `tests/test_sprite_editor.py`:

```python
def test_edit_session_layer_management_renames_duplicates_reorders_visibility_and_opacity(self) -> None:
    image = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
    session = SpriteEditSession.from_image(image, name="layers")

    session.add_layer("detail")
    session.rename_layer(1, "details")
    session.duplicate_layer(1, "details_copy")
    session.reorder_layer(2, 0)
    session.set_layer_visibility(1, False)
    session.set_layer_opacity(0, 0.5)
    session.select_layer(0)

    self.assertEqual([layer.name for layer in session.layers], ["details_copy", "base", "details"])
    self.assertEqual(session.active_layer, 0)
    self.assertFalse(session.layers[1].visible)
    self.assertEqual(session.layers[0].opacity, 0.5)

    session.delete_layer(2)
    self.assertEqual(len(session.layers), 2)
```

- [ ] **Step 2: Run backend layer test and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_editor.SpriteEditorTests.test_edit_session_layer_management_renames_duplicates_reorders_visibility_and_opacity -v
```

Expected: FAIL because the layer methods do not exist.

- [ ] **Step 3: Implement layer methods in `SpriteEditSession`**

Add methods inside `SpriteEditSession` in `tools/sprite_editor.py`:

```python
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
```

- [ ] **Step 4: Run backend editor tests**

Run:

```powershell
python -m unittest tests.test_sprite_editor -v
```

Expected: all editor backend tests pass.

- [ ] **Step 5: Add UI helper methods for layer operations**

In `SpriteSheetToolUi.__init__`, add:

```python
self.editor_layer_name = DpgValue("")
self.editor_layer_opacity = DpgValue(1.0)
```

Add methods:

```python
def editor_layer_rows(self) -> list[str]:
    if self.editor_session is None:
        return []
    rows = []
    for index, layer in enumerate(self.editor_session.layers):
        active = "*" if index == self.editor_session.active_layer else " "
        visible = "visible" if layer.visible else "hidden"
        rows.append(f"{active} {index + 1}. {layer.name} {visible} opacity={layer.opacity:.2f}")
    return rows

def select_editor_layer(self, index: int) -> None:
    if self.editor_session is None:
        self._show_info("Layers", "Load a sprite before selecting a layer.")
        return
    self.editor_session.select_layer(index)
    self.editor_workspace = replace(self.editor_workspace, active_layer_index=index)
    self._refresh_editor_preview()

def duplicate_editor_layer(self, *_args: object) -> None:
    if self.editor_session is None:
        self._show_info("Layers", "Load a sprite before duplicating a layer.")
        return
    self.editor_session.duplicate_layer(self.editor_session.active_layer)
    self._refresh_editor_preview()

def delete_editor_layer(self, *_args: object) -> None:
    if self.editor_session is None:
        self._show_info("Layers", "Load a sprite before deleting a layer.")
        return
    self.editor_session.delete_layer(self.editor_session.active_layer)
    self._refresh_editor_preview()
```

- [ ] **Step 6: Add UI tests for layer rows and actions**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_layer_helpers_show_rows_and_duplicate_delete_layers(self) -> None:
    app = SpriteSheetToolUi(build=False)
    app.editor_session = ui_module.SpriteEditSession.from_image(Image.new("RGBA", (4, 4), (0, 0, 0, 0)), name="layers")

    app.duplicate_editor_layer()
    rows = app.editor_layer_rows()

    self.assertEqual(len(rows), 2)
    self.assertIn("base_copy", rows[1])

    app.delete_editor_layer()
    self.assertEqual(len(app.editor_layer_rows()), 1)
```

- [ ] **Step 7: Run editor and UI tests**

Run:

```powershell
python -m unittest tests.test_sprite_editor tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 6**

Run:

```powershell
git add tools\sprite_editor.py tools\sprite_sheet_tool_ui.py tests\test_sprite_editor.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add editor layer management"
```

Expected: commit succeeds.

---

### Task 7: Palette Panel, Scope-Aware Operations, And Variant Preview

**Files:**
- Modify: `tools/sprite_editor_workspace.py`
- Modify: `tests/test_sprite_editor_workspace.py`
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add failing tests for palette state and scoped operation planning**

Append to `tests/test_sprite_editor_workspace.py`:

```python
from tools.sprite_editor_workspace import PaletteOperationPlan, palette_swatch_rows, scoped_frame_indices


class SpriteEditorPaletteTests(unittest.TestCase):
    def test_palette_swatch_rows_include_hex_counts_and_active_marker(self) -> None:
        image = Image.new("RGBA", (2, 1), (255, 0, 0, 255))
        image.putpixel((1, 0), (0, 255, 0, 255))

        rows = palette_swatch_rows(image, active_color="#00ff00")

        self.assertTrue(any("* #00ff00 count=1" in row for row in rows))
        self.assertTrue(any("#ff0000 count=1" in row for row in rows))

    def test_scoped_frame_indices_resolve_current_selected_and_all_frames(self) -> None:
        state = EditorWorkspaceState(active_frame_index=1, selected_frame_indices=(0, 2))

        self.assertEqual(scoped_frame_indices(state.with_scope(ToolScope.CURRENT_FRAME), 4), [1])
        self.assertEqual(scoped_frame_indices(state.with_scope(ToolScope.SELECTED_FRAMES), 4), [0, 2])
        self.assertEqual(scoped_frame_indices(state.with_scope(ToolScope.ALL_FRAMES), 4), [0, 1, 2, 3])

    def test_palette_operation_plan_is_json_ready(self) -> None:
        plan = PaletteOperationPlan("swap", "#ff0000", "#00ff00", tolerance=8, scope=ToolScope.ALL_FRAMES)

        self.assertEqual(plan.as_dict()["operation"], "swap")
        self.assertEqual(plan.as_dict()["scope"], "all_frames")
```

- [ ] **Step 2: Run palette tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorPaletteTests -v
```

Expected: FAIL because palette helpers do not exist.

- [ ] **Step 3: Implement palette helpers**

Add to `tools/sprite_editor_workspace.py`:

```python
from tools.sprite_editor import extract_palette


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
```

- [ ] **Step 4: Run palette tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace.SpriteEditorPaletteTests -v
```

Expected: palette tests pass.

- [ ] **Step 5: Expand UI palette panel and scoped palette actions**

In `tools/sprite_sheet_tool_ui.py`, import `palette_swatch_rows`.

Add:

```python
def editor_palette_rows(self) -> list[str]:
    if self.editor_session is None:
        return []
    return palette_swatch_rows(self.editor_session.composite(), active_color=str(self.editor_source_color.get()))

def _build_editor_palette_panel(self) -> None:
    rows = self.editor_palette_rows()
    if not rows:
        dpg.add_text("Load a sprite to inspect its palette.", wrap=260)
        return
    for row in rows:
        dpg.add_text(row)
    dpg.add_text("Swap")
    with dpg.group(horizontal=True):
        self._add_input_text("##editor_source_color_panel", self.editor_source_color, "editor_source_color", "editor_source_color", width=110)
        self._add_input_text("##editor_target_color_panel", self.editor_target_color, "editor_target_color", "editor_target_color", width=110)
    self._add_button("Apply Swap", self.apply_editor_palette_swap, "editor_swap_colors", width=-1)
```

- [ ] **Step 6: Add UI test for palette rows**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_palette_rows_show_loaded_sprite_colors(self) -> None:
    app = SpriteSheetToolUi(build=False)
    image = Image.new("RGBA", (2, 1), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 255))
    app.editor_session = ui_module.SpriteEditSession.from_image(image, name="palette")

    rows = app.editor_palette_rows()

    self.assertTrue(any("#ff0000" in row for row in rows))
    self.assertTrue(any("#00ff00" in row for row in rows))
```

- [ ] **Step 7: Run targeted tests**

Run:

```powershell
python -m unittest tests.test_sprite_editor_workspace tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 7**

Run:

```powershell
git add tools\sprite_editor_workspace.py tools\sprite_sheet_tool_ui.py tests\test_sprite_editor_workspace.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: add editor palette workspace panel"
```

Expected: commit succeeds.

---

### Task 8: Animation Editor Backend

**Files:**
- Create: `tools/sprite_animation_editor.py`
- Create: `tests/test_sprite_animation_editor.py`

- [ ] **Step 1: Write failing tests for animation frame sessions, playback, normalization, and export**

Create `tests/test_sprite_animation_editor.py`:

```python
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
        self.assertEqual(normalized.getpixel((0, 0)), (0, 0, 0, 0))

    def test_write_applied_animation_writes_frames_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "frame.png"
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(source)
            session = AnimationEditSession.from_frame_refs("idle", [AnimationFrameRef("sprite_001", source, duration=0.2)])

            result = write_applied_animation(session, root / "applied_project" / "animations", frame_size=(8, 8))

            self.assertTrue(Path(result["manifest"]).exists())
            self.assertTrue(Path(result["frames"][0]["path"]).exists())
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["clip"], "idle")
            self.assertEqual(manifest["frames"][0]["sprite"], "sprite_001")
```

- [ ] **Step 2: Run animation tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_animation_editor -v
```

Expected: FAIL because `tools.sprite_animation_editor` does not exist.

- [ ] **Step 3: Implement animation editor backend**

Create `tools/sprite_animation_editor.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from tools.sprite_editor import SpriteEditSession


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
    selected_frames: tuple[int, ...] = ()

    @classmethod
    def from_frame_refs(cls, name: str, frame_refs: list[AnimationFrameRef], fps: int = 12) -> "AnimationEditSession":
        frames = [SpriteEditSession.open(ref.path) for ref in frame_refs]
        return cls(name=name, frames=frames, frame_refs=frame_refs, fps=max(1, int(fps)))


def playback_next_frame(current: int, frame_count: int) -> int:
    if frame_count <= 0:
        return 0
    return (int(current) + 1) % int(frame_count)


def normalize_frame_image(image: Image.Image, frame_size: tuple[int, int], anchor: str = "bottom-center") -> Image.Image:
    source = image.convert("RGBA")
    width, height = max(1, int(frame_size[0])), max(1, int(frame_size[1]))
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if anchor == "center":
        x = (width - source.width) // 2
        y = (height - source.height) // 2
    else:
        x = (width - source.width) // 2
        y = height - source.height
    output.alpha_composite(source, (max(0, x), max(0, y)))
    return output


def write_applied_animation(
    session: AnimationEditSession,
    output_root: Path,
    *,
    frame_size: tuple[int, int] | None = None,
    anchor: str = "bottom-center",
) -> dict[str, Any]:
    clip_dir = output_root / session.name
    clip_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index, frame_session in enumerate(session.frames, start=1):
        image = frame_session.composite()
        if frame_size is not None:
            image = normalize_frame_image(image, frame_size, anchor=anchor)
        path = clip_dir / f"{session.name}_{index:03d}.png"
        image.save(path)
        ref = session.frame_refs[index - 1]
        frames.append({"sprite": ref.sprite_id, "path": str(path), "duration": ref.duration})
    manifest_path = clip_dir / "animation_edit_manifest.json"
    manifest_path.write_text(json.dumps({"clip": session.name, "fps": session.fps, "frames": frames}, indent=2), encoding="utf-8")
    return {"clip": session.name, "manifest": str(manifest_path), "frames": frames}
```

- [ ] **Step 4: Run animation tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_animation_editor -v
```

Expected: all animation tests pass.

- [ ] **Step 5: Commit Task 8**

Run:

```powershell
git add tools\sprite_animation_editor.py tests\test_sprite_animation_editor.py
git commit -m "feat: add animation editor backend"
```

Expected: commit succeeds.

---

### Task 9: Animation Timeline UI And Frame-Scoped Editing

**Files:**
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_animation_editor.py`

- [ ] **Step 1: Add UI tests for loading animation frames from project clips**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_loads_animation_clip_from_current_project(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        frame = root / "frame.png"
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(frame)
        app = SpriteSheetToolUi(build=False)
        app.current_project_path = root / "project.spritecut.json"
        app.current_project = {
            "animation_clips": [
                {
                    "name": "idle",
                    "frame_rate": 12,
                    "frames": [{"sprite": "sprite_001", "source_file": str(frame), "duration": 0.1}],
                }
            ]
        }

        app.load_editor_animation_clip("idle")

        self.assertIsNotNone(app.editor_animation_session)
        self.assertEqual(app.editor_animation_session.name, "idle")
        self.assertEqual(len(app.editor_animation_session.frames), 1)
```

- [ ] **Step 2: Run UI animation test and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui.SpriteSheetToolUiTests.test_editor_loads_animation_clip_from_current_project -v
```

Expected: FAIL because `load_editor_animation_clip` and `editor_animation_session` do not exist.

- [ ] **Step 3: Wire animation session state into the UI**

In `tools/sprite_sheet_tool_ui.py`, import:

```python
from tools.sprite_animation_editor import AnimationEditSession, AnimationFrameRef, playback_next_frame, write_applied_animation
```

Add fallback import in the `except ModuleNotFoundError` block.

In `SpriteSheetToolUi.__init__`, add:

```python
self.editor_animation_session: AnimationEditSession | None = None
self.editor_animation_clip = DpgValue("")
self.editor_animation_playing = False
self.editor_animation_last_tick: float | None = None
self.editor_animation_fps = DpgValue(12)
```

Add:

```python
def load_editor_animation_clip(self, clip_name: str) -> None:
    if not self.current_project:
        self._show_info("Animation", "Load a SpriteCut project before opening an animation clip.")
        return
    clips = self.current_project.get("animation_clips", [])
    clip = next((item for item in clips if isinstance(item, dict) and item.get("name") == clip_name), None) if isinstance(clips, list) else None
    if not isinstance(clip, dict):
        self._show_info("Animation", f"Animation clip not found: {clip_name}")
        return
    frame_refs: list[AnimationFrameRef] = []
    for frame in clip.get("frames", []):
        if not isinstance(frame, dict):
            continue
        path_text = str(frame.get("source_file", ""))
        path = self._resolve_project_path(path_text) if path_text else None
        if path is not None and path.exists():
            frame_refs.append(AnimationFrameRef(str(frame.get("sprite", "")), path, float(frame.get("duration", 0.0833))))
    if not frame_refs:
        self._show_info("Animation", "No readable frames were found for this clip.")
        return
    self.editor_animation_session = AnimationEditSession.from_frame_refs(str(clip_name), frame_refs, fps=int(clip.get("frame_rate", 12)))
    self.editor_animation_clip.set(str(clip_name))
    self.editor_animation_fps.set(self.editor_animation_session.fps)
    self.editor_session = self.editor_animation_session.frames[0]
    self._refresh_editor_preview()
```

- [ ] **Step 4: Run UI animation load test and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui.SpriteSheetToolUiTests.test_editor_loads_animation_clip_from_current_project -v
```

Expected: test passes.

- [ ] **Step 5: Add playback and timeline helpers**

Add to `SpriteSheetToolUi`:

```python
def toggle_editor_animation_playback(self, *_args: object) -> None:
    self.editor_animation_playing = not self.editor_animation_playing
    self.editor_animation_last_tick = None

def select_editor_animation_frame(self, index: int) -> None:
    if self.editor_animation_session is None:
        return
    index = max(0, min(len(self.editor_animation_session.frames) - 1, int(index)))
    self.editor_animation_session.active_frame = index
    self.editor_session = self.editor_animation_session.frames[index]
    self.editor_workspace = replace(self.editor_workspace, active_frame_index=index)
    self._refresh_editor_preview()

def tick_editor_animation(self, now: float | None = None) -> None:
    if not self.editor_animation_playing or self.editor_animation_session is None:
        return
    current_time = time.monotonic() if now is None else float(now)
    if self.editor_animation_last_tick is not None and current_time - self.editor_animation_last_tick < 1.0 / max(1, int(self.editor_animation_fps.get())):
        return
    self.editor_animation_last_tick = current_time
    self.select_editor_animation_frame(playback_next_frame(self.editor_animation_session.active_frame, len(self.editor_animation_session.frames)))
```

- [ ] **Step 6: Add UI playback tests**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_editor_animation_playback_advances_selected_frame(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "one.png"
        second = root / "two.png"
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(first)
        Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(second)
        app = SpriteSheetToolUi(build=False)
        app.editor_animation_session = ui_module.AnimationEditSession.from_frame_refs(
            "idle",
            [ui_module.AnimationFrameRef("one", first), ui_module.AnimationFrameRef("two", second)],
        )
        app.editor_session = app.editor_animation_session.frames[0]

        app.toggle_editor_animation_playback()
        app.tick_editor_animation(now=1.0)

        self.assertEqual(app.editor_animation_session.active_frame, 1)
        self.assertEqual(app.editor_workspace.active_frame_index, 1)
```

- [ ] **Step 7: Run UI tests**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui tests.test_sprite_animation_editor -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 9**

Run:

```powershell
git add tools\sprite_sheet_tool_ui.py tests\test_sprite_sheet_tool_ui.py tests\test_sprite_animation_editor.py
git commit -m "feat: add editor animation timeline"
```

Expected: commit succeeds.

---

### Task 10: Review/Studio Open-In-Editor And Project-Attached Saves

**Files:**
- Modify: `tools/sprite_project.py`
- Modify: `tests/test_sprite_project.py`
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add project helper tests for attaching edited outputs**

Append to `tests/test_sprite_project.py`:

```python
from tools.sprite_project import attach_sprite_edit_output, attach_animation_edit_output


def test_attach_sprite_edit_output_sets_applied_file_and_review_status(self) -> None:
    project = {"sprites": [{"id": "sprite_001", "review_status": "needs_review"}]}

    updated = attach_sprite_edit_output(project, "sprite_001", "applied/sprite_001.png")

    self.assertEqual(updated["sprites"][0]["applied_output_file"], "applied/sprite_001.png")
    self.assertEqual(updated["sprites"][0]["review_status"], "approved")


def test_attach_animation_edit_output_records_clip_manifest(self) -> None:
    project = {"animation_clips": [{"name": "idle"}]}

    updated = attach_animation_edit_output(project, "idle", "applied/animations/idle/animation_edit_manifest.json")

    self.assertEqual(updated["animation_clips"][0]["applied_manifest"], "applied/animations/idle/animation_edit_manifest.json")
```

- [ ] **Step 2: Run project helper tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_project -v
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: Implement project attachment helpers**

Add to `tools/sprite_project.py`:

```python
def attach_sprite_edit_output(project: dict[str, object], sprite_id: str, applied_output_file: str) -> dict[str, object]:
    project = copy.deepcopy(project)
    sprites = project.get("sprites", [])
    if not isinstance(sprites, list):
        raise ValueError("Project sprites must be a list.")
    for sprite in sprites:
        if isinstance(sprite, dict) and sprite.get("id") == sprite_id:
            sprite["applied_output_file"] = applied_output_file
            sprite["review_status"] = "approved"
            flags = sprite.get("review_flags", [])
            sprite["review_flags"] = [flag for flag in flags if flag != "edited"] if isinstance(flags, list) else []
            return project
    raise ValueError(f"Sprite not found: {sprite_id}")


def attach_animation_edit_output(project: dict[str, object], clip_name: str, manifest_path: str) -> dict[str, object]:
    project = copy.deepcopy(project)
    clips = project.get("animation_clips", [])
    if not isinstance(clips, list):
        raise ValueError("Project animation_clips must be a list.")
    for clip in clips:
        if isinstance(clip, dict) and clip.get("name") == clip_name:
            clip["applied_manifest"] = manifest_path
            return project
    raise ValueError(f"Animation clip not found: {clip_name}")
```

If `copy` is not imported in `tools/sprite_project.py`, add `import copy`.

- [ ] **Step 4: Run project tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_project -v
```

Expected: all project tests pass.

- [ ] **Step 5: Add UI open-selected-sprite and save-to-project helpers**

In `tools/sprite_sheet_tool_ui.py`, import the new project helpers.

Add:

```python
def open_selected_review_sprite_in_editor(self, *_args: object) -> None:
    sprite = self._selected_project_sprite()
    if sprite is None:
        self._show_info("Editor", "Select a Review sprite before opening it in the editor.")
        return
    preview = project_sprite_preview_path_text(sprite)
    if not preview:
        self._show_info("Editor", "The selected sprite has no output image to edit.")
        return
    path = self._resolve_project_path(preview)
    if not path.exists():
        self._show_info("Editor", f"Missing sprite image: {path}")
        return
    self.editor_source_sprite_id = str(sprite["id"])
    self.editor_controller._load_editor_sprite_impl(path)
    self.set_editor_fullscreen(True)

def save_editor_to_project(self, *_args: object) -> None:
    if self.current_project is None or self.current_project_path is None:
        self._show_info("Editor", "Load a SpriteCut project before saving editor output back to a project.")
        return
    if self.editor_animation_session is not None:
        output = write_applied_animation(self.editor_animation_session, self.current_project_path.parent / "applied_project" / "animations")
        self.current_project = attach_animation_edit_output(self.current_project, self.editor_animation_session.name, str(output["manifest"]))
        save_project(self.current_project_path, self.current_project)
        self._show_info("Editor", f"Saved edited animation: {output['manifest']}")
        return
    if self.editor_session is None or not getattr(self, "editor_source_sprite_id", ""):
        self._show_info("Editor", "Open a project sprite in the editor before saving back to the project.")
        return
    output_dir = self.current_project_path.parent / "applied_project" / "sprites" / "edited"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{self.editor_source_sprite_id}.png"
    self.editor_session.composite().save(output_path)
    self.current_project = attach_sprite_edit_output(self.current_project, self.editor_source_sprite_id, str(output_path))
    save_project(self.current_project_path, self.current_project)
    self._show_info("Editor", f"Saved edited sprite: {output_path}")
```

In `SpriteSheetToolUi.__init__`, add:

```python
self.editor_source_sprite_id = ""
```

- [ ] **Step 6: Add UI project save tests**

Append to `tests/test_sprite_sheet_tool_ui.py`:

```python
def test_save_editor_to_project_writes_applied_sprite_and_updates_project(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_path = root / "project.spritecut.json"
        app = SpriteSheetToolUi(build=False)
        app.current_project_path = project_path
        app.current_project = {"sprites": [{"id": "sprite_001", "review_status": "needs_review", "review_flags": []}]}
        app.editor_source_sprite_id = "sprite_001"
        app.editor_session = ui_module.SpriteEditSession.from_image(Image.new("RGBA", (4, 4), (255, 0, 0, 255)), name="sprite_001")

        app.save_editor_to_project()

        self.assertTrue((root / "applied_project" / "sprites" / "edited" / "sprite_001.png").exists())
        self.assertEqual(app.current_project["sprites"][0]["review_status"], "approved")
        self.assertTrue(project_path.exists())
```

- [ ] **Step 7: Run project and UI tests**

Run:

```powershell
python -m unittest tests.test_sprite_project tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 10**

Run:

```powershell
git add tools\sprite_project.py tools\sprite_sheet_tool_ui.py tests\test_sprite_project.py tests\test_sprite_sheet_tool_ui.py
git commit -m "feat: save editor outputs back to projects"
```

Expected: commit succeeds.

---

### Task 11: UX Copy, Complete Tooltips, Help Panel, Docs, And Skill Sync

**Files:**
- Modify: `tools/sprite_sheet_tool_ui.py`
- Modify: `tests/test_sprite_sheet_tool_ui.py`
- Modify: `README.md`
- Modify: `docs/sprite_tool_aaa_guide.md`
- Modify: `skills/codex/spritecut-pipeline/references/spritecut-commands.md`
- Modify: `.claude/skills/spritecut-pipeline/references/spritecut-commands.md`

- [ ] **Step 1: Add tests for complete tooltip/help coverage**

Extend `test_tooltip_copy_covers_primary_workflow_controls` in `tests/test_sprite_sheet_tool_ui.py` with these required keys:

```python
"editor_fullscreen",
"editor_canvas",
"editor_tool_scope",
"editor_tool_pencil",
"editor_tool_eraser",
"editor_tool_eyedropper",
"editor_tool_fill",
"editor_tool_line",
"editor_tool_rect_fill",
"editor_tool_rect_outline",
"editor_tool_select_move",
"editor_tool_crop",
"editor_tool_pan",
"editor_tool_zoom",
"editor_layers_panel",
"editor_palette_panel",
"editor_help_panel",
"editor_timeline_panel",
"editor_save_project",
```

Add:

```python
def test_editor_help_panel_text_mentions_tools_shortcuts_and_mouse(self) -> None:
    app = SpriteSheetToolUi(build=False)

    text = app.editor_help_reference_text()

    self.assertIn("Mouse", text)
    self.assertIn("Ctrl+Z", text)
    self.assertIn("Pencil", text)
    self.assertIn("Animation", text)
```

- [ ] **Step 2: Run tooltip/help tests and verify failure**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui -v
```

Expected: FAIL because several tooltip keys and `editor_help_reference_text` do not exist.

- [ ] **Step 3: Add tooltip copy and help reference text**

Add `TOOLTIP_TEXT` entries in `tools/sprite_sheet_tool_ui.py`:

```python
"editor_tool_pencil": "Draw pixel-perfect strokes with the foreground color. Shortcut: B.",
"editor_tool_eraser": "Erase pixels on the active layer to transparent. Shortcut: E.",
"editor_tool_eyedropper": "Pick a visible canvas color into the active color field. Shortcut: I.",
"editor_tool_fill": "Flood-fill connected pixels with the foreground color. Shortcut: G.",
"editor_tool_line": "Drag to draw a straight line. Shortcut: L.",
"editor_tool_rect_fill": "Drag to draw a filled rectangle. Shortcut: R.",
"editor_tool_rect_outline": "Drag to draw a rectangle outline. Shortcut: Shift+R.",
"editor_tool_select_move": "Select pixels or move the selected region. Shortcut: M.",
"editor_tool_crop": "Drag a crop rectangle and apply it to the current sprite or frame. Shortcut: C.",
"editor_tool_pan": "Move around the zoomed canvas without changing pixels. Shortcut: H or space-drag.",
"editor_tool_zoom": "Zoom the canvas around the cursor with mouse wheel or shortcut keys.",
"editor_layers_panel": "Manage layer order, active layer, visibility, opacity, duplication, and deletion.",
"editor_palette_panel": "Inspect colors, pick foreground/background colors, swap palettes, and generate variants.",
"editor_help_panel": "Read current tool directions, shortcuts, and quick-start guidance.",
"editor_timeline_panel": "Preview and edit frames from a loaded character animation clip.",
```

Add method:

```python
def editor_help_reference_text(self) -> str:
    shortcuts = "\n".join(f"{key}: {value}" for key, value in sorted(EDITOR_SHORTCUTS.items()))
    tools = "\n".join(f"{metadata.label}: {metadata.help_text}" for metadata in EDITOR_TOOLS.values())
    return (
        "Quick Start\n"
        "Load a sprite, choose a tool, edit on the canvas, then save a package or save back to the project.\n\n"
        "Mouse\n"
        "Left click edits with the active tool. Drag previews lines, rectangles, crops, and pans. Mouse wheel zooms on the canvas.\n\n"
        "Shortcuts\n"
        f"{shortcuts}\n\n"
        "Tools\n"
        f"{tools}\n\n"
        "Animation\n"
        "Load a project clip, select a frame, play the preview, edit one frame or all frames, then save applied animation output."
    )
```

- [ ] **Step 4: Run tooltip/help tests and verify pass**

Run:

```powershell
python -m unittest tests.test_sprite_sheet_tool_ui -v
```

Expected: all UI tests pass.

- [ ] **Step 5: Update docs after behavior exists**

Update `README.md` Editor section to mention:

```markdown
The `Editor` tab now includes an embedded workspace and a `Fullscreen Editor` mode with mouse tools, keyboard shortcuts, layers, palette controls, animation timeline preview, contextual help, and project-attached saves.
```

Update `docs/sprite_tool_aaa_guide.md` Sprite Editor section to include:

```markdown
Use `Fullscreen Editor` when polishing sprites or character clips. The left rail chooses tools, the center canvas supports zoom/pan/grid editing, the right panels manage layers/palette/help, and the bottom timeline appears for loaded animation clips.
```

Update both skill command references with the same high-level wording. Keep Codex and Claude skill reference files identical.

- [ ] **Step 6: Run skill sync and docs-related tests**

Run:

```powershell
python -m unittest tests.test_agent_skills tests.test_sprite_sheet_tool_ui -v
```

Expected: all tests pass, including skill pack sync.

- [ ] **Step 7: Commit Task 11**

Run:

```powershell
git add tools\sprite_sheet_tool_ui.py tests\test_sprite_sheet_tool_ui.py README.md docs\sprite_tool_aaa_guide.md skills\codex\spritecut-pipeline\references\spritecut-commands.md .claude\skills\spritecut-pipeline\references\spritecut-commands.md
git commit -m "docs: document editor workspace workflow"
```

Expected: commit succeeds.

---

### Task 12: Final Verification, Packaging, And CI Readiness

**Files:**
- All changed files

- [ ] **Step 1: Run full unit suite**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Expected: all tests pass.

- [ ] **Step 2: Run full compile smoke**

Run:

```powershell
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py tools\sprite_mcp_server.py tools\sprite_editor_workspace.py tools\sprite_animation_editor.py
```

Expected: exit code 0.

- [ ] **Step 3: Run packaging smoke on Windows**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\package_sprite_tool.ps1 -OutputDir dist\sprite-sheet-processor-test
```

Expected: command exits 0 and `dist\sprite-sheet-processor-test` contains launchers, tools, requirements, docs, and skills.

- [ ] **Step 4: Inspect git diff and status**

Run:

```powershell
git status --short --branch
git diff --stat HEAD
```

Expected: no untracked generated output folders are staged accidentally. Only intentional source, tests, docs, and skill files are present before final commit.

- [ ] **Step 5: Commit any final verification/doc cleanup**

If Task 12 produced intentional cleanup edits, commit them:

```powershell
git add README.md docs\sprite_tool_aaa_guide.md skills\codex\spritecut-pipeline\references\spritecut-commands.md .claude\skills\spritecut-pipeline\references\spritecut-commands.md tools\sprite_sheet_tool_ui.py tools\sprite_editor.py tools\sprite_editor_workspace.py tools\sprite_animation_editor.py tools\sprite_project.py tests\test_sprite_sheet_tool_ui.py tests\test_sprite_editor.py tests\test_sprite_editor_workspace.py tests\test_sprite_animation_editor.py tests\test_sprite_project.py
git commit -m "chore: finalize editor workspace upgrade"
```

Expected: commit succeeds or there are no changes to commit.

- [ ] **Step 6: Push and watch CI if the user asks to publish**

Run only when the user asks to push:

```powershell
git push origin main
gh run list --repo DocDamage/realspriteeditor-cutter --branch main --limit 5 --json databaseId,displayTitle,status,conclusion,headSha,url,createdAt
$run = gh run list --repo DocDamage/realspriteeditor-cutter --branch main --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $run --repo DocDamage/realspriteeditor-cutter --exit-status
```

Expected: CI passes on Windows and Ubuntu.
