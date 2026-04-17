param(
    [switch]$SetupOnly,
    [switch]$SkipUpdateCheck,
    [switch]$SkipBrowser,
    [switch]$ForceInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSCommandPath
$venvDir = Join-Path $repoRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$requirementsPath = Join-Path $repoRoot "requirements.txt"
$frontendDir = Join-Path $repoRoot "frontend"
$frontendDistDir = Join-Path $frontendDir "dist"
$frontendPackageJson = Join-Path $frontendDir "package.json"
$frontendLockPath = Join-Path $frontendDir "package-lock.json"
$frontendNodeModulesDir = Join-Path $frontendDir "node_modules"
$stateDir = Join-Path $repoRoot ".startup"
$backendStampPath = Join-Path $stateDir "backend-deps.stamp"
$frontendStampPath = Join-Path $stateDir "frontend-deps.stamp"
$hostName = "127.0.0.1"
$port = 8000
$appDir = Split-Path -Parent $repoRoot
$healthUrl = "http://${hostName}:$port/api/health"
$appUrl = "http://${hostName}:$port/"

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-CommandPath {
    param([string[]]$Names)

    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) {
            return $command.Source
        }
    }

    return $null
}

function Ensure-Directory {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Get-PathWriteTime {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }

    $item = Get-Item $Path -ErrorAction Stop
    if (-not $item.PSIsContainer) {
        return $item.LastWriteTimeUtc
    }

    $children = Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue
    if (-not $children) {
        return $item.LastWriteTimeUtc
    }

    return ($children | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1).LastWriteTimeUtc
}

function Get-LatestWriteTime {
    param([string[]]$Paths)

    $latest = $null
    foreach ($path in $Paths) {
        $timestamp = Get-PathWriteTime -Path $path
        if ($null -eq $timestamp) {
            continue
        }

        if ($null -eq $latest -or $timestamp -gt $latest) {
            $latest = $timestamp
        }
    }

    return $latest
}

function Test-Stale {
    param(
        $SourceTime,
        $TargetTime
    )

    if ($null -eq $TargetTime) {
        return $true
    }

    if ($null -eq $SourceTime) {
        return $false
    }

    return $SourceTime -gt $TargetTime
}

function Invoke-ExternalCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$FailureMessage
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw $FailureMessage
        }
    }
    finally {
        Pop-Location
    }
}

function Update-Stamp {
    param([string]$Path)

    Ensure-Directory -Path (Split-Path -Parent $Path)
    Set-Content -Path $Path -Value (Get-Date).ToString("o") -Encoding ascii
}

function Test-ServerReady {
    param(
        [string]$Url,
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 25
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "The MTGLib server exited before it finished starting."
        }

        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
        }

        Start-Sleep -Seconds 1
    }

    return $false
}

function Check-ForUpdates {
    param([string]$GitPath)

    Write-Step "Checking for app updates"

    if (-not $GitPath) {
        Write-Host "Git is not installed, so update checks are skipped." -ForegroundColor Yellow
        return
    }

    $previousPrompt = $env:GIT_TERMINAL_PROMPT
    $env:GIT_TERMINAL_PROMPT = "0"

    try {
        $gitRoot = (& $GitPath -C $repoRoot rev-parse --show-toplevel 2>$null).Trim()
        if (-not $gitRoot) {
            Write-Host "No git repository was found for this folder. Skipping update check." -ForegroundColor Yellow
            return
        }

        & $GitPath -C $gitRoot -c credential.interactive=never -c core.askPass= fetch --quiet --prune 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Could not reach the remote repository. Skipping update check." -ForegroundColor Yellow
            return
        }

        $upstream = (& $GitPath -C $gitRoot rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null).Trim()
        if (-not $upstream) {
            Write-Host "No upstream branch is configured. Skipping update check." -ForegroundColor Yellow
            return
        }

        $counts = (& $GitPath -C $gitRoot rev-list --left-right --count "HEAD...$upstream" 2>$null).Trim()
        if (-not $counts) {
            Write-Host "Unable to determine update status." -ForegroundColor Yellow
            return
        }

        $parts = $counts -split '\s+'
        if ($parts.Length -lt 2) {
            Write-Host "Unable to determine update status." -ForegroundColor Yellow
            return
        }

        $ahead = [int]$parts[0]
        $behind = [int]$parts[1]

        if ($behind -gt 0) {
            Write-Host "Updates are available: $behind commit(s) behind $upstream." -ForegroundColor Yellow
        }
        elseif ($ahead -gt 0) {
            Write-Host "Local checkout is ahead of $upstream by $ahead commit(s)." -ForegroundColor Yellow
        }
        else {
            Write-Host "App files are up to date." -ForegroundColor Green
        }
    }
    finally {
        $env:GIT_TERMINAL_PROMPT = $previousPrompt
    }
}

Write-Step "Validating prerequisites"

$pythonLauncher = Get-CommandPath -Names @("py.exe", "py", "python.exe", "python")
if (-not $pythonLauncher -and -not (Test-Path $pythonExe)) {
    throw "Python 3 is required. Install Python, then run start.cmd again."
}

$nodePath = Get-CommandPath -Names @("node.exe", "node")
if (-not $nodePath) {
    throw "Node.js is required. Install Node.js, then run start.cmd again."
}

$npmPath = Get-CommandPath -Names @("npm.cmd", "npm.exe", "npm")
if (-not $npmPath) {
    throw "npm is required. Install Node.js, then run start.cmd again."
}

$gitPath = Get-CommandPath -Names @("git.exe", "git")

Ensure-Directory -Path $stateDir

if (-not (Test-Path $pythonExe)) {
    Write-Step "Creating a local Python environment"
    if (-not $pythonLauncher) {
        throw "Python 3 is required to create the local virtual environment."
    }

    $venvArguments = @("-m", "venv", $venvDir)
    $pythonLauncherName = [System.IO.Path]::GetFileName($pythonLauncher)
    if ($pythonLauncherName -match '^py(\.exe)?$') {
        $venvArguments = @("-3", "-m", "venv", $venvDir)
    }

    Invoke-ExternalCommand -FilePath $pythonLauncher -Arguments $venvArguments -WorkingDirectory $repoRoot -FailureMessage "Failed to create the local virtual environment."
}

Write-Step "Preparing backend dependencies"

$backendNeedsInstall = $ForceInstall -or -not (Test-Path $backendStampPath) -or (Test-Stale -SourceTime (Get-PathWriteTime -Path $requirementsPath) -TargetTime (Get-PathWriteTime -Path $backendStampPath))
if ($backendNeedsInstall) {
    Invoke-ExternalCommand -FilePath $pythonExe -Arguments @("-m", "pip", "install", "-r", $requirementsPath) -WorkingDirectory $repoRoot -FailureMessage "Backend dependency installation failed."

    Update-Stamp -Path $backendStampPath
}
else {
    Write-Host "Backend dependencies are already current."
}

Write-Step "Preparing frontend dependencies"

$frontendNeedsInstall = $ForceInstall -or -not (Test-Path $frontendNodeModulesDir) -or -not (Test-Path $frontendStampPath) -or (Test-Stale -SourceTime (Get-LatestWriteTime -Paths @($frontendPackageJson, $frontendLockPath)) -TargetTime (Get-PathWriteTime -Path $frontendStampPath))
if ($frontendNeedsInstall) {
    Invoke-ExternalCommand -FilePath $npmPath -Arguments @("install") -WorkingDirectory $frontendDir -FailureMessage "Frontend dependency installation failed."

    Update-Stamp -Path $frontendStampPath
}
else {
    Write-Host "Frontend dependencies are already current."
}

Write-Step "Ensuring the frontend build is ready"

$frontendSourceTime = Get-LatestWriteTime -Paths @(
    (Join-Path $frontendDir "src"),
    (Join-Path $frontendDir "index.html"),
    $frontendPackageJson,
    (Join-Path $frontendDir "tsconfig.json"),
    (Join-Path $frontendDir "tsconfig.node.json"),
    (Join-Path $frontendDir "vite.config.ts")
)
$frontendDistTime = Get-PathWriteTime -Path $frontendDistDir
$frontendNeedsBuild = $ForceInstall -or (Test-Stale -SourceTime $frontendSourceTime -TargetTime $frontendDistTime)

if ($frontendNeedsBuild) {
    Invoke-ExternalCommand -FilePath $npmPath -Arguments @("run", "build") -WorkingDirectory $frontendDir -FailureMessage "Frontend build failed."
}
else {
    Write-Host "Frontend build output is already current."
}

if (-not $SkipUpdateCheck) {
    Check-ForUpdates -GitPath $gitPath
}

if ($SetupOnly) {
    Write-Host ""
    Write-Host "MTGLib setup completed. Run start.cmd to launch the app." -ForegroundColor Green
    exit 0
}

Write-Step "Starting MTGLib"

$serverProcess = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "mtglib.app.main:app", "--app-dir", $appDir, "--host", $hostName, "--port", "$port") -WorkingDirectory $repoRoot -PassThru

$ready = Test-ServerReady -Url $healthUrl -Process $serverProcess
if ($ready) {
    Write-Host "MTGLib is running at $appUrl" -ForegroundColor Green
    if (-not $SkipBrowser) {
        Start-Process $appUrl | Out-Null
    }
}
else {
    Write-Host "The server is still starting. Open $appUrl once the server window reports it is ready." -ForegroundColor Yellow
}

Write-Host "Server process id: $($serverProcess.Id)"
Write-Host "Close the server window or stop that process to exit the app."