# SpriteCut MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local stdio MCP server that exposes SpriteCut IDE JSON API actions, agent resources/prompts, setup helpers, and production workflow tools.

**Architecture:** Keep `tools/sprite_ide_api.py` as the behavior source of truth. Add a thin, testable `tools/sprite_mcp_server.py` wrapper with lazy MCP SDK imports so the rest of the project remains usable without optional MCP dependencies.

**Tech Stack:** Python unittest, Pillow, optional official MCP Python SDK (`mcp[cli]`), stdio MCP transport.

---

### Task 1: MCP Wrapper Functions

**Files:**
- Create: `tests/test_sprite_mcp_server.py`
- Create: `tools/sprite_mcp_server.py`

- [ ] **Step 1: Write failing tests**

Tests should import wrapper functions from `tools.sprite_mcp_server`, create temporary PNG assets, call `palette_extract`, `palette_swap`, `sprite_edit`, and `autotile_generate`, and assert outputs match existing JSON API behavior.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: import failure for missing `tools.sprite_mcp_server`.

- [ ] **Step 3: Implement wrappers**

Implement plain Python wrapper functions that build command dictionaries and call `run_ide_command`.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: all MCP wrapper tests pass.

### Task 2: MCP Server Factory And Entrypoint

**Files:**
- Modify: `tests/test_sprite_mcp_server.py`
- Modify: `tools/sprite_mcp_server.py`

- [ ] **Step 1: Write failing tests**

Tests should monkeypatch a fake `FastMCP` factory into `build_mcp_server`, verify all tool names are registered, and verify `main()` returns 1 with a missing-SDK message when `ImportError` occurs.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: factory/entrypoint assertions fail until implemented.

- [ ] **Step 3: Implement server factory**

Add `build_mcp_server`, lazy import `FastMCP`, register each wrapper with `@mcp.tool()`, and run `mcp.run(transport="stdio")` in `main`.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: all MCP tests pass.

### Task 3: Agent Resources, Prompts, And Setup Helpers

**Files:**
- Modify: `tests/test_sprite_mcp_server.py`
- Modify: `tools/sprite_mcp_server.py`

- [ ] **Step 1: Write failing tests**

Tests should assert `spritecut://actions`, `spritecut://commands`, `spritecut://quality-checklist`, and `spritecut://sample-pack` resources are registered and return useful text. Tests should assert prompts return strings containing the requested project/path/engine details. Tests should assert `mcp_health_check` and `mcp_client_config` return JSON-compatible setup information.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: failures for missing resources, prompts, and setup helpers.

- [ ] **Step 3: Implement resources, prompts, and setup helpers**

Add resource functions, prompt functions, helper tools, and register them in `build_mcp_server`.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: all MCP tests pass.

### Task 4: Production Workflow Tools

**Files:**
- Modify: `tests/test_sprite_mcp_server.py`
- Modify: `tools/sprite_mcp_server.py`

- [ ] **Step 1: Write failing tests**

Tests should create small synthetic sheets/projects and verify `create_sample_pack`, `process_sheets`, `load_project_summary`, `review_dashboard`, `apply_project_outputs`, `review_and_apply_project`, and `generate_import_plans`.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: failures for missing production tools.

- [ ] **Step 3: Implement production workflow tools**

Use existing cutter, project, studio, and golden fixture modules. Capture cutter stdout/stderr and return logs in the result payload.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_sprite_mcp_server -v`

Expected: all MCP tests pass.

### Task 5: Docs, Requirements, Packaging

**Files:**
- Create: `requirements-mcp.txt`
- Modify: `README.md`
- Modify: `tools/package_sprite_tool.ps1`
- Modify: `tests/test_golden_and_packaging.py`

- [ ] **Step 1: Write failing tests**

Tests should assert `requirements-mcp.txt` exists, contains `mcp[cli]`, README documents `sprite_mcp_server.py`, and the package script includes MCP requirements.

- [ ] **Step 2: Verify tests fail**

Run: `python -m unittest tests.test_golden_and_packaging -v`

Expected: failures for missing requirements/docs/package content.

- [ ] **Step 3: Implement docs and packaging updates**

Add `requirements-mcp.txt`, README MCP setup snippet, and package copy rule.

- [ ] **Step 4: Verify tests pass**

Run: `python -m unittest tests.test_golden_and_packaging -v`

Expected: packaging/doc tests pass.

### Task 6: Full Verification

**Files:**
- All changed files

- [ ] **Step 1: Run full unit suite**

Run: `python -m unittest discover -s tests -p "test_*.py"`

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

Run: `python -m py_compile tools\cut_tileset_sprites.py tools\sprite_processing.py tools\sprite_atlas.py tools\sprite_manifest.py tools\sprite_reports.py tools\sprite_sheet_tool_ui.py tools\sprite_project.py tools\sprite_studio.py tools\sprite_editor.py tools\autotile_tools.py tools\sprite_ide_api.py tools\golden_sprite_fixtures.py tools\sprite_mcp_server.py`

Expected: exit code 0.
