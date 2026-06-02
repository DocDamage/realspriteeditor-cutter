# SpriteCut Quality Checklist

Use this checklist before production handoff, large batches, scripted edit runs, or any claim that SpriteCut output is ready.

## Input Safety

- Confirm the source path exists and points to the intended image or folder.
- Do not overwrite source art.
- Choose a clear output folder name, usually `_organized_sprites`, `_reviewed_sprites`, or a user-provided batch name.
- For unknown, abnormally aligned, or misaligned sprite sheets, start with `--auto-detect-all`.
- Use `--manual-defaults` only when the user asks for fixed parameters or a preset recipe.

## Cutting And Detection

- Inspect `manifest\report.html`, `manifest\manifest.json`, and `project.spritecut.json`.
- Review every low-confidence crop before handoff.
- Run `project.vision_label` for semantic object names and categories; `missing_vision_labels` is a handoff blocker for active sprites.
- Check `needs_review`, `touches_edge`, `tiny_component`, `bbox_clamped`, `manual_split`, and duplicate-name cases.
- For large folders, use `--workers`, `--max-image-megapixels`, and `--resume` instead of restarting from scratch.
- Keep atlas and engine export metadata beside the sprites so output can be traced back to the run.
- Open `manifest\visual_qa.html` to compare before/after crop sheets, flagged crop issues, palette-change samples, and autotile variant samples in one place.

## Editing And Palette

- Run `palette.extract` before broad palette swaps or color-wheel variants.
- Preserve transparency unless the user explicitly asks for a flattened background.
- Use `tolerance` sparingly; exact color swaps are safer for pixel art.
- For variant packs, keep the generated manifest and contact sheet.
- For batch edits, inspect `batch_edit_manifest.json` and `batch_edit_contact.png`.

## Autotiles

- Use `autotile.generate` for the IDE API or `tools.autotile_tools.write_autotile_package` from Python.
- Confirm the output is a 16-mask cardinal set before engine handoff.
- Remember the bit order: north `1`, east `2`, south `4`, west `8`.
- Treat generated autotiles as a starting point when the source tile is not visually seamless.

## Handoff Contract

- Use `Review + Apply` for studio-grade output.
- Hand off `applied_project\sprites`, `applied_project\exports`, `applied_project\studio`, and `applied_project\import_plans`.
- Confirm `applied_project\import_plans` includes the engine plans the user needs.
- Keep reviewed manifests with the final sprites.
- Do not hide low-confidence or manually adjusted sprites from the user.
- Keep the Codex and Claude packs mirrored with `python tools\sync_spritecut_skills.py --check`.
- For global Codex use, copy `skills\codex\spritecut-pipeline` into `$env:USERPROFILE\.codex\skills\spritecut-pipeline`.

## Verification

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py tools\sprite_mcp_server.py tools\sprite_vision_labeler.py
python tools\sync_spritecut_skills.py --check
python tools\sprite_sheet_tool_ui.py --help
python tools\sprite_ide_api.py --help
```
