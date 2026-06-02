# SpriteCut Commands

Use these examples when driving SpriteCut from an agent, IDE task, terminal, or automation script.

## Contents

- Launch And Cutting
- Review And Handoff
- IDE JSON API
- Skill Sync And Install
- Sample Pack
- Editor Operations
- Troubleshooting
- Verification

## Launch And Cutting

Launch the desktop UI:

```powershell
python tools\sprite_sheet_tool_ui.py
```

Cut a folder or single image with automatic detection:

```powershell
python tools\cut_tileset_sprites.py "G:\path\to\sheets" --out-name _organized_sprites --auto-detect-all
```

List repeatable studio presets:

```powershell
python tools\cut_tileset_sprites.py --list-presets
```

Scale a large batch with resume support:

```powershell
python tools\cut_tileset_sprites.py "G:\path\to\sheets" --workers 4 --max-image-megapixels 80 --resume
```

Use manual mode only when the user wants fixed settings:

```powershell
python tools\cut_tileset_sprites.py "G:\path\to\sheets" --manual-defaults --mode tileset --out-name _manual_sprites
```

## Review And Handoff

1. Inspect `manifest\report.html`, `manifest\manifest.json`, and `project.spritecut.json`.
2. Review low-confidence entries, clipped boxes, tiny components, manual splits, and duplicate names.
3. Apply final outputs with `Apply Outputs` or `Review + Apply`.
4. Hand off `applied_project\sprites`, `applied_project\exports`, `applied_project\studio`, and `applied_project\import_plans`.
5. Open `manifest\visual_qa.html` for before/after crop sheets, flagged crop issues, palette-change samples, and autotile variant samples in one report.

## IDE JSON API

Prefer file-based requests on Windows because inline JSON quoting is easy to break:

```powershell
python tools\sprite_ide_api.py --request request.json
```

Relative `input`, `output`, `output_dir`, `package_dir`, and `inputs` paths in a request file resolve from that request file's directory.

Short inline requests are fine for simple calls:

```powershell
python tools\sprite_ide_api.py --json "{""action"":""palette.extract"",""input"":""G:\assets\sprite.png"",""max_colors"":16}"
```

The API also accepts JSON from stdin:

```powershell
Get-Content request.json | python tools\sprite_ide_api.py
```

Successful calls print JSON to stdout with `"ok": true`. Failures print JSON to stderr, return exit code `1`, and include `"ok": false`.

```json
{
  "ok": false,
  "error": "ValueError: Missing required command field: input"
}
```

### palette.extract

Use before palette swaps to inspect actual colors and alpha handling.

```json
{
  "action": "palette.extract",
  "input": "G:/assets/crate.png",
  "max_colors": 16,
  "output": "G:/assets/crate_palette.json"
}
```

### palette.swap

Use for one exact-color recolor output. Add `tolerance` only when the source has antialiasing or color drift.

```json
{
  "action": "palette.swap",
  "input": "G:/assets/crate.png",
  "output": "G:/assets/crate_blue.png",
  "tolerance": 0,
  "swaps": {
    "#ff0000": "#0000ff",
    "#ffaa00": "#ffd966"
  }
}
```

### palette.hue_shift

Use for color-wheel style recolors while preserving alpha.

```json
{
  "action": "palette.hue_shift",
  "input": "G:/assets/crate.png",
  "output": "G:/assets/crate_shifted.png",
  "degrees": 120,
  "saturation": 1.0,
  "value": 1.0
}
```

### palette.variants

Use for multiple named colorways from one source sprite. Variants may use exact swaps, hue shifts, or both.

```json
{
  "action": "palette.variants",
  "input": "G:/assets/crate.png",
  "output_dir": "G:/assets/crate_colorways",
  "name": "crate",
  "variants": [
    {"name": "blue", "swaps": {"#ff0000": "#0000ff"}},
    {"name": "warm_shift", "hue_shift": 35, "saturation": 1.05, "value": 1.0}
  ]
}
```

This writes one PNG per variant, a variants manifest, and a contact sheet.

### sprite.edit

Use for one input sprite and one output sprite.

```json
{
  "action": "sprite.edit",
  "input": "G:/assets/crate.png",
  "output": "G:/assets/crate_edited.png",
  "package_dir": "G:/assets/crate_edit_package",
  "operations": [
    {"tool": "replace_color", "source": "#ff0000", "target": "#0000ff"},
    {"tool": "crop", "rect": [0, 0, 32, 32]},
    {"tool": "resize", "size": [64, 64]}
  ]
}
```

### sprite.batch_edit

Use when the same edit pipeline should run across many sprites.

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

### autotile.generate

Use to turn a tile into a 16-variant cardinal bitmask sheet and engine handoff metadata.

```json
{
  "action": "autotile.generate",
  "input": "G:/assets/floor_tile.png",
  "output_dir": "G:/assets/floor_autotile",
  "name": "floor",
  "engine": "godot"
}
```

Bit values are north `1`, east `2`, south `4`, and west `8`.

## Skill Sync And Install

Check that the Codex and Claude skill packs match:

```powershell
python tools\sync_spritecut_skills.py --check
```

Mirror the canonical Codex pack into the Claude project skill:

```powershell
python tools\sync_spritecut_skills.py --apply
```

Install the Codex skill globally for other repos:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills\spritecut-pipeline"
Copy-Item -Recurse -Force "skills\codex\spritecut-pipeline\*" "$env:USERPROFILE\.codex\skills\spritecut-pipeline"
```

Claude project discovery uses `.claude\skills\spritecut-pipeline\SKILL.md` from this repo.

## Sample Pack

Use `assets\sample-pack` for safe smoke tests before trying commands on user art:

- `misaligned_sheet.png`
- `palette_swap_request.json`
- `autotile_request.json`

From the sample-pack folder:

```powershell
python ..\..\..\..\tools\sprite_ide_api.py --request palette_swap_request.json
python ..\..\..\..\tools\sprite_ide_api.py --request autotile_request.json
```

## Editor Operations

Supported `sprite.edit` and `sprite.batch_edit` operations:

- `add_layer`: `name`, `visible`, `opacity`
- `draw_pixel`: `x`, `y`, `color`
- `draw_line`: `start`, `end`, `color`, `width`
- `fill_rect`: `rect`, `color`
- `erase_rect`: `rect`
- `flood_fill`: `point`, `color`, `tolerance`
- `replace_color`: `source`, `target`, `tolerance`
- `hue_shift`: `degrees`, `saturation`, `value`
- `crop`: `rect`
- `resize`: `size`
- `flip`: `axis` as `horizontal`, `vertical`, `x`, or `y`
- `rotate_90`: `clockwise`

## Troubleshooting

- Missing `action` or required path fields returns `ok": false` and exit code `1`.
- Empty `swaps`, empty `inputs`, or non-list `operations` are rejected.
- If PowerShell mangles quotes, write a `request.json` file and call `--request`.
- If sprites look clipped, inspect `project.spritecut.json` and review `touches_edge` or `bbox_clamped` entries.
- If recolors miss pixels, extract the palette first and consider a small `tolerance`.

## Verification

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile tools\cut_tileset_sprites.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py
python tools\sync_spritecut_skills.py --check
python tools\sprite_sheet_tool_ui.py --help
python tools\sprite_ide_api.py --help
```
