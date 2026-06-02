# AAA Sprite Tool Guide

This guide describes the production workflow for the Sprite Sheet Processor.

## Workflow

1. Choose a source folder or sheet.
2. Process it with the default `--auto-detect-all` profile.
3. Open `manifest/report.html` for a visual batch review.
4. Open `manifest/visual_qa.html` for before/after crop sheets, flagged issues, palette-change samples, and autotile variant samples.
5. Open `project.spritecut.json` in the Review tab for manual corrections.
6. Approve, reject, rename, recategorize, adjust pivots, split, or merge sprites.
7. Click `Apply Outputs` to regenerate corrected crops into `applied_project/sprites/...` and reviewed exports into `applied_project/exports/...`.
8. Open the `Studio` tab for health, queue triage, taxonomy naming, asset search, preset training, profiles, and import planning.
9. Use the `Editor` tab for targeted palette swaps, hue-wheel recolors, edit-package saves, and auto-tile generation.
10. Click `Review + Apply` for the full studio pass, then use the applied crops and engine/import-plan JSON for Unity, Godot, or Unreal handoff.

## Auto Detection

The default run samples source sheets before processing. It infers transparent, white, or dark-background handling; keeps sheet mode automatic; enables atlas packing; writes Unity, Godot, and Unreal export JSON; chooses safer worker counts for batches; and uses 12 FPS when sheets look like animation rows.
Use built-in presets or `--manual-defaults` only when a batch needs a fixed studio recipe.

## Review Signals

The tool writes confidence and review flags for every sprite. Sprites with flags such as `touches_edge`, `tiny_component`, `transparent_heavy`, `odd_aspect`, or `large_region` should be inspected before engine import.
Rejected sprites are skipped by `Apply Outputs`; approved and needs-review sprites are cropped from the original source sheet using the current project bbox, name, and category.
Manual split and merge operations are undoable/redone as full sprite-list edits, so review sessions can recover from structural changes without reprocessing the source sheet.
If a reviewed bbox reaches beyond the source image, `Apply Outputs` clamps it to the image bounds and adds `bbox_clamped` to the sprite flags.

## Studio Tab

The `Studio` tab is the production control surface:

- `Dashboard` shows a batch health score, status counts, and current review queue size.
- `Review Queue` prioritizes sprites with `needs_review`, low confidence, severe flags, or duplicate names.
- `Asset Browser` searches by name, category, source sheet, status, kind, or review flags.
- `Auto Name` applies taxonomy rules such as `{category}_{source_sheet}_{index:03d}` to active sprites.
- `Diff Project` compares the loaded project against another `.spritecut.json` and writes `studio_diff.json`.
- `Profiles` generates collision, pivot, anchor, atlas, and engine import metadata.
- `Train Preset` writes `trained_spritecut_preset.json` beside the loaded project using the current project settings and review corrections.
- `Review + Apply` runs auto naming, profile generation, corrected crop rendering, health/dashboard export, trained preset export, asset browser indexing, and Unity/Godot/Unreal import-plan export in one pass.

The studio pass writes:

- `applied_project/studio/review_dashboard.json`
- `applied_project/studio/batch_health.json`
- `applied_project/studio/atlas_upgrade_plan.json`
- `applied_project/studio/trained_preset.json`
- `applied_project/studio/asset_browser_index.json`
- `applied_project/import_plans/unity_importer_settings.json`
- `applied_project/import_plans/godot_import_plan.json`
- `applied_project/import_plans/unreal_paper2d_import_plan.json`

## Sprite Editor

The `Editor` tab is for single-sprite polish after cutting or review:

- Load one PNG/JPG/WebP sprite into a layered edit session.
- Inspect the dominant visible palette.
- Swap exact colors with transparency preserved.
- Apply hue-wheel recolors by degree.
- Preview complementary, analogous, triadic, and tetradic color suggestions.
- Save an edit package with the edited PNG, palette JSON, and operation manifest.
- Generate a 16-mask cardinal auto-tile package from the current sprite.

The editor backend also supports pixel drawing, lines, rectangles, flood fill, erasing, color replacement, hue shift, crop, resize, horizontal/vertical flip, 90-degree rotation, undo, redo, and layered compositing through `tools.sprite_editor`.

## Auto-Tiles

`tools.autotile_tools` can turn a tile into a 16-variant cardinal bitmask package. Bit values are:

- north = 1
- east = 2
- south = 4
- west = 8

The generated package includes a 4x4 PNG sheet and JSON rules that are suitable for Unity RuleTile-style handoff, Godot TileSet terrain/cardinal metadata, or Unreal Paper2D import notes.

## IDE API

External editors, build scripts, and IDE tasks can call:

```powershell
python tools\sprite_ide_api.py --request request.json
```

Example request:

```json
{
  "action": "palette.swap",
  "input": "G:/assets/sprite.png",
  "output": "G:/assets/sprite_blue.png",
  "swaps": {
    "#ff0000": "#0000ff"
  }
}
```

Supported actions:

- `sprite.edit`
- `sprite.batch_edit`
- `palette.extract`
- `palette.swap`
- `palette.hue_shift`
- `palette.variants`
- `autotile.generate`

`sprite.edit` accepts an `operations` list with JSON-ready tools such as `add_layer`, `draw_pixel`, `draw_line`, `fill_rect`, `erase_rect`, `flood_fill`, `replace_color`, `hue_shift`, `crop`, `resize`, `flip`, and `rotate_90`.
`sprite.batch_edit` applies the same operation list to many input files and writes edited PNGs, a manifest, and `batch_edit_contact.png`.
`palette.variants` writes named colorway PNGs, a palette-variant manifest, and a contact-sheet PNG from one source sprite.

## Animation Review

Animation rows generate `manifest/animation_clips.json`, engine clip metadata, HTML timeline strips, and playback in the UI Review tab. Use a consistent FPS per batch through `--animation-fps`.

## Golden Fixtures

Use `tools/golden_sprite_fixtures.py` helpers to create repeatable synthetic packs and compare generated summaries against expected counts. This is the regression safety net for detection tuning.

## Scaling

Use `--workers` for batch throughput and `--max-image-megapixels` as a memory guard for oversized sheets. Use `--on-error skip` for production batches where one bad sheet should not stop the whole run.
Use `--resume` to reuse an existing output folder and skip source sheets already represented in the manifest.
Use `--include-archives` when source folders contain `.zip` asset packs, or when processing a `.zip` file directly. Extracted images are kept in `_extracted_archives` inside the run output folder.
When scanning a folder, both the CLI and UI skip prior SpriteCut output trees identified by `project.spritecut.json` or `manifest/sprites.json`, including custom-named output folders.

## Visual Regression

Every run writes `manifest/visual_regression.json` with SHA-256 hashes for generated preview PNGs. Keep these files with golden packs or review builds to spot detection changes after threshold, preset, or algorithm edits.

## Visual QA

Every run writes `manifest/visual_qa.html` and `manifest/visual_qa.json`. Use the HTML report to inspect before/after crop sheets, flagged crop issues, hue-shift palette samples, and generated 16-mask autotile samples together before handoff.
