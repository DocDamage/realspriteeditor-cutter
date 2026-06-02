@echo off
setlocal
cd /d "%~dp0"
python tools\sprite_sheet_tool_ui.py %*
if errorlevel 1 pause
