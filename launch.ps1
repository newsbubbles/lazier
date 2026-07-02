#!/usr/bin/env pwsh
# lazier launcher (Windows / PowerShell)
# Frees the target ports (killing any listener) then launches the service(s),
# each in its own PowerShell window so you get live logs.
#
#   .\launch.ps1              # both (default)
#   .\launch.ps1 backend      # backend only
#   .\launch.ps1 frontend     # frontend only
#
# NOTE: do not name a variable $pid — it's a read-only PowerShell automatic variable.

[CmdletBinding()]
param(
    [ValidateSet('both', 'backend', 'frontend')]
    [string]$Target = 'both'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendPort = 5181
$FrontendPort = 5180

function Free-Port([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { Write-Host "port $Port already free" -ForegroundColor DarkGray; return }
    foreach ($procId in ($conns.OwningProcess | Sort-Object -Unique)) {
        if (-not $procId -or $procId -eq 0) { continue }
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        Write-Host "killing PID $procId ($($p.Name)) holding port $Port" -ForegroundColor Yellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 400
}

function Start-InWindow([string]$Title, [string]$Dir, [string]$Cmd) {
    $inner = "`$host.UI.RawUI.WindowTitle = '$Title'; Set-Location -LiteralPath '$Dir'; " +
             "Write-Host '> $Cmd' -ForegroundColor Cyan; $Cmd"
    Start-Process -FilePath 'powershell' -ArgumentList @('-NoExit', '-Command', $inner) | Out-Null
}

function Start-Backend {
    Free-Port $BackendPort
    Write-Host "starting backend on :$BackendPort" -ForegroundColor Green
    Start-InWindow 'lazier-backend' (Join-Path $Root 'backend') `
        "uv run uvicorn lazier.main:app --port $BackendPort --host 127.0.0.1"
}

function Start-Frontend {
    Free-Port $FrontendPort
    Write-Host "starting frontend on :$FrontendPort" -ForegroundColor Green
    Start-InWindow 'lazier-frontend' (Join-Path $Root 'frontend') 'npm run dev'
}

switch ($Target) {
    'backend'  { Start-Backend }
    'frontend' { Start-Frontend }
    'both'     { Start-Backend; Start-Frontend }
}

Write-Host "launched: $Target  (backend :$BackendPort, frontend :$FrontendPort)" -ForegroundColor Cyan
