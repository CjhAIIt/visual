param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 7800,
    [string]$PythonPath = ""
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "plantbackend"

if (-not (Test-Path $backendDir)) {
    Write-Error "Backend directory not found: $backendDir"
    exit 1
}

$pythonCandidates = @()
if ($PythonPath) {
    $pythonCandidates += $PythonPath
}
if ($env:LEGACY_BACKEND_PYTHON_PATH) {
    $pythonCandidates += $env:LEGACY_BACKEND_PYTHON_PATH
}
$pythonCandidates += @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $projectRoot ".venv-train\Scripts\python.exe"),
    (Join-Path $backendDir ".venv\Scripts\python.exe"),
    (Join-Path $backendDir ".venv-train\Scripts\python.exe")
) | Select-Object -Unique

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-Path $candidate)) {
        continue
    }

    & $candidate -c "import uvicorn" *> $null
    if ($LASTEXITCODE -eq 0) {
        $pythonExe = $candidate
        break
    }
}

if (-not $pythonExe) {
    Write-Host "No usable Python environment with uvicorn was found." -ForegroundColor Yellow
    Write-Host "Checked:" -ForegroundColor Yellow
    foreach ($candidate in $pythonCandidates) {
        Write-Host "  $candidate" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "Using Python:" -ForegroundColor Green
Write-Host "  $pythonExe" -ForegroundColor Green
Write-Host "Starting legacy backend on http://$ListenHost`:$Port" -ForegroundColor Green

Push-Location $backendDir
try {
    & $pythonExe -m uvicorn asgi:app --host $ListenHost --port $Port
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}