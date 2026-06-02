# SpriteCut MCP Server Design

## Goal

Add a first-class Model Context Protocol server so MCP-aware IDEs and agents can discover and call SpriteCut tools without hand-writing JSON CLI requests.

## Scope

The first version is a local stdio MCP server. It exposes the existing SpriteCut IDE JSON actions as typed MCP tools and keeps `tools/sprite_ide_api.py` as the source of truth for editor, palette, and autotile behavior.

V2 expands the server for both agent coding assistants and game-dev workflow automation. It adds resources, prompts, setup helpers, and project-level production tools.

## Architecture

`tools/sprite_mcp_server.py` provides two layers:

- A dependency-light wrapper layer with plain Python functions such as `palette_extract`, `sprite_edit`, and `autotile_generate`. These functions normalize arguments into the same command dictionaries already accepted by `run_ide_command`.
- A lazy MCP server factory that imports `FastMCP` only when the MCP server is launched. This lets normal tests and compile checks run even when the optional MCP SDK is not installed.

The server runs over stdio by default. It must not write normal logs to stdout because stdio MCP uses stdout for JSON-RPC protocol messages.

## Tools

The MCP server exposes editor tools:

- `palette_extract`
- `palette_swap`
- `palette_hue_shift`
- `palette_variants`
- `sprite_edit`
- `sprite_batch_edit`
- `autotile_generate`

It also exposes setup and production tools:

- `mcp_health_check`
- `mcp_client_config`
- `create_sample_pack`
- `process_sheets`
- `load_project_summary`
- `review_dashboard`
- `apply_project_outputs`
- `review_and_apply_project`
- `generate_import_plans`

Tool names use underscore style for MCP readability, while payloads map directly to the existing dot-style actions in `sprite_ide_api.py`.

## Resources

Resources provide agent-readable context:

- `spritecut://actions`
- `spritecut://commands`
- `spritecut://quality-checklist`
- `spritecut://sample-pack`

## Prompts

Prompts help agents produce useful SpriteCut workflows:

- `review_sprite_project`
- `plan_palette_variants`
- `generate_sprite_edit_request`
- `prepare_engine_handoff`

## Dependencies

`requirements-mcp.txt` adds the optional MCP dependency: `mcp[cli]>=1.2.0`. Core app, UI, and existing CI do not require it unless MCP tests or runtime launch are requested.

## Error Handling

Wrapper functions raise the same validation errors as `run_ide_command`, so callers get consistent failures across CLI and MCP. The MCP entrypoint exits with a clear stderr message if the optional MCP SDK is missing.

Production tools capture cutter stdout/stderr and return it in JSON-compatible result payloads so stdio MCP protocol output stays clean.

## Documentation

README gains a short MCP section showing how to install MCP dependencies and configure an IDE/client to launch:

```powershell
python tools\sprite_mcp_server.py
```

## Testing

Tests cover direct wrapper calls, action-name mapping, resources, prompts, production workflow helpers, server factory behavior when the MCP dependency is absent or mocked, and packaging inclusion of the MCP server and requirements.
