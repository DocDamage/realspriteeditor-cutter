---
name: spritecut-pipeline
description: "Use when working on SpriteCut or this repository's 2D asset pipeline: cutting abnormally aligned or misaligned sprite sheets and tilesets, auto-detecting packed sprites, naming and organizing outputs, review/apply handoff, palette extraction/swaps/color-wheel recolors, sprite editor workflows, autotile generation, IDE callable JSON requests, or Unity/Godot/Unreal exports."
---

# SpriteCut Pipeline

## Operating Rules

Use this skill to cut, review, edit, recolor, autotile, and export 2D sprite assets with this repository's SpriteCut tooling.

1. Inspect the repo and the user's source path before changing behavior.
2. Preserve source art. Write generated files to named output folders.
3. Prefer project files, manifests, contact sheets, and review dashboards over silent one-off output.
4. For unknown, abnormally aligned, or misaligned sprite sheets, start with `--auto-detect-all`.
5. For code changes, add or update focused tests first, run the targeted test, implement, then verify.

## Tool Map

- `tools/cut_tileset_sprites.py`: detection, cutting, atlases, manifests, project files, and engine exports.
- `tools/sprite_project.py`: non-destructive project review and apply-output work.
- `tools/sprite_studio.py`: dashboards, health, taxonomy, import plans, collision/pivot profiles, diffing, and `Review + Apply`.
- `tools/sprite_editor.py`: single-sprite edits, palette operations, variants, batch edits, and contact sheets.
- `tools/autotile_tools.py`: 16-mask cardinal autotiles.
- `tools/sprite_ide_api.py`: IDE callable JSON workflows.

## Choose The Surface

- For a human desktop workflow:
  ```powershell
  python tools\sprite_sheet_tool_ui.py
  ```
- For cutting a folder or image directly:
  ```powershell
  python tools\cut_tileset_sprites.py "G:\path\to\sheets" --out-name _organized_sprites
  ```
- For IDEs, scripts, batch recolors, edit pipelines, and autotile jobs:
  ```powershell
  python tools\sprite_ide_api.py --request request.json
  ```

Read `references/spritecut-commands.md` when creating JSON requests, choosing CLI flags, or troubleshooting command failures.
Read `references/spritecut-quality-checklist.md` before large batches, destructive-looking edits, handoff packaging, or any task that will claim production readiness.
Use `assets/sample-pack` for safe smoke tests before trying commands on user art.
Run `python tools\sync_spritecut_skills.py --check` after skill edits; run `python tools\sync_spritecut_skills.py --apply` to mirror the Codex pack into `.claude/skills/spritecut-pipeline`.

## Production Workflow

1. Process sources with `--auto-detect-all` unless the user asks for fixed manual settings.
2. Open `manifest/report.html`, `manifest/manifest.json`, and `project.spritecut.json`.
3. Open `manifest/visual_qa.html` for before/after crop sheets, flagged crop issues, palette-change samples, and autotile samples.
4. Review `low_confidence`, `needs_review`, `touches_edge`, `tiny_component`, `bbox_clamped`, `manual_split`, and duplicate-name cases.
5. Apply corrections with `Apply Outputs` or `Review + Apply`.
6. Use `applied_project/sprites`, `applied_project/exports`, `applied_project/studio`, and `applied_project/import_plans` for handoff.

## Editing, Palette, And Autotiles

- Use `palette.extract` before broad recolors so the actual colors are known.
- Use `palette.swap` for exact color replacement and `palette.hue_shift` for wheel-style recolors.
- Use `palette.variants` for multiple named colorways; keep the generated manifest and contact sheet.
- Use `sprite.edit` or `sprite.batch_edit` for scripted pixel edits, crops, resizes, flips, rotations, color replacement, and hue shifts.
- Use `autotile.generate` or `tools.autotile_tools.write_autotile_package` to create 16-variant cardinal bitmask sheets with Unity, Godot, Unreal, or generic rule metadata.

Autotile bit values are north `1`, east `2`, south `4`, and west `8`.

## Safety

- Do not copy Aseprite source code or assets. Use Aseprite only as workflow inspiration unless the user provides separately licensed material.
- Preserve transparency unless the user explicitly asks to flatten backgrounds.
- Do not overwrite source art or reviewed outputs without explicit user direction.
- Do not hide low-confidence, clipped, tiny, or manually split sprites; surface them for review.
- Avoid destructive git or filesystem operations.

## Verification

Before claiming success, run relevant targeted tests plus the full suite when behavior changed:

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py
python tools\sync_spritecut_skills.py --check
python tools\sprite_sheet_tool_ui.py --help
python tools\sprite_ide_api.py --help
```
