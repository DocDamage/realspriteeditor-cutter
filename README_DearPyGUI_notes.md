# Dear PyGUI UI conversion notes

This package replaces the Tkinter desktop wrapper with a Dear PyGUI implementation.

## Files

- `tools/sprite_sheet_tool_ui.py` — full Dear PyGUI replacement for the existing Tkinter UI file.
- `requirements-ui.txt` — UI-only dependency addition for Dear PyGUI.

## Apply

From the repository root:

```powershell
Copy-Item -Force .\tools\sprite_sheet_tool_ui.py .\tools\sprite_sheet_tool_ui.py.bak
Copy-Item -Force <converted-package>\tools\sprite_sheet_tool_ui.py .\tools\sprite_sheet_tool_ui.py
pip install -r <converted-package>\requirements-ui.txt
```

Or install the dependency directly:

```powershell
pip install dearpygui
```

## Verify

```powershell
python -m py_compile tools\sprite_sheet_tool_ui.py
python tools\sprite_sheet_tool_ui.py --help
python -m unittest discover -s tests -p "test_*.py"
```

## Conversion summary

- Removed all `tkinter`, `ttk`, and `ImageTk` usage from the UI file.
- Added Dear PyGUI context, viewport, tab layout, native file dialogs, native tooltips, selectable lists, drawlist-based review canvas, texture-backed image previews, modal messages, and a Dear PyGUI render-loop log/animation tick.
- Preserved the existing cutter command builder, preset serialization, detection preview helpers, project review helpers, studio helpers, editor helpers, and public entry point.
- Kept helper imports usable even when Dear PyGUI is not installed, so non-GUI unit tests can still import helper functions.
