# lazier — bring up the backend (:5181) + frontend (:5180), detached and idempotent.
# Typing `lazier` anywhere runs this (via the shim in %LOCALAPPDATA%\Microsoft\WindowsApps).
# Already-running servers are left alone; only what's down gets started.
$ErrorActionPreference = 'SilentlyContinue'
$root = 'D:\lazier'

function Up($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

$started = $false

if (Up 5181) { Write-Host 'backend  already up   :5181' -ForegroundColor Green }
else {
  Start-Process -FilePath 'uv' `
    -ArgumentList 'run','uvicorn','lazier.main:app','--host','127.0.0.1','--port','5181' `
    -WorkingDirectory "$root\backend" -WindowStyle Hidden `
    -RedirectStandardOutput "$root\backend\.uvicorn.out.log" `
    -RedirectStandardError  "$root\backend\.uvicorn.err.log" | Out-Null
  Write-Host 'backend  starting     :5181' -ForegroundColor Cyan
  $started = $true
}

if (Up 5180) { Write-Host 'frontend already up   :5180' -ForegroundColor Green }
else {
  Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev' `
    -WorkingDirectory "$root\frontend" -WindowStyle Hidden `
    -RedirectStandardOutput "$root\frontend\.vite.out.log" `
    -RedirectStandardError  "$root\frontend\.vite.err.log" | Out-Null
  Write-Host 'frontend starting     :5180' -ForegroundColor Cyan
  $started = $true
}

if ($started) {
  Write-Host 'waiting for health...' -ForegroundColor DarkGray
  for ($i = 0; $i -lt 20; $i++) { Start-Sleep -Seconds 1; if ((Up 5180) -and (Up 5181)) { Start-Sleep -Seconds 2; break } }
}

$b = try { (Invoke-WebRequest 'http://127.0.0.1:5181/api/health' -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 } catch { $false }
$f = try { (Invoke-WebRequest 'http://localhost:5180/'          -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 } catch { $false }
Write-Host ''
Write-Host ('backend  ' + $(if ($b) { 'UP' } else { 'not ready yet' })) -ForegroundColor $(if ($b) { 'Green' } else { 'Yellow' })
Write-Host ('frontend ' + $(if ($f) { 'UP' } else { 'not ready yet' })) -ForegroundColor $(if ($f) { 'Green' } else { 'Yellow' })
Write-Host ''
Write-Host '  lazier -> http://localhost:5180' -ForegroundColor Yellow
if ($started -and $f) { Start-Process 'http://localhost:5180' }   # open the app when freshly launched
