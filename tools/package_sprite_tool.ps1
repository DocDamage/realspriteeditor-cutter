param(
    [string]$OutDir = "dist\sprite-sheet-processor"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if ([System.IO.Path]::IsPathRooted($OutDir)) {
    $Target = $OutDir
} else {
    $Target = Join-Path $Root $OutDir
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null

Copy-Item -Path (Join-Path $Root "tools") -Destination $Target -Recurse -Force
Copy-Item -Path (Join-Path $Root "README.md") -Destination $Target -Force
Copy-Item -Path (Join-Path $Root "docs") -Destination $Target -Recurse -Force
Copy-Item -Path (Join-Path $Root "launch_sprite_tool.bat") -Destination $Target -Force
Copy-Item -Path (Join-Path $Root "sprite_sheet_tool_ui.py") -Destination $Target -Force
Copy-Item -Path (Join-Path $Root "requirements-ui.txt") -Destination $Target -Force
Copy-Item -Path (Join-Path $Root "requirements-dev.txt") -Destination $Target -Force
Copy-Item -Path (Join-Path $Root "requirements-mcp.txt") -Destination $Target -Force
Copy-Item -Path (Join-Path $Root "skills") -Destination $Target -Recurse -Force

Write-Host "Packaged Sprite Sheet Processor to $Target"
