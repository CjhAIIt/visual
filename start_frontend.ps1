param(
    [int]$Port = 5500
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $projectRoot "frontend"

if (-not (Test-Path $frontendDir)) {
    Write-Error "Frontend directory not found: $frontendDir"
    exit 1
}

if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    Write-Error "package.json not found in $frontendDir"
    exit 1
}

function Test-PortAvailable {
    param(
        [int]$CandidatePort
    )

    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $CandidatePort)
        $listener.Start()
        $listener.Stop()
        return $true
    }
    catch {
        return $false
    }
}

$npmCandidates = @("npm.cmd", "npm")
$npmExe = $null
foreach ($candidate in $npmCandidates) {
    try {
        & $candidate --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $npmExe = $candidate
            break
        }
    }
    catch {
        continue
    }
}

if (-not $npmExe) {
    Write-Error "No usable npm executable was found."
    exit 1
}

$portCandidates = @($Port, ($Port + 1), ($Port + 2), 8080, 8081) | Select-Object -Unique
$selectedPort = $null
foreach ($candidatePort in $portCandidates) {
    if (Test-PortAvailable -CandidatePort $candidatePort) {
        $selectedPort = $candidatePort
        break
    }
}

if (-not $selectedPort) {
    Write-Error "No available frontend port was found. Tried: $($portCandidates -join ', ')"
    exit 1
}

Write-Host "Using npm:" -ForegroundColor Green
Write-Host "  $npmExe" -ForegroundColor Green
if ($selectedPort -ne $Port) {
    Write-Host "Port $Port is unavailable, falling back to $selectedPort." -ForegroundColor Yellow
}
Write-Host "Installing frontend dependencies if needed..." -ForegroundColor Green

Push-Location $frontendDir
try {
    & $npmExe install
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    Write-Host "Starting Vite frontend on http://127.0.0.1:$selectedPort" -ForegroundColor Green
    & $npmExe run dev -- --host 127.0.0.1 --port $selectedPort
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
