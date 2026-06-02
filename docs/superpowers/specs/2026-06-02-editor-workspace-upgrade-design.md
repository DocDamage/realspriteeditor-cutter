# Editor Workspace Upgrade Design

## Goal

Turn the existing SpriteCut Editor tab into a user-friendly, full-featured sprite editing workspace while keeping the current app, backend APIs, JSON IDE actions, and MCP tools intact. The upgrade should support both single-sprite pixel editing and character animation/frame editing without becoming a separate application.

## Scope

The editor remains part of `tools/sprite_sheet_tool_ui.py`, but gains a `Fullscreen Editor` workspace mode. Fullscreen mode expands the existing app window and hides non-editor panels so the editor has room for a real canvas, tool rail, layer controls, palette controls, animation timeline, inspector, shortcuts, and help.

The first implementation should be phased. It should improve the current editor without replacing the proven `tools.sprite_editor` backend or breaking existing `sprite.edit`, `palette.*`, and `autotile.generate` workflows.

## Workspace Layout

The Editor tab has two modes:

- Embedded mode: the editor remains inside the current right-side settings tab for quick edits.
- Fullscreen Editor mode: the app hides the normal processing, preview, review, studio, and log panels, leaving a focused editor workspace.

Fullscreen layout:

- Left tool rail: active tool buttons, foreground/background colors, quick actions.
- Center canvas: zoomable sprite canvas with checkerboard transparency, optional pixel grid, pan, fit-to-screen, actual-size, and zoom controls.
- Right panels: layers, palette, tool inspector, and contextual help.
- Bottom timeline: visible when frames or animation clips are loaded.
- Status bar: cursor position, sampled color, zoom level, active layer, active frame, and save state.

## Editing Tools

The first robust tool set should include:

- Pencil
- Eraser
- Eyedropper
- Fill bucket
- Line
- Filled rectangle
- Rectangle outline
- Select/move
- Crop
- Pan
- Zoom
- Palette swap
- Hue shift
- Palette variants
- Flip
- Rotate
- Resize

Each tool should have:

- A stable button/icon state.
- A concise tooltip that explains what the tool does.
- Contextual inspector text explaining mouse usage and key modifiers.
- Keyboard shortcut support.
- Clear error messages when the tool cannot run.

## Mouse And Keyboard Behavior

The editor should support full mouse-driven editing:

- Left click draws, fills, samples, selects, or starts a drag based on the active tool.
- Dragging previews line, rectangle, select, move, crop, and pan operations before committing where appropriate.
- Mouse wheel zooms around the cursor when the cursor is over the canvas.
- Middle mouse or space-drag pans the canvas.
- Eyedropper can sample visible composite colors from the canvas.

Core shortcuts:

- `B`: pencil
- `E`: eraser
- `I`: eyedropper
- `G`: fill bucket
- `L`: line
- `R`: rectangle
- `M`: select/move
- `C`: crop
- `H` or space-drag: pan
- `Ctrl+Z`: undo
- `Ctrl+Y` or `Ctrl+Shift+Z`: redo
- `Ctrl+S`: save package or save back to project
- `+` / `-`: zoom in/out
- `0`: fit to canvas
- `1`: actual size
- Space: play/pause animation when the timeline is focused

The shortcut reference should be visible from the Editor help panel.

## Layers And Palette

Layer controls should expose the existing layered `SpriteEditSession` model:

- Add layer
- Duplicate layer
- Delete layer
- Rename layer
- Toggle visibility
- Adjust opacity
- Reorder layers
- Select active layer

The palette panel should show dominant visible colors, active foreground/background colors, exact hex fields, tolerance controls, and color swatches. Palette operations should work on the active layer, selected region, current frame, or all frames depending on editor state.

## Animation Workflow

Character sprite editing is first-class:

- Load a project animation clip from the current `project.spritecut.json`.
- Show a frame strip with the selected frame.
- Play/pause animation preview.
- Adjust preview FPS.
- Edit one frame, selected frames, or all frames.
- Normalize frames to a shared canvas size.
- Align frames to a shared anchor, defaulting to bottom-center.
- Export edited frames to `applied_project/animations/...`.

The timeline should reuse existing project animation metadata where possible and avoid inventing a second animation format.

## Project Integration

The Review and Studio tabs should be able to open the selected sprite directly in the Editor workspace. The editor supports two save targets:

- Standalone edit package: writes the edited PNG, palette JSON, and operation manifest like the current editor.
- Project-attached edit: writes the edited PNG or edited animation frames into the applied project output and updates project metadata such as `applied_output_file`.

Project-attached saves should preserve the original source art and remain non-destructive.

## Help And Directions

The editor should be understandable by looking at it:

- Every visible control has a useful tooltip.
- The inspector changes when the active tool changes and explains how to use that tool.
- The help panel includes a quick-start guide, shortcut reference, and tool reference.
- Error/info messages should say what happened and what the user can do next.
- Empty states should be specific, for example: "Load a sprite or open one from Review to begin editing."

The app should avoid dense paragraphs in the normal workflow. Longer directions belong in the help panel, not scattered throughout the canvas.

## Data Flow

The UI should continue to call the existing backend operations in `tools.sprite_editor` where possible. New UI-only interaction state, such as canvas zoom, selected tool, selected region, and frame selection, should stay in the UI layer until an edit operation is committed.

Committed edits should go through `SpriteEditSession` so undo/redo, operation manifests, package saves, IDE actions, and MCP behavior remain aligned.

Animation edits should be represented as a small editor-side collection of frame sessions. Saving an animation writes rendered frames and a manifest that maps edited outputs back to project clip/frame metadata.

## Error Handling

The editor should fail softly and explain next steps:

- Missing sprite or project paths show a visible message and keep the workspace open.
- Invalid colors, sizes, or crop rectangles show field-specific errors.
- Unsafe destructive actions, such as deleting a layer with unsaved work, require confirmation.
- Project-attached saves verify the project path is loaded before writing.
- Animation export refuses to overwrite source art and writes only into applied output folders.

## Testing

Tests should cover:

- Editor workspace state helpers and fullscreen mode state transitions.
- Tool selection, shortcut mapping, and contextual help text.
- Canvas coordinate conversion for zoom/pan/grid.
- Mouse operation helpers for pencil, eraser, eyedropper, fill, line, rectangle, select/move, crop, pan, and zoom.
- Layer operations through `SpriteEditSession`.
- Palette panel helpers and palette operation scope.
- Animation frame loading, playback metadata, frame normalization, and applied output writing.
- Project-attached save behavior.
- Existing IDE/MCP editor actions still passing unchanged.

The final verification remains:

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py tools\sprite_mcp_server.py
```

## Phasing

1. Workspace shell and fullscreen mode.
2. Canvas model, zoom, pan, grid, checkerboard, coordinate helpers, and status bar.
3. Mouse tools for pencil, eraser, eyedropper, fill, line, rectangle, select/move, and crop.
4. Keyboard shortcuts and contextual tool help.
5. Layers and palette panels.
6. Animation timeline, playback, frame editing, normalization, and anchor tools.
7. Review/Studio project round-trip save integration.
8. UX polish, complete tooltips, shortcut reference, help panel, and regression tests.

This phasing allows useful improvements to land incrementally while keeping the app usable between steps.
