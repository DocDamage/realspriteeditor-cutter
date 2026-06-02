# GitHub Editor Workflow Roadmap Design

## Goal

Make SpriteCut easier to trust, download, and use by improving GitHub automation, exposing more of the existing sprite editor backend in the desktop UI, and adding lightweight workflow conveniences for repeat sessions.

## Scope

This roadmap is split into three milestones that can be shipped independently:

1. GitHub readiness: automated verification, release packaging, and clearer dependency handoff.
2. Editor upgrade: desktop controls for existing editor backend operations such as undo, redo, crop, resize, flip, rotate, and palette variants.
3. Workflow polish: recent project tracking and sample-pack creation helpers for first-run and repeated production use.

## Architecture

The implementation keeps the existing module boundaries. GitHub automation lives under `.github/workflows`. Packaging remains in `tools/package_sprite_tool.ps1`. Editor and workflow UI additions stay in `tools/sprite_sheet_tool_ui.py`, using the existing `SpriteEditSession`, palette, autotile, and project APIs instead of inventing a new editor backend.

## Components

- `.github/workflows/ci.yml`: runs unit tests and compile checks on pushes and pull requests.
- `.github/workflows/release.yml`: builds a downloadable zip bundle through the packaging script when manually triggered.
- `requirements-dev.txt`: records CI/test dependencies that are currently implicit.
- `tools/package_sprite_tool.ps1`: copies launchers, docs, requirements, skills, and tool modules into a release folder.
- `tools/sprite_sheet_tool_ui.py`: adds editor transform controls, palette variant generation, recent project helpers, and sample pack helper actions.
- `tests/test_golden_and_packaging.py`: validates workflow and package files.
- `tests/test_sprite_sheet_tool_ui.py`: validates new helper behavior without requiring Dear PyGUI.

## Error Handling

CI fails fast on test, compile, or packaging errors. Editor actions show the existing UI error/info messages when no sprite is loaded, input fields are malformed, or output folders cannot be written. Recent project helpers silently ignore missing files and normalize duplicate entries so stale history cannot break startup.

## Testing

Tests cover workflow file presence and commands, packaging contents, editor field parsers, editor operation helper behavior, palette variant package generation, recent project persistence, and sample pack creation. The full suite remains the final verification command.

## Rollout

Milestone 1 can ship immediately because it does not alter runtime behavior. Milestones 2 and 3 add UI affordances around already-tested backend functions, so they are low risk when covered by helper tests.
