# Sprite Sheet Processor

Production-oriented tools for cutting packed 2D sprite sheets, reviewing the results, exporting engine metadata, and keeping non-destructive `.spritecut.json` project state.

## Quick Start

Run the desktop UI:

```powershell
python tools\sprite_sheet_tool_ui.py
```

Run the cutter directly:

```powershell
python tools\cut_tileset_sprites.py "G:\path\to\sheets" --out-name _organized_sprites
```

By default the cutter uses `--auto-detect-all`: it samples the input sheets, detects transparent/white/dark backgrounds, keeps `--mode auto`, enables atlas packing, writes Unity/Godot/Unreal exports, and raises animation batches to 12 FPS when the sheets look like animation rows.

List built-in presets:

```powershell
python tools\cut_tileset_sprites.py --list-presets
```

Scale a batch safely:

```powershell
python tools\cut_tileset_sprites.py "G:\path\to\sheets" --workers 4 --max-image-megapixels 80 --resume
```

Process asset packs that contain ZIP files:

```powershell
python tools\cut_tileset_sprites.py "G:\path\to\asset-library" --include-archives --out-name _organized_sprites
```

You can also pass a `.zip` file directly with `--include-archives`. Extracted source sheets are kept under the run output folder in `_extracted_archives` so review/apply workflows can still find the original sheets.

## Built-In Presets

- `pixel_tileset_white_bg`
- `transparent_animation_rows`
- `packed_props_dark_bg`
- `rpgmaker_tiles`

Presets are optional overrides for repeatable studio recipes. Use `--manual-defaults` when you want the literal CLI values instead of the automatic profile.

Each run writes manifests, an HTML report, engine export JSON, and a non-destructive `project.spritecut.json` review file.
The manifest folder also includes `visual_regression.json`, which hashes generated preview images so detection changes can be compared run-to-run.
The manifest folder also includes `visual_qa.html`, a combined before/after review surface for crop sheets, flagged issues, palette-change samples, and autotile variant samples.

After editing a project in the UI Review tab, use `Apply Outputs` to write corrected crops into `applied_project/sprites/...`, emit reviewed engine metadata in `applied_project/exports/...`, and persist `applied_output_file` paths back into the project file.

The UI also includes a `Studio` tab for production handoff. It adds a health score, prioritized review queue, searchable asset browser, taxonomy auto-naming, rerun diffing, collision/pivot/anchor profile generation, trained preset suggestions, upgraded atlas/import planning, and a one-click `Review + Apply` pass.

The `Editor` tab adds sprite-level editing and recoloring:

- Use the embedded workspace or `Fullscreen Editor` mode for mouse tools, keyboard shortcuts, layers, palette controls, animation timeline preview, contextual help, and project-attached saves.
- Load a single sprite into a non-destructive edit session.
- Extract dominant palette colors.
- Swap exact colors, preserve transparency, and save an edit manifest.
- Apply hue-wheel recolors and preview complementary/analogous/triadic/tetradic palettes.
- Generate 16-mask cardinal auto-tile sheets and Unity/Godot/Unreal-ready rule metadata.

The `Editor` tab now includes an embedded workspace and a `Fullscreen Editor` mode with mouse tools, keyboard shortcuts, layers, palette controls, animation timeline preview, contextual help, and project-attached saves.

For IDEs and scripts, call the JSON API:

```powershell
python tools\sprite_ide_api.py --json "{""action"":""palette.extract"",""input"":""G:\path\sprite.png""}"
```

Supported IDE actions are `sprite.edit`, `sprite.batch_edit`, `sprite.save_to_project`, `project.vision_label`, `palette.extract`, `palette.swap`, `palette.hue_shift`, `palette.variants`, and `autotile.generate`.
When using `--request`, relative `input`, `output`, `output_dir`, `package_dir`, `project_path`, and `inputs` paths resolve from the request file's directory.

For semantic object naming and categorization, install the optional vision dependency and run `project.vision_label` after cutting:

```powershell
python -m pip install -r requirements-vision.txt
python tools\sprite_ide_api.py --json "{""action"":""project.vision_label"",""project_path"":""G:\path\_organized_sprites\project.spritecut.json"",""provider"":""openai""}"
```

The OpenAI provider requires `OPENAI_API_KEY`. The Gemini provider, also available as `nano_banana`, requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`. The pass writes `manifest/vision_label_cache.json`, applies confident `display_name` and `category` labels, and leaves uncertain sprites marked for review. Studio health treats missing active-sprite vision labels as the `missing_vision_labels` blocker so batches do not look handoff-ready before the semantic pass runs.

## SpriteCut MCP Server

MCP-aware IDEs and agents can use SpriteCut through a local stdio MCP server instead of writing JSON requests by hand.

Install the optional MCP dependency:

```powershell
python -m pip install -r requirements-mcp.txt
```

Configure your MCP client to launch:

```powershell
python tools\sprite_mcp_server.py
```

The server exposes editor tools (`palette_extract`, `palette_swap`, `palette_hue_shift`, `palette_variants`, `sprite_edit`, `sprite_batch_edit`, `sprite_save_to_project`, `project_vision_label`, `autotile_generate`), setup helpers (`mcp_health_check`, `mcp_client_config`), and production workflow tools (`create_sample_pack`, `process_sheets`, `load_project_summary`, `review_dashboard`, `apply_project_outputs`, `review_and_apply_project`, `generate_import_plans`). Use `include_archives=true` on `process_sheets` for ZIP-heavy asset libraries.

It also gives agents context resources:

- `spritecut://actions`
- `spritecut://commands`
- `spritecut://quality-checklist`
- `spritecut://sample-pack`

And workflow prompts:

- `review_sprite_project`
- `plan_palette_variants`
- `generate_sprite_edit_request`
- `prepare_engine_handoff`

Use `mcp_client_config` to generate a ready-to-copy stdio config object for clients that use JSON-style MCP server configuration. The editor, palette, and autotile MCP tools call the same backend as `tools\sprite_ide_api.py`, so CLI and MCP behavior stay aligned.

## Agent Skills

This repo includes a reusable SpriteCut skill pack for both Codex and Claude:

- Codex: `skills\codex\spritecut-pipeline`
- Claude: `.claude\skills\spritecut-pipeline`

Each skill tells the agent when to use the SpriteCut pipeline, which modules to prefer, how to call the UI/CLI/IDE JSON API, how to handle review handoff, and what verification commands to run. The shared references live inside each skill folder:

- `references\spritecut-commands.md`
- `references\spritecut-quality-checklist.md`

The skill folders also include `assets\sample-pack` with a tiny misaligned sheet plus palette-swap and autotile JSON requests for smoke tests.

Keep the Codex and Claude skill packs mirrored:

```powershell
python tools\sync_spritecut_skills.py --check
python tools\sync_spritecut_skills.py --apply
```

To make the Codex skill available outside this repo, copy it into your global Codex skills folder:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills\spritecut-pipeline"
Copy-Item -Recurse -Force "skills\codex\spritecut-pipeline\*" "$env:USERPROFILE\.codex\skills\spritecut-pipeline"
```

Example `sprite.edit` request:

```json
{
  "action": "sprite.edit",
  "input": "G:/assets/sprite.png",
  "output": "G:/assets/sprite_edited.png",
  "package_dir": "G:/assets/sprite_edit_package",
  "operations": [
    {"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"},
    {"tool": "crop", "rect": [0, 0, 32, 32]},
    {"tool": "resize", "size": [64, 64]}
  ]
}
```

Example `palette.variants` request:

```json
{
  "action": "palette.variants",
  "input": "G:/assets/crate.png",
  "output_dir": "G:/assets/crate_colorways",
  "name": "crate",
  "variants": [
    {"name": "blue", "swaps": {"#ff0000": "#0000ff"}},
    {"name": "green", "swaps": {"#ff0000": "#00ff00"}}
  ]
}
```

This writes one PNG per colorway, a `*_palette_variants.json` manifest, and a `*_palette_variants_contact.png` review sheet.

Example `sprite.batch_edit` request:

```json
{
  "action": "sprite.batch_edit",
  "inputs": ["G:/assets/crate.png", "G:/assets/barrel.png"],
  "output_dir": "G:/assets/batch_edits",
  "operations": [
    {"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"}
  ]
}
```

This writes edited PNGs, `batch_edit_manifest.json`, and `batch_edit_contact.png`.

`Review + Apply` writes the normal corrected crops plus studio metadata:

- `applied_project/studio/review_dashboard.json`
- `applied_project/studio/batch_health.json`
- `applied_project/studio/atlas_upgrade_plan.json`
- `applied_project/studio/trained_preset.json`
- `applied_project/studio/asset_browser_index.json`
- `applied_project/import_plans/unity_importer_settings.json`
- `applied_project/import_plans/godot_import_plan.json`
- `applied_project/import_plans/unreal_paper2d_import_plan.json`

## Verification

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py tools\sprite_mcp_server.py tools\sprite_vision_labeler.py
```
