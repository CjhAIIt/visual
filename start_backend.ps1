param(
    [int]$Port = 7800,
    [int]$LegacyPort = 7801,
    [string]$LegacyPythonPath = ""
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend-spring"

if (-not (Test-Path $backendDir)) {
    Write-Error "Spring backend directory not found: $backendDir"
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

function Get-JavaMajorVersion {
    param(
        [string]$JavaExecutable
    )

    try {
        $versionLine = & $JavaExecutable -version 2>&1 | Select-Object -First 1
        if ($versionLine -match '"(?<major>\d+)(?:\.\d+)?') {
            return [int]$Matches.major
        }
    }
    catch {
        return $null
    }

    return $null
}

function Resolve-JavaExecutable {
    $candidatePaths = @()

    if ($env:JAVA_HOME) {
        $candidatePaths += (Join-Path $env:JAVA_HOME "bin\\java.exe")
    }

    $javaCommand = Get-Command java -ErrorAction SilentlyContinue
    if ($javaCommand) {
        $candidatePaths += $javaCommand.Source
    }

    $programFilesJava = "C:\\Program Files\\Java"
    if (Test-Path $programFilesJava) {
        $candidatePaths += Get-ChildItem -Path $programFilesJava -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^jdk-(\d+)' } |
            Sort-Object {
                if ($_.Name -match '^jdk-(\d+)') {
                    return [int]$Matches[1]
                }
                return 0
            } -Descending |
            ForEach-Object { Join-Path $_.FullName "bin\\java.exe" }
    }

    foreach ($candidate in ($candidatePaths | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path $candidate)) {
            continue
        }

        $majorVersion = Get-JavaMajorVersion -JavaExecutable $candidate
        if ($majorVersion -ge 21) {
            return $candidate
        }
    }

    return $null
}

if (-not (Test-PortAvailable -CandidatePort $Port)) {
    Write-Error "Backend port $Port is already in use. The Spring gateway expects to own that port."
    exit 1
}

$mavenCandidates = @("mvn.cmd", "mvn")
$mavenExe = $null
foreach ($candidate in $mavenCandidates) {
    try {
        & $candidate --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $mavenExe = $candidate
            break
        }
    }
    catch {
        continue
    }
}

if (-not $mavenExe) {
    Write-Error "No usable Maven executable was found."
    exit 1
}

$javaExe = Resolve-JavaExecutable
if (-not $javaExe) {
    Write-Error "No usable Java 21+ executable was found. Install JDK 21+ or update JAVA_HOME/PATH."
    exit 1
}

$env:SPRING_SERVER_PORT = "$Port"
if (-not $env:LEGACY_BACKEND_PORT) {
    $env:LEGACY_BACKEND_PORT = "$LegacyPort"
}
if (-not $env:LEGACY_BACKEND_BASE_URL) {
    $env:LEGACY_BACKEND_BASE_URL = "http://127.0.0.1:$($env:LEGACY_BACKEND_PORT)"
}
if ($LegacyPythonPath) {
    $env:LEGACY_BACKEND_PYTHON_PATH = $LegacyPythonPath
}

if (Test-PortAvailable -CandidatePort $LegacyPort) {
    Write-Host "Legacy backend port $LegacyPort is available and will be used for auto-start." -ForegroundColor Green
} else {
    Write-Host "Legacy backend port $LegacyPort is already occupied. The Spring gateway will try to reuse the process on $($env:LEGACY_BACKEND_BASE_URL)." -ForegroundColor Yellow
}
if ($env:LEGACY_BACKEND_PYTHON_PATH) {
    Write-Host "Legacy backend Python:" -ForegroundColor Green
    Write-Host "  $($env:LEGACY_BACKEND_PYTHON_PATH)" -ForegroundColor Green
}

Write-Host "Using Maven:" -ForegroundColor Green
Write-Host "  $mavenExe" -ForegroundColor Green
Write-Host "Using Java:" -ForegroundColor Green
Write-Host "  $javaExe" -ForegroundColor Green
Write-Host "Starting Spring backend on http://127.0.0.1:$Port" -ForegroundColor Green

Push-Location $backendDir
try {
    & $mavenExe -q -DskipTests package
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $jarFile = Get-ChildItem -Path (Join-Path $backendDir "target") -Filter "*.jar" |
        Where-Object { $_.Name -notlike "*.original" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $jarFile) {
        Write-Error "No runnable Spring jar was produced in $backendDir\target"
        exit 1
    }

    & $javaExe -jar $jarFile.FullName
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
