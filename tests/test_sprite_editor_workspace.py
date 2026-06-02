from __future__ import annotations

import unittest

from PIL import Image

from tools.sprite_editor import SpriteEditSession
from tools.sprite_editor_workspace import (
    EDITOR_SHORTCUTS,
    EDITOR_TOOLS,
    CanvasView,
    EditorTool,
    EditorWorkspaceState,
    MouseGesture,
    PaletteOperationPlan,
    ToolScope,
    apply_mouse_tool,
    apply_shortcut_action,
    canvas_status_text,
    checkerboard_image,
    palette_swatch_rows,
    scoped_frame_indices,
    shortcut_action_for_key,
    state_help_text,
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
        required = set(EditorTool)

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

        state = state.with_tool(EditorTool.FILL).with_fullscreen(True).with_scope(ToolScope.ALL_FRAMES)

        self.assertEqual(state.active_tool, EditorTool.FILL)
        self.assertTrue(state.fullscreen)
        self.assertEqual(state.tool_scope, ToolScope.ALL_FRAMES)
        self.assertEqual(state.selected_frame_indices, (0, 2))


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


if __name__ == "__main__":
    unittest.main()
