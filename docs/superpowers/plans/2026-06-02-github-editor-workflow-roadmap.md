# GitHub Editor Workflow Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GitHub verification/release automation, expose existing sprite editor operations in the UI, and add lightweight recent-project/sample workflow helpers.

**Architecture:** Keep automation, packaging, editor actions, and workflow helpers in their existing ownership areas. Add testable pure helpers around UI behavior so most coverage runs without Dear PyGUI.

**Tech Stack:** Python unittest, Pillow, NumPy, Dear PyGUI optional UI runtime, PowerShell packaging, GitHub Actions.

---

### Task 1: GitHub Automation And Packaging

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `requirements-dev.txt`
- Modify: `tools/package_sprite_tool.ps1`
- Test: `tests/test_golden_and_packaging.py`

- [ ] **Step 1: Add tests for workflow and package contents**

Add tests that assert CI/release workflows exist, include the unittest/compile/package commands, and packaging copies requirements and skills.

- [ ] **Step 2: Run packaging tests and verify failure**

Run: `python -m unittest tests.test_golden_and_packaging -v`

Expected: failure because workflows and package copies do not exist yet.

- [ ] **Step 3: Add workflow files, dev requirements, and package copies**

Create the workflow YAML files, record `Pillow` and `numpy` in `requirements-dev.txt`, and update the packaging script to include requirement files, skills, and root UI entrypoint.

- [ ] **Step 4: Run packaging tests and verify pass**

Run: `python -m unittest tests.test_golden_and_packaging -v`

Expected: all tests pass.

### Task 2: Editor Operation Controls

**Files:**
- Modify: `tools/sprite_sheet_tool_ui.py`
- Test: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add tests for editor operation helper parsing and behavior**

Add tests for crop/resize text parsing, undo/redo, flip/rotate dispatch, and palette variant package generation.

- [ ] **Step 2: Run UI helper tests and verify failure**

Run: `python -m unittest tests.test_sprite_sheet_tool_ui -v`

Expected: failure because the helpers do not exist yet.

- [ ] **Step 3: Implement editor helpers and wire UI buttons**

Add DpgValue fields, parser helpers, buttons for undo/redo/crop/resize/flip/rotate, and palette variant generation using the existing editor backend.

- [ ] **Step 4: Run UI helper tests and verify pass**

Run: `python -m unittest tests.test_sprite_sheet_tool_ui -v`

Expected: all tests pass.

### Task 3: Recent Projects And Sample Pack Helpers

**Files:**
- Modify: `tools/sprite_sheet_tool_ui.py`
- Test: `tests/test_sprite_sheet_tool_ui.py`

- [ ] **Step 1: Add tests for recent-project persistence and sample-pack creation**

Add tests for deduplicating recent project paths, dropping missing paths when loading, and creating a sample pack through the golden fixture helper.

- [ ] **Step 2: Run UI helper tests and verify failure**

Run: `python -m unittest tests.test_sprite_sheet_tool_ui -v`

Expected: failure because recent-project and sample helper functions do not exist yet.

- [ ] **Step 3: Implement workflow helpers and light UI wiring**

Add recent-project JSON helpers, save loaded projects to recent history, and expose a sample pack directory action.

- [ ] **Step 4: Run UI helper tests and verify pass**

Run: `python -m unittest tests.test_sprite_sheet_tool_ui -v`

Expected: all tests pass.

### Task 4: Full Verification

**Files:**
- All changed files

- [ ] **Step 1: Run full unit suite**

Run: `python -m unittest discover -s tests -p "test_*.py"`

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

Run: `python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py`

Expected: exit code 0.
